"""
/***************************************************************************
 PointerGeocoding Plugin - UI State Management
 ***************************************************************************/

Step 1: 単一状態ストア（UIStateStore）と一方向データフローアーキテクチャ。
UIの表示状態やモードをグローバルに一元管理し、シグナルを用いたリアクティブな
更新を可能にします。
"""
from dataclasses import dataclass, field, replace
from typing import Dict, Any, Optional
from qgis.PyQt.QtCore import QObject, pyqtSignal


@dataclass(frozen=True)
class UIState:
    """メイン画面（Dockおよび各Tab）の表示・動作状態を保持する不変データモデル"""
    tab1_mode: str = "new"  # "new" | "edit"
    tab2_mode: str = "new"  # "new" | "edit"
    selected_point_id: Optional[int] = None
    autonum_mode: str = "auto"  # "auto" | "release"
    focus_active: bool = False
    display_filters: Dict[str, Any] = field(default_factory=dict)
    has_input_error: bool = False
    status_message: str = ""


class UIAction:
    """状態更新の意図を表現する基底クラス"""
    pass


@dataclass
class ChangeTab1ModeAction(UIAction):
    mode: str

@dataclass
class ChangeTab2ModeAction(UIAction):
    mode: str

@dataclass
class SelectPointAction(UIAction):
    point_id: Optional[int]

@dataclass
class ChangeAutonumModeAction(UIAction):
    mode: str

@dataclass
class SetFocusModeAction(UIAction):
    active: bool

@dataclass
class SetDisplayFiltersAction(UIAction):
    filters: Dict[str, Any]

@dataclass
class SetValidationAction(UIAction):
    has_error: bool
    message: str


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

    def dispatch(self, action: UIAction) -> None:
        """Actionを受け取り、新しい状態を生成して差分を通知する"""
        new_state_kwargs = {}
        
        if isinstance(action, ChangeTab1ModeAction):
            new_state_kwargs['tab1_mode'] = action.mode
        elif isinstance(action, ChangeTab2ModeAction):
            new_state_kwargs['tab2_mode'] = action.mode
        elif isinstance(action, SelectPointAction):
            new_state_kwargs['selected_point_id'] = action.point_id
        elif isinstance(action, ChangeAutonumModeAction):
            new_state_kwargs['autonum_mode'] = action.mode
        elif isinstance(action, SetFocusModeAction):
            new_state_kwargs['focus_active'] = action.active
        elif isinstance(action, SetDisplayFiltersAction):
            new_state_kwargs['display_filters'] = action.filters
        elif isinstance(action, SetValidationAction):
            new_state_kwargs['has_input_error'] = action.has_error
            new_state_kwargs['status_message'] = action.message
            
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
            self.state_changed.emit(self._state, diff)