"""
/***************************************************************************
 PointerGeocoding Plugin - Layer and Session Management Module
 ***************************************************************************/

LayerManager mixes in per-responsibility mixin classes defined in
models.py (PluginSettings/RefPointMeta/ImageLayerMeta, get_local_crs,
suppress_crs_prompt) plus settings_io.py / symbology.py / gpkg.py /
grid_csv.py / session_io.py. This module keeps only the QObject signals,
__init__, and the session_image_dir/session_json_dir properties.
"""
# 【変更不可侵の絶対的ルール】 測量座標系（X軸=南北, Y軸=東西）を採用。QGISキャンバス上のX座標(東西)はSurvey Y、Y座標(南北)はSurvey Xに対応する。

import os
from typing import Optional, Tuple, Dict, Any

from qgis.core import (
    QgsVectorLayer,
    QgsRasterLayer,
    QgsGeometry,
    QgsSpatialIndex,
)
from qgis.PyQt.QtCore import QObject, pyqtSignal

from ..logic.core import safe_get_str
from .settings_io import SettingsMetadataMixin
from .symbology import SymbologyMixin
from .gpkg import GpkgCacheMixin
from .grid_csv import GridCsvMixin
from .session_io import SessionIOMixin


class LayerManager(
    QObject,
    SettingsMetadataMixin,
    SymbologyMixin,
    GpkgCacheMixin,
    GridCsvMixin,
    SessionIOMixin,
):
    """Manages the creation, persistence, and loading of project layers and GeoPackage files.

    Handles local CRS assignment, relative path storage, schema migration,
    multiple raster layer retention, and Observer pattern synchronization using QgsSpatialIndex.
    # 【変更不可侵の絶対的ルール】 測量座標系（X軸=南北, Y軸=東西）を採用。QGISキャンバス上のX座標(東西)はSurvey Y、Y座標(南北)はSurvey Xに対応する。

    Step3-B: QObject化により、以下のシグナルで状態変化を通知できる（追加のみ、
    既存メソッドの引数・戻り値・処理内容は変更しない）:
        metadata_updated(str): 画像メタデータが保存された（save_image_metadata経由。
            対象レイヤ名が特定できない一括保存のケースでは空文字を渡す）。
        layer_deleted(str): 指定レイヤのメタデータが削除された。
        settings_changed(dict): プラグイン設定が保存された。
    """

    metadata_updated = pyqtSignal(str)
    layer_deleted = pyqtSignal(str)
    settings_changed = pyqtSignal(dict)

    # LayerManagerの初期化。iface参照とセッション/レイヤー関連の状態、空間インデックス・キャッシュを初期値で構築する。
    def __init__(self, iface: Any = None) -> None:
        """Initialize LayerManager with an optional QgsInterface reference.

        :param iface: Optional QGIS interface instance.
        :type iface: QgisInterface
        """
        super().__init__()
        self.iface = iface
        self.session_dir: Optional[str] = None
        self.gpkg_path: Optional[str] = None
        self.qgz_path: Optional[str] = None
        self.point_layer: Optional[QgsVectorLayer] = None
        self.ref_point_layer: Optional[QgsVectorLayer] = None
        self.raster_layer: Optional[QgsRasterLayer] = None
        self.grid_csv_path: Optional[str] = None
        self.grid_data: Dict[Tuple[int, str, str], Tuple[float, float]] = {}
        self.max_gx: int = 0
        self.unique_gy: set = set()

        # Spatial index and cache properties (Observer pattern)
        self.spatial_index: Optional[QgsSpatialIndex] = None
        self.attr_cache: Dict[int, Dict[str, str]] = {}
        self.geom_cache: Dict[int, QgsGeometry] = {}
        self._signals_connected: bool = False

    # unload時に、シグナル接続・空間インデックス・キャッシュ・レイヤ参照を解放する(プロジェクトのレイヤは破棄せず、二重呼び出し可)。
    def release_resources(self) -> None:
        """Release signal connections, spatial index, caches and layer references (idempotent, no project data touched)."""
        try:
            self._disconnect_point_layer_signals()
        except Exception:
            pass
        self._signals_connected = False
        self.spatial_index = None
        self.attr_cache.clear()
        self.geom_cache.clear()
        self.point_layer = None
        self.ref_point_layer = None
        self.raster_layer = None

    @property
    # セッションのimage/ディレクトリパスを返す(未初期化時はNone)。
    def session_image_dir(self) -> Optional[str]:
        """Return path to the session image/ directory if session is initialized."""
        if self.session_dir:
            return os.path.join(self.session_dir, "image")
        return None

    @property
    # セッションのjson/ディレクトリパスを返す(未初期化時はNone)。
    def session_json_dir(self) -> Optional[str]:
        """Return path to the session json/ directory if session is initialized."""
        if self.session_dir:
            return os.path.join(self.session_dir, "json")
        return None

    # 指定layer_nameを参照するpoint_layerのdrawing_name属性を空文字にクリアする。
    def clear_drawing_name_for_layer(self, layer_name: str) -> None:
        """Clear the drawing_name attribute on point_layer features referencing layer_name.

        No-op if point_layer is not set/valid or does not have a
        "drawing_name" field.

        :param layer_name: Value of the drawing_name attribute to clear
            (matching features have their drawing_name reset to "").
        """
        if not (
            self.point_layer
            and self.point_layer.isValid()
            and "drawing_name" in self.point_layer.fields().names()
        ):
            return

        self.point_layer.startEditing()
        idx = self.point_layer.fields().indexFromName("drawing_name")
        for f in self.point_layer.getFeatures():
            if safe_get_str(f, "drawing_name") == layer_name:
                self.point_layer.changeAttributeValue(f.id(), idx, "")
        self.point_layer.commitChanges()

    # point_layer上のdrawing_name属性をold_nameからnew_nameへ一括リネームする。
    def rename_drawing_name(self, old_name: str, new_name: str) -> None:
        """Rename the drawing_name attribute from old_name to new_name on point_layer.

        No-op if point_layer is not set/valid or does not have a
        "drawing_name" field.

        :param old_name: Current drawing_name value to match.
        :param new_name: New drawing_name value to assign to matching features.
        """
        if not (
            self.point_layer
            and self.point_layer.isValid()
            and "drawing_name" in self.point_layer.fields().names()
        ):
            return

        self.point_layer.startEditing()
        idx = self.point_layer.fields().indexFromName("drawing_name")
        for f in self.point_layer.getFeatures():
            if safe_get_str(f, "drawing_name") == old_name:
                self.point_layer.changeAttributeValue(f.id(), idx, new_name)
        self.point_layer.commitChanges()
