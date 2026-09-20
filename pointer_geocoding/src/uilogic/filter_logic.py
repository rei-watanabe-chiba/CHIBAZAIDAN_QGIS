"""
/***************************************************************************
 PointerGeocoding Plugin - Filter Logic (Controller)
 ***************************************************************************/

Tab 2 の表示設定（フォーカスモード、基準点表示、図面表示切り替え）イベントを受容し、
キャンバスやレイヤツリーの可視性制御を処理するController層です。
UI層からは BuiltPanel を注入（DI）されることで直接イベントをバインドし、循環参照を防ぎます。
"""
from typing import Optional
from qgis.core import QgsProject
from qgis.PyQt.QtCore import QObject, Qt
from qgis.PyQt.QtWidgets import QDialog

from ..ui.core.state import UIStateStore, SetFocusModeAction
from ..ui.dialogs import DisplayFilterDialog


class FilterLogic(QObject):
    """
    表示フィルター・レイヤ可視性制御を担うControllerクラス。
    """
    def __init__(
        self,
        state_store: UIStateStore,
        layer_manager,
        iface,
        parent: Optional[QObject] = None
    ):
        super().__init__(parent)
        self.state_store = state_store
        self.layer_manager = layer_manager
        self.iface = iface
        self.parent_widget = parent
        self.canvas = self.iface.mapCanvas()
        
        self.display_panel = None

    def bind_ui_panels(self, display_panel):
        """Viewから BuiltPanel インスタンスを受け取り、Controller自身でシグナルをバインドする"""
        self.display_panel = display_panel

        # コントローラー主導のイベントバインド（一方向依存を維持）
        self.display_panel.bind("filter_toggled", self._on_filter_toggled)
        self.display_panel.bind("filter_settings_clicked", self._show_display_filter_dialog)
        self.display_panel.bind("ref_point_visibility_changed", self._on_ref_point_visibility_changed)
        self.display_panel.bind("drawing_table_cell_changed", self._on_table_cell_changed)

    def _on_filter_toggled(self, checked: bool) -> None:
        """フォーカスモードのトグルボタン切り替え"""
        self.state_store.dispatch(SetFocusModeAction(checked))

    def _show_display_filter_dialog(self) -> None:
        """表示フィルター設定ダイアログの表示"""
        dlg = DisplayFilterDialog(
            parent=self.parent_widget,
            feature_names=self.state_store.state.feature_name_list,
            initial_filters=self.state_store.state.display_filters,
        )
        if dlg.exec_() == QDialog.Accepted:
            # OKクリック時にフォーカスモードを強制ONにする
            self.state_store.dispatch(SetFocusModeAction(True))

    def _on_ref_point_visibility_changed(self, idx: int) -> None:
        """基準点レイヤの表示/非表示ラジオボタンの切り替え"""
        checked = (idx == 0)
        ref_layer = getattr(self.layer_manager, "ref_point_layer", None)
        if not ref_layer:
            return
            
        root = QgsProject.instance().layerTreeRoot()
        if not root:
            return
            
        ref_group = root.findGroup("基準点データ")
        search_root = ref_group if ref_group else root
        tree_layer = search_root.findLayer(ref_layer.id())
        
        if tree_layer:
            tree_layer.setItemVisibilityChecked(checked)
            if self.canvas:
                self.canvas.refresh()

    def _on_table_cell_changed(self, row: int, col: int) -> None:
        """図面選択テーブルのチェックボックス（可視性）切り替え"""
        table = self.display_panel.get("drawing_list_table")
        item = table.item(row, col)
        
        if item is None or col != 0:
            return
            
        layer_id = item.data(Qt.UserRole)
        if not layer_id:
            return
            
        is_checked = (item.checkState() == Qt.Checked)
        root = QgsProject.instance().layerTreeRoot()
        if root:
            image_group = root.findGroup("画像ファイル")
            if image_group:
                tree_layer = image_group.findLayer(layer_id)
                if tree_layer:
                    tree_layer.setItemVisibilityChecked(is_checked)
                    if self.canvas:
                        self.canvas.refresh()