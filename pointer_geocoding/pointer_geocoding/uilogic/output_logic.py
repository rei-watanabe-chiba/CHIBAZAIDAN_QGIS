"""
/***************************************************************************
 PointerGeocoding Plugin - Output Logic (Controller)
 ***************************************************************************/

Tab 4 (出力) のビジネスロジックを制御するController層です。
EventDispatcherへアクションハンドラを登録し、UIStateから純粋なドメイン型へ翻訳した上で
ファイル出力処理（ロジック層）を実行します。
"""
from dataclasses import dataclass
from typing import Optional, Dict, Any, Callable, List
from qgis.PyQt.QtCore import QObject
from qgis.core import Qgis

from ..logic.transform import export_points_to_csv
from ..ui.core.state import UIAction, UIStateStore, SetValidationAction
from ..ui.core.validators import RequiredValidator

@dataclass
class ExportCsvAction(UIAction):
    """CSV出力を実行するAction"""
    pass

class OutputLogic(QObject):
    """
    CSV出力制御を担うControllerクラス。
    """
    def __init__(
        self, 
        state_store: UIStateStore, 
        layer_manager: Any, 
        dispatcher: Any,
        parent: Optional[QObject] = None
    ) -> None:
        """
        Args:
            state_store (UIStateStore): 状態管理ストア
            layer_manager (Any): レイヤ管理オブジェクト
            dispatcher (Any): EventDispatcher インスタンス
            parent (Optional[QObject]): 親QObject
        """
        super().__init__(parent)
        self.state_store = state_store
        self.layer_manager = layer_manager
        self.dispatcher = dispatcher
        self.parent_widget = parent

        self.show_message_bar_cb: Callable[[str, str, int, int], None] = lambda t, m, l, d: None

    def bind_view_callbacks(self, callbacks: Dict[str, Any]) -> None:
        """View層からメッセージバー操作などのコールバックを受け取る"""
        self.show_message_bar_cb = callbacks.get("show_message_bar", self.show_message_bar_cb)

    def register_handlers(self) -> None:
        """
        EventDispatcher に対し、自身が担当する Action のハンドラと前置バリデーションを登録する
        """
        # CSVエクスポートの前置バリデーション: パスが空であってはならない
        validators = [
            (RequiredValidator(message="CSVの保存先パスを指定してください", focus_field_id="csv_path"), 
             lambda action: self.state_store.state.output_csv_path)
        ]
        
        self.dispatcher.register_handler(
            ExportCsvAction, 
            self._handle_export_csv,
            validators=validators
        )

    # =========================================================================
    # イベントハンドラ (Action Execution)
    # =========================================================================

    def _handle_export_csv(self, action: ExportCsvAction) -> Optional[List[UIAction]]:
        """
        ExportCsvAction の処理を行うハンドラ。
        Dispatcherによって実行され、必要に応じて結果Actionのリストを返す。
        """
        state = self.state_store.state
        filepath = state.output_csv_path
        
        # [RULE-TYPE-03] UI用のインデックス値を、ドメインに必要な文字列表現に即時翻訳
        # 0: UTF-8 (BOM付き) -> "utf-8-sig"
        # 1: Shift-JIS -> "cp932"
        encoding_str = "utf-8-sig" if state.output_encoding == 0 else "cp932"
        
        point_layer = self.layer_manager.point_layer
        
        # [RULE-GEO-01] ビジネスロジック関数の呼び出し。
        # 境界内(export_points_to_csv内部)で to_survey_coords による変換が実行される。
        success, msg = export_points_to_csv(
            point_layer, filepath, encoding=encoding_str, parent=self.parent_widget
        )

        if success:
            self.show_message_bar_cb("CSV出力完了", msg, Qgis.MessageLevel.Success, 5)
            return []
        else:
            # 失敗時は UIState にエラーメッセージを反映する Action を返す
            return [SetValidationAction(has_error=True, message=msg)]