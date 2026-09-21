# --- src/uilogic/digitizing_logic.py の完全置き換え ---
from typing import Dict, Any, Optional, Tuple
from contextlib import contextmanager

from qgis.core import QgsPointXY, QgsProject, Qgis
from qgis.PyQt.QtCore import QObject
from qgis.PyQt.QtWidgets import QDialog

from ..logic.core import (
    check_point_duplicate, build_point_ident, get_next_point_number,
    get_next_point_id, build_digitized_feature, insert_feature_to_layer,
    pixel_from_affine, safe_get_str, ExcavationType, AttributeType
)
from ..ui.constants import UILabels, UIMessages
from ..ui.core.state import (
    UIStateStore, ChangeTab2ModeAction, SelectPointAction, ChangeAutonumModeAction,
    SetValidationAction, SetPointInfoErrorAction, SetDigitizedWithBranchAction,
    ResetSelectionAction, SetFocusModeAction, SetProcessingAction, UpdateDigitizingInputsAction,
    SetPointInfoSummaryAction, SetFeatureCacheAction, SetSuppressCommitAction
)
from ..ui.dialogs import PointNameEntryDialog, PointEditDialog, FeatureManageDialog
from ..ui.core.builder import BuiltPanel
from ..ui.style import UIStyleHelper


class DigitizingLogic(QObject):
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
        
        self.map_tool = None
        self.parent_widget = None
        self.update_symbology_opacity_cb = None
        self.get_drawing_layer_names_cb = None

    def bind_view_callbacks(self, callbacks: Dict[str, Any]):
        self.map_tool = callbacks.get("map_tool")
        self.parent_widget = callbacks.get("parent_widget")
        self.update_symbology_opacity_cb = callbacks.get("update_symbology_opacity")
        self.get_drawing_layer_names_cb = callbacks.get("get_drawing_layer_names")

    def bind_ui_panels(self, mode_panel: BuiltPanel, point_info_panel: BuiltPanel, attribute_panel: BuiltPanel, display_panel: BuiltPanel):
        self.mode_panel = mode_panel
        self.point_info_panel = point_info_panel
        self.attribute_panel = attribute_panel
        self.display_panel = display_panel

        self.mode_panel.bind("mode_changed", self._on_mode_changed)
        self.point_info_panel.bind("autonum_mode_changed", self._on_autonum_mode_changed)
        self.point_info_panel.bind("delete_point_clicked", self.handle_delete_selected_point)
        self.point_info_panel.bind("point_identity_changed", self.validate_and_sync)
        self.point_info_panel.bind("branch_text_changed", self._on_branch_text_changed)
        
        self.attribute_panel.bind("category_changed", self._on_category_changed)
        self.attribute_panel.bind("excavation_type_changed", self._on_excavation_type_changed)
        self.attribute_panel.bind("feature_combo_changed", self.validate_and_sync)
        self.attribute_panel.bind("manage_feature_clicked", self.handle_manage_feature_clicked)
        
        self.display_panel.bind("filter_toggled", self._on_filter_toggled)

    # ==========================================
    # パネルからの値取得・ヘルパーメソッド
    # ==========================================
    def is_sp_attribute(self) -> bool:
        # CoreUIBuilderのget_valueは表示テキスト(currentText)を返すため、
        # コンボボックスから直接データ値(currentData)を取得する
        combo_attr = self.attribute_panel.get("attribute_code")
        attr_value = combo_attr.currentData() or combo_attr.currentText()
        return attr_value == AttributeType.SP.value

    def get_current_point_name_and_branch(self) -> Tuple[str, str]:
        if self.is_sp_attribute():
            pname = self.point_info_panel.get_value("point_name_sp")
        else:
            pname = str(self.point_info_panel.get_value("point_name"))
        branch = self.point_info_panel.get_value("branch_no")
        return pname, branch

    def is_feature_name_missing(self) -> bool:
        if self.attribute_panel.get_value("excavation_type") != ExcavationType.FEATURE.value:
            return False
        feat = self.attribute_panel.get_value("feature_name")
        return not feat or feat in (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成"))

    def get_digitizing_input_state(self) -> Dict[str, Any]:
        pname, branch = self.get_current_point_name_and_branch()
        ex_type = self.attribute_panel.get_value("excavation_type")
        feat_name = self.attribute_panel.get_value("feature_name")
        is_feat = (ex_type == ExcavationType.FEATURE.value)
        is_missing = is_feat and (not feat_name or feat_name in (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成")))
        
        can_click = True
        error_msg = ""
        if not pname:
            can_click = False
            error_msg = UIMessages.ERR_POINT_NAME_REQUIRED
        elif is_missing:
            can_click = False
            error_msg = UIMessages.ERR_NEW_FEATURE_REQUIRED
            
        # CoreUIBuilderのget_valueは表示テキスト(currentText)を返すため、
        # コンボボックスから直接データ値(currentData)を取得する
        combo_attr = self.attribute_panel.get("attribute_code")
        attr_value = combo_attr.currentData() or combo_attr.currentText()
            
        return {
            "can_click": can_click,
            "error_message": error_msg,
            "drawing_name": self.state_store.state.selected_drawing_name,
            "excavation_type": ex_type,
            "feature_name": feat_name,
            "color_code": self.state_store.state.current_feature_color,
            "attribute_type": attr_value,
            "point_name": pname,
            "branch_no": branch
        }

    @contextmanager
    def busy_interaction_guard(self):
        """重い処理中に UI 全体をロックし、WaitCursor を表示する"""
        self.state_store.dispatch(SetProcessingAction(True))
        try:
            yield
        finally:
            self.state_store.dispatch(SetProcessingAction(False))

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
        if mode == "auto" and not self.is_sp_attribute():
            self.apply_next_point_number()
        self.validate_and_sync()

    def _on_branch_text_changed(self, text: str):
        if not text.strip() and self.state_store.state.has_digitized_with_branch:
            self.apply_next_point_number()
            self.state_store.dispatch(SetDigitizedWithBranchAction(False))
        self.validate_and_sync()

    def _on_category_changed(self, *args):
        if self.state_store.state.selected_point_id is None:
            self.apply_next_point_number()
        self.validate_and_sync()

    def _on_excavation_type_changed(self, index: int):
        self._on_category_changed()

    def _on_filter_toggled(self, checked: bool):
        self.state_store.dispatch(SetFocusModeAction(checked))

    # ==========================================
    # 自動連番・ラベル更新・遺構管理ロジック
    # ==========================================
    def apply_next_point_number(self):
        inputs = {}
        if self.is_sp_attribute():
            inputs["point_name_sp"] = ""
        elif self.state_store.state.autonum_mode == "auto":
            ex_type = self.attribute_panel.get_value("excavation_type")
            feat_name = self.attribute_panel.get_value("feature_name")
            if feat_name in (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成")):
                feat_name = ""
            next_num = get_next_point_number(self.point_layer, ex_type, feat_name)
            inputs["point_name"] = next_num
        
        if inputs:
            self.state_store.dispatch(UpdateDigitizingInputsAction(inputs))
        self.refresh_point_info_labels()

    def refresh_point_info_labels(self):
        ex_type = self.attribute_panel.get_value("excavation_type")
        group_label = self.attribute_panel.get_value("feature_name") if ex_type == ExcavationType.FEATURE.value else ExcavationType.GRID.value
        pname, branch = self.get_current_point_name_and_branch()
        
        summary = {
            "group": group_label or "-",
            "pointname": f"{pname} {branch}".strip() if pname else "-",
            "coords": "-",
        }
        self.state_store.dispatch(SetPointInfoSummaryAction(summary))

    def handle_manage_feature_clicked(self):
        feature_colors = {name: "#FF5722" for name in self.state_store.state.feature_name_list if name != UILabels.UNREGISTERED}
        if self.point_layer and self.point_layer.isValid():
            for feat in self.point_layer.getFeatures():
                fname = safe_get_str(feat, "feature_name").strip()
                if fname and fname not in (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成")):
                    c_code = safe_get_str(feat, "color_code").strip()
                    if c_code:
                        feature_colors[fname] = c_code
                    elif fname not in feature_colors:
                        feature_colors[fname] = "#FF5722"

        dlg = FeatureManageDialog(parent=self.parent_widget, feature_colors=feature_colors, on_update_callback=self.rename_and_recolor_feature)
        UIStyleHelper.apply_theme(dlg)
        
        if dlg.exec_() == QDialog.Accepted:
            new_name = dlg.result_text.strip()
            if new_name:
                if hasattr(dlg, "result_color") and dlg.result_color:
                    self.state_store.dispatch(SetFeatureCacheAction(color_hex=dlg.result_color))
                if new_name not in self.state_store.state.feature_name_list:
                    temp_list = list(self.state_store.state.feature_name_list)
                    temp_list.append(new_name)
                    self.state_store.dispatch(SetFeatureCacheAction(feature_list=temp_list))
                
                # UIのコンボボックスで新しい項目を選択させる指示を Dispatch
                self.state_store.dispatch(UpdateDigitizingInputsAction({"feature_name": new_name}))

    def rename_and_recolor_feature(self, old_name: str, new_name: str, new_color: str) -> None:
        if not self.point_layer or not self.point_layer.isValid():
            return
        fields = self.point_layer.fields()
        feat_idx = fields.indexFromName("feature_name")
        color_idx = fields.indexFromName("color_code")
        if feat_idx == -1 or color_idx == -1:
            return

        self.point_layer.startEditing()
        for feat in self.point_layer.getFeatures():
            if safe_get_str(feat, "feature_name") == old_name:
                self.point_layer.changeAttributeValue(feat.id(), feat_idx, new_name)
                self.point_layer.changeAttributeValue(feat.id(), color_idx, new_color)
        self.point_layer.commitChanges()

        self.state_store.dispatch(SetSuppressCommitAction(True))
        try:
            temp_list = list(self.state_store.state.feature_name_list)
            if old_name in temp_list:
                temp_list[temp_list.index(old_name)] = new_name
            elif new_name not in temp_list:
                temp_list.append(new_name)
                
            self.state_store.dispatch(SetFeatureCacheAction(color_hex=new_color, feature_list=temp_list))
            self.state_store.dispatch(UpdateDigitizingInputsAction({"feature_name": new_name}))
        finally:
            self.state_store.dispatch(SetSuppressCommitAction(False))

        self.validate_and_sync()

    # ==========================================
    # バリデーション・空間検索・コミット
    # ==========================================
    def validate_and_sync(self, *args):
        if self.state_store.state.suppress_realtime_commit:
            return
        self.refresh_point_info_labels()

        input_state = self.get_digitizing_input_state()
        pname = input_state.get("point_name", "")
        branch = input_state.get("branch_no", "")
        ex_type = input_state.get("excavation_type", "")
        feat_name = input_state.get("feature_name", "")
        
        is_feat_missing = self.is_feature_name_missing()
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
        drawing_name = self.state_store.state.selected_drawing_name
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
        drawing_name = self.state_store.state.selected_drawing_name
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
        with self.busy_interaction_guard():
            field_names = self.point_layer.fields().names()
            self.point_layer.startEditing()
            for field_name, value in updates.items():
                if field_name in field_names:
                    idx = field_names.index(field_name)
                    self.point_layer.changeAttributeValue(selected_edit_point_id, idx, value)
            self.point_layer.commitChanges()
            if current_selected_data is not None:
                current_selected_data.update(updates)
                self.state_store.dispatch(SelectPointAction(selected_edit_point_id, current_selected_data))
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
        input_state = self.get_digitizing_input_state()
        if not input_state.get("can_click", False):
            return
        pname, branch = self.get_current_point_name_and_branch()
        dup_ident = self.check_realtime_duplicate(
            input_state["excavation_type"], input_state["feature_name"], 
            pname, branch, state_model.selected_point_id
        )
        if self.is_feature_name_missing() or dup_ident:
            self.state_store.dispatch(SetPointInfoErrorAction(has_error=True))
            return
        drawing_name = input_state.get("drawing_name", "")
        is_valid, _ = self.validate_drawing_bounds(drawing_name, map_point)
        if not is_valid:
            self.state_store.dispatch(SetPointInfoErrorAction(has_error=True, is_out_of_bounds=True))
            return
        self.state_store.dispatch(SetPointInfoErrorAction(has_error=False, is_out_of_bounds=False))
        self._create_digitized_point_from_state(input_state, map_point)

    def _handle_release_mode_click(self, map_point: QgsPointXY) -> None:
        if self.is_feature_name_missing():
            self.state_store.dispatch(SetPointInfoErrorAction(has_error=True))
            return
        drawing_name = self.state_store.state.selected_drawing_name
        if drawing_name == UILabels.DRAWING_UNSPECIFIED:
            drawing_name = ""
        is_valid, _ = self.validate_drawing_bounds(drawing_name, map_point)
        if not is_valid:
            self.state_store.dispatch(SetPointInfoErrorAction(has_error=True, is_out_of_bounds=True))
            return
        self.state_store.dispatch(SetPointInfoErrorAction(has_error=False, is_out_of_bounds=False))
        
        input_state = self.get_digitizing_input_state()
        excavation_type = input_state["excavation_type"]
        feature_name = input_state["feature_name"]
        is_sp = self.is_sp_attribute()
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
            "attribute_type": self.attribute_panel.get_value("attribute_code"),
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

        with self.busy_interaction_guard():
            insert_feature_to_layer(self.point_layer, new_feat)
            has_branch = bool(branch_no)
            self.state_store.dispatch(SetDigitizedWithBranchAction(has_branch=has_branch))
            if not has_branch:
                self.apply_next_point_number()
            self.validate_and_sync()
            
            if self.update_symbology_opacity_cb:
                self.update_symbology_opacity_cb()
            elif self.iface and self.iface.mapCanvas():
                self.iface.mapCanvas().refresh()


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
            
        drawing_names = self.get_drawing_layer_names_cb() if self.get_drawing_layer_names_cb else []
        dialog = PointEditDialog(
            layer_manager=self.layer_manager,
            feature_data=data,
            drawing_names=drawing_names,
            parent=self.parent_widget
        )
        result = dialog.exec_()
        if self.map_tool and hasattr(self.map_tool, "set_interaction_locked"):
            self.map_tool.set_interaction_locked(False)
            
        if result == PointEditDialog.Accepted:
            if dialog.dialog_action == "delete":
                self.state_store.dispatch(SelectPointAction(data.get("feature_id")))
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
                with self.busy_interaction_guard():
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
        with self.busy_interaction_guard():
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