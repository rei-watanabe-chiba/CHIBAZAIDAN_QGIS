"""
/***************************************************************************
 PointerGeocoding Plugin - Filter Logic (Controller)
 ***************************************************************************/

Tab 2 の表示設定（レイヤツリー可視性制御等）の副作用イベントを受容し処理する
Controller層です。UI（View）の知識は一切持たず、DispatcherからのActionのみを処理します。
"""
from typing import Optional
from qgis.core import QgsProject
from qgis.PyQt.QtCore import QObject

from ..ui.core.state import (
    UIStateStore, SetRefLayerVisibilityAction, SetDrawingLayerVisibilityAction,
    ToggleAllDrawingsVisibilityAction, UIAction
)

class FilterLogic(QObject):
    """
    表示フィルター・レイヤ可視性制御（QGISプロジェクト上の副作用）を担うControllerクラス。
    """
    def __init__(
        self,
        state_store: UIStateStore,
        layer_manager,
        dispatcher,
        iface,
        parent: Optional[QObject] = None
    ):
        super().__init__(parent)
        self.state_store = state_store
        self.layer_manager = layer_manager
        self.iface = iface
        self.canvas = self.iface.mapCanvas()
        
        # Dispatcher にハンドラを登録
        dispatcher.register_handler(SetRefLayerVisibilityAction, self.handle_ref_layer_visibility)
        dispatcher.register_handler(SetDrawingLayerVisibilityAction, self.handle_drawing_layer_visibility)
        dispatcher.register_handler(ToggleAllDrawingsVisibilityAction, self.handle_toggle_all_drawings_visibility)

    def handle_ref_layer_visibility(self, action: SetRefLayerVisibilityAction) -> Optional[UIAction]:
        """基準点レイヤの表示/非表示を切り替える"""
        ref_layer = getattr(self.layer_manager, "ref_point_layer", None)
        if not ref_layer:
            return None
            
        root = QgsProject.instance().layerTreeRoot()
        if not root:
            return None
            
        ref_group = root.findGroup("基準点データ")
        search_root = ref_group if ref_group else root
        tree_layer = search_root.findLayer(ref_layer.id())
        
        if tree_layer:
            tree_layer.setItemVisibilityChecked(action.visible)
            if self.canvas:
                self.canvas.refresh()
        return None

    def handle_drawing_layer_visibility(self, action: SetDrawingLayerVisibilityAction) -> Optional[UIAction]:
        """個別の図面レイヤの表示/非表示を切り替える"""
        root = QgsProject.instance().layerTreeRoot()
        if root:
            image_group = root.findGroup("画像ファイル")
            if image_group:
                tree_layer = image_group.findLayer(action.layer_id)
                if tree_layer:
                    tree_layer.setItemVisibilityChecked(action.visible)
                    if self.canvas:
                        self.canvas.refresh()
        return None

    def handle_toggle_all_drawings_visibility(self, action: ToggleAllDrawingsVisibilityAction) -> Optional[UIAction]:
        """全図面レイヤの表示/非表示を一括で切り替える"""
        root = QgsProject.instance().layerTreeRoot()
        if not root:
            return None
            
        image_group = root.findGroup("画像ファイル")
        if not image_group:
            return None
            
        for tree_layer in image_group.findLayers():
            tree_layer.setItemVisibilityChecked(action.visible)
            
        if self.canvas:
            self.canvas.refresh()
        return None