"""
/***************************************************************************
 PointerGeocoding Plugin - Filter Logic (Controller)
 ***************************************************************************/

Tab 2 の表示設定（フォーカスモード、基準点表示、図面表示切り替え）に関連する
QGISレイヤツリーの可視性制御を処理するController層です。
ダイアログ操作やUIイベントの直接バインドはViewへ移管され、
EventDispatcher経由で発行されたActionに応答してレイヤ状態を操作します。
"""
from typing import Optional, List
from qgis.core import QgsProject
from qgis.PyQt.QtCore import QObject

from ..ui.core.state import (
    UIStateStore, 
    UIAction, 
    ChangeRefPointVisibilityAction, 
    ChangeDrawingVisibilityAction
)


class FilterLogic(QObject):
    """
    レイヤ可視性制御を担う純粋なControllerクラス。
    """
    def __init__(
        self,
        state_store: UIStateStore,
        layer_manager,
        iface,
        dispatcher,
        parent: Optional[QObject] = None
    ):
        """
        Args:
            state_store (UIStateStore): UI状態管理ストア
            layer_manager (Any): GeoPackageおよび設定管理
            iface (QgisInterface): QGISインターフェース
            dispatcher (Any): 中央アクションディスパッチャー
            parent (QObject): 親オブジェクト
        """
        super().__init__(parent)
        self.state_store = state_store
        self.layer_manager = layer_manager
        self.iface = iface
        self.dispatcher = dispatcher
        self.parent_widget = parent
        self.canvas = self.iface.mapCanvas() if self.iface else None

        # EventDispatcherへのアクションハンドラ登録
        self.dispatcher.register_handler(ChangeRefPointVisibilityAction, self.handle_ref_point_visibility)
        self.dispatcher.register_handler(ChangeDrawingVisibilityAction, self.handle_drawing_visibility)

    # =========================================================================
    # Action Handlers (イベントディスパッチャ対応)
    # =========================================================================

    def handle_ref_point_visibility(self, action: ChangeRefPointVisibilityAction) -> Optional[List[UIAction]]:
        """
        基準点レイヤの表示/非表示を切り替えるアクションハンドラ。
        """
        ref_layer = getattr(self.layer_manager, "ref_point_layer", None)
        if not ref_layer:
            return []
            
        root = QgsProject.instance().layerTreeRoot()
        if not root:
            return []
            
        ref_group = root.findGroup("基準点データ")
        search_root = ref_group if ref_group else root
        tree_layer = search_root.findLayer(ref_layer.id())
        
        if tree_layer:
            tree_layer.setItemVisibilityChecked(action.is_visible)
            if self.canvas:
                self.canvas.refresh()
                
        return []

    def handle_drawing_visibility(self, action: ChangeDrawingVisibilityAction) -> Optional[List[UIAction]]:
        """
        図面選択テーブルのチェックボックス操作に伴い、
        対象の画像レイヤの可視性を切り替えるアクションハンドラ。
        """
        root = QgsProject.instance().layerTreeRoot()
        if root:
            image_group = root.findGroup("画像ファイル")
            if image_group:
                tree_layer = image_group.findLayer(action.layer_id)
                if tree_layer:
                    tree_layer.setItemVisibilityChecked(action.is_visible)
                    if self.canvas:
                        self.canvas.refresh()
                        
        return []