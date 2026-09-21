"""
/***************************************************************************
 PointerGeocoding Plugin - UI State & Actions
 ***************************************************************************/

単一方向データフロー (Unidirectional Data Flow) を実現するための状態管理モジュール。
Action の発行 -> Dispatcher (副作用処理) -> Reducer (純粋な状態更新) -> UIStateStore (通知)
のサイクルで UI の状態を管理します。
"""
from dataclasses import dataclass, field, replace
from typing import Dict, Any, Optional, List, Tuple
from qgis.PyQt.QtCore import QObject, pyqtSignal

# =========================================================================
# 1. State Data Model
# =========================================================================

@dataclass(frozen=True)
class UIState:
    """メイン画面（Dockおよび各Tab）の表示・動作状態を保持する不変データモデル"""
    # 1. UIモード管理
    tab1_mode: str = "new"  # "new" | "edit"
    tab2_mode: str = "new"  # "new" | "edit"
    autonum_mode: str = "auto"  # "auto" | "release"
    
    # 2. 選択・編集状態
    selected_point_id: Optional[int] = None
    selected_point_data: Optional[Dict[str, Any]] = None
    has_digitized_with_branch: bool = False
    selected_drawing_name: str = ""
    
    # 3. 制御フラグ
    suppress_realtime_commit: bool = False
    has_input_error: bool = False
    point_info_has_error: bool = False
    is_out_of_bounds: bool = False
    status_message: str = ""
    
    # 4. キャッシュ・表示データ
    focus_active: bool = False
    display_filters: Dict[str, Any] = field(default_factory=dict)
    point_info_summary: Dict[str, str] = field(
        default_factory=lambda: {"group": "-", "pointname": "-", "coords": "-"}
    )
    
    # 5. 遺構カラー・リストキャッシュ
    current_feature_color: str = "#FF5722"
    feature_name_list: List[str] = field(default_factory=list)

    # 6. 画像管理 (Tab1) 状態
    current_copied_image_path: Optional[str] = None
    confirmed_layer_name: Optional[str] = None
    calculated_affine_params: Optional[Tuple[float, float, float, float, float, float]] = None
    ref_points_data: List[Dict[str, Any]] = field(default_factory=list)
    tab1_residual_summary: str = ""
    
    # 7. プログラムからの入力制御・UIロック状態
    is_processing: bool = False
    digitizing_inputs: Dict[str, Any] = field(default_factory=dict)
    
    # 8. 出力 (Tab4) 状態
    output_encoding: int = 0  # 0: UTF-8, 1: Shift-JIS
    output_csv_path: str = ""


# =========================================================================
# 2. Actions (Intentions)
# =========================================================================

class UIAction:
    """状態更新や副作用の意図を表現する基底クラス"""
    pass

# --- 【共通・制御フラグ系 Action】 ---
@dataclass
class SetProcessingAction(UIAction):
    is_processing: bool

@dataclass
class SetValidationAction(UIAction):
    has_error: bool
    message: str

@dataclass
class SetSuppressCommitAction(UIAction):
    suppress: bool


# --- 【Tab1: 画像管理・事前配置系 Action】 ---
@dataclass
class ChangeTab1ModeAction(UIAction):
    mode: str

@dataclass
class SetGeorefStateAction(UIAction):
    image_path: Optional[str] = None
    layer_name: Optional[str] = None
    affine_params: Optional[Tuple[float, float, float, float, float, float]] = None
    ref_points: Optional[List[Dict[str, Any]]] = None
    clear_ref_points: bool = False
    residual_summary: Optional[str] = None

# Tab1 副作用リクエスト系 (Dispatcherで処理され、Stateは直接持たない)
@dataclass
class PreviewCanvasClickedAction(UIAction):
    pixel_x: float
    pixel_y: float

@dataclass
class SelectEditLayerAction(UIAction):
    layer_name: str

@dataclass
class UpdateRefTableCellAction(UIAction):
    row: int
    column: int
    text_x: str
    text_y: str

@dataclass
class ConfirmImageAction(UIAction):
    layer_name: str
    image_path: str

@dataclass
class DeleteLayerAction(UIAction):
    layer_name: str

@dataclass
class RenameLayerAction(UIAction):
    old_name: str
    new_name: str

@dataclass
class TransformAction(UIAction):
    pass

@dataclass
class ExportLayerAction(UIAction):
    layer_name: str


# --- 【Tab2: 共通・モード・選択切り替え系 Action】 ---
@dataclass
class ChangeTab2ModeAction(UIAction):
    mode: str

@dataclass
class ChangeAutonumModeAction(UIAction):
    mode: str

@dataclass
class SetFocusModeAction(UIAction):
    active: bool

@dataclass
class SelectDrawingAction(UIAction):
    drawing_name: str

@dataclass
class SetDisplayFiltersAction(UIAction):
    filters: Dict[str, Any]

@dataclass
class SetFeatureCacheAction(UIAction):
    color_hex: Optional[str] = None
    feature_list: Optional[List[str]] = None

@dataclass
class SetPointInfoSummaryAction(UIAction):
    summary: Dict[str, str]

@dataclass
class SetPointInfoErrorAction(UIAction):
    has_error: bool
    is_out_of_bounds: bool = False


# --- 【Tab2: 打刻・ポイント編集系 Action】 ---
@dataclass
class SelectPointAction(UIAction):
    point_id: Optional[int]
    point_data: Optional[Dict[str, Any]] = None

@dataclass
class ResetSelectionAction(UIAction):
    pass

@dataclass
class SetDigitizedWithBranchAction(UIAction):
    has_branch: bool

@dataclass
class UpdateDigitizingInputsAction(UIAction):
    inputs: Dict[str, Any]
    
@dataclass
class TriggerAutoNumberAction(UIAction):
    """出土形態や遺構名が変更された際、DBを検索して自動採番を再実行する"""
    pass

@dataclass
class OpenFeatureManageAction(UIAction):
    """遺構管理ダイアログを開き、必要に応じてDBのカラー・名称を一括更新する"""
    pass

@dataclass
class OpenPointEditAction(UIAction):
    """キャンバス上の既存点がクリックされた際、編集ダイアログを開く"""
    point_data: Dict[str, Any]

# Tab2 副作用リクエスト系 (キャンバス操作、DB操作)
@dataclass
class CanvasDigitizeAction(UIAction):
    """キャンバスでの打刻（新規追加）を実行する"""
    map_point: Any  # QgsPointXY
    is_release_mode: bool = False
    release_point_name: str = ""
    release_branch_no: str = ""

@dataclass
class CommitEditPointAction(UIAction):
    """既存ポイントの属性変更をコミットする"""
    point_id: int
    updates: Dict[str, Any]

@dataclass
class DeletePointAction(UIAction):
    """ポイントを削除する"""
    point_id: int


# --- 【Tab2: QGISレイヤ可視性制御系 Action (副作用のみ)】 ---
@dataclass
class SetRefLayerVisibilityAction(UIAction):
    visible: bool

@dataclass
class SetDrawingLayerVisibilityAction(UIAction):
    layer_id: str
    visible: bool

@dataclass
class ToggleAllDrawingsVisibilityAction(UIAction):
    visible: bool


# --- 【Tab3: 環境設定系 Action】 ---
@dataclass
class SaveSettingsAction(UIAction):
    settings: Dict[str, Any]


# --- 【Tab4: 出力系 Action】 ---
@dataclass
class UpdateOutputSettingsAction(UIAction):
    encoding: Optional[int] = None
    csv_path: Optional[str] = None

@dataclass
class ExportCsvAction(UIAction):
    pass


# =========================================================================
# 3. Reducer (Pure Function)
# =========================================================================

def ui_state_reducer(state: UIState, action: UIAction) -> Dict[str, Any]:
    """Actionの内容に基づき、UIStateの更新差分（kwargs辞書）を生成する純粋関数。
    ※ 副作用のみのAction(DB保存、QGIS操作等)はここには記載せず、Dispatcherで処理されます。
    """
    new_state_kwargs = {}
    
    # 共通制御フラグ系
    if isinstance(action, SetProcessingAction):
        new_state_kwargs['is_processing'] = action.is_processing
    elif isinstance(action, SetValidationAction):
        new_state_kwargs['has_input_error'] = action.has_error
        new_state_kwargs['status_message'] = action.message
    elif isinstance(action, SetSuppressCommitAction):
        new_state_kwargs['suppress_realtime_commit'] = action.suppress
        
    # Tab1: 画像管理系
    elif isinstance(action, ChangeTab1ModeAction):
        new_state_kwargs['tab1_mode'] = action.mode
    elif isinstance(action, SetGeorefStateAction):
        if action.image_path is not None:
            new_state_kwargs['current_copied_image_path'] = action.image_path
        if action.layer_name is not None:
            new_state_kwargs['confirmed_layer_name'] = action.layer_name
        if action.affine_params is not None:
            new_state_kwargs['calculated_affine_params'] = action.affine_params
        if action.ref_points is not None:
            new_state_kwargs['ref_points_data'] = action.ref_points
        elif action.clear_ref_points:
            new_state_kwargs['ref_points_data'] = []
        if action.residual_summary is not None:
            new_state_kwargs['tab1_residual_summary'] = action.residual_summary
            
    # Tab2: 共通・表示制御系
    elif isinstance(action, ChangeTab2ModeAction):
        new_state_kwargs['tab2_mode'] = action.mode
    elif isinstance(action, ChangeAutonumModeAction):
        new_state_kwargs['autonum_mode'] = action.mode
    elif isinstance(action, SetFocusModeAction):
        new_state_kwargs['focus_active'] = action.active
    elif isinstance(action, SelectDrawingAction):
        new_state_kwargs['selected_drawing_name'] = action.drawing_name
    elif isinstance(action, SetDisplayFiltersAction):
        new_state_kwargs['display_filters'] = action.filters
    elif isinstance(action, SetFeatureCacheAction):
        if action.color_hex is not None:
            new_state_kwargs['current_feature_color'] = action.color_hex
        if action.feature_list is not None:
            new_state_kwargs['feature_name_list'] = action.feature_list
    elif isinstance(action, SetPointInfoSummaryAction):
        new_state_kwargs['point_info_summary'] = action.summary
    elif isinstance(action, SetPointInfoErrorAction):
        new_state_kwargs['point_info_has_error'] = action.has_error
        new_state_kwargs['is_out_of_bounds'] = action.is_out_of_bounds

    # Tab2: 打刻・編集系
    elif isinstance(action, SelectPointAction):
        new_state_kwargs['selected_point_id'] = action.point_id
        new_state_kwargs['selected_point_data'] = action.point_data
    elif isinstance(action, ResetSelectionAction):
        new_state_kwargs['selected_point_id'] = None
        new_state_kwargs['selected_point_data'] = None
        new_state_kwargs['is_out_of_bounds'] = False
        new_state_kwargs['point_info_has_error'] = False
        new_state_kwargs['has_digitized_with_branch'] = False
    elif isinstance(action, SetDigitizedWithBranchAction):
        new_state_kwargs['has_digitized_with_branch'] = action.has_branch
    elif isinstance(action, UpdateDigitizingInputsAction):
        current_inputs = dict(state.digitizing_inputs)
        current_inputs.update(action.inputs)
        new_state_kwargs['digitizing_inputs'] = current_inputs

    # Tab4: 出力系
    elif isinstance(action, UpdateOutputSettingsAction):
        if action.encoding is not None:
            new_state_kwargs['output_encoding'] = action.encoding
        if action.csv_path is not None:
            new_state_kwargs['output_csv_path'] = action.csv_path

    return new_state_kwargs


# =========================================================================
# 4. State Store
# =========================================================================

class UIStateStore(QObject):
    state_changed = pyqtSignal(object, dict)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._state = UIState()

    @property
    def state(self) -> UIState:
        return self._state

    def dispatch_silent(self, action: UIAction) -> None:
        self._apply_action(action, emit_signal=False)

    def dispatch(self, action: UIAction) -> None:
        self._apply_action(action, emit_signal=True)

    def _apply_action(self, action: UIAction, emit_signal: bool = True) -> None:
        # 純粋関数に計算を委譲
        new_state_kwargs = ui_state_reducer(self._state, action)
        
        if not new_state_kwargs:
            return

        new_state = replace(self._state, **new_state_kwargs)
        
        diff = {k: v for k, v in new_state_kwargs.items() if getattr(self._state, k) != v}
                
        if diff:
            self._state = new_state
            if emit_signal:
                self.state_changed.emit(self._state, diff)