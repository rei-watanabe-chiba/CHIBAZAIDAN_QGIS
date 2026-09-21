"""
/***************************************************************************
 PointerGeocoding Plugin - Settings Logic (Controller)
 ***************************************************************************/

Tab 3 (環境設定) のビジネスロジックを処理するController層です。
EventDispatcher からルーティングされた Action を受け取り、JSONへの設定保存と、
レイヤ・シンボロジへの適用を実行します。UI（View）の知識は一切持ちません。
"""
from typing import Optional, Dict, Any
from qgis.PyQt.QtCore import QObject

from ..ui.constants import UILabels
from ..ui.core.state import UIStateStore, SaveSettingsAction, UIAction


class SettingsLogic(QObject):
    """環境設定の保存・シンボロジ適用を担うControllerクラス。"""

    def __init__(
        self, 
        state_store: UIStateStore, 
        layer_manager: Any, 
        dispatcher: Any,
        iface: Any, 
        parent: Optional[QObject] = None
    ):
        super().__init__(parent)
        self.state_store = state_store
        self.layer_manager = layer_manager
        self.iface = iface
        self.parent_widget = parent

        # ディスパッチャーへハンドラを登録する
        dispatcher.register_handler(SaveSettingsAction, self.handle_save_settings)

        if self.layer_manager:
            self.layer_manager.settings_changed.connect(self._on_layer_manager_settings_changed)

    def handle_save_settings(self, action: SaveSettingsAction) -> Optional[UIAction]:
        """設定保存処理を実行するハンドラ"""
        if not self.layer_manager or not self.layer_manager.session_dir:
            return None

        self.layer_manager.ensure_json_dir()
        self.layer_manager.save_settings(action.settings)
        return None

    def _on_layer_manager_settings_changed(self, new_settings: dict) -> None:
        """設定保存完了のシグナルを受け取り、各レイヤのシンボロジを再構築する"""
        ref_layer = self.layer_manager.ref_point_layer
        if ref_layer and ref_layer.isValid():
            self.layer_manager.apply_ref_point_symbology(ref_layer, new_settings)

        point_layer = self.layer_manager.point_layer
        if point_layer and point_layer.isValid():
            self.layer_manager.apply_point_symbology(point_layer, new_settings)
            
            # 非表示式 (Focus Mode / 透過度) の再注入
            state = self.state_store.state
            is_focus_on = state.focus_active
            filters = dict(state.display_filters) if is_focus_on else {}
            
            if is_focus_on:
                if filters.get("target_drawing") == UILabels.FILTER_DRAWING_SELECTED:
                    filters["target_drawing_name"] = state.selected_drawing_name
                else:
                    filters["target_drawing_name"] = None

            expr = self.layer_manager.build_opacity_expression(is_focus_on, filters, 0)
            self.layer_manager.apply_opacity_expression(point_layer, expr)

            if self.iface and self.iface.mapCanvas():
                self.iface.mapCanvas().refresh()
        elif self.iface and self.iface.mapCanvas():
            self.iface.mapCanvas().refresh()