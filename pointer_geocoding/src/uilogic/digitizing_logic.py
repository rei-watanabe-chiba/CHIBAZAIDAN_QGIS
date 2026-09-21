"""
/***************************************************************************
 PointerGeocoding Plugin - Digitizing Logic (Controller)
 ***************************************************************************/

Tab 2 (連続打刻・点編集) のイベントに対するドメインロジックを実行するController層です。
GUI（ダイアログ操作等）はViewへ移譲され、ユーザーの意思決定アクションを受容して
データ操作と状態更新（UIStateStoreへの反映）を行います。
"""
from typing import Dict, Any, Optional, Tuple, List
from contextlib import contextmanager

from qgis.core import QgsPointXY, QgsProject, Qgis
from qgis.PyQt.QtCore import QObject

from ..logic.core import (
    check_point_duplicate, build_point_ident, get_next_point_number,
    get_next_point_id, build_digitized_feature, insert_feature_to_layer,
    pixel_from_affine, safe_get_str, ExcavationType, AttributeType
)
from ..ui.constants import UILabels, UIMessages
from ..ui.core.state import (
    UIStateStore, UIAction, SelectPointAction, SetValidationAction, SetPointInfoErrorAction,
    SetDigitizedWithBranchAction, ResetSelectionAction, SetProcessingAction,
    UpdateDigitizingInputsAction, SetPointInfoSummaryAction, SetFeatureCacheAction,
    SetSuppressCommitAction, CanvasClickAction, AddManualDigitizedPointAction,
    DeletePointAction, UpdatePointAttributesAction, UpdateFeatureCategoryAction,
    ValidateDigitizingInputsAction
)


class DigitizingLogic(QObject):
    """
    点群の打刻、自動採番、重複判定、編集・削除を処理するドメインロジック。
    単一方向データフローに準拠し、EventDispatcherから呼び出されるハンドラを提供します。
    """

    def __init__(
        self,
        state_store: UIStateStore,
        layer_manager: Any,
        layers_dict: Dict[str, Any],
        iface: Any,
        dispatcher: Any,
        parent: Optional[QObject] = None
    ):
        """
        Args:
            state_store (UIStateStore): UI状態管理ストア
            layer_manager (Any): GeoPackageおよび設定管理
            layers_dict (Dict[str, Any]): レイヤキャッシュ
            iface (QgisInterface): QGISインターフェース
            dispatcher (Any): 中央アクションディスパッチャー
            parent (QObject): 親オブジェクト
        """
        super().__init__(parent)
        self.state_store = state_store
        self.layer_manager = layer_manager
        self.iface = iface
        self.dispatcher = dispatcher
        self.point_layer = layers_dict.get("point_layer")
        
        self.update_symbology_opacity_cb = None
        self.refresh_canvas_cb = None

        # ==========================================
        # Dispatcherへのアクションハンドラ登録
        # ==========================================
        self.dispatcher.register_handler(CanvasClickAction, self.handle_canvas_click)
        self.dispatcher.register_handler(AddManualDigitizedPointAction, self.handle_add_manual_point)
        self.dispatcher.register_handler(DeletePointAction, self.handle_delete_point)
        self.dispatcher.register_handler(UpdatePointAttributesAction, self.handle_update_attributes)
        self.dispatcher.register_handler(UpdateFeatureCategoryAction, self.handle_update_feature_category)
        
        # リアルタイムバリデーション（軽量同期用）
        self.dispatcher.register_handler(ValidateDigitizingInputsAction, self.handle_validate_inputs)

    def bind_view_callbacks(self, callbacks: Dict[str, Any]) -> None:
        """
        View側のUI更新/再描画コールバックをDI（依存性注入）する。
        ControllerからViewへの逆インポートを防ぎます。
        """
        self.update_symbology_opacity_cb = callbacks.get("update_symbology_opacity")
        self.refresh_canvas_cb = callbacks.get("refresh_canvas")

    @contextmanager
    def busy_interaction_guard(self):
        """局所ガード（連続打刻など、Dispatcherの大域ロックを利用しつつ即時復帰する処理用）"""
        self.state_store.dispatch(SetProcessingAction(True))
        try:
            yield
        finally:
            self.state_store.dispatch(SetProcessingAction(False))

    # ==========================================
    # ヘルパー: 状態取得および純粋計算メソッド
    # ==========================================
    def is_feature_name_missing(self, inputs: Dict[str, Any]) -> bool:
        """遺構モードにおいて、遺構名が未指定かどうかを判定する"""
        if inputs.get("excavation_type") != ExcavationType.FEATURE.value:
            return False
        feat = inputs.get("feature_name")
        return not feat or feat in (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成"))

    def calculate_next_point_number(self, excavation_type: str, feature_name: str, is_sp: bool) -> str:
        """
        現在のカテゴリに基づいて自動採番された次の点名を返す。
        （SP属性は自動採番対象から除外される [RULE-DOMAIN-06]）
        """
        if is_sp:
            return ""
        if feature_name in (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成")):
            feature_name = ""
        next_num = get_next_point_number(self.point_layer, excavation_type, feature_name)
        return str(next_num)

    def get_last_created_point_name(self, excavation_type: str, feature_name: str, is_sp: bool) -> str:
        """指定カテゴリで最後に作成された点名を取得する（手動入力補完用）"""
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

    def validate_drawing_bounds(self, drawing_name: str, map_point: QgsPointXY) -> Tuple[bool, Optional[Tuple[float, float]]]:
        """打刻点が対象図面のピクセル範囲内に収まっているかを判定する"""
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

    def check_realtime_duplicate(
        self, ex_type: str, feat_name: str, pname: str, branch: str, selected_edit_point_id: Optional[int], drawing_name: str
    ) -> Optional[str]:
        """全図面を対象に点名の重複をチェックし、エラー識別子を返す [RULE-DOMAIN-06]"""
        if not self.point_layer or not self.point_layer.isValid() or not pname:
            return None
        if feat_name in (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成")):
            feat_name = ""
        if drawing_name == UILabels.DRAWING_UNSPECIFIED:
            drawing_name = ""
            
        is_dup = check_point_duplicate(
            self.point_layer, ex_type, feat_name, pname, branch, drawing_name,
            exclude_feature_id=selected_edit_point_id,
        )
        return build_point_ident(ex_type, feat_name, pname, branch, drawing_name) if is_dup else None

    # ==========================================
    # Action Handlers (イベントディスパッチャ対応)
    # ==========================================

    def handle_validate_inputs(self, action: ValidateDigitizingInputsAction) -> Optional[List[UIAction]]:
        """UIの入力状態のリアルタイムバリデーションと同期を処理する"""
        state = self.state_store.state
        if state.suppress_realtime_commit:
            return []
            
        inputs = state.digitizing_inputs
        pname = str(inputs.get("point_name", ""))
        branch = str(inputs.get("branch_no", ""))
        ex_type = inputs.get("excavation_type", "")
        feat_name = inputs.get("feature_name", "")
        drawing_name = state.selected_drawing_name
        
        is_missing_feat = self.is_feature_name_missing(inputs)
        dup_ident = self.check_realtime_duplicate(ex_type, feat_name, pname, branch, state.selected_point_id, drawing_name)
        
        out_of_bounds = False
        if state.selected_point_id is not None:
            if feat := self.point_layer.getFeature(state.selected_point_id):
                if feat.isValid() and feat.hasGeometry():
                    out_of_bounds = not self.validate_drawing_bounds(drawing_name, feat.geometry().asPoint())[0]
        else:
            out_of_bounds = state.is_out_of_bounds
            
        has_err = is_missing_feat or bool(dup_ident) or out_of_bounds
        
        status_msg = ""
        if is_missing_feat:
            status_msg = UILabels.STATUS_ERR_FEATURE_REQUIRED
        elif out_of_bounds:
            status_msg = UILabels.STATUS_ERR_OUT_OF_BOUNDS
        elif dup_ident:
            status_msg = UILabels.STATUS_ERR_DUPLICATE
            
        group_label = feat_name if ex_type == ExcavationType.FEATURE.value else ExcavationType.GRID.value
        summary = {
            "group": group_label or "-",
            "pointname": f"{pname} {branch}".strip() if pname else "-",
            "coords": "-",
        }
        
        return [
            SetValidationAction(has_err, status_msg),
            SetPointInfoErrorAction(has_err, out_of_bounds),
            SetPointInfoSummaryAction(summary)
        ]

    def handle_canvas_click(self, action: CanvasClickAction) -> Optional[List[UIAction]]:
        """キャンバスがクリックされた時の自動打刻処理"""
        if not self.point_layer or not self.point_layer.isValid():
            return []
            
        map_point = action.map_point
        state = self.state_store.state
        inputs = state.digitizing_inputs
        
        pname = str(inputs.get("point_name", ""))
        branch = str(inputs.get("branch_no", ""))
        ex_type = inputs.get("excavation_type", "")
        feat_name = inputs.get("feature_name", "")
        drawing_name = state.selected_drawing_name
        
        # バリデーション
        if not pname or self.is_feature_name_missing(inputs):
            return [SetPointInfoErrorAction(has_error=True)]
            
        dup_ident = self.check_realtime_duplicate(ex_type, feat_name, pname, branch, state.selected_point_id, drawing_name)
        if dup_ident:
            return [SetPointInfoErrorAction(has_error=True)]
            
        is_valid, coords = self.validate_drawing_bounds(drawing_name, map_point)
        if not is_valid:
            return [SetPointInfoErrorAction(has_error=True, is_out_of_bounds=True)]
            
        return self._create_point(inputs, map_point, coords, drawing_name)

    def handle_add_manual_point(self, action: AddManualDigitizedPointAction) -> Optional[List[UIAction]]:
        """解除モード等で手動入力された打刻点の作成処理"""
        map_point = action.map_point
        state = self.state_store.state
        inputs = state.digitizing_inputs.copy()
        
        inputs["point_name"] = action.point_name
        inputs["branch_no"] = action.branch_no
        drawing_name = state.selected_drawing_name
        
        is_valid, coords = self.validate_drawing_bounds(drawing_name, map_point)
        return self._create_point(inputs, map_point, coords, drawing_name)

    def _create_point(self, inputs: Dict[str, Any], map_point: QgsPointXY, pixel_coords: Optional[Tuple[float, float]], drawing_name: str) -> List[UIAction]:
        """新規点を生成してレイヤに書き込む共通内部メソッド"""
        next_id = get_next_point_id(self.point_layer)
        feat_dict = {
            "drawing_name": drawing_name if drawing_name != UILabels.DRAWING_UNSPECIFIED else "",
            "excavation_type": inputs.get("excavation_type", ""),
            "feature_name": inputs.get("feature_name", "") if inputs.get("excavation_type") == ExcavationType.FEATURE.value else "",
            "color_code": self.state_store.state.current_feature_color,
            "attribute_type": inputs.get("attribute_type", ""),
            "point_name": inputs.get("point_name", ""),
            "branch_no": inputs.get("branch_no", ""),
        }
        
        new_feat = build_digitized_feature(self.point_layer, next_id, map_point, feat_dict, pixel_coords=pixel_coords)
        
        with self.busy_interaction_guard():
            insert_feature_to_layer(self.point_layer, new_feat)
            if self.update_symbology_opacity_cb:
                self.update_symbology_opacity_cb()
            if self.refresh_canvas_cb:
                self.refresh_canvas_cb()
                
        has_branch = bool(feat_dict["branch_no"])
        
        # 新規作成後はバリデーションを再発行してUIを同期する
        return [
            SetDigitizedWithBranchAction(has_branch=has_branch),
            ValidateDigitizingInputsAction()
        ]

    def handle_delete_point(self, action: DeletePointAction) -> Optional[List[UIAction]]:
        """指定されたIDの点を削除する"""
        fid = action.feature_id
        if self.point_layer and self.point_layer.isValid():
            with self.busy_interaction_guard():
                self.point_layer.startEditing()
                self.point_layer.deleteFeature(fid)
                self.point_layer.commitChanges()
                
            self.iface.messageBar().pushMessage(
                UIMessages.MSG_DELETE_SUCCESS_TITLE,
                UIMessages.MSG_DELETE_SUCCESS,
                level=Qgis.MessageLevel.Success,
                duration=3,
            )
        return [ResetSelectionAction(), ValidateDigitizingInputsAction()]

    def handle_update_attributes(self, action: UpdatePointAttributesAction) -> Optional[List[UIAction]]:
        """既存点の属性を更新する [RULE-PERSIST-05]"""
        fid = action.feature_id
        updates = action.updates
        
        if self.point_layer and self.point_layer.isValid():
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
                    
        return [ResetSelectionAction(), ValidateDigitizingInputsAction()]

    def handle_update_feature_category(self, action: UpdateFeatureCategoryAction) -> Optional[List[UIAction]]:
        """遺構名とカラーを一括更新する"""
        old_name = action.old_name
        new_name = action.new_name
        new_color = action.new_color
        
        if not self.point_layer or not self.point_layer.isValid():
            return []
            
        fields = self.point_layer.fields()
        feat_idx = fields.indexFromName("feature_name")
        color_idx = fields.indexFromName("color_code")
        if feat_idx == -1 or color_idx == -1:
            return []
            
        with self.busy_interaction_guard():
            self.point_layer.startEditing()
            for feat in self.point_layer.getFeatures():
                if safe_get_str(feat, "feature_name") == old_name:
                    self.point_layer.changeAttributeValue(feat.id(), feat_idx, new_name)
                    self.point_layer.changeAttributeValue(feat.id(), color_idx, new_color)
            self.point_layer.commitChanges()
            
        temp_list = list(self.state_store.state.feature_name_list)
        if old_name in temp_list:
            temp_list[temp_list.index(old_name)] = new_name
        elif new_name not in temp_list:
            temp_list.append(new_name)
            
        return [
            SetFeatureCacheAction(color_hex=new_color, feature_list=temp_list),
            UpdateDigitizingInputsAction({"feature_name": new_name}),
            ValidateDigitizingInputsAction()
        ]