from dataclasses import dataclass, field, replace
from typing import Dict, Any, Optional, List, Tuple
from qgis.PyQt.QtCore import QObject, pyqtSignal

@dataclass(frozen=True)
class UIState:
    """メイン画面（Dockおよび各Tab）の表示・動作状態を保持する不変データモデル"""
    # 1. UIモード管理
    tab1_mode: str = "new"  # "new" | "edit"
    tab2_mode: str = "new"  # "new" | "edit"
    autonum_mode: str = "auto"  # "auto" | "release"
    
    # 2. 選択・編集状態
    selected_point_id: Optional[int] = None
    has_digitized_with_branch: bool = False
    selected_drawing_name: str = ""

    # 3. 制御フラグ
    has_input_error: bool = False
    point_info_has_error: bool = False
    is_out_of_bounds: bool = False
    status_message: str = ""
    error_focus_field: Optional[str] = None  # エラー発生時のフォーカス対象フィールドID
    
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
    
    # 7. プログラムからの入力制御・UIロック状態
    is_processing: bool = False
    digitizing_inputs: Dict[str, Any] = field(default_factory=dict)
    
    # 8. 出力 (Tab4) 状態
    output_encoding: int = 0  # 0: UTF-8, 1: Shift-JIS
    output_csv_path: str = ""

class UIAction:
    """状態更新の意図を表現する基底クラス"""
    pass

# ==========================================
# モード・選択切り替え系 Action
# ==========================================
@dataclass
class ChangeTab1ModeAction(UIAction):
    mode: str

@dataclass
class ChangeTab2ModeAction(UIAction):
    mode: str

@dataclass
class ChangeAutonumModeAction(UIAction):
    mode: str

@dataclass
class SetDigitizedWithBranchAction(UIAction):
    has_branch: bool

@dataclass
class SelectDrawingAction(UIAction):
    drawing_name: str

# ==========================================
# 画像管理 (Tab1) 系 Action
# ==========================================
@dataclass
class SetGeorefStateAction(UIAction):
    image_path: Optional[str] = None
    layer_name: Optional[str] = None
    affine_params: Optional[Tuple[float, float, float, float, float, float]] = None
    ref_points: Optional[List[Dict[str, Any]]] = None
    clear_ref_points: bool = False

# ==========================================
# 表示制御・フィルター系 Action
# ==========================================
@dataclass
class SetFocusModeAction(UIAction):
    active: bool

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

# ==========================================
# バリデーション・制御フラグ系 Action
# ==========================================
@dataclass
class SetValidationAction(UIAction):
    has_error: bool
    message: str
    focus_field_id: Optional[str] = None

@dataclass
class SetPointInfoErrorAction(UIAction):
    has_error: bool
    is_out_of_bounds: bool = False

@dataclass
class ResetSelectionAction(UIAction):
    pass

@dataclass
class SetProcessingAction(UIAction):
    is_processing: bool

@dataclass
class UpdateDigitizingInputsAction(UIAction):
    inputs: Dict[str, Any]

# ==========================================
# 出力 (Tab4) 系 Action
# ==========================================
@dataclass
class UpdateOutputSettingsAction(UIAction):
    encoding: Optional[int] = None
    csv_path: Optional[str] = None

# ==========================================
# 打刻・編集・レイヤ操作 (Tab 2) ドメイン Action [新規追加]
# ==========================================
@dataclass
class ValidateDigitizingInputsAction(UIAction):
    """UIの入力状態のリアルタイムバリデーションと同期を要求するAction"""
    pass

@dataclass
class CanvasClickAction(UIAction):
    """キャンバスがクリックされた時のAction (新規打刻のトリガー)"""
    map_point: Any  # QgsPointXY

@dataclass
class AddManualDigitizedPointAction(UIAction):
    """リリースモード等で手動入力された名前で点を追加するAction"""
    map_point: Any  # QgsPointXY
    point_name: str
    branch_no: str

@dataclass
class DeletePointAction(UIAction):
    """指定されたIDの点を削除するAction"""
    feature_id: int

@dataclass
class UpdatePointAttributesAction(UIAction):
    """既存点の属性を更新するAction"""
    feature_id: int
    updates: Dict[str, Any]

@dataclass
class UpdateFeatureCategoryAction(UIAction):
    """遺構名・カラーを一括更新するAction"""
    old_name: str
    new_name: str
    new_color: str

@dataclass
class ChangeRefPointVisibilityAction(UIAction):
    """基準点の表示/非表示を切り替えるAction"""
    is_visible: bool

@dataclass
class ChangeDrawingVisibilityAction(UIAction):
    """図面（画像）の表示/非表示を切り替えるAction"""
    layer_id: str
    is_visible: bool


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

    def dispatch_batch(self, actions: List[UIAction]) -> None:
        """
        複数のUIActionを一括適用し、変更差分を統合して1回のみ state_changed シグナルを発行する。
        EventDispatcherのパイプライン処理等で使用する。
        """
        if not actions:
            return
            
        all_diff = {}
        for action in actions:
            diff = self._apply_action(action, emit_signal=False)
            if diff:
                all_diff.update(diff)
                
        if all_diff:
            self.state_changed.emit(self._state, all_diff)

    def _apply_action(self, action: UIAction, emit_signal: bool = True) -> dict:
        """
        アクションを現在の状態に適用し、差分を返す。
        ※ドメイン層の Action (CanvasClickAction 等) は直接 State を変更しないため、ここには記述しません。
        """
        new_state_kwargs = {}
        
        # モード・選択切り替え系
        if isinstance(action, ChangeTab1ModeAction):
            new_state_kwargs['tab1_mode'] = action.mode
        elif isinstance(action, ChangeTab2ModeAction):
            new_state_kwargs['tab2_mode'] = action.mode
        elif isinstance(action, ChangeAutonumModeAction):
            new_state_kwargs['autonum_mode'] = action.mode
        elif isinstance(action, SetDigitizedWithBranchAction):
            new_state_kwargs['has_digitized_with_branch'] = action.has_branch
        elif isinstance(action, SelectDrawingAction):
            new_state_kwargs['selected_drawing_name'] = action.drawing_name
            
        # 画像管理 (Tab1) 系
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
            
        # 表示制御・フィルター系
        elif isinstance(action, SetFocusModeAction):
            new_state_kwargs['focus_active'] = action.active
        elif isinstance(action, SetDisplayFiltersAction):
            new_state_kwargs['display_filters'] = action.filters
        elif isinstance(action, SetFeatureCacheAction):
            if action.color_hex is not None:
                new_state_kwargs['current_feature_color'] = action.color_hex
            if action.feature_list is not None:
                new_state_kwargs['feature_name_list'] = action.feature_list
        elif isinstance(action, SetPointInfoSummaryAction):
            new_state_kwargs['point_info_summary'] = action.summary
            
        # バリデーション・制御フラグ系
        elif isinstance(action, SetValidationAction):
            new_state_kwargs['has_input_error'] = action.has_error
            new_state_kwargs['status_message'] = action.message
            new_state_kwargs['error_focus_field'] = action.focus_field_id
        elif isinstance(action, SetPointInfoErrorAction):
            new_state_kwargs['point_info_has_error'] = action.has_error
            new_state_kwargs['is_out_of_bounds'] = action.is_out_of_bounds
        elif isinstance(action, SetProcessingAction):
            new_state_kwargs['is_processing'] = action.is_processing
        elif isinstance(action, UpdateDigitizingInputsAction):
            current_inputs = dict(self._state.digitizing_inputs)
            current_inputs.update(action.inputs)
            new_state_kwargs['digitizing_inputs'] = current_inputs
        
        # 出力 (Tab4) 系
        elif isinstance(action, UpdateOutputSettingsAction):
            if action.encoding is not None:
                new_state_kwargs['output_encoding'] = action.encoding
            if action.csv_path is not None:
                new_state_kwargs['output_csv_path'] = action.csv_path
            
        # 状態リセット（クリーンアップ）
        elif isinstance(action, ResetSelectionAction):
            new_state_kwargs['selected_point_id'] = None
            new_state_kwargs['is_out_of_bounds'] = False
            new_state_kwargs['point_info_has_error'] = False
            new_state_kwargs['has_digitized_with_branch'] = False
            new_state_kwargs['has_input_error'] = False
            new_state_kwargs['error_focus_field'] = None

        diff = {}
        if new_state_kwargs:
            new_state = replace(self._state, **new_state_kwargs)
            diff = {k: v for k, v in new_state_kwargs.items() if getattr(self._state, k) != v}
                    
            if diff:
                self._state = new_state
                if emit_signal:
                    self.state_changed.emit(self._state, diff)
                    
        return diff