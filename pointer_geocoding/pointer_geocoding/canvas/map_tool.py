"""
/***************************************************************************
 PointerGeocoding Plugin - Custom Map Digitizing and Georeferencing Tools
 ***************************************************************************/
"""
# 【変更不可侵の絶対的ルール】 測量座標系（X軸=南北, Y軸=東西）を採用。QGISキャンバス上のX座標(東西)はSurvey Y、Y座標(南北)はSurvey Xに対応する。

import math
from typing import Optional, Any, Dict, List, Tuple

from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsRectangle,
    QgsFeatureRequest,
    QgsCoordinateReferenceSystem,
    QgsSpatialIndex,
    QgsSymbol,
    Qgis,
)
from qgis.gui import (
    QgsMapTool,
    QgsMapCanvas,
    QgsMapMouseEvent,
    QgsVertexMarker,
    QgsMapCanvasItem,
    QgsRubberBand,
)
from qgis.PyQt.QtCore import Qt, pyqtSignal, QRectF
from qgis.PyQt.QtGui import QColor, QCursor, QFont, QPainter
from qgis.PyQt.QtWidgets import QInputDialog, QWidget

from ..logic.core import ExcavationType

# QgsRubberBand用のポリゴンジオメトリ種別を返す(QGISバージョン差異を吸収)。
def _polygon_geometry_type() -> Any:
    try:
        return Qgis.GeometryType.Polygon
    except AttributeError:
        from qgis.core import QgsWkbTypes
        return QgsWkbTypes.PolygonGeometry


class PreviewTextItem(QgsMapCanvasItem):
    """Temporary canvas item to display text labels for reference points."""
    # 参照点ラベル項目の初期化。表示テキスト・フォント・表示位置を設定する。
    def __init__(self, canvas: QgsMapCanvas, map_pt: QgsPointXY, text: str, font_size: int = 10):
        super().__init__(canvas)
        self.map_pt = map_pt
        self.text = text
        self.font = QFont("sans-serif", font_size)
        self.font.setBold(True)
        self.setPos(self.toCanvasCoordinates(self.map_pt))

    # ラベルテキストをキャンバス上に描画する。
    def paint(self, painter: QPainter, option: Any = None, widget: Optional[QWidget] = None) -> None:
        painter.setFont(self.font)
        painter.setPen(QColor("#D32F2F"))
        # Offset to top right
        painter.drawText(10, -10, self.text)

    # ラベル項目の描画範囲(バウンディングボックス)を返す。
    def boundingRect(self) -> QRectF:
        return QRectF(0, -30, 150, 40)

    # 地図座標からキャンバス座標へ変換し、ラベルの表示位置を更新する。
    def updatePosition(self) -> None:
        self.setPos(self.toCanvasCoordinates(self.map_pt))


class ImageGeorefTool(QgsMapTool):
    """Custom QgsMapTool for picking reference points on the temporary preview canvas.

    Translates preview canvas coordinates into image pixel coordinates (X, Y)
    where (0, 0) is the top-left of the image. Provides 15px hover snap detection and visual box marker.
    """

    point_clicked = pyqtSignal(float, float)  # Emits (pixel_x, pixel_y)
    ref_point_moved = pyqtSignal(int, float, float)  # Emits (ref point index, pixel_x, pixel_y)

    # ドラッグ開始判定の半径(px)と、クリックとドラッグを区別する移動量の閾値(px)。
    _DRAG_GRAB_RADIUS_PX = 15.0
    _DRAG_START_THRESHOLD_PX = 4.0

    # プレビュー用ジオリファレンスツールの初期化。キャンバス・ラスタ・スナップ用マーカーを設定する。
    def __init__(self, canvas: QgsMapCanvas, raster_layer: QgsRasterLayer, label_font_size: int = 10) -> None:
        """Initialize preview georeferencing tool.

        :param canvas: Preview map canvas instance.
        :type canvas: QgsMapCanvas
        :param raster_layer: The unreferenced raster layer being previewed.
        :type raster_layer: QgsRasterLayer
        :param label_font_size: Font size for reference point labels.
        :type label_font_size: int
        """
        super().__init__(canvas)
        self.canvas = canvas
        self.raster_layer = raster_layer
        self._label_font_size = label_font_size
        self.markers: List[QgsVertexMarker] = []
        self.text_items: List[PreviewTextItem] = []
        self.ref_points_data: List[Dict[str, Any]] = []

        # Highlight marker for snapping on hover
        self.snap_marker = QgsVertexMarker(self.canvas)
        self.snap_marker.setIconType(QgsVertexMarker.ICON_BOX)
        self.snap_marker.setColor(QColor("#D32F2F"))
        self.snap_marker.setPenWidth(2)
        self.snap_marker.setIconSize(14)
        self.snap_marker.hide()

        # Drag-move state for reference points.
        self._drag_pending: bool = False
        self._drag_active: bool = False
        self._drag_suppress_release: bool = False
        self._drag_press_pos = None
        self._drag_index: int = -1

    # ホバースナップ判定に使う参照点リストを更新する。
    def set_ref_points_data(self, ref_points_data: List[Dict[str, Any]]) -> None:
        """Update reference points list for hover snapping.

        :param ref_points_data: List of reference point dicts.
        :type ref_points_data: List[Dict[str, Any]]
        """
        self._reset_drag()
        self.ref_points_data = ref_points_data

    # プレビューキャンバス上でツールが有効化された際の処理。カーソルを十字に設定する。
    def activate(self) -> None:
        """Called when tool is activated on the preview canvas."""
        super().activate()
        self.setCursor(Qt.CrossCursor)

    # ツール無効化時の処理。ドラッグ状態を破棄しスナップマーカーを非表示にする。
    def deactivate(self) -> None:
        """Called when tool is deactivated."""
        self._reset_drag()
        if self.snap_marker:
            self.snap_marker.hide()
        super().deactivate()

    # 重い処理中にキャンバス操作をロック/アンロックする。
    def set_interaction_locked(self, locked: bool) -> None:
        """Lock or unlock canvas interactions during heavy operations."""
        self._interaction_locked = locked
        if locked:
            self._reset_drag()
            if self.snap_marker:
                self.snap_marker.hide()
            self.setCursor(Qt.WaitCursor)
        else:
            self.setCursor(Qt.CrossCursor)

    # マウス移動時、15px以内の近傍参照点をボックスマーカーでハイライトする。
    def canvasMoveEvent(self, event: QgsMapMouseEvent) -> None:
        """Highlight nearby reference points within 15px with visual box marker on hover."""
        if self.snap_marker is None:
            return
        if getattr(self, "_interaction_locked", False):
            if self.snap_marker:
                self.snap_marker.hide()
            return

        # Drag handling: start dragging once movement exceeds the threshold;
        # while dragging only the snap marker follows (no hover processing).
        if self._drag_pending and self._drag_press_pos is not None:
            if not self._drag_active:
                dx = event.pos().x() - self._drag_press_pos.x()
                dy = event.pos().y() - self._drag_press_pos.y()
                if math.hypot(dx, dy) > self._DRAG_START_THRESHOLD_PX:
                    self._drag_active = True
            if self._drag_active:
                if self.snap_marker:
                    px, py = self._canvas_pos_to_pixel(event.pos())
                    pt = self._pixel_to_map_point(px, py)
                    if pt is None:
                        pt = self.toMapCoordinates(event.pos())
                    self.snap_marker.setCenter(pt)
                    self.snap_marker.show()
                return

        if not self.ref_points_data:
            if self.snap_marker:
                self.snap_marker.hide()
            self.setCursor(Qt.CrossCursor)
            return

        extent = self.raster_layer.extent()
        w = float(self.raster_layer.width())
        h = float(self.raster_layer.height())
        if w <= 0 or h <= 0 or extent.width() <= 0 or extent.height() <= 0:
            if self.snap_marker:
                self.snap_marker.hide()
            self.setCursor(Qt.CrossCursor)
            return

        snapped_index = self._nearest_ref_index(event.pos(), 15.0)
        snapped_pt: Optional[QgsPointXY] = None
        if snapped_index is not None:
            rdata = self.ref_points_data[snapped_index]
            snapped_pt = self._pixel_to_map_point(
                float(rdata.get("pixel_x", 0.0)), float(rdata.get("pixel_y", 0.0))
            )

        if snapped_pt is not None:
            self.snap_marker.setCenter(snapped_pt)
            self.snap_marker.show()
            self.setCursor(Qt.PointingHandCursor)
        else:
            if self.snap_marker:
                self.snap_marker.hide()
            self.setCursor(Qt.CrossCursor)

    # 画面座標から radius px 以内にある最近傍の基準点インデックスを返す(無ければNone)。
    def _nearest_ref_index(self, screen_pos, radius: float) -> Optional[int]:
        if not self.ref_points_data or not self.raster_layer:
            return None
        extent = self.raster_layer.extent()
        w = float(self.raster_layer.width())
        h = float(self.raster_layer.height())
        if w <= 0 or h <= 0 or extent.width() <= 0 or extent.height() <= 0:
            return None

        nearest_index: Optional[int] = None
        min_dist = float("inf")
        for i, rdata in enumerate(self.ref_points_data):
            rx = float(rdata.get("pixel_x", 0.0))
            ry = float(rdata.get("pixel_y", 0.0))
            r_map_x = extent.xMinimum() + (rx / w) * extent.width()
            r_map_y = extent.yMaximum() - (ry / h) * extent.height()
            r_screen = self.toCanvasCoordinates(QgsPointXY(r_map_x, r_map_y))
            dist = math.hypot(screen_pos.x() - r_screen.x(), screen_pos.y() - r_screen.y())
            if dist <= radius and dist < min_dist:
                min_dist = dist
                nearest_index = i
        return nearest_index

    # ピクセル座標に対応する画面位置から radius px 以内の最近傍基準点インデックスを返す(無ければNone)。
    def find_snapped_index_at_pixel(self, pixel_x: float, pixel_y: float, radius: float = 15.0) -> Optional[int]:
        pt = self._pixel_to_map_point(pixel_x, pixel_y)
        if pt is None:
            return None
        return self._nearest_ref_index(self.toCanvasCoordinates(pt), radius)

    # キャンバス上の位置をピクセル座標へ変換し、画像範囲内にクランプして返す。
    def _canvas_pos_to_pixel(self, pos) -> Tuple[float, float]:
        map_point = self.toMapCoordinates(pos)
        if not self.raster_layer or not self.raster_layer.isValid():
            return map_point.x(), abs(map_point.y())

        extent = self.raster_layer.extent()
        w = float(self.raster_layer.width())
        h = float(self.raster_layer.height())

        if extent.width() > 0 and extent.height() > 0 and w > 0 and h > 0:
            pixel_x = (map_point.x() - extent.xMinimum()) / (extent.width() / w)
            pixel_y = (extent.yMaximum() - map_point.y()) / (extent.height() / h)
        else:
            pixel_x = map_point.x()
            pixel_y = abs(map_point.y())

        # Clamp within pixel bounds
        pixel_x = max(0.0, min(w, pixel_x))
        pixel_y = max(0.0, min(h, pixel_y))
        return pixel_x, pixel_y

    # ピクセル座標を地図座標へ変換する(画像が無効な場合はNone)。
    def _pixel_to_map_point(self, pixel_x: float, pixel_y: float) -> Optional[QgsPointXY]:
        if not self.raster_layer or not self.raster_layer.isValid():
            return None
        extent = self.raster_layer.extent()
        w = float(self.raster_layer.width())
        h = float(self.raster_layer.height())
        if w <= 0 or h <= 0:
            return None
        return QgsPointXY(
            extent.xMinimum() + (pixel_x / w) * extent.width(),
            extent.yMaximum() - (pixel_y / h) * extent.height(),
        )

    # ドラッグ状態を破棄し、スナップマーカーを隠す。
    def _reset_drag(self) -> None:
        self._drag_pending = False
        self._drag_active = False
        self._drag_press_pos = None
        self._drag_index = -1
        if self.snap_marker:
            self.snap_marker.hide()

    # 左ボタン押下を処理する。基準点から15px以内の押下時のみドラッグ準備状態に入る。
    def canvasPressEvent(self, event: QgsMapMouseEvent) -> None:
        """Handle mouse press: arm reference point dragging when pressed within 15px of a point."""
        if self.snap_marker is None:
            return
        self._drag_suppress_release = False
        if getattr(self, "_interaction_locked", False):
            return
        if event.button() != Qt.LeftButton or not self.ref_points_data:
            return

        extent = self.raster_layer.extent()
        w = float(self.raster_layer.width())
        h = float(self.raster_layer.height())
        if w <= 0 or h <= 0 or extent.width() <= 0 or extent.height() <= 0:
            return

        mouse_screen = event.pos()
        nearest_index = self._nearest_ref_index(mouse_screen, self._DRAG_GRAB_RADIUS_PX)

        if nearest_index is not None:
            self._drag_pending = True
            self._drag_active = False
            self._drag_press_pos = mouse_screen
            self._drag_index = nearest_index

    # Escでドラッグを取消し、スナップマーカーを隠す。他のキーは親クラスへ委譲する。
    def keyPressEvent(self, event) -> None:
        """Cancel an in-progress reference point drag with Esc; delegate other keys."""
        if self.snap_marker is None:
            super().keyPressEvent(event)
            return
        if event.key() == Qt.Key_Escape and (self._drag_pending or self._drag_active):
            if self._drag_active:
                self._drag_suppress_release = True
            self._reset_drag()
            event.accept()
            return
        super().keyPressEvent(event)

    # プレビューキャンバス上でのマウスリリースを処理し、ドラッグ確定またはクリックをシグナル送出する。
    def canvasReleaseEvent(self, event: QgsMapMouseEvent) -> None:
        """Process mouse release event: emit ref_point_moved after a drag, else point_clicked."""
        if self.snap_marker is None:
            return
        if getattr(self, "_interaction_locked", False):
            return

        if event.button() != Qt.LeftButton:
            return

        if self._drag_suppress_release:
            self._drag_suppress_release = False
            return

        if self._drag_active:
            index = self._drag_index
            pixel_x, pixel_y = self._canvas_pos_to_pixel(event.pos())
            self._reset_drag()
            self.ref_point_moved.emit(index, pixel_x, pixel_y)
            return
        self._reset_drag()

        pixel_x, pixel_y = self._canvas_pos_to_pixel(event.pos())
        self.point_clicked.emit(pixel_x, pixel_y)

    # 指定ピクセル位置に頂点マーカーとラベルをプレビューキャンバス上へ配置する。
    def add_point_marker(self, pixel_x: float, pixel_y: float, name: str = "") -> None:
        """Place a visual vertex marker on the preview canvas at the given pixel location.

        :param pixel_x: X pixel coordinate.
        :type pixel_x: float
        :param pixel_y: Y pixel coordinate.
        :type pixel_y: float
        :param name: Label text for the point.
        :type name: str
        """
        if not self.raster_layer or not self.raster_layer.isValid():
            return

        extent = self.raster_layer.extent()
        w = float(self.raster_layer.width())
        h = float(self.raster_layer.height())
        if w <= 0 or h <= 0:
            return

        map_x = extent.xMinimum() + (pixel_x / w) * extent.width()
        map_y = extent.yMaximum() - (pixel_y / h) * extent.height()
        map_pt = QgsPointXY(map_x, map_y)

        marker = QgsVertexMarker(self.canvas)
        marker.setIconType(QgsVertexMarker.ICON_CROSS)
        marker.setColor(QColor("#D32F2F"))
        marker.setPenWidth(2)
        # Convert mm to approx pixels or use fixed size, here UIConfig says 4.0 but that's for QgsSymbol.
        # Let's use 12 for canvas vertex marker.
        marker.setIconSize(12)
        marker.setCenter(map_pt)
        marker.show()
        self.markers.append(marker)

        if name:
            label = PreviewTextItem(self.canvas, map_pt, name, font_size=self._label_font_size)
            self.text_items.append(label)

    # プレビューキャンバスシーンから全ての頂点マーカーとラベルを除去する。
    def clear_markers(self) -> None:
        """Remove all visual vertex markers from the preview canvas scene."""
        for m in self.markers:
            try:
                self.canvas.scene().removeItem(m)
            except Exception:
                pass
        self.markers.clear()
        
        for t in self.text_items:
            try:
                self.canvas.scene().removeItem(t)
            except Exception:
                pass
        self.text_items.clear()
        self.markers.clear()

    # マップツールのマーカー類(スナップマーカー含む)を全て破棄する。
    def clean_up(self) -> None:
        """Clean up map tool markers."""
        self.clear_markers()
        if self.snap_marker:
            try:
                self.canvas.scene().removeItem(self.snap_marker)
            except Exception:
                pass
            self.snap_marker = None


class CanvasDigitizingTool(QgsMapTool):
    """Custom QgsMapTool for continuous artifact point digitizing on the main canvas.

    Integrates QgsSpatialIndex for high-performance hover snapping,
    supports Focus Mode category filtering, and records canvas/real-world coordinates.
    """

    # Step3: canvas_clicked notifies the dock of a plain click (no existing point hit).
    # Feature validation/construction/layer writes are handled by
    # MainDockWidget._on_canvas_clicked, not by this tool.
    canvas_clicked = pyqtSignal(QgsPointXY)
    existing_point_selected = pyqtSignal(dict)
    # Emitted when a blank-space click occurs while in edit mode
    # (snap-to-existing-feature detection missed). Edit mode itself is
    # kept; only the dock widget's currently-selected feature should be
    # deselected in response.
    blank_click_in_edit_mode = pyqtSignal()
    # Emitted when a drag of the selected-point marker is released (destination
    # in canvas coordinates). The feature ID is supplied by the dock widget from
    # its own state; this tool holds no selection state.
    point_move_requested = pyqtSignal(QgsPointXY)
    # Emitted when a Shift+drag rectangle selection is released in edit mode. Carries the
    # list of feature IDs inside the rectangle (already passed through the focus/filter
    # check); an empty list means nothing was hit. Replaces any existing selection.
    points_area_selected = pyqtSignal(list)

    # ドラッグ開始判定の半径(px)と、クリックとドラッグを区別する移動量の閾値(px)。
    _DRAG_GRAB_RADIUS_PX = 15.0
    _DRAG_START_THRESHOLD_PX = 4.0
    # 点名検索ヒット時のズーム縮尺(1:N の N)。
    SEARCH_ZOOM_SCALE = 10

    # デジタイジングツールの初期化。ホバー/選択マーカー、フォーカス状態、シンボロジー適用を行う。
    def __init__(
        self,
        canvas: QgsMapCanvas,
        point_layer: QgsVectorLayer,
        dock_widget: Optional[QWidget] = None,
        layer_manager: Optional[Any] = None,
    ) -> None:
        """Initialize the digitizing map tool.

        :param canvas: Main map canvas instance.
        :type canvas: QgsMapCanvas
        :param point_layer: Vector layer for digitized points.
        :type point_layer: QgsVectorLayer
        :param dock_widget: Reference to the main dock widget for state synchronization.
        :type dock_widget: Optional[QWidget]
        :param layer_manager: Optional LayerManager instance with spatial index and caches.
        :type layer_manager: Optional[Any]
        """
        super().__init__(canvas)
        self.canvas = canvas
        self.point_layer = point_layer
        self.dock_widget = dock_widget
        self.layer_manager = layer_manager or (
            getattr(dock_widget, "layer_manager", None) if dock_widget else None
        )

        # Highlight vertex marker on hover
        self.hover_marker = QgsVertexMarker(self.canvas)
        self.hover_marker.setIconType(QgsVertexMarker.ICON_BOX)
        self.hover_marker.setColor(QColor("#D32F2F"))
        self.hover_marker.setPenWidth(2)
        self.hover_marker.setIconSize(14)
        self.hover_marker.hide()

        # Selected-point marker (same red box style as hover_marker),
        # displayed persistently while an existing point is selected for
        # editing/number-correction/deletion, independent of mouse hover.
        # Cleared on: selecting another point, a plain canvas click, or the
        # dock's "reset" button.
        self.selected_marker = QgsVertexMarker(self.canvas)
        self.selected_marker.setIconType(QgsVertexMarker.ICON_BOX)
        self.selected_marker.setColor(QColor("#D32F2F"))
        self.selected_marker.setPenWidth(2)
        self.selected_marker.setIconSize(14)
        self.selected_marker.hide()

        # Markers for the multi-selection made by Shift+drag area selection.
        self._multi_markers: List[QgsVertexMarker] = []

        # Rubber band and state for the Shift+drag rectangle (edit mode only).
        self._area_band = QgsRubberBand(self.canvas, _polygon_geometry_type())
        self._area_band.setColor(QColor(25, 118, 210, 50))
        self._area_band.setStrokeColor(QColor(25, 118, 210, 220))
        self._area_band.setWidth(1)
        self._area_band.hide()
        self._area_pending: bool = False
        self._area_active: bool = False
        self._area_press_pos = None
        self._area_origin: Optional[QgsPointXY] = None

        # Focus mode state cache, pushed one-way from MainDockWidget via
        # update_focus_state() (Step3: replaces pulling dock_widget getters).
        self._focus_active: bool = False
        self._focus_filter: Dict[str, str] = {}

        # Tab2 digitizing mode cache ("new" / "edit"), pushed one-way from
        # MainDockWidget via update_tab2_mode() whenever state_store.state.tab2_mode
        # changes. This tool must never read dock_widget/state_store directly
        # (Core_Architecture_UIUX.md section 2: input modules only push events
        # out, they never pull UI state in).
        self._tab2_mode: str = "new"

        # Drag-move state for the selected-point marker (edit mode only).
        self._drag_pending: bool = False
        self._drag_active: bool = False
        self._drag_suppress_release: bool = False
        self._drag_press_pos = None
        self._drag_origin_center: Optional[QgsPointXY] = None

        # Initialize categorised symbology for point layer (symbology
        # construction lives in layer/symbology.py, delegated to via
        # self.layer_manager).
        if self.layer_manager and hasattr(self.layer_manager, "apply_point_symbology"):
            current_settings = (
                self.layer_manager.load_settings()
                if hasattr(self.layer_manager, "load_settings")
                else None
            )
            self.layer_manager.apply_point_symbology(self.point_layer, current_settings)

    # マップツールが有効化された際の処理。カーソルを十字に設定する。
    def activate(self) -> None:
        """Called when the map tool becomes active."""
        super().activate()
        self.setCursor(Qt.CrossCursor)

    # マップツール無効化時の処理。ホバー/選択マーカーを非表示にする。
    def deactivate(self) -> None:
        """Called when the map tool is deactivated."""
        self._reset_drag(restore_marker=True)
        self._reset_area()
        if self.hover_marker:
            self.hover_marker.hide()
        if self.selected_marker:
            self.selected_marker.hide()
        for marker in self._multi_markers:
            marker.hide()
        super().deactivate()

    # 指定位置に選択中ポイントの永続マーカーを表示する。
    def show_selected_marker(self, map_point: QgsPointXY) -> None:
        """Display the persistent selection marker at the given point.

        :param map_point: Location of the selected existing point (canvas coordinates).
        :type map_point: QgsPointXY
        """
        if self.selected_marker:
            self.selected_marker.setCenter(map_point)
            self.selected_marker.show()

    # 指定座標をキャンバス中心にし、検索用の固定縮尺へズームする(再描画はQGISに委ねる)。
    def zoom_to_point(self, map_point: QgsPointXY) -> None:
        """Center the canvas on the given point and zoom to SEARCH_ZOOM_SCALE.

        :param map_point: Target location (canvas coordinates).
        :type map_point: QgsPointXY
        """
        self.canvas.setCenter(map_point)
        self.canvas.zoomScale(self.SEARCH_ZOOM_SCALE)

    # ドラッグ状態をリセットし、必要なら選択マーカーをドラッグ開始前の位置へ戻す。
    def _reset_drag(self, restore_marker: bool = False) -> None:
        if (
            restore_marker
            and self._drag_active
            and self._drag_origin_center is not None
            and self.selected_marker
        ):
            self.selected_marker.setCenter(self._drag_origin_center)
        self._drag_pending = False
        self._drag_active = False
        self._drag_press_pos = None
        self._drag_origin_center = None

    # 矩形選択(Shift+ドラッグ)の状態をリセットし、ラバーバンドを非表示にする。
    def _reset_area(self) -> None:
        self._area_pending = False
        self._area_active = False
        self._area_press_pos = None
        self._area_origin = None
        if self._area_band:
            self._area_band.reset(_polygon_geometry_type())
            self._area_band.hide()

    # 複数選択された点の位置に、選択マーカーを表示する(既存の複数マーカーは置換)。
    def show_multi_markers(self, points: List[QgsPointXY]) -> None:
        self.clear_multi_markers()
        for pt in points:
            marker = QgsVertexMarker(self.canvas)
            marker.setIconType(QgsVertexMarker.ICON_BOX)
            marker.setColor(QColor("#D32F2F"))
            marker.setPenWidth(2)
            marker.setIconSize(14)
            marker.setCenter(pt)
            marker.show()
            self._multi_markers.append(marker)

    # 複数選択用マーカーをすべて除去する。
    def clear_multi_markers(self) -> None:
        for marker in self._multi_markers:
            try:
                self.canvas.scene().removeItem(marker)
            except Exception:
                pass
        self._multi_markers = []

    # 選択中ポイントの永続マーカーを非表示にする。
    def clear_selected_marker(self) -> None:
        """Hide the persistent selection marker.

        Called when selection is cleared: another point is selected (marker is
        immediately repositioned instead), a plain canvas click occurs, or the
        dock's "reset" button is pressed.
        """
        if self.selected_marker:
            self.selected_marker.hide()

    # MainDockWidgetから送られるフォーカスモードの状態を受け取りローカルにキャッシュする。
    def update_focus_state(self, active: bool, filters: Dict[str, Any]) -> None:
        """Receive Focus Mode state pushed from MainDockWidget and cache it locally.

        Called by MainDockWidget whenever the focus toggle or display filter
        settings change, so this tool never needs to call back into the dock widget to read UI state.

        :param active: Whether Focus Mode is currently active.
        :type active: bool
        :param filters: Dict with filter criteria ('attributes', 'excavation_types', 'feature_names', 'drawing_name').
        :type filters: Dict[str, Any]
        """
        self._focus_active = bool(active)
        self._focus_filter = dict(filters) if filters else {}

    # MainDockWidgetから送られるTab2デジタイジングモード("new"/"edit")を受け取りキャッシュする。
    def update_tab2_mode(self, mode: str) -> None:
        """Receive the Tab2 digitizing mode pushed from MainDockWidget and cache it locally.

        Called by MainDockWidget whenever state_store.state.tab2_mode changes
        (see _on_state_changed), so this tool never needs to read
        dock_widget.state_store (or any UI state) directly to decide how
        canvasMoveEvent/_handle_digitize_click should branch.

        :param mode: New digitizing mode, expected to be "new" or "edit".
        :type mode: str
        """
        self._tab2_mode = mode if mode in ("new", "edit") else "new"
        self._reset_drag(restore_marker=True)
        self._reset_area()

    # Symbology construction/styling (apply_point_symbology) lives in
    # layer/symbology.py, reached via self.layer_manager. This tool's
    # responsibility is limited to geometry selection and canvas
    # interaction.

    # フォーカスモードのフィルター条件(update_focus_stateで受信済み)を通過した候補IDのみを返す。OFF時は候補をそのまま返す。
    def _filter_focus_candidates(
        self, candidate_ids: List[int], attr_cache: Dict[int, Dict[str, Any]]
    ) -> List[int]:
        if not self._focus_active:
            return list(candidate_ids)
        focus_filter: Dict[str, Any] = self._focus_filter
        valid_ids: List[int] = []

        target_drawing = focus_filter.get("target_drawing_name")
        req_drawing = target_drawing.strip() if target_drawing is not None else None
        if req_drawing == "-- 未指定 --":
            req_drawing = ""

        raw_attrs = focus_filter.get("attributes")
        if raw_attrs is None and "attribute_type" in focus_filter:
            raw_attrs = [focus_filter["attribute_type"]] if focus_filter["attribute_type"] else []
        req_attrs = set(raw_attrs) if raw_attrs is not None else None

        raw_excs = focus_filter.get("excavation_types")
        if raw_excs is None and "excavation_type" in focus_filter:
            raw_excs = [focus_filter["excavation_type"]] if focus_filter["excavation_type"] else []
        req_excs = set(raw_excs) if raw_excs is not None else None

        raw_feats = focus_filter.get("feature_names")
        if raw_feats is None and "feature_name" in focus_filter:
            raw_feats = [focus_filter["feature_name"]] if focus_filter["feature_name"] else []
        req_feats = set(raw_feats) if raw_feats is not None else None

        for fid in candidate_ids:
            cached = attr_cache.get(fid)
            if cached is not None:
                c_drawing = cached.get("drawing_name", "").strip()
                c_excavation = cached.get("excavation_type", "").strip()
                c_feature = cached.get("feature_name", "").strip()
                c_attribute = cached.get("attribute_type", "").strip()

                # 1. 図面判定
                if req_drawing is not None:
                    if not req_drawing:
                        if c_drawing:  # 未指定が選択されているのに図面名を持つものは除外
                            continue
                    else:
                        if c_drawing != req_drawing:  # 特定図面が選択されているのに一致しないものは除外
                            continue

                # 2. 属性判定
                if req_attrs is not None and c_attribute not in req_attrs:
                    continue

                # 3. 出土形態判定
                if req_excs is not None and c_excavation not in req_excs:
                    continue

                # 4. 遺構名判定 (出土形態が遺構の場合)
                if c_excavation == ExcavationType.FEATURE.value:
                    if req_feats is not None and c_feature not in req_feats:
                        continue

                valid_ids.append(fid)
        return valid_ids

    # 矩形(地図座標)内にあり、フォーカス/フィルター判定を通過した点のフィーチャIDを昇順で返す。
    def find_feature_ids_in_rect(self, rect: QgsRectangle) -> List[int]:
        lm = self.layer_manager or (
            getattr(self.dock_widget, "layer_manager", None) if self.dock_widget else None
        )
        if lm is None or lm.spatial_index is None:
            return []
        candidate_ids = lm.spatial_index.intersects(rect)
        if not candidate_ids:
            return []
        attr_cache = getattr(lm, "attr_cache", {})
        geom_cache = getattr(lm, "geom_cache", {})
        result: List[int] = []
        for fid in self._filter_focus_candidates(candidate_ids, attr_cache):
            geom = geom_cache.get(fid)
            if geom is None and self.point_layer and self.point_layer.isValid():
                f = self.point_layer.getFeature(fid)
                if f.isValid():
                    geom = f.geometry()
            if geom and geom.type() == 0 and rect.contains(geom.asPoint()):
                result.append(fid)
        return sorted(result)

    # QgsSpatialIndexを用いて15px以内の最近傍フィーチャIDを検索する(フォーカスモード絞り込み対応)。
    def find_nearest_feature_id(
        self, map_point: QgsPointXY
    ) -> Optional[Tuple[int, float]]:
        """Find closest feature ID to map_point within 15px using QgsSpatialIndex.

        Applies focus mode category filtering using the state most recently pushed
        via update_focus_state(), falling back to overall nearest point within 15px
        if no filtered match is found.

        :param map_point: Target point in map canvas coordinates.
        :type map_point: QgsPointXY
        :return: Tuple of (feature_id, distance) if found within tolerance, None otherwise.
        :rtype: Optional[Tuple[int, float]]
        """
        lm = self.layer_manager or (
            getattr(self.dock_widget, "layer_manager", None) if self.dock_widget else None
        )
        if lm is None or lm.spatial_index is None:
            return None

        radius = 15.0 * self.canvas.mapUnitsPerPixel()
        search_rect = QgsRectangle(
            map_point.x() - radius,
            map_point.y() - radius,
            map_point.x() + radius,
            map_point.y() + radius,
        )

        # 1. Fast bounding box intersection query via QgsSpatialIndex
        candidate_ids = lm.spatial_index.intersects(search_rect)
        if not candidate_ids:
            return None

        # 2. Focus mode filtering (state pushed one-way from the dock via update_focus_state)
        attr_cache = getattr(lm, "attr_cache", {})
        valid_ids =self._filter_focus_candidates(candidate_ids, attr_cache)

        # 3. Calculate exact Euclidean distance for candidates and select nearest
        pt_geom = QgsGeometry.fromPointXY(map_point)
        geom_cache = getattr(lm, "geom_cache", {})
        
        def find_best(fids: List[int]) -> Optional[Tuple[int, float]]:
            best_fid = None
            min_dist = float("inf")
            for fid in fids:
                geom = geom_cache.get(fid)
                if geom is None and self.point_layer and self.point_layer.isValid():
                    f = self.point_layer.getFeature(fid)
                    if f.isValid():
                        geom = f.geometry()
                if geom and geom.type() == 0:
                    dist = geom.distance(pt_geom)
                    if dist < min_dist:
                        min_dist = dist
                        best_fid = fid
            if best_fid is not None and min_dist <= radius:
                return best_fid, min_dist
            return None

        # フィルターON時は、条件に合致した(valid_ids)フィーチャのみを対象とする
        # （対象外フィーチャへのフォールバック検索は行わない）。
        # フィルターOFF時は、周辺の全フィーチャ(candidate_ids)がそのまま対象となる。
        return find_best(valid_ids)

    # 後方互換用ヘルパー。(QgsFeature, 距離)のタプルを返す。
    def find_nearest_feature(
        self, layer: QgsVectorLayer, map_point: QgsPointXY
    ) -> Optional[Tuple[QgsFeature, float]]:
        """Backward-compatible helper returning (QgsFeature, distance).

        :param layer: Target vector layer.
        :type layer: QgsVectorLayer
        :param map_point: Coordinate in canvas map coordinates.
        :type map_point: QgsPointXY
        :return: (QgsFeature, distance) if found, None otherwise.
        :rtype: Optional[Tuple[QgsFeature, float]]
        """
        nearest = self.find_nearest_feature_id(map_point)
        if nearest is not None and layer and layer.isValid():
            fid, dist = nearest
            feat = layer.getFeature(fid)
            if feat.isValid():
                return feat, dist
        return None

    # 重い処理中にキャンバス操作をロック/アンロックする(カウンタで多重ロックに対応)。
    def set_interaction_locked(self, locked: bool) -> None:
        """Lock or unlock canvas interactions during heavy operations."""
        current_count = getattr(self, "_interaction_lock_count", 0)
        if locked:
            current_count += 1
        else:
            current_count = max(0, current_count - 1)
        self._interaction_lock_count = current_count
        self._interaction_locked = (current_count > 0)

        if self._interaction_locked:
            self._reset_drag(restore_marker=True)
            self._reset_area()
            if hasattr(self, "hover_marker") and self.hover_marker:
                self.hover_marker.hide()
            self.setCursor(Qt.WaitCursor)
        else:
            self.setCursor(Qt.CrossCursor)

    @property
    # 現在インタラクションがロックされているかどうかを返す。
    def is_interaction_locked(self) -> bool:
        return getattr(self, "_interaction_locked", False)

    # 左ボタン押下を処理する。編集モードで選択マーカー近傍(15px以内)の押下時のみドラッグ準備状態に入る。
    def canvasPressEvent(self, event: QgsMapMouseEvent) -> None:
        """Handle mouse press: arm marker dragging when pressed near the selected marker."""
        self._drag_suppress_release = False
        if getattr(self, "_interaction_locked", False):
            return
        self._reset_area()
        if event.button() != Qt.LeftButton or self._tab2_mode != "edit":
            return
        # Shift+left press starts a rectangle selection; it takes priority over marker dragging.
        if event.modifiers() & Qt.ShiftModifier:
            self._area_pending = True
            self._area_active = False
            self._area_press_pos = event.pos()
            self._area_origin = self.toMapCoordinates(event.pos())
            return
        marker = self.selected_marker
        if marker is None or not marker.isVisible():
            return
        center = marker.center()
        marker_px = self.toCanvasCoordinates(center)
        press_pos = event.pos()
        dx = press_pos.x() - marker_px.x()
        dy = press_pos.y() - marker_px.y()
        if (dx * dx + dy * dy) ** 0.5 <= self._DRAG_GRAB_RADIUS_PX:
            self._drag_pending = True
            self._drag_active = False
            self._drag_press_pos = press_pos
            self._drag_origin_center = QgsPointXY(center)

    # Escでドラッグを取消し、選択マーカーを元の位置へ戻す。他のキーは親クラスへ委譲する。
    def keyPressEvent(self, event) -> None:
        """Cancel an in-progress marker drag or rectangle selection with Esc; delegate other keys."""
        if event.key() == Qt.Key_Escape and (self._area_pending or self._area_active):
            if self._area_active:
                self._drag_suppress_release = True
            self._reset_area()
            event.accept()
            return
        if event.key() == Qt.Key_Escape and (self._drag_pending or self._drag_active):
            if self._drag_active:
                self._drag_suppress_release = True
            self._reset_drag(restore_marker=True)
            event.accept()
            return
        super().keyPressEvent(event)

    # マウス移動を処理する。QgsSpatialIndexで15px以内の近傍点をハイライトする(モードにより分岐)。
    def canvasMoveEvent(self, event: QgsMapMouseEvent) -> None:
        """Handle mouse movement: highlight nearby points within 15px tolerance using QgsSpatialIndex.

        In both "new" and "edit" modes, an existing point within 15px is
        shown with the red hover marker and PointingHandCursor (in "new" mode
        this previews the snap candidate that a click would select, mirroring
        _handle_digitize_click()); with no hit the marker is hidden and the
        cursor is CrossCursor. Marker dragging (_drag_pending/_drag_active)
        only applies in "edit" mode.

        Uses the mode cached locally via update_tab2_mode() (pushed one-way
        from MainDockWidget); this tool never reads dock_widget.state_store
        directly.
        """
        if getattr(self, "_interaction_locked", False):
            if hasattr(self, "hover_marker") and self.hover_marker:
                self.hover_marker.hide()
            return

        mode = self._tab2_mode

        # Rectangle selection (edit mode only): start once movement exceeds the threshold;
        # while active only the rubber band follows (no hover processing).
        if mode == "edit" and self._area_pending and self._area_press_pos is not None:
            if not self._area_active:
                dx = event.pos().x() - self._area_press_pos.x()
                dy = event.pos().y() - self._area_press_pos.y()
                if (dx * dx + dy * dy) ** 0.5 > self._DRAG_START_THRESHOLD_PX:
                    self._area_active = True
                    if self.hover_marker:
                        self.hover_marker.hide()
            if self._area_active:
                rect = QgsRectangle(self._area_origin, self.toMapCoordinates(event.pos()))
                self._area_band.setToGeometry(QgsGeometry.fromRect(rect), None)
                self._area_band.show()
                return

        # Drag handling (edit mode only): start dragging once movement exceeds the threshold;
        # while dragging only the selected marker follows (no hover processing).
        if mode == "edit" and self._drag_pending and self._drag_press_pos is not None:
            if not self._drag_active:
                dx = event.pos().x() - self._drag_press_pos.x()
                dy = event.pos().y() - self._drag_press_pos.y()
                if (dx * dx + dy * dy) ** 0.5 > self._DRAG_START_THRESHOLD_PX:
                    self._drag_active = True
                    if self.hover_marker:
                        self.hover_marker.hide()
            if self._drag_active:
                if self.selected_marker:
                    self.selected_marker.setCenter(self.toMapCoordinates(event.pos()))
                return

        map_point = self.toMapCoordinates(event.pos())
        nearest = self.find_nearest_feature_id(map_point)

        if nearest is not None:
            fid, _ = nearest
            lm = self.layer_manager or (
                getattr(self.dock_widget, "layer_manager", None) if self.dock_widget else None
            )
            geom = getattr(lm, "geom_cache", {}).get(fid) if lm else None
            if geom is None and self.point_layer:
                f = self.point_layer.getFeature(fid)
                geom = f.geometry()

            if geom and geom.type() == 0:  # Point geometry
                pt = geom.asPoint()
                self.hover_marker.setCenter(pt)
                self.hover_marker.show()
                self.setCursor(Qt.PointingHandCursor)
                return

        self.hover_marker.hide()
        self.setCursor(Qt.CrossCursor)

    # マウスボタンリリースを処理し、連続デジタイジングロジックへ橋渡しする。
    def canvasReleaseEvent(self, event: QgsMapMouseEvent) -> None:
        """Handle mouse button release: route to continuous digitizing logic."""
        if getattr(self, "_interaction_locked", False):
            return

        if event.button() != Qt.LeftButton:
            return

        if self._drag_suppress_release:
            self._drag_suppress_release = False
            return

        if self._area_pending:
            if self._area_active and self._area_origin is not None:
                rect = QgsRectangle(self._area_origin, self.toMapCoordinates(event.pos()))
                self._reset_area()
                self._finish_area_select(rect)
                return
            # Below the drag threshold: treat as a normal click (fall through).
            self._reset_area()

        if self._drag_active:
            # Confirm the drag; the dock decides success/rejection and resyncs the marker.
            map_point = self.toMapCoordinates(event.pos())
            self._reset_drag(restore_marker=False)
            self.point_move_requested.emit(map_point)
            return
        self._reset_drag(restore_marker=False)

        map_point = self.toMapCoordinates(event.pos())
        self._handle_digitize_click(map_point)

    # 矩形内の点を抽出して複数選択マーカーを表示し、points_area_selected を発行する(0件は空リスト)。
    def _finish_area_select(self, rect: QgsRectangle) -> None:
        ids = self.find_feature_ids_in_rect(rect)
        if self.hover_marker:
            self.hover_marker.hide()
        if not ids:
            self.clear_multi_markers()
            self.points_area_selected.emit([])
            return
        lm = self.layer_manager or (
            getattr(self.dock_widget, "layer_manager", None) if self.dock_widget else None
        )
        geom_cache = getattr(lm, "geom_cache", {}) if lm else {}
        points: List[QgsPointXY] = []
        for fid in ids:
            geom = geom_cache.get(fid)
            if geom is None and self.point_layer and self.point_layer.isValid():
                f = self.point_layer.getFeature(fid)
                if f.isValid():
                    geom = f.geometry()
            if geom and geom.type() == 0:
                points.append(geom.asPoint())
        # Multi-selection hides the single selected marker (dragging then never arms).
        self.clear_selected_marker()
        self.show_multi_markers(points)
        self.points_area_selected.emit(ids)

    # メインキャンバス上のクリックを処理する。Tab2モード("new"/"edit")により新規登録/既存選択に分岐する。
    def _handle_digitize_click(self, map_point: QgsPointXY) -> None:
        """Process click event on main georeferenced canvas.

        Click behavior branches on the dock widget's tab2_current_mode
        ("new" / "edit"), pushed one-way from MainDockWidget:

        - "new" mode: existing-feature snap detection is tried first; a hit
          selects the point via existing_point_selected (the dock switches
          to edit mode). A miss is treated as a plain canvas click and
          forwarded to MainDockWidget._on_canvas_clicked for new-point
          digitizing.
        - "edit" mode: only existing-feature snap detection is performed;
          a hit selects the point via existing_point_selected as before.
          A miss (blank click) never creates a new point; it emits
          blank_click_in_edit_mode so the dock widget can clear the
          current selection while remaining in edit mode.

        Falls back to "new" mode if tab2_current_mode is missing or holds
        an unexpected value (defensive default).

        Uses the mode cached locally via update_tab2_mode() (pushed one-way
        from MainDockWidget); this tool never reads dock_widget.state_store
        directly.
        """
        if not self.dock_widget:
            return

        mode = self._tab2_mode

        if mode == "new":
            # New mode: try snapping to an existing point first; a hit selects it.
            nearest = self.find_nearest_feature_id(map_point)
            if nearest is not None and self._select_existing_feature(nearest[0]):
                return
            # Otherwise a plain canvas click. Input validation, duplicate checking,
            # feature construction and the layer write are all handled by
            # MainDockWidget._on_canvas_clicked (Step3: event-driven
            # decoupling — this tool no longer reads dock_widget state or
            # touches point_layer directly).
            self.clear_selected_marker()
            self.canvas_clicked.emit(map_point)
            return

        # Edit mode: only snap-to-existing-feature selection; a blank-space
        # click never creates a new point, but it does emit
        # blank_click_in_edit_mode so the dock widget clears the current
        # selection (the mode itself stays "edit").
        nearest = self.find_nearest_feature_id(map_point)
        if nearest is not None:
            self._select_existing_feature(nearest[0])
        else:
            # Blank click while in edit mode: keep edit mode active, but let
            # the dock widget clear any currently-selected feature.
            self.blank_click_in_edit_mode.emit()

    # 指定IDの既設点のデータdictを組み立て、選択マーカー表示と existing_point_selected 発行を行う。成功時True。
    def _select_existing_feature(self, fid: int) -> bool:
        feat = self.point_layer.getFeature(fid)
        if not feat.isValid():
            return False
        data = {
            "point_id": feat["point_id"],
            "drawing_name": (
                feat["drawing_name"]
                if "drawing_name" in feat.fields().names()
                else ""
            ),
            "excavation_type": feat["excavation_type"],
            "feature_name": feat["feature_name"],
            "color_code": feat["color_code"],
            "attribute_type": feat["attribute_type"],
            "point_name": feat["point_name"],
            "branch_no": feat["branch_no"],
            "canvas_x": feat["canvas_x"],
            "canvas_y": feat["canvas_y"],
            "feature_id": feat.id(),
        }
        # Show the persistent selection marker at the hit point's
        # exact stored location (independent of hover, remains until
        # selection changes).
        self.show_selected_marker(QgsPointXY(feat["canvas_x"], feat["canvas_y"]))
        self.existing_point_selected.emit(data)
        return True

    # キャンバス上の頂点マーカー(ホバー/選択)を安全に除去する。
    def clean_up(self) -> None:
        """Remove canvas vertex markers safely."""
        if self.hover_marker:
            try:
                self.canvas.scene().removeItem(self.hover_marker)
            except Exception:
                pass
            self.hover_marker = None
        if self.selected_marker:
            try:
                self.canvas.scene().removeItem(self.selected_marker)
            except Exception:
                pass
            self.selected_marker = None
        self.clear_multi_markers()
        if self._area_band:
            try:
                self.canvas.scene().removeItem(self._area_band)
            except Exception:
                pass
            self._area_band = None
