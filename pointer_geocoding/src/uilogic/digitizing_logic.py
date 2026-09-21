"""
/***************************************************************************
 PointerGeocoding Plugin - Digitizing Logic (Controller)
 ***************************************************************************/

Tab 2 (打刻・ポイント編集) のビジネスロジックを処理するController層です。
リアルタイムバリデーション、自動採番、遺構管理などのドメイン知識を完全に保持し、
DispatcherからのActionおよびStateの変更監視によって動作します。
"""
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
    UIStateStore, CanvasDigitizeAction, CommitEditPointAction, DeletePointAction,
    SetPointInfoErrorAction, SetValidationAction, SetDigitizedWithBranchAction,
    ResetSelectionAction, SelectPointAction, UIAction, SetProcessingAction,
    UpdateDigitizingInputsAction, SetPointInfoSummaryAction, SetFeatureCacheAction,
    SetSuppressCommitAction, TriggerAutoNumberAction, OpenFeatureManageAction,
    OpenPointEditAction
)
from ..ui.dialogs import PointNameEntryDialog, PointEditDialog, FeatureManageDialog
from ..ui.style import UIStyleHelper


class DigitizingLogic(QObject):
    def __init__(self, state_store: UIStateStore, layer_manager: Any, layers_dict: Dict[str, Any], dispatcher, iface, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.state_store = state_store
        self.layer_manager = layer_manager
        self.iface = iface
        self.point_layer = layers_dict.get("point_layer")
        self.parent_widget = parent

        # ディスパッチャーへハンドラを登録
        dispatcher.register_validator(CanvasDigitizeAction, self.validate_canvas_digitize)
        dispatcher.register_handler(CanvasDigitizeAction, self.handle_canvas_digitize)

        dispatcher.register_validator(CommitEditPointAction, self.validate_commit_edit_point)
        dispatcher.register_handler(CommitEditPointAction, self.handle_commit_edit_point)

        dispatcher.register_handler(DeletePointAction, self.handle_delete_point)
        dispatcher.register_handler(OpenFeatureManageAction, self.handle_open_feature_manage)
        dispatcher.register_handler(OpenPointEditAction, self.handle_open_point_edit)
        dispatcher.register_handler(TriggerAutoNumberAction, self.handle_trigger_auto_number)

        # DIされた副作用コールバック
        self.update_symbology_opacity_cb = lambda: None
        self.get_drawing_layer_names_cb = lambda: []

        # Stateの変更を監視し、リアルタイムバリデーションを実行
        self.state_store.state_changed.connect(self._on_state_changed)

    def bind_view_callbacks(self, callbacks: Dict[str, Any]):
        self.update_symbology_opacity_cb = callbacks.get("update_symbology_opacity", self.update_symbology_opacity_cb)
        self.get_drawing_layer_names_cb = callbacks.get("get_drawing_layer_names", self.get_drawing_layer_names_cb)

    @contextmanager
    def busy_interaction_guard(self):
        """重い処理中に UI 全体をロックし、WaitCursor を表示する"""
        self.state_store.dispatch(SetProcessingAction(True))
        try:
            yield
        finally:
            self.state_store.dispatch(SetProcessingAction(False))

    # ==========================================
    # State監視とリアルタイムバリデーション
    # ==========================================
    def _on_state_changed(self, new_state, diff: Dict[str, Any]):
        if new_state.suppress_realtime_commit:
            return
            
        # 入力値や対象図面が変わるたびに重複・範囲外チェックを走らせる
        if any(k in diff for k in ("digitizing_inputs", "selected_drawing_name", "selected_point_id")):
            self.validate_and_sync()

    def validate_and_sync(self):
        inputs = self.state_store.state.digitizing_inputs
        pname = inputs.get("point_name_sp") if inputs.get("attribute_code") == AttributeType.SP.value else str(inputs.get("point_name", ""))
        branch = inputs.get("branch_no", "")
        ex_type = inputs.get("excavation_type", "")
        feat_name = inputs.get("feature_name", "")
        
        is_feat_missing = (ex_type == ExcavationType.FEATURE.value) and (not feat_name or feat_name in (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成")))
        
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
            
        # Stateにエラー状態を反映 (Viewがこれを検知して赤枠等を描画する)
        self.state_store.dispatch_silent(SetPointInfoErrorAction(has_err, out_of_bounds))
        if has_err:
            self.state_store.dispatch_silent(SetValidationAction(has_error=True, message=status_msg))
            
        self.refresh_point_info_labels(ex_type, feat_name, pname, branch)

    def refresh_point_info_labels(self, ex_type: str, feat_name: str, pname: str, branch: str):
        group_label = feat_name if ex_type == ExcavationType.FEATURE.value else ExcavationType.GRID.value
        summary = {
            "group": group_label or "-",
            "pointname": f"{pname} {branch}".strip() if pname else "-",
            "coords": "-",
        }
        self.state_store.dispatch_silent(SetPointInfoSummaryAction(summary))

    # ==========================================
    # 自動採番 (TriggerAutoNumberAction)
    # ==========================================
    def handle_trigger_auto_number(self, action: TriggerAutoNumberAction) -> Optional[UIAction]:
        inputs = self.state_store.state.digitizing_inputs
        if inputs.get("attribute_code") == AttributeType.SP.value:
            self.state_store.dispatch(UpdateDigitizingInputsAction({"point_name_sp": ""}))
            return None
            
        if self.state_store.state.autonum_mode == "auto":
            ex_type = inputs.get("excavation_type", "")
            feat_name = inputs.get("feature_name", "")
            if feat_name in (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成")):
                feat_name = ""
            next_num = get_next_point_number(self.point_layer, ex_type, feat_name)
            self.state_store.dispatch(UpdateDigitizingInputsAction({"point_name": next_num}))
            
        return None

    def _get_last_created_point_name(self, excavation_type: str, feature_name: str, is_sp: bool) -> str:
        if not self.point_layer or not self.point_layer.isValid(): return ""
        max_point_id = None
        latest_point_name = None
        for feat in self.point_layer.getFeatures():
            ex_type = safe_get_str(feat, "excavation_type")
            if excavation_type == ExcavationType.GRID.value:
                if ex_type != ExcavationType.GRID.value: continue
            else:
                f_name = safe_get_str(feat, "feature_name")
                if ex_type != ExcavationType.FEATURE.value or f_name != feature_name: continue
            feat_is_sp = safe_get_str(feat, "attribute_type") == AttributeType.SP.value
            if feat_is_sp != is_sp: continue
            
            pid = feat["point_id"]
            if pid is None or not isinstance(pid, int): continue
            if max_point_id is None or pid > max_point_id:
                max_point_id = pid
                latest_point_name = feat["point_name"]
        return "" if latest_point_name is None else str(latest_point_name)

    # ==========================================
    # 遺構管理 (OpenFeatureManageAction)
    # ==========================================
    def handle_open_feature_manage(self, action: OpenFeatureManageAction) -> Optional[UIAction]:
        feature_colors = {name: "#FF5722" for name in self.state_store.state.feature_name_list if name != UILabels.UNREGISTERED}
        if self.point_layer and self.point_layer.isValid():
            for feat in self.point_layer.getFeatures():
                fname = safe_get_str(feat, "feature_name").strip()
                if fname and fname not in (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成")):
                    c_code = safe_get_str(feat, "color_code").strip()
                    if c_code: feature_colors[fname] = c_code
                    elif fname not in feature_colors: feature_colors[fname] = "#FF5722"

        dlg = FeatureManageDialog(parent=self.parent_widget, feature_colors=feature_colors, on_update_callback=self.rename_and_recolor_feature)
        UIStyleHelper.apply_theme(dlg)
        
        if dlg.exec_() == QDialog.Accepted:
            new_name = dlg.result_text.strip()
            if new_name:
                if hasattr(dlg, "result_color") and dlg.result_color:
                    self.state_store.dispatch(SetFeatureCacheAction(color_hex=dlg.result_color))
                temp_list = list(self.state_store.state.feature_name_list)
                if new_name not in temp_list:
                    temp_list.append(new_name)
                    self.state_store.dispatch(SetFeatureCacheAction(feature_list=temp_list))
                self.state_store.dispatch(UpdateDigitizingInputsAction({"feature_name": new_name}))
        return None

    def rename_and_recolor_feature(self, old_name: str, new_name: str, new_color: str) -> None:
        if not self.point_layer or not self.point_layer.isValid(): return
        fields = self.point_layer.fields()
        feat_idx = fields.indexFromName("feature_name")
        color_idx = fields.indexFromName("color_code")
        if feat_idx == -1 or color_idx == -1: return

        with self.busy_interaction_guard():
            self.point_layer.startEditing()
            for feat in self.point_layer.getFeatures():
                if safe_get_str(feat, "feature_name") == old_name:
                    self.point_layer.changeAttributeValue(feat.id(), feat_idx, new_name)
                    self.point_layer.changeAttributeValue(feat.id(), color_idx, new_color)
            self.point_layer.commitChanges()

        self.state_store.dispatch_silent(SetSuppressCommitAction(True))
        try:
            temp_list = list(self.state_store.state.feature_name_list)
            if old_name in temp_list: temp_list[temp_list.index(old_name)] = new_name
            elif new_name not in temp_list: temp_list.append(new_name)
            self.state_store.dispatch(SetFeatureCacheAction(color_hex=new_color, feature_list=temp_list))
            self.state_store.dispatch(UpdateDigitizingInputsAction({"feature_name": new_name}))
        finally:
            self.state_store.dispatch_silent(SetSuppressCommitAction(False))

    # ==========================================
    # キャンバス打刻 (CanvasDigitizeAction)
    # ==========================================
    def validate_canvas_digitize(self, action: CanvasDigitizeAction) -> Optional[str]:
        if not self.point_layer or not self.point_layer.isValid():
            return "打刻点レイヤが無効です。"
            
        state = self.state_store.state
        inputs = state.digitizing_inputs
        pname = action.release_point_name if action.is_release_mode else inputs.get("point_name", "")
        branch = action.release_branch_no if action.is_release_mode else inputs.get("branch_no", "")
        ex_type = inputs.get("excavation_type", "")
        feat_name = inputs.get("feature_name", "")

        # 手動（解除）モードの場合はここでダイアログを開く
        if state.autonum_mode == "release" and not action.is_release_mode:
            drawing_name = state.selected_drawing_name if state.selected_drawing_name != UILabels.DRAWING_UNSPECIFIED else ""
            is_valid_bounds, _ = self.validate_drawing_bounds(drawing_name, action.map_point)
            if not is_valid_bounds:
                self.state_store.dispatch_silent(SetPointInfoErrorAction(has_error=True, is_out_of_bounds=True))
                return "打刻点が図面範囲外です。"
                
            is_sp = (inputs.get("attribute_code") == AttributeType.SP.value)
            last_pname = self._get_last_created_point_name(ex_type, feat_name, is_sp)
            dlg = PointNameEntryDialog(self.point_layer, ex_type, feat_name, drawing_name, is_sp, self.parent_widget, initial_point_name=last_pname)
            if dlg.exec_() != QDialog.Accepted:
                return "キャンセルされました。"
            # 値を上書きして続行
            action.is_release_mode = True
            action.release_point_name, action.release_branch_no = dlg.get_values()
            pname, branch = action.release_point_name, action.release_branch_no

        if not pname:
            return UIMessages.ERR_POINT_NAME_REQUIRED
        if ex_type == ExcavationType.FEATURE.value and (not feat_name or feat_name in (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成"))):
            return UIMessages.ERR_NEW_FEATURE_REQUIRED

        drawing_name = state.selected_drawing_name if state.selected_drawing_name != UILabels.DRAWING_UNSPECIFIED else ""
        if check_point_duplicate(self.point_layer, ex_type, feat_name, pname, branch, drawing_name):
            ident = build_point_ident(ex_type, feat_name, pname, branch, drawing_name)
            return UIMessages.ERR_POINT_NAME_DUPLICATE.format(ident=ident)

        is_valid_bounds, _ = self.validate_drawing_bounds(drawing_name, action.map_point)
        if not is_valid_bounds:
            self.state_store.dispatch_silent(SetPointInfoErrorAction(has_error=True, is_out_of_bounds=True))
            
        return None

    def handle_canvas_digitize(self, action: CanvasDigitizeAction) -> Optional[UIAction]:
        state = self.state_store.state
        inputs = state.digitizing_inputs
        drawing_name = state.selected_drawing_name if state.selected_drawing_name != UILabels.DRAWING_UNSPECIFIED else ""
        ex_type = inputs.get("excavation_type", "")
        feat_name = inputs.get("feature_name", "") if ex_type == ExcavationType.FEATURE.value else ""
        color_code = state.current_feature_color if ex_type == ExcavationType.FEATURE.value else ""
        attr_type = inputs.get("attribute_code", "")
        pname = action.release_point_name if action.is_release_mode else str(inputs.get("point_name", ""))
        branch = action.release_branch_no if action.is_release_mode else str(inputs.get("branch_no", ""))

        next_id = get_next_point_id(self.point_layer)
        is_valid_bounds, coords = self.validate_drawing_bounds(drawing_name, action.map_point)
        pixel_coords = coords if coords is not None else (0.0, 0.0)

        new_feat = build_digitized_feature(
            self.point_layer, next_id, action.map_point,
            {
                "drawing_name": drawing_name, "excavation_type": ex_type, "feature_name": feat_name,
                "color_code": color_code, "attribute_type": attr_type, "point_name": pname, "branch_no": branch,
            },
            pixel_coords=pixel_coords,
        )

        with self.busy_interaction_guard():
            insert_feature_to_layer(self.point_layer, new_feat)
            self.update_symbology_opacity_cb()

        has_branch = bool(branch)
        if not has_branch:
            # 採番を進めるActionを返す
            self.state_store.dispatch(TriggerAutoNumberAction())

        return SetDigitizedWithBranchAction(has_branch=has_branch)

    # ==========================================
    # 既存点の編集・削除
    # ==========================================
    def handle_open_point_edit(self, action: OpenPointEditAction) -> Optional[UIAction]:
        drawing_names = self.get_drawing_layer_names_cb()
        dialog = PointEditDialog(layer_manager=self.layer_manager, feature_data=action.point_data, drawing_names=drawing_names, parent=self.parent_widget)
        
        result = dialog.exec_()
        if result == QDialog.Accepted:
            if dialog.dialog_action == "delete":
                self.state_store.dispatch(SelectPointAction(point_id=action.point_data.get("feature_id")))
                return DeletePointAction(point_id=action.point_data.get("feature_id"))
            elif dialog.dialog_action == "confirm":
                return CommitEditPointAction(point_id=action.point_data.get("feature_id"), updates=dialog.feature_data)
        
        return ResetSelectionAction()

    def validate_commit_edit_point(self, action: CommitEditPointAction) -> Optional[str]:
        if not self.point_layer or not self.point_layer.isValid(): return "打刻点レイヤが無効です。"
        updates = action.updates
        ex_type = updates.get("excavation_type", "")
        feat_name = updates.get("feature_name", "")
        pname = updates.get("point_name", "")
        branch = updates.get("branch_no", "")
        
        if ex_type == ExcavationType.FEATURE.value and not feat_name:
            return UIMessages.ERR_NEW_FEATURE_REQUIRED
        if not pname: return UIMessages.ERR_POINT_NAME_REQUIRED
            
        if check_point_duplicate(self.point_layer, ex_type, feat_name, pname, branch, updates.get("drawing_name", ""), exclude_feature_id=action.point_id):
            return UIMessages.ERR_POINT_NAME_DUPLICATE.format(ident=build_point_ident(ex_type, feat_name, pname, branch, updates.get("drawing_name", "")))
        return None

    def handle_commit_edit_point(self, action: CommitEditPointAction) -> Optional[UIAction]:
        with self.busy_interaction_guard():
            field_names = self.point_layer.fields().names()
            self.point_layer.startEditing()
            for field_name, value in action.updates.items():
                if field_name in field_names:
                    self.point_layer.changeAttributeValue(action.point_id, field_names.index(field_name), value)
            self.point_layer.commitChanges()
            self.update_symbology_opacity_cb()
            
        state = self.state_store.state
        if state.selected_point_data:
            new_data = dict(state.selected_point_data)
            new_data.update(action.updates)
            return SelectPointAction(point_id=action.point_id, point_data=new_data)
        return None

    def handle_delete_point(self, action: DeletePointAction) -> Optional[UIAction]:
        if not self.point_layer or not self.point_layer.isValid(): return None
        # 削除確認はPointEditDialog側またはここで処理
        with self.busy_interaction_guard():
            self.point_layer.startEditing()
            self.point_layer.deleteFeature(action.point_id)
            self.point_layer.commitChanges()
            
        if self.iface:
            self.iface.messageBar().pushMessage(UIMessages.MSG_DELETE_SUCCESS_TITLE, UIMessages.MSG_DELETE_SUCCESS, level=Qgis.MessageLevel.Success, duration=3)
        return ResetSelectionAction()

    # ==========================================
    # バウンダリチェックヘルパー
    # ==========================================
    def validate_drawing_bounds(self, drawing_name: str, map_point: QgsPointXY) -> Tuple[bool, Optional[Tuple[float, float]]]:
        if not drawing_name or drawing_name == UILabels.DRAWING_UNSPECIFIED: return True, (0.0, 0.0)
        meta = self.layer_manager.load_image_metadata() if self.layer_manager else None
        layer_meta = meta.get(drawing_name) if meta else None
        if not layer_meta or not layer_meta.get("affine_params"): return False, None
            
        px, py = pixel_from_affine(layer_meta.get("affine_params"), map_point)
        raster_layer = None
        root = QgsProject.instance().layerTreeRoot()
        if root and root.findGroup("画像ファイル"):
            for tree_layer in root.findGroup("画像ファイル").findLayers():
                if tree_layer.layer() and tree_layer.layer().name() == drawing_name:
                    raster_layer = tree_layer.layer()
                    break
                        
        if raster_layer and hasattr(raster_layer, "width") and hasattr(raster_layer, "height"):
            if 0 <= px <= raster_layer.width() and 0 <= py <= raster_layer.height():
                return True, (px, py)
        return False, None

    def check_realtime_out_of_bounds(self, selected_edit_point_id: int) -> bool:
        if selected_edit_point_id is None or not self.point_layer or not self.point_layer.isValid(): return False
        drawing_name = self.state_store.state.selected_drawing_name
        if not drawing_name or drawing_name == UILabels.DRAWING_UNSPECIFIED: return False
        feat = self.point_layer.getFeature(selected_edit_point_id)
        if not feat.isValid() or not feat.hasGeometry(): return False
        is_valid, _ = self.validate_drawing_bounds(drawing_name, feat.geometry().asPoint())
        return not is_valid

    def check_realtime_duplicate(self, ex_type: str, feat_name: str, pname: str, branch: str, selected_edit_point_id: Optional[int]) -> Optional[str]:
        if not self.point_layer or not self.point_layer.isValid() or not pname: return None
        feat_name = "" if feat_name in (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成")) else feat_name
        drawing_name = self.state_store.state.selected_drawing_name
        drawing_name = "" if drawing_name == UILabels.DRAWING_UNSPECIFIED else drawing_name
        if check_point_duplicate(self.point_layer, ex_type, feat_name, pname, branch, drawing_name, exclude_feature_id=selected_edit_point_id):
            return build_point_ident(ex_type, feat_name, pname, branch, drawing_name)
        return None