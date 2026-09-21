"""
/***************************************************************************
 PointerGeocoding Plugin - Georeferencing Logic (Controller)
 ***************************************************************************/

Tab 1 (画像管理・事前配置) のビジネスロジックを処理するController層です。
EventDispatcher からルーティングされた Action を受け取り、アフィン変換、ファイル操作、
レイヤの配置を実行します。UI（View）の知識は一切持ちません。
"""
import os
import math
from typing import Optional, List, Tuple, Dict, Any

from qgis.core import QgsProject, QgsPointXY, Qgis
from qgis.PyQt.QtCore import QObject
from qgis.PyQt.QtWidgets import QMessageBox, QDialog

from ..logic.transform import CoordinateTransformer
from ..logic.core import evaluate_residuals, from_survey_coords, safe_get_str
from ..ui.constants import UILabels, UIMessages
from ..ui.dialogs import GridInputDialog
from ..ui.core.state import (
    UIStateStore, SetGeorefStateAction, UIAction, SetValidationAction,
    ConfirmImageAction, DeleteLayerAction, RenameLayerAction, TransformAction, ExportLayerAction,
    SelectEditLayerAction, PreviewCanvasClickedAction, UpdateRefTableCellAction
)
from ..ui.core.validators import RequiredValidator, RegexValidator, DuplicateValidator

class GeorefLogic(QObject):
    WORLD_FILE_EXTENSIONS = (".tfw", ".jgw", ".pgw", ".bpw", ".wld")
    INVALID_CHARS_PATTERN = r'[\\/:*?"<>|]'

    def __init__(self, state_store: UIStateStore, layer_manager, layers_dict, dispatcher, iface, parent=None):
        super().__init__(parent)
        self.state_store = state_store
        self.layer_manager = layer_manager
        self.point_layer = layers_dict.get("point_layer")
        self.iface = iface
        self.parent_widget = parent

        # ディスパッチャーへハンドラとバリデータ登録
        dispatcher.register_validator(ConfirmImageAction, self.validate_confirm_image)
        dispatcher.register_handler(ConfirmImageAction, self.handle_confirm_image)
        
        dispatcher.register_handler(DeleteLayerAction, self.handle_delete_layer)
        
        dispatcher.register_validator(RenameLayerAction, self.validate_rename_layer)
        dispatcher.register_handler(RenameLayerAction, self.handle_rename_layer)
        
        dispatcher.register_validator(TransformAction, self.validate_transform)
        dispatcher.register_handler(TransformAction, self.handle_transform)
        
        dispatcher.register_validator(ExportLayerAction, self.validate_export_layer)
        dispatcher.register_handler(ExportLayerAction, self.handle_export_layer)

        dispatcher.register_handler(SelectEditLayerAction, self.handle_select_edit_layer)
        dispatcher.register_handler(PreviewCanvasClickedAction, self.handle_preview_canvas_clicked)
        dispatcher.register_handler(UpdateRefTableCellAction, self.handle_update_ref_table_cell)

        # DIされたコールバック等
        self.get_image_dialog_cb = lambda: None
        self.is_focus_mode_active_cb = lambda: False
        self.update_symbology_opacity_cb = lambda: None
        self.ensure_drawing_selected_cb = lambda name: None
        self.ensure_drawing_visible_cb = lambda name: None
        self.update_drawing_combo_cb = lambda: None
        self.preview_click_handler_cb = None

    def bind_view_callbacks(self, callbacks: Dict[str, Any]) -> None:
        self.get_image_dialog_cb = callbacks.get("get_image_dialog", self.get_image_dialog_cb)
        self.is_focus_mode_active_cb = callbacks.get("is_focus_mode_active", self.is_focus_mode_active_cb)
        self.update_symbology_opacity_cb = callbacks.get("update_symbology_opacity", self.update_symbology_opacity_cb)
        self.ensure_drawing_selected_cb = callbacks.get("ensure_drawing_selected", self.ensure_drawing_selected_cb)
        self.ensure_drawing_visible_cb = callbacks.get("ensure_drawing_visible", self.ensure_drawing_visible_cb)
        self.update_drawing_combo_cb = callbacks.get("update_drawing_combo", self.update_drawing_combo_cb)
        self.preview_click_handler_cb = callbacks.get("preview_click_handler")

    def bind_ui_panels(self, info_panel, mode_panel, image_panel, transform_panel) -> None:
        self.info_panel = info_panel
        self.mode_panel = mode_panel
        self.image_panel = image_panel
        self.transform_panel = transform_panel

    # =========================================================================
    # Select Edit Layer (編集レイヤの切り替え)
    # =========================================================================
    def handle_select_edit_layer(self, action: SelectEditLayerAction) -> Optional[UIAction]:
        layer_name = action.layer_name
        if not layer_name:
            return SetGeorefStateAction(image_path="", layer_name="", clear_ref_points=True, affine_params=None, residual_summary="")

        meta = self.layer_manager.load_image_metadata()
        layer_meta = meta.get(layer_name, {})
        image_path = layer_meta.get("file_path", "")
        
        if not image_path or not os.path.isfile(image_path):
            project = QgsProject.instance()
            for tree_layer in project.layerTreeRoot().findLayers():
                l = tree_layer.layer()
                if l and l.isValid() and l.name() == layer_name and hasattr(l, 'source'):
                    src = l.source()
                    if os.path.isfile(src):
                        image_path = src
                        break
                        
        affine = layer_meta.get("affine_params")
        ref_points = [{"name": r.get("name", ""), "pixel_x": r.get("pixel_x", 0.0), "pixel_y": r.get("pixel_y", 0.0), "real_x": r.get("real_x", 0.0), "real_y": r.get("real_y", 0.0)} for r in layer_meta.get("ref_points", [])]
        
        self.state_store.dispatch(SetGeorefStateAction(
            image_path=image_path, layer_name=layer_name, ref_points=ref_points, 
            affine_params=tuple(affine) if affine else None, residual_summary=""
        ))
        
        if image_path:
            self._open_preview_canvas(image_path)
            
        return None

    # =========================================================================
    # 画像選択・確認 (Confirm)
    # =========================================================================
    def validate_confirm_image(self, action: ConfirmImageAction) -> Optional[str]:
        state = self.state_store.state
        if state.tab1_mode == "edit":
            return None  # 編集モード時はプレビュー再表示のみなのでバリデーション不要

        # View側で行っていたバリデーションをDispatcherパイプラインへ移動
        if not action.layer_name:
            return UIMessages.ERR_REQUIRED_IMAGE_NAME
            
        result = RegexValidator(self.INVALID_CHARS_PATTERN).validate(action.layer_name)
        if not result.is_valid:
            return UIMessages.ERR_INVALID_IMAGE_NAME
            
        meta = self.layer_manager.load_image_metadata()
        if action.layer_name in meta:
            return UIMessages.ERR_DUPLICATE_LAYER_NAME.format(name=action.layer_name)

        if not action.image_path or not os.path.isfile(action.image_path):
            return UIMessages.ERR_INVALID_IMAGE
            
        src_base, _ = os.path.splitext(action.image_path)
        if any(os.path.isfile(src_base + ext) for ext in self.WORLD_FILE_EXTENSIONS):
            return UIMessages.ERR_SOURCE_HAS_WORLDFILE
            
        return None

    def handle_confirm_image(self, action: ConfirmImageAction) -> Optional[UIAction]:
        state = self.state_store.state
        if state.tab1_mode == "edit":
            if state.current_copied_image_path:
                self._open_preview_canvas(state.current_copied_image_path)
            return None

        self.state_store.dispatch(SetGeorefStateAction(
            layer_name=action.layer_name,
            image_path=action.image_path,
            clear_ref_points=True,
            affine_params=None,
            residual_summary=""
        ))
        self._open_preview_canvas(action.image_path)
        return None

    def _open_preview_canvas(self, image_path: str):
        state = self.state_store.state
        dialog = self.get_image_dialog_cb()
        
        if dialog and dialog.raster_layer is not None:
            current_src = dialog.raster_layer.source()
            if os.path.normcase(os.path.normpath(current_src)) != os.path.normcase(os.path.normpath(image_path)):
                self._create_preview_layer(image_path)
            else:
                dialog.set_ref_points_data(state.ref_points_data)
                dialog.show()
                dialog.raise_()
                dialog.activateWindow()
        else:
            self._create_preview_layer(image_path)

    def _create_preview_layer(self, image_path: str):
        success, msg, r_layer = self.layer_manager.load_preview_raster(image_path)
        if not success or r_layer is None:
            self.state_store.dispatch(SetValidationAction(has_error=True, message=UIMessages.ERR_PREVIEW_FAILED.format(msg=msg)))
            return
        dialog = self.get_image_dialog_cb()
        if dialog:
            dialog.setup_raster(r_layer, self.preview_click_handler_cb, self.state_store.state.ref_points_data)
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()

    # =========================================================================
    # プレビュークリック (スナップ・ダイアログ処理)
    # =========================================================================
    def handle_preview_canvas_clicked(self, action: PreviewCanvasClickedAction) -> Optional[UIAction]:
        pixel_x, pixel_y = action.pixel_x, action.pixel_y
        ref_points = self.state_store.state.ref_points_data
        dialog = self.get_image_dialog_cb()
        snapped_index = None

        # スナップ判定 (Controllerの管轄)
        if dialog and dialog.raster_layer and dialog.georef_tool:
            tool, rlayer = dialog.georef_tool, dialog.raster_layer
            extent, w, h = rlayer.extent(), float(rlayer.width()), float(rlayer.height())
            if w > 0 and h > 0:
                click_map_x = extent.xMinimum() + (pixel_x / w) * extent.width()
                click_map_y = extent.yMaximum() - (pixel_y / h) * extent.height()
                click_screen = tool.toCanvasCoordinates(QgsPointXY(click_map_x, click_map_y))

                min_dist = float("inf")
                for idx, rdata in enumerate(ref_points):
                    rx, ry = float(rdata["pixel_x"]), float(rdata["pixel_y"])
                    r_map_x = extent.xMinimum() + (rx / w) * extent.width()
                    r_map_y = extent.yMaximum() - (ry / h) * extent.height()
                    r_screen = tool.toCanvasCoordinates(QgsPointXY(r_map_x, r_map_y))
                    dist = math.hypot(click_screen.x() - r_screen.x(), click_screen.y() - r_screen.y())
                    if dist <= 15.0 and dist < min_dist:
                        min_dist, snapped_index = dist, idx

        if snapped_index is not None:
            existing = dict(ref_points[snapped_index])
            others = [r["name"] for i, r in enumerate(ref_points) if i != snapped_index]
            dlg = GridInputDialog(self.layer_manager, existing_point=existing, existing_names=others, parent=dialog or self.parent_widget)
            if dlg.exec_() == QDialog.Accepted:
                new_refs = list(ref_points)
                if dlg.dialog_action == "delete":
                    del new_refs[snapped_index]
                elif dlg.dialog_action == "confirm":
                    new_refs[snapped_index] = existing
                    new_refs[snapped_index]["name"] = dlg.result_grid_name
                    new_refs[snapped_index]["real_x"] = dlg.result_real_x
                    new_refs[snapped_index]["real_y"] = dlg.result_real_y
                return SetGeorefStateAction(ref_points=new_refs, affine_params=None)
            return None

        if len(ref_points) >= 4:
            QMessageBox.information(self.parent_widget, UIMessages.MSG_TITLE_LIMIT, UIMessages.MSG_LIMIT_REFS)
            return None

        others = [r["name"] for r in ref_points]
        dlg = GridInputDialog(self.layer_manager, existing_point=None, existing_names=others, parent=dialog or self.parent_widget)
        if dlg.exec_() == QDialog.Accepted and dlg.dialog_action == "confirm":
            new_refs = list(ref_points)
            new_refs.append({"name": dlg.result_grid_name, "pixel_x": pixel_x, "pixel_y": pixel_y, "real_x": dlg.result_real_x, "real_y": dlg.result_real_y})
            return SetGeorefStateAction(ref_points=new_refs, affine_params=None)
            
        return None

    def handle_update_ref_table_cell(self, action: UpdateRefTableCellAction) -> Optional[UIAction]:
        ref_points = self.state_store.state.ref_points_data
        if action.row >= len(ref_points) or action.column not in (2, 3): 
            return None

        new_refs = [dict(r) for r in ref_points]
        try:
            if action.text_x and action.text_y:
                math_x, math_y = from_survey_coords(float(action.text_x), float(action.text_y))
                new_refs[action.row]["real_x"], new_refs[action.row]["real_y"] = math_x, math_y
            else:
                new_refs[action.row]["real_x"], new_refs[action.row]["real_y"] = None, None
        except ValueError:
            new_refs[action.row]["real_x"], new_refs[action.row]["real_y"] = None, None

        return SetGeorefStateAction(ref_points=new_refs, affine_params=None)

    # =========================================================================
    # レイヤ操作 (Delete / Rename)
    # =========================================================================
    def handle_delete_layer(self, action: DeleteLayerAction) -> Optional[UIAction]:
        layer_name = action.layer_name
        
        # 確認ダイアログ等は View層ではなく Action発行の前に済ませるか、Controllerが出す。
        # 本システムではMessageBoxはControllerが出してよい設計とされている。
        reply = QMessageBox.question(
            self.parent_widget, UIMessages.MSG_CONFIRM_DELETE_LAYER_TITLE,
            UIMessages.MSG_CONFIRM_DELETE_LAYER.format(name=layer_name),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes: return None
        
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
            
        dialog = self.get_image_dialog_cb()
        if dialog: dialog.clean_up()

        return SetGeorefStateAction(image_path="", layer_name="", clear_ref_points=True, affine_params=None, residual_summary="")

    def validate_rename_layer(self, action: RenameLayerAction) -> Optional[str]:
        if not action.new_name:
            return UIMessages.ERR_REQUIRED_IMAGE_NAME
        result = RegexValidator(self.INVALID_CHARS_PATTERN).validate(action.new_name)
        if not result.is_valid:
            return UIMessages.ERR_INVALID_IMAGE_NAME
            
        if action.old_name == action.new_name:
            return "変更がありません。"
        meta = self.layer_manager.load_image_metadata()
        if action.old_name not in meta:
            return UIMessages.ERR_LAYER_META_NOT_FOUND.format(name=action.old_name)
        if action.new_name in meta:
            return UIMessages.ERR_DUPLICATE_LAYER_NAME.format(name=action.new_name)
        return None

    def handle_rename_layer(self, action: RenameLayerAction) -> Optional[UIAction]:
        old_name, new_name = action.old_name, action.new_name
        project = QgsProject.instance()
        for tree_layer in project.layerTreeRoot().findLayers():
            layer = tree_layer.layer()
            if layer and layer.name() == old_name:
                layer.setName(new_name)
                break

        meta = self.layer_manager.load_image_metadata()
        meta[new_name] = meta.pop(old_name)
        self.layer_manager.save_image_metadata(meta)
        
        image_path = meta[new_name].get("file_path", self.state_store.state.current_copied_image_path)
        self.layer_manager.rename_drawing_name(old_name, new_name)
        
        self.ensure_drawing_selected_cb(new_name)
        QMessageBox.information(self.parent_widget, UIMessages.MSG_RENAME_LAYER_SUCCESS_TITLE, UIMessages.MSG_RENAME_LAYER_SUCCESS.format(old=old_name, new=new_name))

        return SetGeorefStateAction(layer_name=new_name, image_path=image_path)

    # =========================================================================
    # 座標変換・配置 (Transform / Export)
    # =========================================================================
    def validate_transform(self, action: TransformAction) -> Optional[str]:
        state = self.state_store.state
        if len(state.ref_points_data) < 2:
            return UIMessages.ERR_MIN_2_REFS
        for rdata in state.ref_points_data:
            if rdata["real_x"] is None or rdata["real_y"] is None:
                return UIMessages.ERR_INPUT_REAL_COORDS.format(name=rdata["name"])
        return None

    def handle_transform(self, action: TransformAction) -> Optional[UIAction]:
        state = self.state_store.state
        local_pts, real_pts = [], []
        for rdata in state.ref_points_data:
            local_pts.append((float(rdata["pixel_x"]), float(rdata["pixel_y"])))
            real_pts.append((float(rdata["real_x"]), float(rdata["real_y"])))

        affine_params = CoordinateTransformer.compute_affine_points(local_pts, real_pts, parent=None)
        if affine_params is None:
            return SetValidationAction(has_error=True, message="座標変換パラメータの算出に失敗しました。")

        rotation_deg, aspect_ratio_pct = evaluate_residuals(state.ref_points_data, affine_params)
        mode_str = UILabels.TRANSFORM_HELMERT if len(local_pts) == 2 else UILabels.TRANSFORM_AFFINE.format(count=len(local_pts))
        res_summary = (
            f"【{mode_str} 計算完了】\n"
            f"画像の回転角度: {rotation_deg:.2f} 度\n"
            f"アスペクト比(縦/横): {aspect_ratio_pct:.2f} %"
        )
        
        if self.iface:
            self.iface.messageBar().pushMessage(
                UIMessages.MSG_TITLE_INFO, UILabels.MSG_TRANSFORM_SUCCESS,
                level=Qgis.MessageLevel.Success, duration=4,
            )
            
        return SetGeorefStateAction(affine_params=affine_params, residual_summary=res_summary)

    def validate_export_layer(self, action: ExportLayerAction) -> Optional[str]:
        state = self.state_store.state
        if state.calculated_affine_params is None:
            return UILabels.ERR_TRANSFORM_NOT_CALCULATED
        if not state.current_copied_image_path or not os.path.isfile(state.current_copied_image_path):
            return UIMessages.ERR_IMAGE_FILE_NOT_FOUND
        return None

    def handle_export_layer(self, action: ExportLayerAction) -> Optional[UIAction]:
        from ..logic.transform import update_point_layer_geometry
        state = self.state_store.state
        dest_path = state.current_copied_image_path
        
        session_img_dir = self.layer_manager.session_image_dir
        current_dir = os.path.normcase(os.path.normpath(os.path.dirname(dest_path)))
        already_in_session = bool(session_img_dir) and current_dir == os.path.normcase(os.path.normpath(session_img_dir))
        
        if not already_in_session:
            success, msg, copy_path = self.layer_manager.copy_image_to_session(dest_path)
            if not success:
                return SetValidationAction(has_error=True, message=msg)
            dest_path = copy_path

        success, msg, _ = self.layer_manager.write_world_file(dest_path, state.calculated_affine_params)
        if not success:
            return SetValidationAction(has_error=True, message=UIMessages.ERR_WORLDFILE_FAILED.format(msg=msg))

        self.layer_manager.update_image_metadata(
            action.layer_name, dest_path, state.ref_points_data, state.calculated_affine_params
        )

        if self.point_layer and self.point_layer.isValid():
            update_point_layer_geometry(self.point_layer, state.calculated_affine_params, drawing_name=action.layer_name)

        success, msg, raster_layer = self.layer_manager.load_georeferenced_raster(
            dest_path, custom_layer_name=action.layer_name
        )
        if not success or raster_layer is None:
            return SetValidationAction(has_error=True, message=UIMessages.ERR_CANVAS_PLACEMENT_FAILED.format(msg=msg))

        if self.iface:
            self.iface.mapCanvas().setExtent(raster_layer.extent())
            self.iface.mapCanvas().refresh()
            self.iface.messageBar().pushMessage(
                UIMessages.MSG_GEOREF_COMPLETE_TITLE, UIMessages.MSG_GEOREF_COMPLETE,
                level=Qgis.MessageLevel.Success, duration=6,
            )

        self.update_drawing_combo_cb()
        self.ensure_drawing_selected_cb(action.layer_name)
        self.ensure_drawing_visible_cb(action.layer_name)
        dialog = self.get_image_dialog_cb()
        if dialog: dialog.close()

        if state.tab1_mode == "new":
            return SetGeorefStateAction(image_path="", layer_name="", clear_ref_points=True, affine_params=None, residual_summary="")
        return None