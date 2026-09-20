"""
/***************************************************************************
 PointerGeocoding Plugin - Tab 2 (Display Filter) Mixin
 ***************************************************************************/
"""
from typing import Dict, Any, List, Tuple, Optional

from qgis.core import QgsProject
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QTableWidgetItem, QDialog

from ...logic.core import AttributeType, ExcavationType
from ..constants import UILabels
from ..dialogs import DisplayFilterDialog


class Tab2DisplayFilterMixin:
    """Mixin providing Tab 2 (Focus Mode, Display Filter, and Drawing List) behavior."""

    def _get_drawing_layers(self) -> List[Tuple[str, str, bool]]:
        """Extract valid raster layer information from the '画像ファイル' group in QGIS layer tree."""
        root = QgsProject.instance().layerTreeRoot()
        if not root:
            return []
        image_group = root.findGroup("画像ファイル")
        if not image_group:
            return []

        result: List[Tuple[str, str, bool]] = []
        for tree_layer in image_group.findLayers():
            layer = tree_layer.layer()
            if layer and layer.isValid():
                result.append((layer.name(), layer.id(), tree_layer.itemVisibilityChecked()))
        return result

    def _get_drawing_layer_names(self) -> List[str]:
        """Extract valid raster layer names from the '画像ファイル' group in QGIS layer tree."""
        return [info[0] for info in self._get_drawing_layers()]

    def _update_drawing_combo(self, *args: Any) -> None:
        """Dynamically refresh the target drawing table."""
        if not hasattr(self, "table_drawing_list") or self.table_drawing_list is None:
            return

        current_selection = self._get_target_drawing_name()
        self.table_drawing_list.blockSignals(True)
        self.table_drawing_list.setRowCount(0)

        # Row 0: DRAWING_UNSPECIFIED
        self.table_drawing_list.insertRow(0)
        item_col0 = QTableWidgetItem()
        item_col0.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        item_col0.setCheckState(Qt.Unchecked)
        self.table_drawing_list.setItem(0, 0, item_col0)

        item_col1 = QTableWidgetItem(UILabels.DRAWING_UNSPECIFIED)
        item_col1.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        self.table_drawing_list.setItem(0, 1, item_col1)

        layers_info = self._get_drawing_layers()
        for r_idx, (name, layer_id, is_vis) in enumerate(layers_info, start=1):
            self.table_drawing_list.insertRow(r_idx)

            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            chk_item.setCheckState(Qt.Checked if is_vis else Qt.Unchecked)
            chk_item.setData(Qt.UserRole, layer_id)
            self.table_drawing_list.setItem(r_idx, 0, chk_item)

            name_item = QTableWidgetItem(name)
            name_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            self.table_drawing_list.setItem(r_idx, 1, name_item)

        self.table_drawing_list.blockSignals(False)
        self._ensure_drawing_selected(current_selection)

        if hasattr(self, "radio_ref_point_visible") and self.radio_ref_point_visible is not None:
            self._sync_ref_point_visibility_radios()

    def _on_table_cell_changed(self, item: QTableWidgetItem) -> None:
        """Toggle canvas visibility when checkbox column state changes."""
        if item is None or item.column() != 0:
            return
        layer_id = item.data(Qt.UserRole)
        if not layer_id:
            return
        is_checked = item.checkState() == Qt.Checked
        root = QgsProject.instance().layerTreeRoot()
        if root and layer_id:
            image_group = root.findGroup("画像ファイル")
            if image_group:
                tree_layer = image_group.findLayer(layer_id)
                if tree_layer:
                    tree_layer.setItemVisibilityChecked(is_checked)
                    self.canvas.refresh()

    def _on_table_selection_changed(self) -> None:
        """Handle selection changes in table_drawing_list."""
        self._on_category_changed()
        self._commit_attribute_fields_if_editing()

    def _on_header_clicked(self, logical_index: int) -> None:
        """Handle clicking the horizontal header (column 0 toggle all)."""
        if logical_index != 0:
            return
        row_count = self.table_drawing_list.rowCount()
        if row_count <= 1:
            return

        all_checked = True
        for row in range(1, row_count):
            item = self.table_drawing_list.item(row, 0)
            if item and item.checkState() != Qt.Checked:
                all_checked = False
                break

        new_state = Qt.Unchecked if all_checked else Qt.Checked
        for row in range(1, row_count):
            item = self.table_drawing_list.item(row, 0)
            if item:
                item.setCheckState(new_state)

    def _get_target_drawing_name(self) -> str:
        """Return the text of col 1 for the currently selected row in table_drawing_list."""
        if not hasattr(self, "table_drawing_list") or self.table_drawing_list is None:
            return UILabels.DRAWING_UNSPECIFIED
        row = -1
        sel_model = self.table_drawing_list.selectionModel()
        if sel_model:
            selected_rows = sel_model.selectedRows()
            if selected_rows:
                row = selected_rows[0].row()
        if row < 0:
            row = self.table_drawing_list.currentRow()

        if row <= 0:
            return UILabels.DRAWING_UNSPECIFIED
        item = self.table_drawing_list.item(row, 1)
        if not item:
            return UILabels.DRAWING_UNSPECIFIED
        return item.text().strip()

    def _ensure_drawing_selected(self, layer_name: str) -> None:
        """Select and scroll to the row corresponding to layer_name in table_drawing_list."""
        if not hasattr(self, "table_drawing_list") or self.table_drawing_list is None:
            return
        row_count = self.table_drawing_list.rowCount()
        if row_count == 0:
            return

        target_row = 0
        if layer_name and layer_name != UILabels.DRAWING_UNSPECIFIED:
            for r in range(1, row_count):
                item = self.table_drawing_list.item(r, 1)
                if item and item.text() == layer_name:
                    target_row = r
                    break

        self.table_drawing_list.selectRow(target_row)
        scroll_item = self.table_drawing_list.item(target_row, 1)
        if scroll_item:
            self.table_drawing_list.scrollToItem(scroll_item)

    def _find_ref_point_tree_layer(self) -> Optional[Any]:
        """Locate the QgsLayerTreeLayer node for the shared 基準点レイヤ (ref_point_layer)."""
        ref_layer = getattr(self.layer_manager, "ref_point_layer", None) if self.layer_manager else None
        if ref_layer is None:
            return None
        root = QgsProject.instance().layerTreeRoot()
        if not root:
            return None
        ref_group = root.findGroup("基準点データ")
        search_root = ref_group if ref_group else root
        return search_root.findLayer(ref_layer.id())

    def _sync_ref_point_visibility_radios(self) -> None:
        """Initialize/refresh 基準点 visibility radio buttons from the actual layer tree state."""
        tree_layer = self._find_ref_point_tree_layer()
        enabled = tree_layer is not None
        self.radio_ref_point_visible.setEnabled(enabled)
        self.radio_ref_point_hidden.setEnabled(enabled)

        is_visible = tree_layer.itemVisibilityChecked() if tree_layer else True
        self.radio_ref_point_visible.blockSignals(True)
        self.radio_ref_point_hidden.blockSignals(True)
        self.radio_ref_point_visible.setChecked(is_visible)
        self.radio_ref_point_hidden.setChecked(not is_visible)
        self.radio_ref_point_visible.blockSignals(False)
        self.radio_ref_point_hidden.blockSignals(False)

    def _on_ref_point_visibility_radio_toggled(self, checked: bool) -> None:
        """Toggle canvas visibility for the shared 基準点レイヤ."""
        tree_layer = self._find_ref_point_tree_layer()
        if tree_layer:
            tree_layer.setItemVisibilityChecked(checked)
            self.canvas.refresh()

    def _ensure_drawing_visible(self, drawing_name: str) -> None:
        """Ensure the specified drawing is checked ON in table_drawing_list and visible on canvas."""
        if not hasattr(self, "table_drawing_list") or self.table_drawing_list is None:
            return
        if not drawing_name or drawing_name == UILabels.DRAWING_UNSPECIFIED:
            return

        root = QgsProject.instance().layerTreeRoot()
        image_group = root.findGroup("画像ファイル") if root else None

        for r in range(1, self.table_drawing_list.rowCount()):
            name_item = self.table_drawing_list.item(r, 1)
            if name_item and name_item.text() == drawing_name:
                chk_item = self.table_drawing_list.item(r, 0)
                if chk_item and chk_item.checkState() != Qt.Checked:
                    self.table_drawing_list.blockSignals(True)
                    chk_item.setCheckState(Qt.Checked)
                    self.table_drawing_list.blockSignals(False)

                    layer_id = chk_item.data(Qt.UserRole)
                    if image_group and layer_id:
                        tree_layer = image_group.findLayer(layer_id)
                        if tree_layer:
                            tree_layer.setItemVisibilityChecked(True)
                    self.canvas.refresh()
                break

    def is_focus_mode_active(self) -> bool:
        """Return whether Focus / Filter Mode is currently active."""
        btn = getattr(self, "btn_filter", None) or getattr(self, "btn_focus_mode", None)
        return bool(btn is not None and btn.isChecked())

    def get_focus_category_filter(self) -> Dict[str, Any]:
        """Return dictionary of filter criteria for display filtering."""
        filters = self.tab2_state.current_display_filters
        if not filters:
            feature_names = list(self.tab2_state.feature_name_list)
            filters = {
                "attributes": [
                    AttributeType.S.value,
                    AttributeType.P.value,
                    AttributeType.C.value,
                    AttributeType.SP.value,
                ],
                "excavation_types": [
                    ExcavationType.FEATURE.value,
                    ExcavationType.GRID.value,
                ],
                "feature_names": feature_names,
                "target_drawing": UILabels.FILTER_DRAWING_SELECTED,
            }
            self.tab2_state.current_display_filters = filters

        target_drawing_setting = filters.get("target_drawing", UILabels.FILTER_DRAWING_SELECTED)

        drawing_name = ""
        if target_drawing_setting == UILabels.FILTER_DRAWING_SELECTED:
            d_name = self._get_target_drawing_name()
            if d_name != UILabels.DRAWING_UNSPECIFIED:
                drawing_name = d_name

        return {
            "attributes": list(filters.get("attributes", [])),
            "excavation_types": list(filters.get("excavation_types", [])),
            "feature_names": list(filters.get("feature_names", [])),
            "drawing_name": drawing_name,
            "target_drawing": target_drawing_setting,
        }

    def _push_focus_state_to_tool(self) -> None:
        """Push current Focus Mode state to CanvasDigitizingTool."""
        if getattr(self, "map_tool", None) is not None:
            self.map_tool.update_focus_state(
                self.is_focus_mode_active(), self.get_focus_category_filter()
            )

    def _on_focus_mode_toggled(self, checked: bool) -> None:
        """Handle Filter Mode toggle button click."""
        btn = getattr(self, "btn_filter", None) or getattr(self, "btn_focus_mode", None)
        if btn is not None:
            if checked:
                btn.setText(UILabels.BTN_FILTER_ON)
                btn.setStyleSheet(
                    "background-color: #1976D2; color: #FFFFFF; font-weight: bold; border-radius: 4px; padding: 4px;"
                )
            else:
                btn.setText(UILabels.BTN_FILTER_OFF)
                btn.setStyleSheet("")

        self._push_focus_state_to_tool()
        self.update_symbology_opacity()

    def _on_filter_settings_clicked(self) -> None:
        """Open DisplayFilterDialog to configure display filter parameters."""
        feature_names: List[str] = []
        if hasattr(self, "feature_colors") and self.feature_colors:
            feature_names = sorted(list(self.feature_colors.keys()))
        elif hasattr(self, "layer_manager") and getattr(self.layer_manager, "feature_colors", None):
            feature_names = sorted(list(self.layer_manager.feature_colors.keys()))

        current = dict(self.tab2_state.current_display_filters)
        if not current.get("feature_names") and feature_names:
            current["feature_names"] = list(feature_names)

        dlg = DisplayFilterDialog(
            parent=self,
            feature_names=feature_names,
            initial_filters=current,
        )
        if dlg.exec_() == QDialog.Accepted:
            self.tab2_state.current_display_filters = dlg.get_filters()
            self._push_focus_state_to_tool()
            if self.is_focus_mode_active():
                self.update_symbology_opacity()