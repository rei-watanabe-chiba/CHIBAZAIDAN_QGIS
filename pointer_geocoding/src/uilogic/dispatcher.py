"""
/***************************************************************************
 PointerGeocoding Plugin - Event Dispatcher
 ***************************************************************************/

イベント層（Controller）の心臓部となるディスパッチャーです。
UI層からの Action を受容し、「前置バリデーション」「ビジーガード」「例外キャッチ」
の共通パイプラインを経てドメインロジックへ委譲し、結果を UIStateStore へ反映します。
"""
import traceback
from typing import Dict, Type, Callable, Optional, Any

from qgis.core import QgsMessageLog, Qgis
from qgis.PyQt.QtCore import QObject

from ..ui.core.state import UIStateStore, UIAction, SetProcessingAction, SetValidationAction


class EventDispatcher(QObject):
    """
    UIからのアクションを受け取り、一元的なパイプライン処理を経て
    ドメインロジック（ハンドラ）へ処理を振り分ける層。
    """
    
    def __init__(self, state_store: UIStateStore, layer_manager: Any, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.state_store = state_store
        self.layer_manager = layer_manager
        
        # Actionの型 -> ハンドラ関数のマッピング
        # ハンドラは、ドメイン処理を実行後に後続のUIActionを返す（または何も返さない）
        self._handlers: Dict[Type[UIAction], Callable[[UIAction], Optional[UIAction]]] = {}
        
        # Actionの型 -> 前置バリデーション関数のマッピング
        # バリデーション失敗時はエラーメッセージ(str)を返し、成功時は None を返す
        self._validators: Dict[Type[UIAction], Callable[[UIAction], Optional[str]]] = {}

    def register_handler(self, action_type: Type[UIAction], handler: Callable[[UIAction], Optional[UIAction]]) -> None:
        """アクションに対するハンドラ（ドメインロジックの入り口）を登録する"""
        self._handlers[action_type] = handler

    def register_validator(self, action_type: Type[UIAction], validator_func: Callable[[UIAction], Optional[str]]) -> None:
        """
        アクションに対する前置バリデーション関数を登録する。
        （内部で ChainValidator 等を呼び出し、エラーメッセージを抽出して返す想定）
        """
        self._validators[action_type] = validator_func

    def dispatch(self, action: UIAction) -> None:
        """
        アクションを受容し、共通パイプライン（検証・ビジーガード・例外キャッチ）を経て処理する。
        """
        handler = self._handlers.get(type(action))
        
        # 1. ハンドラ未登録のアクション（単なるUI状態の変更など）は、そのまま StateStore へ素通りさせる
        if not handler:
            self.state_store.dispatch(action)
            return

        # 2. 前置バリデーション
        validator_func = self._validators.get(type(action))
        if validator_func:
            error_message = validator_func(action)
            if error_message:
                # バリデーションエラー時は処理を中断し、Stateにエラー状態を反映
                self.state_store.dispatch(SetValidationAction(has_error=True, message=error_message))
                return

        # 3. ビジーガード開始（カーソルを待機状態にする等、Viewが検知してUIをロックする）
        self.state_store.dispatch(SetProcessingAction(is_processing=True))
        
        try:
            # 4. ハンドラの実行 (ドメインロジックへの処理委譲)
            # ハンドラは純粋な計算やデータの永続化を行い、成功時には次のUIState更新用Actionを返す
            result_action = handler(action)
            
            if result_action:
                self.state_store.dispatch(result_action)
                
            # 成功時、必要に応じて以前のエラー状態をクリアする
            # self.state_store.dispatch(SetValidationAction(has_error=False, message=""))
            
        except Exception as e:
            # 5. 例外キャッチ
            err_msg = f"処理中に予期せぬエラーが発生しました:\n{str(e)}"
            # QGISのメッセージログに詳細なスタックトレースを出力
            QgsMessageLog.logMessage(f"{err_msg}\n{traceback.format_exc()}", "PointerGeocoding", Qgis.Critical)
            
            # 画面上にエラーを表示するため、StateStoreへエラー状態を Dispatch
            self.state_store.dispatch(SetValidationAction(has_error=True, message=err_msg))
            
        finally:
            # 6. ビジーガード終了（UIロック解除）
            self.state_store.dispatch(SetProcessingAction(is_processing=False))