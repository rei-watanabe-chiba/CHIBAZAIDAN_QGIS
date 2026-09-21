"""
/***************************************************************************
 PointerGeocoding Plugin - Output Logic (Controller)
 ***************************************************************************/

Tab 4 (出力) のビジネスロジックを処理するController層です。
EventDispatcher からルーティングされた Action を受け取り、CSVエクスポート等の
ドメイン処理を実行します。UI（View）の知識は一切持ちません。
"""
import os
from typing import Optional, Any
from qgis.PyQt.QtCore import QObject
from qgis.core import Qgis

from ..logic.transform import export_points_to_csv
from ..ui.core.state import UIStateStore, ExportCsvAction, UIAction


class OutputLogic(QObject):
    """CSV出力制御を担うControllerクラス。"""

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

        # ディスパッチャーへハンドラと前置バリデーションを登録する
        dispatcher.register_validator(ExportCsvAction, self.validate_export_csv)
        dispatcher.register_handler(ExportCsvAction, self.handle_export_csv)

    def validate_export_csv(self, action: ExportCsvAction) -> Optional[str]:
        """CSV出力前のバリデーション（Dispatcherから自動で呼ばれる）"""
        state = self.state_store.state
        if not state.output_csv_path:
            return "CSV出力先ファイルを指定してください。"
        return None

    def handle_export_csv(self, action: ExportCsvAction) -> Optional[UIAction]:
        """CSV出力処理を実行するハンドラ"""
        state = self.state_store.state
        filepath = state.output_csv_path
        
        # 事前整理: UIの選択状態(0, 1)を即座に内部パラメータに翻訳
        encoding = "utf-8-sig" if state.output_encoding == 0 else "cp932"
        point_layer = self.layer_manager.point_layer
        
        # ビジネスロジック関数（純粋な処理）への委譲
        success, msg = export_points_to_csv(
            point_layer, filepath, encoding=encoding, parent=self.parent_widget
        )

        if success and self.iface:
            self.iface.messageBar().pushMessage(
                "CSV出力完了", msg, level=Qgis.MessageLevel.Success, duration=5
            )
            
        return None