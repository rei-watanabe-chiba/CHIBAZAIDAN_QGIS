"""
/***************************************************************************
 PointerGeocoding Plugin - UI State Management
 ***************************************************************************/

Step 1: 単一状態ストア（UIStateStore）と一方向データフローアーキテクチャ。
UIの表示状態やモードをグローバルに一元管理し、シグナルを用いたリアクティブな
更新を可能にします。旧 tab2_state.py の状態もここに統合されています。
"""
from dataclasses import dataclass, field, replace
from typing import Dict, Any, Optional, List
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
    selected_point_data: Optional[Dict[str, Any]] = None
    has_digitized_with_branch: bool = False
    
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
    current_feature_color: str = "#FF5722"  # QColorではなくHEX文字列で状態管理
    feature_name_list: List[str] = field(default_factory=list)


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
class SelectPointAction(UIAction):
    point_id: Optional[int]
    point_data: Optional[Dict[str, Any]] = None

@dataclass
class ChangeAutonumModeAction(UIAction):
    mode: str

@dataclass
class SetDigitizedWithBranchAction(UIAction):
    has_branch: bool

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

@dataclass
class SetPointInfoErrorAction(UIAction):
    has_error: bool
    is_out_of_bounds: bool = False

@dataclass
class SetSuppressCommitAction(UIAction):
    suppress: bool

@dataclass
class ResetSelectionAction(UIAction):
    """新規モード切替時などに呼ばれる「状態クリーンアップ」用のAction"""
    pass


class UIStateStore(QObject):
    """単一状態ストア: 状態の保持とActionのディスパッチ、差分通知を行う"""
    
    # 引数: (新しい状態: UIState, 変更された差分: Dict[str, Any])
    state_changed = pyqtSignal(object, dict)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._state = UIState()

    @property
    def state(self) -> UIState:
        return self._state

    def dispatch_silent(self, action: UIAction) -> None:
        """UIイベントの無限ループを防ぐためのサイレント更新（シグナルを発火しないディスパッチ）"""
        self._apply_action(action, emit_signal=False)

    def dispatch(self, action: UIAction) -> None:
        """Actionを受け取り、新しい状態を生成して差分を通知する"""
        self._apply_action(action, emit_signal=True)

    def _apply_action(self, action: UIAction, emit_signal: bool = True) -> None:
        new_state_kwargs = {}
        
        # モード・選択切り替え系
        if isinstance(action, ChangeTab1ModeAction):
            new_state_kwargs['tab1_mode'] = action.mode
        elif isinstance(action, ChangeTab2ModeAction):
            new_state_kwargs['tab2_mode'] = action.mode
        elif isinstance(action, SelectPointAction):
            new_state_kwargs['selected_point_id'] = action.point_id
            new_state_kwargs['selected_point_data'] = action.point_data
        elif isinstance(action, ChangeAutonumModeAction):
            new_state_kwargs['autonum_mode'] = action.mode
        elif isinstance(action, SetDigitizedWithBranchAction):
            new_state_kwargs['has_digitized_with_branch'] = action.has_branch
            
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
        elif isinstance(action, SetPointInfoErrorAction):
            new_state_kwargs['point_info_has_error'] = action.has_error
            new_state_kwargs['is_out_of_bounds'] = action.is_out_of_bounds
        elif isinstance(action, SetSuppressCommitAction):
            new_state_kwargs['suppress_realtime_commit'] = action.suppress
            
        # 状態リセット（クリーンアップ）
        elif isinstance(action, ResetSelectionAction):
            new_state_kwargs['selected_point_id'] = None
            new_state_kwargs['selected_point_data'] = None
            new_state_kwargs['is_out_of_bounds'] = False
            new_state_kwargs['point_info_has_error'] = False
            new_state_kwargs['has_digitized_with_branch'] = False

        if not new_state_kwargs:
            return

        new_state = replace(self._state, **new_state_kwargs)
        
        # 差分（変更があったプロパティ）の抽出
        diff = {}
        for k, v in new_state_kwargs.items():
            if getattr(self._state, k) != v:
                diff[k] = v
                
        if diff:
            self._state = new_state
            if emit_signal:
                self.state_changed.emit(self._state, diff)