"""
/***************************************************************************
 PointerGeocoding Plugin - EventDispatcher
 ***************************************************************************/

アプリケーション全体のアクションと状態更新を一元管理する中央ディスパッチャー。
前置バリデーション、ビジー制御（画面ロック）、横断例外キャッチのパイプラインを提供し、
単一方向データフロー（Unidirectional Data Flow）を実現します。
"""
import traceback
from typing import Callable, Dict, List, Optional, Tuple, Type, Any

from qgis.core import QgsMessageLog, Qgis

from ..ui.core.state import UIAction, UIStateStore, SetProcessingAction, SetValidationAction
from ..ui.core.validators import Validator, ValidationResult


class EventDispatcher:
    """
    ユーザーアクション（UIAction）を受け取り、登録されたハンドラとパイプライン
    （バリデーション -> ビジーガード -> 実行 -> 例外キャッチ -> State更新）
    を経由して UIStateStore へ処理結果を反映するディスパッチャークラス。
    """

    def __init__(self, state_store: UIStateStore) -> None:
        """
        Args:
            state_store (UIStateStore): 状態管理ストア
        """
        self.state_store = state_store
        # action_type -> {"handler": Callable, "validators": List}
        self._handlers: Dict[Type[UIAction], Dict[str, Any]] = {}

    def register_handler(
        self,
        action_type: Type[UIAction],
        handler: Callable[[UIAction], Optional[List[UIAction]]],
        validators: Optional[List[Tuple[Validator, Callable[[UIAction], Any]]]] = None
    ) -> None:
        """
        特定の UIAction に対するハンドラと前置バリデーターを登録する。

        Args:
            action_type: 対象の UIAction クラス
            handler: アクションを実行し、結果として適用すべき UIAction のリストを返す関数
            validators: (Validatorインスタンス, アクションから検証値を取り出す関数) のリスト
        """
        self._handlers[action_type] = {
            "handler": handler,
            "validators": validators or []
        }

    def dispatch(self, action: UIAction) -> None:
        """
        アクションをディスパッチし、パイプライン処理を実行する。
        登録されていないアクションは直接 UIStateStore へ渡される。

        Args:
            action: 発行された UIAction
        """
        action_type = type(action)
        if action_type not in self._handlers:
            # ハンドラが登録されていない軽量アクション（UI表示の切り替えなど）は直接StateStoreへ
            self.state_store.dispatch(action)
            return

        config = self._handlers[action_type]
        handler = config["handler"]
        validators = config["validators"]

        # 1. 前置バリデーション (Pre-validation)
        for validator, extractor in validators:
            value_to_check = extractor(action)
            result: ValidationResult = validator.validate(value_to_check)
            if not result.is_valid:
                # バリデーション失敗時、エラー状態をセットしてパイプラインを中断
                self.state_store.dispatch(SetValidationAction(
                    has_error=True,
                    message=result.message,
                    focus_field_id=result.focus_field_id
                ))
                return

        # バリデーションクリア時はエラー状態をリセット (シグナルは出さずにサイレント更新)
        self.state_store.dispatch_silent(SetValidationAction(has_error=False, message=""))

        # 2. パイプライン実行 (Busy Guard -> Handler -> Catch -> Dispatch)
        # 大域ロック開始
        self.state_store.dispatch(SetProcessingAction(True))
        
        try:
            # 3. ハンドラ実行 (純粋計算・ドメインロジック呼び出し)
            result_actions = handler(action)
            
            # 4. 処理結果を UIStateStore へ Dispatch (バッチ更新)
            if result_actions:
                self.state_store.dispatch_batch(result_actions)
                
        except Exception as e:
            # 横断例外キャッチ: エラーを安全に UIState へ反映し、UIロックのままになるのを防ぐ
            error_msg = f"処理中にエラーが発生しました: {str(e)}"
            QgsMessageLog.logMessage(f"{error_msg}\n{traceback.format_exc()}", "PointerGeocoding", Qgis.MessageLevel.Critical)
            
            self.state_store.dispatch(SetValidationAction(
                has_error=True,
                message=error_msg
            ))
        finally:
            # 大域ロック解除
            self.state_store.dispatch(SetProcessingAction(False))