"""
/***************************************************************************
 PointerGeocoding Plugin - Settings Logic (Controller)
 ***************************************************************************/

Tab 3 (環境設定) のビジネスロジックを制御するController層です。
EventDispatcher経由で受容したUIActionに基づき、設定の読み書きと
シンボロジの更新処理（ドメイン操作）を一元的に実行します。
"""
from dataclasses import dataclass
from typing import Optional, Dict, Any, Callable, List
from qgis.PyQt.QtCore import QObject
from qgis.core import Qgis

from ..ui.constants import UILabels
from ..ui.core.state import UIAction
from ..layer.models import PluginSettings


# =========================================================================
# UIAction Definitions for Tab 3
# =========================================================================

@dataclass
class ApplySettingsAction(UIAction):
    """入力された設定をPluginSettings DTOとして適用・保存するAction"""
    settings: PluginSettings

@dataclass
class PickColorAction(UIAction):
    """カラーピッカーを起動し色を変更するAction"""
    field_id: str
    current_color: str

@dataclass
class ChangeScaleModeAction(UIAction):
    """スケールの「常時/指定」モードを切り替えるAction"""
    scale_type: str  # "major" or "minor"
    is_active: bool


class SettingsLogic(QObject):
    """
    環境設定ダイアログの制御・シンボロジ同期を担うControllerクラス。
    """
    def __init__(self, layer_manager: Any, iface: Any, dispatcher: Any, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.layer_manager = layer_manager
        self.iface = iface
        self.dispatcher = dispatcher
        self.parent_widget = parent
        self.canvas = self.iface.mapCanvas() if self.iface else None

        # View層からDIされるコールバック関数の初期化
        self.is_focus_mode_active_cb: Callable[[], bool] = lambda: False
        self.update_symbology_opacity_cb: Callable[[], None] = lambda: None
        self.open_color_dialog_cb: Callable[[str], Optional[str]] = lambda c: None
        self.set_panel_value_cb: Callable[[str, Any], None] = lambda f, v: None
        self.set_widget_enabled_cb: Callable[[str, bool], None] = lambda w, e: None

    def bind_view_callbacks(self, callbacks: Dict[str, Any]) -> None:
        """View層から必要な情報取得メソッドやGUI操作ヘルパーをバインドする"""
        self.is_focus_mode_active_cb = callbacks.get("is_focus_mode_active", self.is_focus_mode_active_cb)
        self.update_symbology_opacity_cb = callbacks.get("update_symbology_opacity", self.update_symbology_opacity_cb)
        self.open_color_dialog_cb = callbacks.get("open_color_dialog", self.open_color_dialog_cb)
        self.set_panel_value_cb = callbacks.get("set_panel_value", self.set_panel_value_cb)
        self.set_widget_enabled_cb = callbacks.get("set_widget_enabled", self.set_widget_enabled_cb)

    def register_handlers(self) -> None:
        """EventDispatcher に対し、自身が担当する Action のハンドラを登録する"""
        self.dispatcher.register_handler(ApplySettingsAction, self._handle_apply_settings)
        self.dispatcher.register_handler(PickColorAction, self._handle_pick_color)
        self.dispatcher.register_handler(ChangeScaleModeAction, self._handle_scale_mode_changed)

    # =========================================================================
    # イベントハンドラ (Action Execution)
    # =========================================================================

    def _handle_pick_color(self, action: PickColorAction) -> Optional[List[UIAction]]:
        """カラーピッカーを起動し、選択された色をViewにセットする"""
        new_color = self.open_color_dialog_cb(action.current_color)
        if new_color:
            self.set_panel_value_cb(action.field_id, new_color)
        return []

    def _handle_scale_mode_changed(self, action: ChangeScaleModeAction) -> Optional[List[UIAction]]:
        """スケールの有効/無効状態をViewに連動させる"""
        widget_id = "major_scale_value" if action.scale_type == "major" else "minor_scale_value"
        self.set_widget_enabled_cb(widget_id, action.is_active)
        return []

    def _handle_apply_settings(self, action: ApplySettingsAction) -> Optional[List[UIAction]]:
        """UIから取得した設定値(PluginSettings DTO)を永続化し、シンボロジを一括更新する"""
        if not self.layer_manager or not self.layer_manager.session_dir:
            if self.iface:
                self.iface.messageBar().pushMessage(
                    "設定適用", UILabels.TAB3_APPLY_NO_SESSION, level=Qgis.MessageLevel.Warning, duration=3
                )
            return []

        settings = action.settings
        
        # 設定の永続化
        self.layer_manager.ensure_json_dir()
        self.layer_manager.save_settings(settings)

        # 辞書化してシンボロジ更新メソッドへ渡す
        settings_dict = settings.to_dict()
        
        ref_layer = self.layer_manager.ref_point_layer
        if ref_layer and ref_layer.isValid():
            self.layer_manager.apply_ref_point_symbology(ref_layer, settings_dict)

        point_layer = self.layer_manager.point_layer
        if point_layer and point_layer.isValid():
            self.layer_manager.apply_point_symbology(point_layer, settings_dict)
            
            # 非表示式 (Focus Mode / 透過度) の再注入またはキャンバス再描画
            if self.is_focus_mode_active_cb():
                self.update_symbology_opacity_cb()
            elif self.canvas:
                self.canvas.refresh()
        elif self.canvas:
            self.canvas.refresh()

        if self.iface:
            self.iface.messageBar().pushMessage(
                "設定適用", UILabels.TAB3_APPLY_SUCCESS, level=Qgis.MessageLevel.Success, duration=3
            )
            
        return []

    # =========================================================================
    # データ同期 (初期化時ロード)
    # =========================================================================

    def load_initial_settings(self, *args) -> None:
        """
        起動時やダイアログ表示時に、永続化された設定データを読み込みUIコンポーネントへ反映する。
        View側から呼び出される。
        """
        if self.layer_manager and hasattr(self.layer_manager, "load_settings_dataclass"):
            settings = self.layer_manager.load_settings_dataclass()
        else:
            return

        sc_maj = settings.scale_major_grid
        sc_min = settings.scale_minor_grid

        # 読み込んだ設定をViewのフィールド形式に合わせて変換
        values = {
            "ref_sym_size": settings.ref_symbol_size,
            "ref_sym_linewidth": settings.ref_symbol_line_width,
            "ref_line_color": settings.ref_symbol_line_color,
            "point_sym_size": settings.point_symbol_size,
            "point_sym_linewidth": settings.point_symbol_line_width,
            "point_line_color": settings.point_symbol_line_color,
            "point_fill_toggle": 0 if settings.point_symbol_fill_enabled else 1,
            "lbl_size": settings.label_size,
            "halo_toggle": 0 if settings.label_halo else 1,
            "lbl_offset": settings.label_offset,
            "major_scale_mode": 0 if sc_maj <= 0 else 1,
            "minor_scale_mode": 0 if sc_min <= 0 else 1,
        }
        
        if sc_maj > 0:
            values["major_scale_value"] = sc_maj
        if sc_min > 0:
            values["minor_scale_value"] = sc_min

        # View側へ値を反映
        for k, v in values.items():
            self.set_panel_value_cb(k, v)
            
        # スケールの有効状態を連動
        self.set_widget_enabled_cb("major_scale_value", sc_maj > 0)
        self.set_widget_enabled_cb("minor_scale_value", sc_min > 0)