"""
/***************************************************************************
 PointerGeocoding Plugin - Digitizing Logic (Controller)
 ***************************************************************************/

Step A-2: UIイベントを受容し、ビジネスロジック（打刻・編集・重複チェック・コミット）
を処理するController層です。View層からは BuiltPanel を注入（DI）されることで
直接イベントをバインドし、循環参照（Circular Import）を防ぎます。
"""
from typing import Dict, Any, Optional, Tuple
from contextlib import nullcontext

from qgis.core import QgsPointXY, QgsProject, Qgis
from qgis.PyQt.QtCore import QObject

from ..logic.core import (
    check_point_duplicate, build_point_ident, get_next_point_number,
    get_next_point_id, build_digitized_feature, insert_feature_to_layer,
    pixel_from_affine, safe_get_str, ExcavationType, AttributeType
)
from ..ui.constants import UILabels, UIMessages
from ..ui.core.state import (
    UIStateStore, ChangeTab2ModeAction, SelectPointAction, ChangeAutonumModeAction,
    SetValidationAction, SetPointInfoErrorAction, SetDigitizedWithBranchAction,
    ResetSelectionAction, SetFocusModeAction
)
from ..ui.dialogs import PointNameEntryDialog, PointEditDialog
from ..ui.core.builder import BuiltPanel


class DigitizingLogic(QObject):
    """
    打刻・編集・重複チェック・コミット制御を担うControllerクラス。
    """
    def __init__(
        self,
        state_store: UIStateStore,
        layer_manager: Any,
        layers_dict: Dict[str, Any],
        iface: Any,
        parent: Optional[QObject] = None
    ):
        super().__init__(parent)
        self.state_store = state_store
        self.layer_manager = layer_manager
        self.iface = iface
        self.point_layer = layers_dict.get("point_layer")
        
        # 注入されるViewコールバックとUIコンポーネント
        self.get_digitizing_input_state_cb = None
        self.get_target_drawing_name_cb = None
        self.is_sp_attribute_cb = None
        self.get_attribute_value_cb = None
        self.get_current_point_name_and_branch_cb = None
        self.is_feature_name_missing_cb = None
        self.busy_interaction_guard_cb = lambda: nullcontext()
        self.update_symbology_opacity_cb = None
        self.get_drawing_layer_names_cb = None
        self.apply_next_point_number_cb = None
        self.refresh_point_info_labels_cb = None
        self.category_changed_cb = None
        self.excavation_type_changed_cb = None
        self.map_tool = None
        self.parent_widget = None

    # ==========================================
    # DI (依存性の注入)
    # ==========================================
    def bind_view_callbacks(self, callbacks: Dict[str, Any]):
        """View層から必要な情報取得メソッドやヘルパーをバインドする"""
        self.get_digitizing_input_state_cb = callbacks.get("get_digitizing_input_state")
        self.get_target_drawing_name_cb = callbacks.get("get_target_drawing_name")
        self.is_sp_attribute_cb = callbacks.get("is_sp_attribute")
        self.get_attribute_value_cb = callbacks.get("get_attribute_value")
        self.get_current_point_name_and_branch_cb = callbacks.get("get_current_point_name_and_branch")
        self.is_feature_name_missing_cb = callbacks.get("is_feature_name_missing")
        self.busy_interaction_guard_cb = callbacks.get("busy_interaction_guard", lambda: nullcontext())
        self.update_symbology_opacity_cb = callbacks.get("update_symbology_opacity")
        self.get_drawing_layer_names_cb = callbacks.get("get_drawing_layer_names")
        self.apply_next_point_number_cb = callbacks.get("apply_next_point_number")
        self.refresh_point_info_labels_cb = callbacks.get("refresh_point_info_labels")
        self.category_changed_cb = callbacks.get("category_changed")
        self.excavation_type_changed_cb = callbacks.get("excavation_type_changed")
        self.map_tool = callbacks.get("map_tool")
        self.parent_widget = callbacks.get("parent_widget")

    def bind_ui_panels(self, mode_panel: BuiltPanel, point_info_panel: BuiltPanel, attribute_panel: BuiltPanel, display_panel: BuiltPanel):
        """Viewから BuiltPanel インスタンスを受け取り、Controller自身でシグナルをバインドする"""
        self.mode_panel = mode_panel
        self.point_info_panel = point_info_panel
        self.attribute_panel = attribute_panel
        self.display_panel = display_panel

        # コントローラー主導のイベントバインド（一方向依存を維持）
        self.mode_panel.bind("mode_changed", self._on_mode_changed)
        self.point_info_panel.bind("autonum_mode_changed", self._on_autonum_mode_changed)
        self.point_info_panel.bind("delete_point_clicked", self.handle_delete_selected_point)
        self.point_info_panel.bind("point_identity_changed", self.validate_and_sync)
        self.point_info_panel.bind("branch_text_changed", self._on_branch_text_changed)
        
        self.attribute_panel.bind("category_changed", self._on_category_changed)
        self.attribute_panel.bind("excavation_type_changed", self._on_excavation_type_changed)
        self.attribute_panel.bind("feature_combo_changed", self.validate_and_sync)
        
        self.display_panel.bind("filter_toggled", self._on_filter_toggled)

    # ==========================================
    # UI イベント受容ロジック
    # ==========================================
    def _on_mode_changed(self, index: int):
        mode = "new" if index == 0 else "edit"
        self.state_store.dispatch(ChangeTab2ModeAction(mode))
        if mode == "new" and self.state_store.state.selected_point_id is not None:
            self.state_store.dispatch(ResetSelectionAction())
        self.validate_and_sync()

    def _on_autonum_mode_changed(self, index: int):
        mode = "auto" if index == 0 else "release"
        self.state_store.dispatch(ChangeAutonumModeAction(mode))
        if mode == "auto" and not self.is_sp_attribute_cb():
            if self.apply_next_point_number_cb:
                self.apply_next_point_number_cb()
        self.validate_and_sync()

    def _on_branch_text_changed(self, text: str):
        if not text.strip() and self.state_store.state.has_digitized_with_branch:
            if self.apply_next_point_number_cb:
                self.apply_next_point_number_cb()
            self.state_store.dispatch_silent(SetDigitizedWithBranchAction(False))
        self.validate_and_sync()

    def _on_category_changed(self, *args):
        if self.category_changed_cb:
            self.category_changed_cb()
        self.validate_and_sync()

    def _on_excavation_type_changed(self, index: int):
        if self.excavation_type_changed_cb:
            self.excavation_type_changed_cb()
        self.validate_and_sync()

    def _on_filter_toggled(self, checked: bool):
        self.state_store.dispatch(SetFocusModeAction(checked))

    # ==========================================
    # ビジネスロジック・バリデーション
    # ==========================================
    def validate_and_sync(self, *args):
        if self.state_store.state.suppress_realtime_commit:
            return
        if self.refresh_point_info_labels_cb:
            self.refresh_point_info_labels_cb()

        input_state = self.get_digitizing_input_state_cb()
        pname = input_state.get("point_name", "")
        branch = input_state.get("branch_no", "")
        ex_type = input_state.get("excavation_type", "")
        feat_name = input_state.get("feature_name", "")
        
        is_feat_missing = self.is_feature_name_missing_cb()
        dup_ident = self.check_realtime_duplicate(
            ex_type, feat_name, pname, branch, self.state_store.state.selected_point_id
        )
        
        is_editing = self.state_store.state.selected_point_id is not None
        out_of_bounds = self.check_realtime_out_of_bounds(self.state_store.state.selected_point_id) if is_editing else self.state_store.state.is_out_of_bounds
        
        has_err = is_feat_missing or bool(dup_ident) or out_of_bounds
        
        status_msg = ""
        if is_feat_missing:
            status_msg = UILabels.STATUS_ERR_FEATURE_REQUIRED
        elif out_of_bounds:
            status_msg = UILabels.STATUS_ERR_OUT_OF_BOUNDS
        elif dup_ident:
            status_msg = UILabels.STATUS_ERR_DUPLICATE
            
        self.state_store.dispatch(SetValidationAction(has_err, status_msg))
        self.state_store.dispatch(SetPointInfoErrorAction(has_err, out_of_bounds))
        
        if is_editing and not has_err:
            updates = {
                "drawing_name": input_state.get("drawing_name", ""),
                "excavation_type": ex_type,
                "feature_name": feat_name if ex_type == ExcavationType.FEATURE.value else "",
                "color_code": input_state.get("color_code", "") if ex_type == ExcavationType.FEATURE.value else "",
                "attribute_type": input_state.get("attribute_type", ""),
                "point_name": pname,
                "branch_no": branch,
            }
            self.commit_fields_to_feature(updates, self.state_store.state.selected_point_id, self.state_store.state.selected_point_data)

    def validate_drawing_bounds(self, drawing_name: str, map_point: QgsPointXY) -> Tuple[bool, Optional[Tuple[float, float]]]:
        if not drawing_name or drawing_name == UILabels.DRAWING_UNSPECIFIED:
            return True, (0.0, 0.0)
        if not self.layer_manager:
            return False, None
        meta = self.layer_manager.load_image_metadata()
        layer_meta = meta.get(drawing_name) if meta else None
        if not layer_meta:
            return False, None
        affine_params = layer_meta.get("affine_params")
        if not affine_params:
            return False, None
        px, py = pixel_from_affine(affine_params, map_point)
        raster_layer = None
        root = QgsProject.instance().layerTreeRoot()
        if root:
            image_group = root.findGroup("画像ファイル")
            if image_group:
                for tree_layer in image_group.findLayers():
                    l = tree_layer.layer()
                    if l and l.isValid() and l.name() == drawing_name:
                        raster_layer = l
                        break
        if raster_layer is None:
            layers = QgsProject.instance().mapLayersByName(drawing_name)
            if layers and layers[0].isValid():
                raster_layer = layers[0]
        if raster_layer is None or not hasattr(raster_layer, "width") or not hasattr(raster_layer, "height"):
            return False, None
        width = raster_layer.width()
        height = raster_layer.height()
        if 0 <= px <= width and 0 <= py <= height:
            return True, (px, py)
        return False, None

    def check_realtime_out_of_bounds(self, selected_edit_point_id: int) -> bool:
        if selected_edit_point_id is None:
            return False
        if not self.point_layer or not self.point_layer.isValid():
            return False
        drawing_name = self.get_target_drawing_name_cb()
        if not drawing_name or drawing_name == UILabels.DRAWING_UNSPECIFIED:
            return False
        feat = self.point_layer.getFeature(selected_edit_point_id)
        if not feat.isValid() or not feat.hasGeometry():
            return False
        map_point = feat.geometry().asPoint()
        is_valid, _ = self.validate_drawing_bounds(drawing_name, map_point)
        return not is_valid

    def check_realtime_duplicate(self, ex_type: str, feat_name: str, pname: str, branch: str, selected_edit_point_id: Optional[int]) -> Optional[str]:
        if not self.point_layer or not self.point_layer.isValid():
            return None
        if not pname:
            return None
        if feat_name in (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成")):
            feat_name = ""
        drawing_name = self.get_target_drawing_name_cb()
        if drawing_name == UILabels.DRAWING_UNSPECIFIED:
            drawing_name = ""
        is_dup = check_point_duplicate(
            self.point_layer, ex_type, feat_name, pname, branch, drawing_name,
            exclude_feature_id=selected_edit_point_id,
        )
        if not is_dup:
            return None
        return build_point_ident(ex_type, feat_name, pname, branch, drawing_name)

    def commit_fields_to_feature(self, updates: Dict[str, Any], selected_edit_point_id: int, current_selected_data: Dict[str, Any]) -> bool:
        if selected_edit_point_id is None or not self.point_layer:
            return False
        with self.busy_interaction_guard_cb():
            field_names = self.point_layer.fields().names()
            self.point_layer.startEditing()
            for field_name, value in updates.items():
                if field_name in field_names:
                    idx = field_names.index(field_name)
                    self.point_layer.changeAttributeValue(selected_edit_point_id, idx, value)
            self.point_layer.commitChanges()
            if current_selected_data is not None:
                current_selected_data.update(updates)
                self.state_store.dispatch_silent(SelectPointAction(selected_edit_point_id, current_selected_data))
            if self.update_symbology_opacity_cb:
                self.update_symbology_opacity_cb()
        return True

    # ==========================================
    # キャンバス打刻・編集連携
    # ==========================================
    def handle_canvas_click(self, map_point: QgsPointXY):
        if not self.point_layer or not self.point_layer.isValid():
            return
        state_model = self.state_store.state
        if state_model.autonum_mode == "release":
            self._handle_release_mode_click(map_point)
            return
        input_state = self.get_digitizing_input_state_cb()
        if not input_state.get("can_click", False):
            return
        pname, branch = self.get_current_point_name_and_branch_cb()
        dup_ident = self.check_realtime_duplicate(
            input_state["excavation_type"], input_state["feature_name"], 
            pname, branch, state_model.selected_point_id
        )
        if self.is_feature_name_missing_cb() or dup_ident:
            self.state_store.dispatch(SetPointInfoErrorAction(has_error=True))
            return
        drawing_name = input_state.get("drawing_name", "")
        is_valid, _ = self.validate_drawing_bounds(drawing_name, map_point)
        if not is_valid:
            self.state_store.dispatch(SetPointInfoErrorAction(has_error=True, is_out_of_bounds=True))
            return
        self.state_store.dispatch_silent(SetPointInfoErrorAction(has_error=False, is_out_of_bounds=False))
        self._create_digitized_point_from_state(input_state, map_point)

    def _handle_release_mode_click(self, map_point: QgsPointXY) -> None:
        if self.is_feature_name_missing_cb():
            self.state_store.dispatch(SetPointInfoErrorAction(has_error=True))
            return
        drawing_name = self.get_target_drawing_name_cb()
        if drawing_name == UILabels.DRAWING_UNSPECIFIED:
            drawing_name = ""
        is_valid, _ = self.validate_drawing_bounds(drawing_name, map_point)
        if not is_valid:
            self.state_store.dispatch(SetPointInfoErrorAction(has_error=True, is_out_of_bounds=True))
            return
        self.state_store.dispatch_silent(SetPointInfoErrorAction(has_error=False, is_out_of_bounds=False))
        
        input_state = self.get_digitizing_input_state_cb()
        excavation_type = input_state["excavation_type"]
        feature_name = input_state["feature_name"]
        is_sp = self.is_sp_attribute_cb()
        last_point_name = self._get_last_created_point_name(excavation_type, feature_name, is_sp)

        dlg = PointNameEntryDialog(
            self.point_layer, excavation_type, feature_name, drawing_name, is_sp,
            self.parent_widget, initial_point_name=last_point_name
        )
        if dlg.exec_() != PointNameEntryDialog.Accepted:
            return

        point_name, branch_no = dlg.get_values()
        state_dict = {
            "drawing_name": drawing_name,
            "excavation_type": excavation_type,
            "feature_name": feature_name,
            "color_code": self.state_store.state.current_feature_color,
            "attribute_type": self.get_attribute_value_cb(),
            "point_name": point_name,
            "branch_no": branch_no,
        }
        self._create_digitized_point_from_state(state_dict, map_point)

    def _create_digitized_point_from_state(self, state: Dict[str, Any], map_point: QgsPointXY) -> None:
        drawing_name = state.get("drawing_name", "")
        if drawing_name == UILabels.DRAWING_UNSPECIFIED:
            drawing_name = ""
        excavation_type = state["excavation_type"]
        feature_name = state["feature_name"]
        color_code = state["color_code"]
        attribute_type = state["attribute_type"]
        point_name = state["point_name"]
        branch_no = state["branch_no"]

        next_point_id = get_next_point_id(self.point_layer)
        _, coords = self.validate_drawing_bounds(drawing_name, map_point)
        pixel_coords = coords if coords is not None else (0.0, 0.0)

        new_feat = build_digitized_feature(
            self.point_layer, next_point_id, map_point,
            {
                "drawing_name": drawing_name,
                "excavation_type": excavation_type,
                "feature_name": feature_name if excavation_type == ExcavationType.FEATURE.value else "",
                "color_code": color_code if excavation_type == ExcavationType.FEATURE.value else "",
                "attribute_type": attribute_type,
                "point_name": point_name,
                "branch_no": branch_no,
            },
            pixel_coords=pixel_coords,
        )

        with self.busy_interaction_guard_cb():
            insert_feature_to_layer(self.point_layer, new_feat)
            has_branch = bool(branch_no)
            self.state_store.dispatch(SetDigitizedWithBranchAction(has_branch=has_branch))
            if not has_branch:
                if self.apply_next_point_number_cb:
                    self.apply_next_point_number_cb()
            self.validate_and_sync()

    def _get_last_created_point_name(self, excavation_type: str, feature_name: str, is_sp: bool) -> str:
        if not self.point_layer or not self.point_layer.isValid():
            return ""
        max_point_id = None
        latest_point_name = None
        for feat in self.point_layer.getFeatures():
            ex_type = safe_get_str(feat, "excavation_type")
            if excavation_type == ExcavationType.GRID.value:
                if ex_type != ExcavationType.GRID.value:
                    continue
            else:
                f_name = safe_get_str(feat, "feature_name")
                if ex_type != ExcavationType.FEATURE.value or f_name != feature_name:
                    continue
            feat_is_sp = safe_get_str(feat, "attribute_type") == AttributeType.SP.value
            if feat_is_sp != is_sp:
                continue
            pid = feat["point_id"]
            if pid is None or not isinstance(pid, int):
                continue
            if max_point_id is None or pid > max_point_id:
                max_point_id = pid
                latest_point_name = feat["point_name"]
        return "" if latest_point_name is None else str(latest_point_name)

    def handle_existing_point_selected(self, data: dict):
        if self.map_tool and hasattr(self.map_tool, "set_interaction_locked"):
            self.map_tool.set_interaction_locked(True)
        dialog = PointEditDialog(
            layer_manager=self.layer_manager,
            feature_data=data,
            drawing_names=self.get_drawing_layer_names_cb(),
            parent=self.parent_widget
        )
        result = dialog.exec_()
        if self.map_tool and hasattr(self.map_tool, "set_interaction_locked"):
            self.map_tool.set_interaction_locked(False)
            
        if result == PointEditDialog.Accepted:
            if dialog.dialog_action == "delete":
                self.state_store.dispatch_silent(SelectPointAction(data.get("feature_id")))
                self.handle_delete_selected_point()
            elif dialog.dialog_action == "confirm" and self.point_layer:
                fid = data.get("feature_id")
                updates = {
                    "drawing_name": dialog.feature_data["drawing_name"],
                    "excavation_type": dialog.feature_data["excavation_type"],
                    "feature_name": dialog.feature_data["feature_name"],
                    "attribute_type": dialog.feature_data["attribute_type"],
                    "point_name": dialog.feature_data["point_name"],
                    "branch_no": dialog.feature_data["branch_no"],
                }
                with self.busy_interaction_guard_cb():
                    field_names = self.point_layer.fields().names()
                    self.point_layer.startEditing()
                    for field_name, value in updates.items():
                        if field_name in field_names:
                            idx = field_names.index(field_name)
                            self.point_layer.changeAttributeValue(fid, idx, value)
                    self.point_layer.commitChanges()
                    if self.update_symbology_opacity_cb:
                        self.update_symbology_opacity_cb()
                        
        self.state_store.dispatch(ResetSelectionAction())
        if self.map_tool:
            self.map_tool.clear_selected_marker()

    def handle_delete_selected_point(self):
        state = self.state_store.state
        if state.selected_point_id is None or not self.point_layer:
            return
        with self.busy_interaction_guard_cb():
            self.point_layer.startEditing()
            self.point_layer.deleteFeature(state.selected_point_id)
            self.point_layer.commitChanges()
            self.iface.messageBar().pushMessage(
                UIMessages.MSG_DELETE_SUCCESS_TITLE,
                UIMessages.MSG_DELETE_SUCCESS,
                level=Qgis.MessageLevel.Success,
                duration=3,
            )
            self.state_store.dispatch(ResetSelectionAction())
            if self.map_tool:
                self.map_tool.clear_selected_marker()