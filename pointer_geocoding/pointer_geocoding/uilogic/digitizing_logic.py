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

from qgis.core import QgsPointXY, QgsProject, Qgis, QgsGeometry
from qgis.PyQt.QtCore import QObject

from ..logic.core import (
    check_point_duplicate, build_point_ident, get_next_point_number,
    get_next_point_id, build_digitized_feature, insert_feature_to_layer, point_duplicate_key,
    pixel_from_affine, get_source_image_size, safe_get_str, ExcavationType, AttributeType
)
from ..ui.constants import UILabels, UIMessages
from ..ui.core.state import (
    UIStateStore, UIAction, SetValidationAction, SetPointInfoErrorAction,
    SetDigitizedWithBranchAction, ResetSelectionAction, SetProcessingAction,
    UpdateDigitizingInputsAction, SetPointInfoSummaryAction, SetFeatureCacheAction,
    CanvasClickAction, AddManualDigitizedPointAction,
    DeletePointAction, UpdatePointAttributesAction, UpdateFeatureCategoryAction,
    ValidateDigitizingInputsAction, SelectPointAction, MovePointAction,
    SetPointSearchAction, SetFocusModeAction, ChangeTab2ModeAction
)


class DigitizingLogic(QObject):
    """
    点群の打刻、自動採番、重複判定、編集・削除を処理するドメインロジック。
    単一方向データフローに準拠し、EventDispatcherから呼び出されるハンドラを提供します。
    """

    # StateStore/LayerManager/Dispatcher等を受け取り、アクションハンドラをDispatcherに登録する初期化処理。
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
        self.dispatcher.register_handler(MovePointAction, self.handle_move_point)

        # リアルタイムバリデーション（軽量同期用）は、EventDispatcherの重いパイプライン
        # （SetProcessingActionによるドック全体の一時無効化）を経由すると入力中ウィジェットの
        # フォーカスが失われるため、ハンドラ登録はせずrun_validation()経由で直接呼び出す。

    # View側のUI更新/再描画コールバックをControllerに依存性注入する。
    def bind_view_callbacks(self, callbacks: Dict[str, Any]) -> None:
        """
        View側のUI更新/再描画コールバックをDI（依存性注入）する。
        ControllerからViewへの逆インポートを防ぎます。
        """
        self.update_symbology_opacity_cb = callbacks.get("update_symbology_opacity")
        self.refresh_canvas_cb = callbacks.get("refresh_canvas")

    @contextmanager
    # 処理中フラグをdispatchし、離脱時に必ず解除するコンテキストマネージャ。
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
    # 遺構モードにおいて遺構名が未指定かどうかを判定する。
    def is_feature_name_missing(self, inputs: Dict[str, Any]) -> bool:
        """遺構モードにおいて、遺構名が未指定かどうかを判定する"""
        if inputs.get("excavation_type") != ExcavationType.FEATURE.value:
            return False
        feat = inputs.get("feature_name")
        return not feat or feat in (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成"))

    # 現在のカテゴリに基づいて自動採番された次の点名を算出する。
    def calculate_next_point_number(self, excavation_type: str, feature_name: str, is_sp: bool) -> int:
        """
        現在のカテゴリに基づいて自動採番された次の点名を返す。
        （SP属性は自動採番対象から除外される [RULE-DOMAIN-06]。呼び出し元
        apply_next_point_number() が is_sp=True の場合は本メソッドを呼び出さない
        ようガードしているため、is_sp引数はここでは分岐に使用しない）
        """
        if feature_name in (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成")):
            feature_name = ""
        return get_next_point_number(self.point_layer, excavation_type, feature_name)

    # 指定カテゴリで最後に作成された点名をレイヤ走査により取得する。
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

    # 打刻点が対象図面のピクセル範囲内に収まっているかをアフィン変換で判定する。
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
            
        # 元画像のピクセル寸法で判定する(回転ワールドファイルではレイヤ寸法が回転後になるため)
        size = get_source_image_size(raster_layer)
        if size is None:
            return False, None
        width, height = size
        if 0 <= px <= width and 0 <= py <= height:
            return True, (px, py)
        return False, None

    # 全図面を対象に点名の重複有無をチェックし、重複時は識別子を返す。
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

    # UI入力状態のリアルタイムバリデーションを行い、StateStore更新用のActionを組み立てる。
    def handle_validate_inputs(self, action: ValidateDigitizingInputsAction) -> Optional[List[UIAction]]:
        """UIの入力状態のリアルタイムバリデーションと同期を処理する"""
        state = self.state_store.state
        # 編集モードでは新規モード入力欄由来のエラーを出さないため、検証せずエラーなしを返す
        if state.tab2_mode == "edit":
            return [SetValidationAction(False, ""), SetPointInfoErrorAction(False, False)]

        inputs = state.digitizing_inputs
        pname = str(inputs.get("point_name", ""))
        branch = str(inputs.get("branch_no", ""))
        ex_type = inputs.get("excavation_type", "")
        feat_name = inputs.get("feature_name", "")
        drawing_name = state.selected_drawing_name

        is_missing_feat = self.is_feature_name_missing(inputs)
        dup_ident = self.check_realtime_duplicate(ex_type, feat_name, pname, branch, state.selected_point_id, drawing_name)
        
        out_of_bounds = state.is_out_of_bounds

        has_err = is_missing_feat or bool(dup_ident) or out_of_bounds
        
        status_msg = ""
        if is_missing_feat:
            status_msg = UILabels.STATUS_ERR_FEATURE_REQUIRED
        elif out_of_bounds:
            status_msg = UILabels.STATUS_ERR_OUT_OF_BOUNDS
        elif dup_ident:
            status_msg = UILabels.STATUS_ERR_DUPLICATE
            
        actions: List[UIAction] = [
            SetValidationAction(has_err, status_msg),
            SetPointInfoErrorAction(has_err, out_of_bounds),
        ]

        # 編集モードでは、選択点のINFO要約(SelectPointActionで設定済み)を入力欄の値で上書きしない
        if state.tab2_mode != "edit":
            group_label = feat_name if ex_type == ExcavationType.FEATURE.value else ExcavationType.GRID.value
            summary = {
                "group": group_label or "-",
                "pointname": f"{pname} {branch}".strip() if pname else "-",
                "coords": "-",
            }
            actions.append(SetPointInfoSummaryAction(summary))

        return actions

    # 選択点データからINFO要約(グループ/点名+枝番/座標)を組み立てる。
    def build_point_summary(self, data: Dict[str, Any]) -> Dict[str, str]:
        """選択点データからINFO要約を作成する。座標は測量座標系(X=canvas_y, Y=canvas_x)で表示する。"""
        ex_type = str(data.get("excavation_type") or "")
        feat_name = str(data.get("feature_name") or "")
        group_label = feat_name if ex_type == ExcavationType.FEATURE.value else ExcavationType.GRID.value
        pname = str(data.get("point_name") or "")
        branch = str(data.get("branch_no") or "")
        cx = data.get("canvas_x")
        cy = data.get("canvas_y")
        try:
            coords = f"{float(cy):.3f}, {float(cx):.3f}"
        except (TypeError, ValueError):
            coords = "-"
        return {
            "group": group_label or "-",
            "pointname": f"{pname} {branch}".strip() if pname else "-",
            "coords": coords,
        }

    # 点レイヤから指定IDの最新値を再取得し、選択点データ(dict)として返す。取得不能ならNone。
    def read_point_data(self, fid: int) -> Optional[Dict[str, Any]]:
        """DBの最新値を再取得して選択点データを組み立てる(編集確定後の再選択用)"""
        if not self.point_layer or not self.point_layer.isValid():
            return None
        feat = self.point_layer.getFeature(fid)
        if not feat.isValid():
            return None
        names = feat.fields().names()
        return {
            "point_id": feat["point_id"] if "point_id" in names else None,
            "drawing_name": safe_get_str(feat, "drawing_name"),
            "excavation_type": safe_get_str(feat, "excavation_type"),
            "feature_name": safe_get_str(feat, "feature_name"),
            "color_code": safe_get_str(feat, "color_code"),
            "attribute_type": safe_get_str(feat, "attribute_type"),
            "point_name": safe_get_str(feat, "point_name"),
            "branch_no": safe_get_str(feat, "branch_no"),
            "canvas_x": feat["canvas_x"] if "canvas_x" in names else None,
            "canvas_y": feat["canvas_y"] if "canvas_y" in names else None,
            "feature_id": feat.id(),
        }

    # 指定IDの点を再読込して再選択するActionを返す。読込不能なら選択解除Actionを返す。
    def _reselect_action(self, fid: int) -> UIAction:
        data = self.read_point_data(fid)
        if data is None:
            return ResetSelectionAction()
        return SelectPointAction(fid, data, self.build_point_summary(data))

    # 点名が完全一致する全フィーチャのIDをfid昇順で返す(読込不能な点は除外)。
    def find_points_by_name(self, name: str) -> List[int]:
        if not name or not self.point_layer or not self.point_layer.isValid():
            return []
        if "point_name" not in self.point_layer.fields().names():
            return []
        hit_ids = sorted(
            feat.id() for feat in self.point_layer.getFeatures()
            if safe_get_str(feat, "point_name") == name
        )
        return [fid for fid in hit_ids if self.read_point_data(fid) is not None]

    # 点名検索の1回分(押下)に対応するAction列を組み立てて返す。空入力なら空リスト(何もしない)。
    def build_point_search_actions(self, text: str) -> List[UIAction]:
        """
        検索文字列(strip後)と完全一致する点を fid 昇順で並べ、押下ごとに順送りで選択するAction列を返す。
        ヒット時: [SetFocusModeAction(False)] → [ChangeTab2ModeAction('edit')] → SelectPointAction → SetPointSearchAction。
        0件時: SetPointSearchAction(hit_ids=(), index=-1, query) のみ(選択は変更しない)。
        SelectPointAction は検索状態をデフォルトへ戻すため、SetPointSearchAction は必ずその後ろに置く。
        """
        query = (text or "").strip()
        if not query:
            return []

        hit_ids = self.find_points_by_name(query)
        if not hit_ids:
            return [SetPointSearchAction((), -1, query)]

        state = self.state_store.state
        if state.search_query == query and 0 <= state.search_index < len(hit_ids):
            index = (state.search_index + 1) % len(hit_ids)
        else:
            index = 0
        fid = hit_ids[index]
        data = self.read_point_data(fid)
        if data is None:
            return [SetPointSearchAction((), -1, query)]

        actions: List[UIAction] = []
        if state.focus_active:
            actions.append(SetFocusModeAction(False))
        if state.tab2_mode == "new":
            actions.append(ChangeTab2ModeAction("edit"))
        actions.append(SelectPointAction(fid, data, self.build_point_summary(data)))
        actions.append(SetPointSearchAction(tuple(hit_ids), index, query))
        return actions

    # リアルタイムバリデーションをEventDispatcherを経由せず直接StateStoreへ反映する。
    def run_validation(self) -> None:
        """
        リアルタイムバリデーションをEventDispatcherを経由せずに直接実行する。

        ValidateDigitizingInputsActionをEventDispatcherへdispatchすると
        SetProcessingAction(True)→ハンドラ→SetProcessingAction(False)という
        重いパイプラインを経由し、is_processing=Trueの瞬間にドック全体が
        setEnabled(False)されてフォーカス中のウィジェット（点名/枝番の入力欄等）の
        フォーカスが失われてしまう。1文字入力のたびに発生するこの処理は軽量かつ
        確定前のUIイベントであるため、Core_Architecture_UIUX.mdの
        【未登録操作のローカル受容】方針に従いパイプラインを素通りしてStateStoreへ
        直接反映する。
        """
        actions = self.handle_validate_inputs(ValidateDigitizingInputsAction())
        if actions:
            self.state_store.dispatch_batch(actions)

    # キャンバスクリック時にバリデーションを経て点を自動打刻する。
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
        if self.is_feature_name_missing(inputs):
            return [
                SetValidationAction(True, UILabels.STATUS_ERR_FEATURE_REQUIRED),
                SetPointInfoErrorAction(has_error=True),
            ]
        if not pname:
            return [SetPointInfoErrorAction(has_error=True)]

        dup_ident = self.check_realtime_duplicate(ex_type, feat_name, pname, branch, state.selected_point_id, drawing_name)
        if dup_ident:
            return [
                SetValidationAction(True, UILabels.STATUS_ERR_DUPLICATE),
                SetPointInfoErrorAction(has_error=True),
            ]
            
        is_valid, coords = self.validate_drawing_bounds(drawing_name, map_point)
        if not is_valid:
            return [
                SetValidationAction(True, UILabels.STATUS_ERR_OUT_OF_BOUNDS),
                SetPointInfoErrorAction(has_error=True, is_out_of_bounds=True),
            ]

        return self._create_point(inputs, map_point, coords, drawing_name)

    # 解除モード等で手動入力された点名・枝番を用いて打刻点を作成する。
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
    
    # 自動採番モード時に次の連番を計算し、入力欄更新用のActionを返す。
    def apply_next_point_number(self) -> Optional[UIAction]:
        """現在のカテゴリに基づき最新の連番（最新point_idのpoint_name+1）を計算してActionを返す"""
        state = self.state_store.state
        inputs = state.digitizing_inputs
        ex_type = inputs.get("excavation_type", ExcavationType.GRID.value)
        feat_name = inputs.get("feature_name", "")
        # attribute_code / attribute_type の両方のキーに対応
        attr_code = inputs.get("attribute_code") or inputs.get("attribute_type", "")
        is_sp = (attr_code == AttributeType.SP.value)
        
        if state.autonum_mode == "auto" and not is_sp:
            next_pname = self.calculate_next_point_number(ex_type, feat_name, is_sp)
            return UpdateDigitizingInputsAction({"point_name": next_pname})
        return None

    # 新規点フィーチャを組み立ててレイヤへ書き込み、後続採番・再描画も行う共通内部処理。
    def _create_point(
        self, inputs: Dict[str, Any], map_point: QgsPointXY, pixel_coords: Optional[Tuple[float, float]], drawing_name: str
    ) -> List[UIAction]:
        """新規点を生成してレイヤに書き込む共通内部メソッド"""
        next_id = get_next_point_id(self.point_layer)
        attr_code = inputs.get("attribute_code") or inputs.get("attribute_type", "")
        
        feat_dict = {
            "drawing_name": drawing_name if drawing_name != UILabels.DRAWING_UNSPECIFIED else "",
            "excavation_type": inputs.get("excavation_type", ""),
            "feature_name": inputs.get("feature_name", "") if inputs.get("excavation_type") == ExcavationType.FEATURE.value else "",
            "color_code": self.state_store.state.current_feature_color,
            "attribute_type": attr_code,
            "point_name": inputs.get("point_name", ""),
            "branch_no": inputs.get("branch_no", ""),
        }
        
        new_feat = build_digitized_feature(self.point_layer, next_id, map_point, feat_dict, pixel_coords=pixel_coords)
        
        with self.busy_interaction_guard():
            insert_feature_to_layer(self.point_layer, new_feat)
            # update_symbology_opacity_cb() recalculates the data-driven opacity
            # expression for the new feature and triggers the layer's own native
            # repaint (QgsVectorLayer.triggerRepaint()) internally; it no longer
            # issues a separate manual canvas.refresh(). refresh_canvas_cb() below
            # remains as the single explicit redraw for this new-point path
            # (Core_Architecture_UIUX.md section 2: no duplicate manual repaints).
            if self.update_symbology_opacity_cb:
                self.update_symbology_opacity_cb()
            if self.refresh_canvas_cb:
                self.refresh_canvas_cb()

        has_branch = bool(feat_dict["branch_no"])
        actions: List[UIAction] = [
            SetPointInfoErrorAction(has_error=False, is_out_of_bounds=False),
            SetDigitizedWithBranchAction(has_branch=has_branch),
        ]
        
        # 【重要】 打刻成功後、枝番がなくSP属性でなく自動採番モードの場合、次の連番を自動計算してActionを発行する
        is_sp = (attr_code == AttributeType.SP.value)
        if not has_branch and not is_sp and self.state_store.state.autonum_mode == "auto":
            autonum_action = self.apply_next_point_number()
            if autonum_action:
                actions.append(autonum_action)
            
        actions.append(ValidateDigitizingInputsAction())
        return actions

    # 指定IDの点をレイヤから削除し、成功メッセージを表示する。
    def handle_delete_point(self, action: DeletePointAction) -> Optional[List[UIAction]]:
        """指定されたID(単体または複数)の点を、1回の編集セッションでまとめて削除する"""
        if action.feature_ids is not None:
            requested_ids = list(action.feature_ids)
        elif action.feature_id is not None:
            requested_ids = [action.feature_id]
        else:
            requested_ids = []

        deleted_count = 0
        if self.point_layer and self.point_layer.isValid():
            # 存在しないIDは無視する
            target_ids = [fid for fid in dict.fromkeys(requested_ids) if self.point_layer.getFeature(fid).isValid()]
            if target_ids:
                with self.busy_interaction_guard():
                    self.point_layer.startEditing()
                    self.point_layer.deleteFeatures(target_ids)
                    if self.point_layer.commitChanges():
                        deleted_count = len(target_ids)
                        # update_symbology_opacity_cb() はレイヤーのネイティブ再描画に任せる(手動refreshは行わない)
                        if self.update_symbology_opacity_cb:
                            self.update_symbology_opacity_cb()
                    else:
                        self._rollback_and_resync()

                if deleted_count:
                    message = (
                        UIMessages.MSG_DELETE_SUCCESS
                        if deleted_count == 1
                        else UIMessages.MSG_DELETE_SUCCESS_COUNT.format(count=deleted_count)
                    )
                    self.iface.messageBar().pushMessage(
                        UIMessages.MSG_DELETE_SUCCESS_TITLE,
                        message,
                        level=Qgis.MessageLevel.Success,
                        duration=3,
                    )
                else:
                    self._notify_commit_failed()

        actions: List[UIAction] = [ResetSelectionAction()]
        autonum_action = self._autonum_action_if_auto()
        if autonum_action:
            actions.append(autonum_action)
        actions.append(ValidateDigitizingInputsAction())
        return actions

    # 自動採番モードのときだけ、現在の入力カテゴリに基づく「次の点名」を再計算するActionを返す(既存点の点名は変更しない)。
    def _autonum_action_if_auto(self) -> Optional[UIAction]:
        if self.state_store.state.autonum_mode == "auto":
            return self.apply_next_point_number()
        return None

    # commitChanges失敗時に編集内容を破棄し、空間インデックス/属性キャッシュを再構築する。
    def _rollback_and_resync(self) -> None:
        self.point_layer.rollBack()
        if self.layer_manager and hasattr(self.layer_manager, "init_spatial_index_and_cache"):
            self.layer_manager.init_spatial_index_and_cache()

    # 保存失敗をメッセージバーへ通知する。
    def _notify_commit_failed(self) -> None:
        self.iface.messageBar().pushMessage(
            UIMessages.MSG_COMMIT_FAILED_TITLE,
            UIMessages.MSG_COMMIT_FAILED,
            level=Qgis.MessageLevel.Critical,
            duration=5,
        )

    # 既存点の属性を更新し、図面変更時は境界チェックも行う。
    def handle_update_attributes(self, action: UpdatePointAttributesAction) -> Optional[List[UIAction]]:
        """既存点の属性を更新する [RULE-PERSIST-05]"""
        if action.feature_ids is not None:
            return self._handle_bulk_update(list(action.feature_ids), dict(action.updates))
        fid = action.feature_id
        updates = action.updates

        if self.point_layer and self.point_layer.isValid():
            new_drawing_name = updates.get("drawing_name")
            if new_drawing_name and new_drawing_name != UILabels.DRAWING_UNSPECIFIED:
                current_feat = self.point_layer.getFeature(fid)
                current_drawing_name = safe_get_str(current_feat, "drawing_name")
                if new_drawing_name != current_drawing_name and current_feat.hasGeometry():
                    is_valid, _ = self.validate_drawing_bounds(new_drawing_name, current_feat.geometry().asPoint())
                    if not is_valid:
                        self.iface.messageBar().pushMessage(
                            UIMessages.MSG_UPDATE_OUT_OF_BOUNDS_TITLE,
                            UIMessages.MSG_UPDATE_OUT_OF_BOUNDS,
                            level=Qgis.MessageLevel.Warning,
                            duration=5,
                        )
                        return [self._reselect_action(fid), ValidateDigitizingInputsAction()]

            with self.busy_interaction_guard():
                field_names = self.point_layer.fields().names()
                self.point_layer.startEditing()
                for field_name, value in updates.items():
                    if field_name in field_names:
                        idx = field_names.index(field_name)
                        self.point_layer.changeAttributeValue(fid, idx, value)
                self.point_layer.commitChanges()

                # update_symbology_opacity_cb() only recalculates the data-driven
                # opacity expression and lets the layer's own native repaint signal
                # (triggerRepaint(), invoked internally) drive the redraw; no manual
                # canvas.refresh() is issued here, mirroring handle_delete_point()'s
                # reliance on QGIS's native signals (Core_Architecture_UIUX.md section 2).
                if self.update_symbology_opacity_cb:
                    self.update_symbology_opacity_cb()

        # 更新後もその点を選択したままにし、最新値でINFOを再表示する
        return [self._reselect_action(fid), ValidateDigitizingInputsAction()]

    # 複数点の属性(出土形態・遺構名・属性記号・図面名)を1編集セッション・1commitで一括更新する。
    def _handle_bulk_update(self, feature_ids: List[int], updates: Dict[str, Any]) -> List[UIAction]:
        """
        一括変更。点名・枝番は変更しない(既存点の点名は保持)。スキップ規則:
        SP属性の点 / 図面変更先が範囲外 / 実効の出土形態=遺構で遺構名が空 / 重複(出土形態[+遺構名]・点名・枝番)。
        重複は「選択外の全点のキー集合」+「選択点の現在キー」を更新前に1回だけ作り、選択点を順に判定して
        採用した点のキーへ差し替える(バッチ内衝突も検出。選択点の現在キーを含めるため、選択点同士の
        キー入れ替えは保守的に重複扱いとなる)。キー定義は core.point_duplicate_key(check_point_duplicate と一致)。
        """
        skipped = {"sp": 0, "dup": 0, "bounds": 0, "feature": 0}
        updated_count = 0
        commit_failed = False

        if self.point_layer and self.point_layer.isValid() and updates:
            # 存在しないIDは無視する(重複IDも1件に集約)
            selected: List[Any] = []
            for fid in dict.fromkeys(feature_ids):
                feat = self.point_layer.getFeature(fid)
                if feat.isValid():
                    selected.append(feat)

            # 重複キー集合(更新前に1回だけ構築)
            key_counts: Dict[Any, int] = {}
            for feat in self.point_layer.getFeatures():
                key = point_duplicate_key(
                    safe_get_str(feat, "excavation_type"), safe_get_str(feat, "feature_name"),
                    safe_get_str(feat, "point_name"), safe_get_str(feat, "branch_no"),
                )
                if key is not None:
                    key_counts[key] = key_counts.get(key, 0) + 1

            feature_updates: List[Tuple[int, Dict[str, Any]]] = []
            unspecified = (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成"))
            for feat in selected:
                fid = feat.id()
                if safe_get_str(feat, "attribute_type") == AttributeType.SP.value:
                    skipped["sp"] += 1
                    continue

                cur_ex = safe_get_str(feat, "excavation_type")
                cur_feat = safe_get_str(feat, "feature_name")
                cur_pname = safe_get_str(feat, "point_name")
                cur_branch = safe_get_str(feat, "branch_no")
                cur_drawing = safe_get_str(feat, "drawing_name")

                new_ex = updates.get("excavation_type", cur_ex)
                new_feat = updates.get("feature_name", cur_feat)
                if new_feat in unspecified:
                    new_feat = ""
                if new_ex == ExcavationType.GRID.value:
                    new_feat = ""
                elif new_ex == ExcavationType.FEATURE.value and not new_feat:
                    skipped["feature"] += 1
                    continue

                if "drawing_name" in updates:
                    new_drawing = updates["drawing_name"]
                    if new_drawing and new_drawing != UILabels.DRAWING_UNSPECIFIED and new_drawing != cur_drawing and feat.hasGeometry():
                        is_valid, _ = self.validate_drawing_bounds(new_drawing, feat.geometry().asPoint())
                        if not is_valid:
                            skipped["bounds"] += 1
                            continue
                    if new_drawing == UILabels.DRAWING_UNSPECIFIED:
                        new_drawing = ""
                else:
                    new_drawing = cur_drawing

                old_key = point_duplicate_key(cur_ex, cur_feat, cur_pname, cur_branch)
                new_key = point_duplicate_key(new_ex, new_feat, cur_pname, cur_branch)
                if new_key != old_key and new_key is not None:
                    if key_counts.get(new_key, 0) > 0:
                        skipped["dup"] += 1
                        continue
                    if old_key is not None:
                        key_counts[old_key] = key_counts.get(old_key, 1) - 1
                    key_counts[new_key] = key_counts.get(new_key, 0) + 1

                new_values: Dict[str, Any] = {"drawing_name": new_drawing, "excavation_type": new_ex, "feature_name": new_feat}
                if "attribute_type" in updates:
                    new_values["attribute_type"] = updates["attribute_type"]
                feature_updates.append((fid, new_values))

            if feature_updates:
                with self.busy_interaction_guard():
                    self.point_layer.startEditing()
                    field_names = self.point_layer.fields().names()
                    for fid, values in feature_updates:
                        for field_name, value in values.items():
                            if field_name in field_names:
                                self.point_layer.changeAttributeValue(fid, field_names.index(field_name), value)
                    if self.point_layer.commitChanges():
                        updated_count = len(feature_updates)
                        # 再描画はレイヤーのネイティブシグナルに任せ、手動refreshは行わない(Core_Architecture_UIUX.md §2)。
                        if self.update_symbology_opacity_cb:
                            self.update_symbology_opacity_cb()
                    else:
                        self._rollback_and_resync()
                if not updated_count:
                    commit_failed = True
                    self._notify_commit_failed()

            if not commit_failed and (updated_count or sum(skipped.values())):
                self._notify_bulk_update_result(updated_count, skipped)

        actions: List[UIAction] = [ResetSelectionAction()]
        autonum_action = self._autonum_action_if_auto()
        if autonum_action:
            actions.append(autonum_action)
        actions.append(ValidateDigitizingInputsAction())
        return actions

    # 一括変更の結果(更新件数・スキップ件数と内訳)をメッセージバーへ表示する。
    def _notify_bulk_update_result(self, updated: int, skipped: Dict[str, int]) -> None:
        total_skipped = sum(skipped.values())
        message = UIMessages.MSG_BULK_UPDATE_RESULT.format(updated=updated)
        if total_skipped:
            parts = []
            for key, template in (
                ("sp", UIMessages.MSG_BULK_SKIP_SP),
                ("dup", UIMessages.MSG_BULK_SKIP_DUPLICATE),
                ("bounds", UIMessages.MSG_BULK_SKIP_OUT_OF_BOUNDS),
                ("feature", UIMessages.MSG_BULK_SKIP_FEATURE_REQUIRED),
            ):
                if skipped[key]:
                    parts.append(template.format(n=skipped[key]))
            message += " " + UIMessages.MSG_BULK_UPDATE_SKIPPED.format(skipped=total_skipped, detail=", ".join(parts))
        self.iface.messageBar().pushMessage(
            UIMessages.MSG_BULK_UPDATE_TITLE,
            message,
            level=Qgis.MessageLevel.Warning if total_skipped else Qgis.MessageLevel.Success,
            duration=5,
        )

    # 既存点を指定位置へ移動し、ジオメトリと座標属性を更新する(図面範囲外なら破棄)。
    def handle_move_point(self, action: MovePointAction) -> Optional[List[UIAction]]:
        """既存点のドラッグ移動を確定する"""
        fid = action.feature_id
        map_point = action.map_point

        if not self.point_layer or not self.point_layer.isValid():
            return [self._reselect_action(fid), ValidateDigitizingInputsAction()]

        feat = self.point_layer.getFeature(fid)
        if not feat.isValid():
            return [ResetSelectionAction(), ValidateDigitizingInputsAction()]

        drawing_name = safe_get_str(feat, "drawing_name")
        is_valid, pixel_coords = self.validate_drawing_bounds(drawing_name, map_point)
        if not is_valid or pixel_coords is None:
            self.iface.messageBar().pushMessage(
                UIMessages.MSG_UPDATE_OUT_OF_BOUNDS_TITLE,
                UIMessages.MSG_UPDATE_OUT_OF_BOUNDS,
                level=Qgis.MessageLevel.Warning,
                duration=5,
            )
            return [self._reselect_action(fid), ValidateDigitizingInputsAction()]

        with self.busy_interaction_guard():
            fields = self.point_layer.fields()
            new_values = {
                "canvas_x": map_point.x(),
                "canvas_y": map_point.y(),
                "real_x": map_point.x(),
                "real_y": map_point.y(),
                "pixel_x": pixel_coords[0],
                "pixel_y": pixel_coords[1],
            }
            self.point_layer.startEditing()
            self.point_layer.changeGeometry(fid, QgsGeometry.fromPointXY(map_point))
            for field_name, value in new_values.items():
                idx = fields.indexFromName(field_name)
                if idx != -1:
                    self.point_layer.changeAttributeValue(fid, idx, value)
            self.point_layer.commitChanges()

            # 再描画はレイヤーのネイティブシグナルに任せ、手動refreshは行わない(Core_Architecture_UIUX.md §2)。
            if self.update_symbology_opacity_cb:
                self.update_symbology_opacity_cb()

        return [self._reselect_action(fid), ValidateDigitizingInputsAction()]

    # 遺構名とカラーコードを対象フィーチャ群に一括反映し、遺構名キャッシュも更新する。
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