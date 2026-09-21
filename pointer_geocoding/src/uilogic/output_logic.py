"""
/***************************************************************************
 PointerGeocoding Plugin - Output Logic (Controller)
 ***************************************************************************/

Tab 4 (出力) のUIイベントを受容し、ビジネスロジック（CSVエクスポート等）
を処理するController層です。View層からは BuiltPanel と コールバックを
DI (注入) されることで、循環参照を防ぎつつ単一方向データフローを実現します。
"""
import os
from typing import Optional, Dict, Any, Callable
from qgis.PyQt.QtCore import QObject
from qgis.core import Qgis

from ..logic.transform import export_points_to_csv
from ..ui.core.state import UIStateStore, UpdateOutputSettingsAction
from ..ui.core.builder import BuiltPanel


class OutputLogic(QObject):
    """
    CSV出力制御を担うControllerクラス。
    """
    def __init__(
        self, 
        state_store: UIStateStore, 
        layer_manager: Any, 
        parent: Optional[QObject] = None
    ):
        super().__init__(parent)
        self.state_store = state_store
        self.layer_manager = layer_manager
        self.parent_widget = parent

        self.panel: Optional[BuiltPanel] = None
        self.browse_csv_dialog_cb: Callable[[str], str] = lambda d: ""
        self.show_message_bar_cb: Callable[[str, str, int, int], None] = lambda t, m, l, d: None

    def bind_view_callbacks(self, callbacks: Dict[str, Any]) -> None:
        """View層からファイルダイアログやメッセージバー操作などの関数を受け取る"""
        self.browse_csv_dialog_cb = callbacks.get("browse_csv_dialog", self.browse_csv_dialog_cb)
        self.show_message_bar_cb = callbacks.get("show_message_bar", self.show_message_bar_cb)

    def bind_ui_panels(self, panel: BuiltPanel) -> None:
        """Viewから BuiltPanel インスタンスを受け取り、シグナルをバインドする"""
        self.panel = panel
        
        self.panel.bind("encoding_changed", self._on_encoding_changed)
        self.panel.bind("csv_path_changed", self._on_csv_path_changed)
        self.panel.bind("browse_csv_clicked", self._on_browse_csv_clicked)
        self.panel.bind("export_csv_clicked", self._on_export_csv_clicked)
        
        # UIStateStoreからの状態変更検知イベントを接続
        self.state_store.state_changed.connect(self.on_state_changed)

    # =========================================================================
    # 状態の同期 (一方向データフローの受け口)
    # =========================================================================

    def on_state_changed(self, new_state: Any, diff: Dict[str, Any]) -> None:
        if not self.panel:
            return
            
        if "output_encoding" in diff:
            widget = self.panel.get("encoding")
            widget.blockSignals(True)
            self.panel.set_value("encoding", new_state.output_encoding)
            widget.blockSignals(False)
            
        if "output_csv_path" in diff:
            widget = self.panel.get("csv_path")
            widget.blockSignals(True)
            self.panel.set_value("csv_path", new_state.output_csv_path)
            widget.blockSignals(False)

    # =========================================================================
    # イベントハンドラ・Action Dispatch
    # =========================================================================

    def _on_encoding_changed(self, idx: int) -> None:
        self.state_store.dispatch(UpdateOutputSettingsAction(encoding=idx))

    def _on_csv_path_changed(self, *args) -> None:
        path = self.panel.get_value("csv_path").strip()
        self.state_store.dispatch(UpdateOutputSettingsAction(csv_path=path))

    def _on_browse_csv_clicked(self) -> None:
        start_dir = self.layer_manager.session_dir if self.layer_manager.session_dir else os.path.expanduser("~")
        # Viewから渡された関数でダイアログを起動
        filepath = self.browse_csv_dialog_cb(start_dir)
        if filepath:
            norm_path = os.path.normpath(filepath)
            self.state_store.dispatch(UpdateOutputSettingsAction(csv_path=norm_path))

    def _on_export_csv_clicked(self) -> None:
        state = self.state_store.state
        filepath = state.output_csv_path
        
        if not filepath:
            self._on_browse_csv_clicked()
            # キャンセルされた場合は終了
            filepath = self.state_store.state.output_csv_path
            if not filepath:
                return

        encoding = "utf-8-sig" if state.output_encoding == 0 else "cp932"
        point_layer = self.layer_manager.point_layer
        
        # ビジネスロジック関数の呼び出し
        success, msg = export_points_to_csv(
            point_layer, filepath, encoding=encoding, parent=self.parent_widget
        )

        if success:
            self.show_message_bar_cb("CSV出力完了", msg, Qgis.MessageLevel.Success, 5)