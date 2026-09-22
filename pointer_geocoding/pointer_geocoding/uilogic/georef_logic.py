"""
/***************************************************************************
 PointerGeocoding Plugin - Georeferencing Logic (Controller)
 ***************************************************************************/

Tab 1 (画像管理・事前配置) のイベントに対するドメインロジックを実行するController層です。
GUI（QMessageBox等）の操作は完全にViewへ移譲され、EventDispatcherを介した
安全な処理（例外キャッチ・ビジーガード）を提供します。
"""
# 【変更不可侵の絶対的ルール】 測量座標系（X軸=南北, Y軸=東西）を採用。QGISキャンバス上のX座標(東西)はSurvey Y、Y座標(南北)はSurvey Xに対応する。

import os
import math
from dataclasses import dataclass
from typing import Optional, List, Tuple, Dict, Any

from qgis.core import QgsProject, QgsPointXY
from qgis.PyQt.QtCore import QObject

from ..logic.transform import CoordinateTransformer
from ..logic.core import (
    to_survey_coords,
    from_survey_coords,
    update_point_layer_geometry,
    evaluate_residuals,
    safe_get_str,
)
from ..ui.core.state import UIAction, SetGeorefStateAction, SetValidationAction


@dataclass
class DeleteLayerAction(UIAction):
    layer_name: str
    has_points: bool

@dataclass
class RenameLayerAction(UIAction):
    old_name: str
    new_name: str

@dataclass
class ExecuteTransformAction(UIAction):
    pass

@dataclass
class ExportLayerAction(UIAction):
    layer_name: str
    image_path: str


class GeorefLogic(QObject):
    """
    画像管理・幾何補正（ジオリファレンス）の純粋なビジネスロジックを担うクラス。
    """
    INVALID_CHARS_PATTERN = r'[\\/:*?"<>|]'
    WORLD_FILE_EXTENSIONS = (".tfw", ".jgw", ".pgw", ".bpw", ".wld")

    def __init__(self, state_store, layer_manager, layers_dict, iface, dispatcher, parent=None):
        super().__init__(parent)
        self.state_store = state_store
        self.layer_manager = layer_manager
        self.layers_dict = layers_dict
        self.iface = iface
        self.dispatcher = dispatcher
        self.point_layer = layers_dict.get("point_layer")
        self.parent_widget = parent

        self._is_modifying_layer = False

        # ハンドラの登録
        self.dispatcher.register_handler(DeleteLayerAction, self.handle_delete_layer)
        self.dispatcher.register_handler(RenameLayerAction, self.handle_rename_layer)
        self.dispatcher.register_handler(ExecuteTransformAction, self.handle_execute_transform)
        self.dispatcher.register_handler(ExportLayerAction, self.handle_export_layer)

        # View からのコールバック (DI)
        self.get_image_dialog_cb = lambda: None
        self.is_focus_mode_active_cb = lambda: False
        self.update_symbology_opacity_cb = lambda: None
        self.ensure_drawing_selected_cb = lambda name: None
        self.ensure_drawing_visible_cb = lambda name: None
        self.update_drawing_combo_cb = lambda: None

    def bind_view_callbacks(self, callbacks: Dict[str, Any]) -> None:
        """View層で解決されるべき操作を注入する"""
        self.get_image_dialog_cb = callbacks.get("get_image_dialog", self.get_image_dialog_cb)
        self.is_focus_mode_active_cb = callbacks.get("is_focus_mode_active", self.is_focus_mode_active_cb)
        self.update_symbology_opacity_cb = callbacks.get("update_symbology_opacity", self.update_symbology_opacity_cb)
        self.ensure_drawing_selected_cb = callbacks.get("ensure_drawing_selected", self.ensure_drawing_selected_cb)
        self.ensure_drawing_visible_cb = callbacks.get("ensure_drawing_visible", self.ensure_drawing_visible_cb)
        self.update_drawing_combo_cb = callbacks.get("update_drawing_combo", self.update_drawing_combo_cb)

    # =========================================================================
    # View向けヘルパーメソッド（純粋計算・状態取得）
    # =========================================================================

    def set_modifying_layer(self, is_modifying: bool) -> None:
        self._is_modifying_layer = is_modifying

    def is_modifying_layer(self) -> bool:
        return self._is_modifying_layer

    def convert_to_math_coords(self, sx: float, sy: float) -> Tuple[float, float]:
        """測量座標から数学座標への変換アダプタ呼び出し (ルール [RULE-GEO-01])"""
        return from_survey_coords(sx, sy)

    def convert_to_survey_coords(self, math_x: float, math_y: float) -> Tuple[float, float]:
        """数学座標から測量座標への変換アダプタ呼び出し (ルール [RULE-GEO-01])"""
        return to_survey_coords(math_x, math_y)

    def get_residuals_summary(self, ref_points: List[Dict[str, Any]], affine_params: Tuple) -> Tuple[float, float]:
        return evaluate_residuals(ref_points, affine_params)

    def check_layer_has_points(self, layer_name: str) -> bool:
        """指定レイヤに属する打刻点が存在するかどうかを返す"""
        if self.point_layer and self.point_layer.isValid() and "drawing_name" in self.point_layer.fields().names():
            for f in self.point_layer.getFeatures():
                if safe_get_str(f, "drawing_name") == layer_name:
                    return True
        return False

    def load_edit_layer_metadata(self, layer_name: str) -> Optional[Dict[str, Any]]:
        """編集対象レイヤのメタデータをロードし、整合性を担保して返す"""
        meta = self.layer_manager.load_image_metadata()
        layer_meta = meta.get(layer_name, {})
        image_path = layer_meta.get("file_path", "")
        
        # パスが見つからない場合はプロジェクトから探索
        if not image_path or not os.path.isfile(image_path):
            project = QgsProject.instance()
            for tree_layer in project.layerTreeRoot().findLayers():
                l = tree_layer.layer()
                if l and l.isValid() and l.name() == layer_name and hasattr(l, 'source'):
                    src = l.source()
                    if os.path.isfile(src):
                        image_path = src
                        break
        
        if not image_path:
            return None
            
        affine_params = layer_meta.get("affine_params")
        if affine_params is not None:
            affine_params = tuple(affine_params)
            
        ref_points = [{
            "name": r.get("name", ""),
            "pixel_x": r.get("pixel_x", 0.0),
            "pixel_y": r.get("pixel_y", 0.0),
            "real_x": r.get("real_x", 0.0),
            "real_y": r.get("real_y", 0.0),
        } for r in layer_meta.get("ref_points", [])]
            
        return {
            "image_path": image_path,
            "layer_name": layer_name,
            "ref_points": ref_points,
            "affine_params": affine_params
        }

    def show_preview_if_needed(self, on_point_clicked_cb) -> None:
        """UIStateのパスに基づいてプレビューキャンバスを準備・表示する"""
        state = self.state_store.state
        if not state.current_copied_image_path or not os.path.isfile(state.current_copied_image_path):
            return

        image_dialog = self.get_image_dialog_cb()
        if image_dialog and image_dialog.raster_layer is not None:
            current_src = image_dialog.raster_layer.source()
            if os.path.normcase(os.path.normpath(current_src)) != os.path.normcase(os.path.normpath(state.current_copied_image_path)):
                self._create_preview_canvas(state.current_copied_image_path, on_point_clicked_cb)
            else:
                image_dialog.set_ref_points_data(state.ref_points_data)
                image_dialog.show()
                image_dialog.raise_()
                image_dialog.activateWindow()
        else:
            self._create_preview_canvas(state.current_copied_image_path, on_point_clicked_cb)

    def _create_preview_canvas(self, image_path: str, on_point_clicked_cb) -> bool:
        success, msg, raster_layer = self.layer_manager.load_preview_raster(image_path)
        if not success or raster_layer is None:
            self.state_store.dispatch(SetValidationAction(True, msg))
            return False

        image_dialog = self.get_image_dialog_cb()
        if image_dialog:
            ref_points_data = self.state_store.state.ref_points_data
            image_dialog.setup_raster(raster_layer, on_point_clicked_cb, ref_points_data)
            # setup_raster()冒頭のclean_up()で古いImageGeorefToolのマーカーは全消去され、
            # 新規ImageGeorefToolにはset_ref_points_data()によるスナップ用データしか渡らない
            # （マーカーシンボル自体は生成されない）ため、ここで明示的に再構築する。
            for rdata in ref_points_data:
                image_dialog.add_marker(rdata["pixel_x"], rdata["pixel_y"], rdata.get("name", ""))
            image_dialog.show()
            image_dialog.raise_()
            image_dialog.activateWindow()

        return True

    def find_snapped_ref_point(self, pixel_x: float, pixel_y: float) -> Optional[int]:
        """プレビューキャンバス上でのクリック座標から、スナップ対象となる既存の基準点インデックスを返す"""
        image_dialog = self.get_image_dialog_cb()
        ref_points = self.state_store.state.ref_points_data
        
        if image_dialog and image_dialog.raster_layer and image_dialog.georef_tool:
            tool = image_dialog.georef_tool
            rlayer = image_dialog.raster_layer
            extent = rlayer.extent()
            w = float(rlayer.width())
            h = float(rlayer.height())

            if w > 0 and h > 0 and extent.width() > 0 and extent.height() > 0:
                click_map_x = extent.xMinimum() + (pixel_x / w) * extent.width()
                click_map_y = extent.yMaximum() - (pixel_y / h) * extent.height()
                click_screen = tool.toCanvasCoordinates(QgsPointXY(click_map_x, click_map_y))

                min_dist = float("inf")
                snapped_index = None
                for idx, rdata in enumerate(ref_points):
                    rx = float(rdata["pixel_x"])
                    ry = float(rdata["pixel_y"])
                    r_map_x = extent.xMinimum() + (rx / w) * extent.width()
                    r_map_y = extent.yMaximum() - (ry / h) * extent.height()
                    r_screen = tool.toCanvasCoordinates(QgsPointXY(r_map_x, r_map_y))
                    dist = math.hypot(click_screen.x() - r_screen.x(), click_screen.y() - r_screen.y())
                    if dist <= 15.0 and dist < min_dist:
                        min_dist = dist
                        snapped_index = idx
                return snapped_index
        return None

    # =========================================================================
    # EventDispatcher Action Handlers (Heavy Logic & Persistence)
    # =========================================================================

    def handle_delete_layer(self, action: DeleteLayerAction) -> Optional[List[UIAction]]:
        layer_name = action.layer_name

        if action.has_points:
            self.layer_manager.clear_drawing_name_for_layer(layer_name)

        project = QgsProject.instance()
        for tree_layer in project.layerTreeRoot().findLayers():
            l = tree_layer.layer()
            if l and l.name() == layer_name:
                project.removeMapLayer(l.id())
                break

        meta = self.layer_manager.load_image_metadata()
        if layer_name in meta:
            file_path = meta[layer_name].get("file_path", "")
            if os.path.exists(file_path):
                try: os.remove(file_path)
                except Exception: pass

            base, _ = os.path.splitext(file_path)
            for ext in self.WORLD_FILE_EXTENSIONS:
                if os.path.exists(base + ext):
                    try: os.remove(base + ext)
                    except Exception: pass

            self.layer_manager.delete_image_metadata(layer_name)

        image_dialog = self.get_image_dialog_cb()
        if image_dialog is not None:
            image_dialog.clean_up()

        if self.is_focus_mode_active_cb():
            self.update_symbology_opacity_cb()
            
        return []

    def handle_rename_layer(self, action: RenameLayerAction) -> Optional[List[UIAction]]:
        old_name = action.old_name
        new_name = action.new_name

        meta = self.layer_manager.load_image_metadata()
        if new_name in meta:
            return [SetValidationAction(True, f"同名のレイヤが既に存在します: {new_name}")]

        project = QgsProject.instance()
        for tree_layer in project.layerTreeRoot().findLayers():
            layer = tree_layer.layer()
            if layer and layer.name() == old_name:
                layer.setName(new_name)
                break

        meta[new_name] = meta.pop(old_name)
        self.layer_manager.save_image_metadata(meta)
        self.layer_manager.rename_drawing_name(old_name, new_name)

        image_path = meta[new_name].get("file_path", self.state_store.state.current_copied_image_path)
        if self.is_focus_mode_active_cb():
            self.update_symbology_opacity_cb()
        self.ensure_drawing_selected_cb(new_name)

        return [SetGeorefStateAction(layer_name=new_name, image_path=image_path)]

    def handle_execute_transform(self, action: ExecuteTransformAction) -> Optional[List[UIAction]]:
        state = self.state_store.state
        local_pts = [(float(r["pixel_x"]), float(r["pixel_y"])) for r in state.ref_points_data]
        real_pts = [(float(r["real_x"]), float(r["real_y"])) for r in state.ref_points_data]

        affine_params = CoordinateTransformer.compute_affine_points(local_pts, real_pts, parent=self.parent_widget)
        if affine_params is None:
            return [SetValidationAction(True, "座標変換の計算に失敗しました。")]

        return [SetGeorefStateAction(affine_params=affine_params)]

    def handle_export_layer(self, action: ExportLayerAction) -> Optional[List[UIAction]]:
        state = self.state_store.state
        layer_name = action.layer_name
        src_path = action.image_path

        session_img_dir = self.layer_manager.session_image_dir
        current_dir = os.path.normcase(os.path.normpath(os.path.dirname(src_path)))
        already_in_session = bool(session_img_dir) and current_dir == os.path.normcase(os.path.normpath(session_img_dir))

        dest_path = src_path
        if not already_in_session:
            success, msg, copy_path = self.layer_manager.copy_image_to_session(src_path)
            if not success:
                return [SetValidationAction(True, msg)]
            dest_path = copy_path

        success, msg, _ = self.layer_manager.write_world_file(dest_path, state.calculated_affine_params)
        if not success:
            return [SetValidationAction(True, f"ワールドファイルの書き込みに失敗: {msg}")]

        self.layer_manager.update_image_metadata(
            layer_name, dest_path, state.ref_points_data, state.calculated_affine_params
        )

        if self.point_layer and self.point_layer.isValid():
            update_point_layer_geometry(self.point_layer, state.calculated_affine_params, drawing_name=layer_name)

        success, msg, raster_layer = self.layer_manager.load_georeferenced_raster(
            dest_path, custom_layer_name=layer_name
        )
        if not success or raster_layer is None:
            return [SetValidationAction(True, f"キャンバス配置に失敗: {msg}")]

        self.iface.mapCanvas().setExtent(raster_layer.extent())
        self.iface.mapCanvas().refresh()

        self.update_drawing_combo_cb()
        self.ensure_drawing_selected_cb(layer_name)
        self.ensure_drawing_visible_cb(layer_name)

        return []