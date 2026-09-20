"""
/***************************************************************************
 PointerGeocoding Plugin - Tab 2 (Digitizing Core) Mixin
 ***************************************************************************/
"""
import os
from contextlib import nullcontext
from typing import Dict, Any, List, Tuple, Optional

from qgis.core import QgsProject, QgsPointXY, Qgis
from qgis.PyQt.QtCore import Qt, pyqtSlot
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QScrollArea, QFrame,
    QMessageBox, QDialog, QTableWidget
)

try:
    from qgis.PyQt.QtGui import QRegularExpressionValidator
    from qgis.PyQt.QtCore import QRegularExpression
    HAS_QT_REGEX = True
except ImportError:
    from qgis.PyQt.QtGui import QRegExpValidator
    from qgis.PyQt.QtCore import QRegExp
    HAS_QT_REGEX = False

from ..style import UIStyleHelper
from ...logic.core import (
    check_point_duplicate, build_point_ident, get_next_point_number,
    get_next_point_id, build_digitized_feature, insert_feature_to_layer,
    pixel_from_affine, safe_get_str, to_survey_coords,
    ExcavationType, AttributeType
)
from ..constants import UIConfig, UILabels, UIPlaceholders, UIDialogTitles, UIMessages
from ..dialogs import FeatureManageDialog, PointNameEntryDialog
from .tab2_schemas import TAB2_MODE_TOGGLE_SPEC, TAB2_POINT_INFO_SPEC, TAB2_ATTRIBUTE_SPEC, TAB2_DISPLAY_FILTER_SPEC
from ..core import CoreUIBuilder


class Tab2DigitizingCoreMixin:
    """Mixin providing core Tab 2 continuous digitizing, editing, and real-time commit behavior."""

    def _create_tab2_ui(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(
            UIConfig.PANEL_CONTAINER_MARGIN_LEFT,
            0,
            UIConfig.PANEL_CONTAINER_MARGIN_RIGHT,
            UIConfig.PANEL_MARGIN,
        )
        layout.setSpacing(0)

        # =============================================================
        # 先頭：新規/編集モード切替トグル
        # =============================================================
        self.tab2_state.current_mode = "new"
        self.tab2_state.suppress_realtime_commit = False
        
        mode_panel = CoreUIBuilder.build(TAB2_MODE_TOGGLE_SPEC, parent=container)
        mode_panel.bind("mode_changed", self._on_tab2_mode_changed)
        
        self.tab2_mode_container = mode_panel.get("tab2_mode")
        self.tab2_mode_buttons = mode_panel.get_buttons("tab2_mode")
        
        layout.addWidget(mode_panel.widget)
        layout.addSpacing(UIConfig.PANEL_MARGIN)

        # =============================================================
        # Panel 1: 点情報パネル (CoreUI)
        # =============================================================
        self.tab2_state.autonum_mode = "auto"
        point_info_panel = CoreUIBuilder.build(TAB2_POINT_INFO_SPEC, parent=container)
        self.group_point_info = point_info_panel.widget
        
        self.panel_point_info = point_info_panel.get("point_info_summary")
        self.lbl_point_info_status = QLabel(self.panel_point_info)
        self.lbl_point_info_status.setWordWrap(True)
        self.panel_point_info.layout().addWidget(self.lbl_point_info_status)
        UIStyleHelper.update_status_panel(
            self.panel_point_info, self.lbl_point_info_status, UILabels.STATUS_NEW_POINT, "info"
        )
        
        self.edit_point_name = point_info_panel.get("point_name")
        self.edit_point_name_sp = point_info_panel.get("point_name_sp")
        self.edit_branch_no = point_info_panel.get("branch_no")
        
        if HAS_QT_REGEX:
            self.edit_point_name_sp.setValidator(
                QRegularExpressionValidator(QRegularExpression(r"^[A-Za-z0-9_-]+$"), self.edit_point_name_sp)
            )
        else:
            self.edit_point_name_sp.setValidator(
                QRegExpValidator(QRegExp(r"^[A-Za-z0-9_-]+$"), self.edit_point_name_sp)
            )
            
        self.tab2_autonum_container = point_info_panel.get_row("autonum_mode")
        self.tab2_autonum_buttons = point_info_panel.get_buttons("autonum_mode")
        self.widget_new_mode_actions = self.tab2_autonum_container
        
        self.widget_edit_mode_actions = point_info_panel.get_row("edit_mode_actions")
        self.btn_delete_point = point_info_panel.get("delete_point")

        point_info_panel.bind("point_identity_changed", self._on_point_identity_changed)
        point_info_panel.bind("branch_text_changed", self._on_branch_text_changed)
        point_info_panel.bind("autonum_mode_changed", self._on_tab2_autonum_mode_changed)
        point_info_panel.bind("delete_point_clicked", self._on_delete_selected_point)

        layout.addWidget(self.group_point_info)
        layout.addWidget(UIStyleHelper.build_separator(container))

        # =============================================================
        # Panel 2: 属性パネル (CoreUI)
        # =============================================================
        attr_panel = CoreUIBuilder.build(TAB2_ATTRIBUTE_SPEC, parent=container)
        self.group_attribute_panel = attr_panel.widget
        
        self.combo_attribute = attr_panel.get("attribute_code")
        self.combo_excavation_type = attr_panel.get("excavation_type")
        self.combo_feature_name = attr_panel.get("feature_name")
        self.row_feature_selector = attr_panel.get_row("feature_name")
        self.row_feature_actions = attr_panel.get_row("feature_actions")
        self.btn_manage_feature = attr_panel.get("manage_feature")

        attr_panel.bind("category_changed", self._on_category_changed)
        attr_panel.bind("excavation_type_changed", self._on_excavation_type_changed)
        attr_panel.bind("feature_combo_changed", self._on_feature_combo_changed)
        attr_panel.bind("manage_feature_clicked", self._on_manage_feature_clicked)

        self.combo_attribute.blockSignals(True)
        for value in UILabels.ATTRIBUTE_OPTIONS:
            self.combo_attribute.addItem(UILabels.ATTRIBUTE_DISPLAY_MAP.get(value, value), value)
        self.combo_attribute.blockSignals(False)
        
        self.combo_excavation_type.blockSignals(True)
        self.combo_excavation_type.addItems(UILabels.EXCAVATION_OPTIONS)
        self.combo_excavation_type.blockSignals(False)
        
        self.combo_feature_name.blockSignals(True)
        self.combo_feature_name.addItem(UILabels.UNREGISTERED)
        self.combo_feature_name.blockSignals(False)
        
        layout.addWidget(self.group_attribute_panel)
        layout.addWidget(UIStyleHelper.build_separator(container))

        # =============================================================
        # Panel 3: 表示設定パネル (CoreUI)
        # =============================================================
        display_panel = CoreUIBuilder.build(TAB2_DISPLAY_FILTER_SPEC, parent=container)
        self.group_display = display_panel.widget
        self.group_focus = self.group_display
        self.group_drawing_list = self.group_display
        
        self.btn_filter = display_panel.get("filter_toggle")
        self.btn_filter.setCheckable(True)
        self.btn_focus_mode = self.btn_filter
        self.btn_filter_settings = display_panel.get("filter_settings")
        
        radios = display_panel.get_buttons("ref_point_visibility")
        self.radio_ref_point_visible = radios[0]
        self.radio_ref_point_hidden = radios[1]
        self.radio_ref_point_visible.toggled.connect(self._on_ref_point_visibility_radio_toggled)

        self.table_drawing_list = display_panel.get("drawing_list_table")
        self.table_drawing_list.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_drawing_list.setSelectionMode(QTableWidget.SingleSelection)
        self.table_drawing_list.setFocusPolicy(Qt.NoFocus)
        self.table_drawing_list.setShowGrid(False)
        self.table_drawing_list.setStyleSheet(
            "QTableView::indicator { subcontrol-position: center; }"
            "QTableView { border: none; }"
            "QTableView::item:focus { border: none; outline: none; }"
        )
        self.table_drawing_list.verticalHeader().setVisible(False)
        self.table_drawing_list.verticalHeader().setMinimumSectionSize(20)
        self.table_drawing_list.verticalHeader().setDefaultSectionSize(20)
        header = self.table_drawing_list.horizontalHeader()
        header.setStretchLastSection(True)
        header.resizeSection(0, 40)
        self.table_drawing_list.setColumnWidth(0, 40)
        
        self.table_drawing_list.itemSelectionChanged.connect(self._on_table_selection_changed)
        header.sectionClicked.connect(self._on_header_clicked)
        self.table_drawing_list.itemChanged.connect(self._on_table_cell_changed)
        
        display_panel.bind("filter_toggled", self._on_focus_mode_toggled)
        display_panel.bind("filter_settings_clicked", self._on_filter_settings_clicked)
        
        self.tab2_state.current_display_filters = {
            "attributes": [AttributeType.S.value, AttributeType.P.value, AttributeType.C.value, AttributeType.SP.value],
            "excavation_types": [ExcavationType.FEATURE.value, ExcavationType.GRID.value],
            "feature_names": [],
            "target_drawing": UILabels.FILTER_DRAWING_SELECTED,
        }

        layout.addWidget(self.group_display)
        layout.addStretch()

        scroll.setWidget(container)

        self.tab2_state.point_info_has_error = False
        self._update_feature_related_visibility()
        self._sync_ref_point_visibility_radios()

        return scroll

    def _get_attribute_value(self) -> str:
        if not hasattr(self, "combo_attribute"):
            return ""
        return self.combo_attribute.currentData() or self.combo_attribute.currentText()

    def _set_attribute_value(self, value: str) -> None:
        idx = self.combo_attribute.findData(value)
        if idx >= 0:
            self.combo_attribute.setCurrentIndex(idx)
        else:
            self.combo_attribute.setCurrentText(value)

    def _on_category_changed(self, *args: Any) -> None:
        current_drawing = self._get_target_drawing_name()
        if current_drawing and current_drawing != UILabels.DRAWING_UNSPECIFIED:
            self._ensure_drawing_visible(current_drawing)

        self.tab2_state.is_out_of_bounds = False

        if self.tab2_state.selected_edit_point_id is not None:
            self._update_point_name_widget_visibility()
        else:
            self._apply_next_point_number()

        self._push_focus_state_to_tool()
        if self.is_focus_mode_active():
            self.update_symbology_opacity()

        self._refresh_point_info_labels()
        self._update_point_info_status()

    def _update_feature_related_visibility(self) -> None:
        is_feature = self.combo_excavation_type.currentText() == ExcavationType.FEATURE.value
        self.row_feature_selector.setVisible(is_feature)
        self.row_feature_actions.setVisible(is_feature)
        self.btn_manage_feature.setEnabled(is_feature)

    def _on_excavation_type_changed(self, index: int) -> None:
        self._update_feature_related_visibility()
        self._on_category_changed()
        self._commit_attribute_fields_if_editing()

    def _on_feature_combo_changed(self, text: str) -> None:
        self._update_feature_related_visibility()
        self._on_category_changed()
        self._commit_attribute_fields_if_editing()

    def _restore_feature_names(self) -> None:
        if not self.point_layer or not self.point_layer.isValid():
            return
        UIStyleHelper.populate_combo_from_layer_field(
            self.combo_feature_name,
            self.point_layer,
            "feature_name",
            leading_item=UILabels.UNREGISTERED,
            target_list=self.tab2_state.feature_name_list,
        )

    def register_new_feature_name(self, new_name: str) -> str:
        clean_name = new_name.strip()
        idx = self.combo_feature_name.findText(clean_name)
        if idx >= 0:
            self.combo_feature_name.setCurrentIndex(idx)
        else:
            self.combo_feature_name.addItem(clean_name)
            self.tab2_state.feature_name_list.append(clean_name)
            self.combo_feature_name.setCurrentText(clean_name)
        return clean_name

    def _rename_and_recolor_feature(self, old_name: str, new_name: str, new_color: str) -> None:
        if not self.point_layer or not self.point_layer.isValid():
            return
        fields = self.point_layer.fields()
        feat_idx = fields.indexFromName("feature_name")
        color_idx = fields.indexFromName("color_code")
        if feat_idx == -1 or color_idx == -1:
            return

        updated_count = 0
        self.point_layer.startEditing()
        for feat in self.point_layer.getFeatures():
            curr_feat_name = safe_get_str(feat, "feature_name")
            if curr_feat_name == old_name:
                self.point_layer.changeAttributeValue(feat.id(), feat_idx, new_name)
                self.point_layer.changeAttributeValue(feat.id(), color_idx, new_color)
                updated_count += 1
        self.point_layer.commitChanges()

        prev_suppress = self.tab2_state.suppress_realtime_commit
        self.tab2_state.suppress_realtime_commit = True
        self.combo_feature_name.blockSignals(True)
        try:
            if old_name in self.tab2_state.feature_name_list:
                idx = self.tab2_state.feature_name_list.index(old_name)
                self.tab2_state.feature_name_list[idx] = new_name
            elif new_name not in self.tab2_state.feature_name_list:
                self.tab2_state.feature_name_list.append(new_name)

            cur_text = self.combo_feature_name.currentText()
            found_idx = self.combo_feature_name.findText(old_name)
            if found_idx >= 0:
                self.combo_feature_name.setItemText(found_idx, new_name)
                if cur_text == old_name:
                    self.combo_feature_name.setCurrentIndex(found_idx)
            else:
                new_idx = self.combo_feature_name.findText(new_name)
                if new_idx < 0:
                    self.combo_feature_name.addItem(new_name)
                    new_idx = self.combo_feature_name.findText(new_name)
                if cur_text == old_name:
                    self.combo_feature_name.setCurrentIndex(new_idx)

            if self.combo_feature_name.currentText() == new_name:
                self.tab2_state.current_feature_color = QColor(new_color)
        finally:
            self.combo_feature_name.blockSignals(False)
            self.tab2_state.suppress_realtime_commit = prev_suppress

        self._update_point_info_status()

    def _on_manage_feature_clicked(self) -> None:
        feature_colors: Dict[str, str] = {}
        for name in self.tab2_state.feature_name_list:
            if name and name not in (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成")):
                feature_colors[name] = "#FF5722"

        if self.point_layer and self.point_layer.isValid():
            for feat in self.point_layer.getFeatures():
                fname = safe_get_str(feat, "feature_name").strip()
                if fname and fname not in (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成")):
                    c_code = safe_get_str(feat, "color_code").strip()
                    if c_code:
                        feature_colors[fname] = c_code
                    elif fname not in feature_colors:
                        feature_colors[fname] = "#FF5722"

        cur_text = self.combo_feature_name.currentText().strip()
        initial_feature = cur_text if cur_text in feature_colors else None

        dlg = FeatureManageDialog(
            parent=self,
            feature_colors=feature_colors,
            on_update_callback=self._rename_and_recolor_feature,
            initial_feature=initial_feature,
        )
        UIStyleHelper.apply_theme(dlg)
        if dlg.exec_() == QDialog.Accepted:
            new_name = dlg.result_text.strip()
            if new_name:
                if hasattr(dlg, "result_color") and dlg.result_color:
                    self.tab2_state.current_feature_color = QColor(dlg.result_color)
                self.register_new_feature_name(new_name)

    def get_digitizing_input_state(self) -> Dict[str, Any]:
        d_name = self._get_target_drawing_name()
        if d_name == UILabels.DRAWING_UNSPECIFIED:
            d_name = ""
        ex_type = self.combo_excavation_type.currentText()
        feat_name = self.combo_feature_name.currentText().strip()
        is_placeholder_feat = (not feat_name) or feat_name in (
            UILabels.UNREGISTERED,
            getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成"),
        )

        attr_type = self._get_attribute_value()
        pname, branch = self._get_current_point_name_and_branch()

        if not pname:
            return {"can_click": False, "error_message": UIMessages.ERR_POINT_NAME_REQUIRED}

        if ex_type == ExcavationType.FEATURE.value and is_placeholder_feat:
            return {"can_click": False, "error_message": UIMessages.ERR_NEW_FEATURE_REQUIRED}

        return {
            "can_click": True,
            "drawing_name": d_name,
            "excavation_type": ex_type,
            "feature_name": feat_name,
            "color_code": self.tab2_state.current_feature_color.name(),
            "attribute_type": attr_type,
            "point_name": pname,
            "branch_no": branch,
        }

    def _is_sp_attribute(self) -> bool:
        return hasattr(self, "combo_attribute") and self._get_attribute_value() == AttributeType.SP.value

    def _update_point_name_widget_visibility(self) -> None:
        is_sp = self._is_sp_attribute()
        self.edit_point_name.setVisible(not is_sp)
        self.edit_point_name_sp.setVisible(is_sp)
        self._update_autonum_toggle_for_sp(is_sp)

    def _update_autonum_toggle_for_sp(self, is_sp: bool) -> None:
        if not hasattr(self, "tab2_autonum_buttons"):
            return
        was_forced_by_sp = not self.tab2_autonum_buttons[0].isEnabled()
        if is_sp:
            if not self.tab2_autonum_buttons[1].isChecked():
                self.tab2_autonum_buttons[1].setChecked(True)
            self.tab2_autonum_buttons[0].setEnabled(False)
            self.tab2_autonum_buttons[1].setEnabled(False)
        else:
            self.tab2_autonum_buttons[0].setEnabled(True)
            self.tab2_autonum_buttons[1].setEnabled(True)
            is_editing_existing = self.tab2_state.selected_edit_point_id is not None
            if was_forced_by_sp and not is_editing_existing and not self.tab2_autonum_buttons[0].isChecked():
                self.tab2_autonum_buttons[0].setChecked(True)

    def _on_tab2_autonum_mode_changed(self, index: int) -> None:
        self.tab2_state.autonum_mode = "auto" if index == 0 else "release"
        if self.tab2_state.autonum_mode == "auto" and not self._is_sp_attribute():
            self.edit_point_name.setValue(self._get_next_point_number())
            self._refresh_point_info_labels()

    def _on_tab2_mode_changed(self, index: int) -> None:
        self.tab2_state.current_mode = "new" if index == 0 else "edit"
        self.tab2_state.is_out_of_bounds = False
        is_new = (self.tab2_state.current_mode == "new")
        self.widget_new_mode_actions.setVisible(is_new)
        self.widget_edit_mode_actions.setVisible(not is_new)
        self.edit_point_name.setEnabled(is_new)
        self.edit_point_name_sp.setEnabled(is_new)
        self.edit_branch_no.setEnabled(is_new)
        self.group_attribute_panel.setEnabled(is_new)
        if self.tab2_state.current_mode == "new" and self.tab2_state.selected_edit_point_id is not None:
            self._reset_point_selection()

    def _get_next_point_number(self) -> int:
        ex_type = self.combo_excavation_type.currentText()
        feat_name = ""
        if ex_type == ExcavationType.FEATURE.value:
            feat_name = self.combo_feature_name.currentText().strip()
            if feat_name in (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成")):
                feat_name = ""
        return get_next_point_number(self.point_layer, ex_type, feat_name)

    def _get_current_point_name_and_branch(self) -> Tuple[str, str]:
        pname = (
            self.edit_point_name_sp.text().strip()
            if self._is_sp_attribute()
            else str(self.edit_point_name.value())
        )
        branch = self.edit_branch_no.text().strip() if hasattr(self, "edit_branch_no") else ""
        return pname, branch

    def _is_feature_name_missing(self) -> bool:
        if self.combo_excavation_type.currentText() != ExcavationType.FEATURE.value:
            return False
        feat_text = self.combo_feature_name.currentText().strip()
        return (not feat_text) or feat_text in (
            UILabels.UNREGISTERED,
            getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成"),
        )

    def _check_realtime_duplicate(self) -> Optional[str]:
        if not self.point_layer or not self.point_layer.isValid():
            return None
        pname, branch = self._get_current_point_name_and_branch()
        if not pname:
            return None
        ex_type = self.combo_excavation_type.currentText()
        feat_name = self.combo_feature_name.currentText().strip()
        if feat_name in (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成")):
            feat_name = ""
        drawing_name = self._get_target_drawing_name()
        if drawing_name == UILabels.DRAWING_UNSPECIFIED:
            drawing_name = ""
        is_dup = check_point_duplicate(
            self.point_layer, ex_type, feat_name, pname, branch, drawing_name,
            exclude_feature_id=self.tab2_state.selected_edit_point_id,
        )
        if not is_dup:
            return None
        return build_point_ident(ex_type, feat_name, pname, branch, drawing_name)

    def _validate_drawing_bounds(self, drawing_name: str, map_point: QgsPointXY) -> Tuple[bool, Optional[Tuple[float, float]]]:
        if not drawing_name or drawing_name == UILabels.DRAWING_UNSPECIFIED:
            return True, (0.0, 0.0)
        if not self.layer_manager:
            return False, None
        meta = self.layer_manager.load_image_metadata()
        layer_meta = meta.get(drawing_name) if meta else None
        if not layer_meta:
            return False, None
        affine_params = layer_meta.get("affine_params")
        if not affine_params:
            return False, None
        px, py = pixel_from_affine(affine_params, map_point)
        raster_layer = None
        root = QgsProject.instance().layerTreeRoot()
        if root:
            image_group = root.findGroup("画像ファイル")
            if image_group:
                for tree_layer in image_group.findLayers():
                    l = tree_layer.layer()
                    if l and l.isValid() and l.name() == drawing_name:
                        raster_layer = l
                        break
        if raster_layer is None:
            layers = QgsProject.instance().mapLayersByName(drawing_name)
            if layers and layers[0].isValid():
                raster_layer = layers[0]
        if raster_layer is None or not hasattr(raster_layer, "width") or not hasattr(raster_layer, "height"):
            return False, None
        width = raster_layer.width()
        height = raster_layer.height()
        if 0 <= px <= width and 0 <= py <= height:
            return True, (px, py)
        return False, None

    def _check_realtime_out_of_bounds(self) -> bool:
        if self.tab2_state.selected_edit_point_id is None:
            return False
        if not self.point_layer or not self.point_layer.isValid():
            return False
        drawing_name = self._get_target_drawing_name()
        if not drawing_name or drawing_name == UILabels.DRAWING_UNSPECIFIED:
            return False
        feat = self.point_layer.getFeature(self.tab2_state.selected_edit_point_id)
        if not feat.isValid() or not feat.hasGeometry():
            return False
        map_point = feat.geometry().asPoint()
        is_valid, _ = self._validate_drawing_bounds(drawing_name, map_point)
        return not is_valid

    def _build_point_info_text(self, status_text: str) -> str:
        summary = self.tab2_state.point_info_summary or {}
        return "\n".join([
            status_text,
            f"{UILabels.LBL_INFO_GROUP_OR_FEATURE} {summary.get('group', '-')}",
            f"{UILabels.LBL_INFO_POINT_BRANCH} {summary.get('pointname', '-')}",
            f"{UILabels.LBL_INFO_COORDS} {summary.get('coords', '-')}",
        ])

    def _update_error_borders(self) -> None:
        UIStyleHelper.set_error_border(self.combo_feature_name, self._is_feature_name_missing())
        is_dup = bool(self._check_realtime_duplicate())
        is_sp = self._is_sp_attribute()
        UIStyleHelper.set_error_border(self.edit_point_name, is_dup and not is_sp)
        UIStyleHelper.set_error_border(self.edit_point_name_sp, is_dup and is_sp)

    def _update_point_info_status(self) -> None:
        if not hasattr(self, "lbl_point_info_status"):
            return
        is_editing = self.tab2_state.selected_edit_point_id is not None
        tooltip = ""
        if self._is_feature_name_missing():
            status_type, text = "error", UILabels.STATUS_ERR_FEATURE_REQUIRED
            self.tab2_state.point_info_has_error = True
        elif is_editing and self._check_realtime_out_of_bounds():
            status_type, text = "error", UILabels.STATUS_ERR_OUT_OF_BOUNDS
            self.tab2_state.point_info_has_error = True
        elif not is_editing and self.tab2_state.is_out_of_bounds:
            status_type, text = "error", UILabels.STATUS_ERR_OUT_OF_BOUNDS
            self.tab2_state.point_info_has_error = True
        else:
            dup_ident = self._check_realtime_duplicate()
            if dup_ident:
                status_type, text = "error", UILabels.STATUS_ERR_DUPLICATE
                tooltip = dup_ident
                self.tab2_state.point_info_has_error = True
            else:
                self.tab2_state.point_info_has_error = False
                if is_editing:
                    status_type, text = "warning", UILabels.STATUS_EDIT_POINT
                else:
                    status_type, text = "info", UILabels.STATUS_NEW_POINT

        full_text = self._build_point_info_text(text)
        UIStyleHelper.update_status_panel(
            self.panel_point_info, self.lbl_point_info_status, full_text, status_type
        )
        self.lbl_point_info_status.setToolTip(tooltip)
        self._update_error_borders()

    def _commit_fields_to_feature(self, updates: Dict[str, Any]) -> bool:
        if self.tab2_state.selected_edit_point_id is None or not self.point_layer:
            return False
        with (self.busy_interaction_guard() if hasattr(self, "busy_interaction_guard") else nullcontext()):
            field_names = self.point_layer.fields().names()
            self.point_layer.startEditing()
            for field_name, value in updates.items():
                if field_name in field_names:
                    idx = field_names.index(field_name)
                    self.point_layer.changeAttributeValue(self.tab2_state.selected_edit_point_id, idx, value)
            self.point_layer.commitChanges()
            if self.tab2_state.selected_point_data is not None:
                self.tab2_state.selected_point_data.update(updates)
            if self.is_focus_mode_active():
                self.update_symbology_opacity()
        return True

    def _commit_point_identity_if_editing(self, *args: Any) -> None:
        if self.tab2_state.suppress_realtime_commit:
            return
        if self.tab2_state.selected_edit_point_id is None or not self.point_layer:
            return
        if self.tab2_state.point_info_has_error:
            return
        pname, branch = self._get_current_point_name_and_branch()
        if not pname:
            return
        updates: Dict[str, Any] = {"point_name": pname, "branch_no": branch}
        if self._commit_fields_to_feature(updates):
            self._refresh_point_info_labels(override=self.tab2_state.selected_point_data)
            self._update_point_info_status()

    def _commit_attribute_fields_if_editing(self, *args: Any) -> None:
        if self.tab2_state.suppress_realtime_commit:
            return
        if self.tab2_state.selected_edit_point_id is None or not self.point_layer:
            return
        if self.tab2_state.point_info_has_error:
            return
        raw_drawing = self._get_target_drawing_name()
        drawing_name = "" if raw_drawing == UILabels.DRAWING_UNSPECIFIED else raw_drawing
        ex_type = self.combo_excavation_type.currentText()
        feat_name = self.combo_feature_name.currentText().strip()
        if feat_name in (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成")):
            feat_name = ""
        is_feature = ex_type == ExcavationType.FEATURE.value
        attr_value = self._get_attribute_value()

        updates: Dict[str, Any] = {
            "drawing_name": drawing_name,
            "excavation_type": ex_type,
            "feature_name": feat_name if is_feature else "",
            "color_code": self.tab2_state.current_feature_color.name() if is_feature else "",
            "attribute_type": attr_value,
        }

        old_drawing_name = ""
        if self.tab2_state.selected_point_data is not None:
            old_drawing_name = str(self.tab2_state.selected_point_data.get("drawing_name") or "").strip()

        if drawing_name != old_drawing_name:
            feat = self.point_layer.getFeature(self.tab2_state.selected_edit_point_id)
            if feat.isValid() and feat.hasGeometry():
                map_point = feat.geometry().asPoint()
                is_valid, px_coords = self._validate_drawing_bounds(drawing_name, map_point)
                if not is_valid:
                    self._update_point_info_status()
                    return
                if px_coords is not None:
                    updates["pixel_x"] = px_coords[0]
                    updates["pixel_y"] = px_coords[1]

        if self._commit_fields_to_feature(updates):
            self._refresh_point_info_labels(override=self.tab2_state.selected_point_data)
            self._update_point_info_status()

    def _on_point_identity_changed(self, *args: Any) -> None:
        self._refresh_point_info_labels()
        self._update_point_info_status()

    def _refresh_point_info_labels(self, override: Optional[Dict[str, Any]] = None) -> None:
        if not hasattr(self, "lbl_point_info_status"):
            return
        if override is not None:
            ex_type = str(override.get("excavation_type") or ExcavationType.GRID.value)
            if ex_type == ExcavationType.FEATURE.value:
                group_label = str(override.get("feature_name") or "") or UILabels.UNREGISTERED
            else:
                group_label = ExcavationType.GRID.value
            pname = str(override.get("point_name") or "")
            branch = str(override.get("branch_no") or "")
            cx = override.get("canvas_x")
            cy = override.get("canvas_y")
            if cx is not None and cy is not None:
                survey_x, survey_y = to_survey_coords(float(cx), float(cy))
                coords_text = f"X: {survey_x:.3f}  Y: {survey_y:.3f}"
            else:
                coords_text = "-"
        else:
            ex_type = self.combo_excavation_type.currentText()
            if ex_type == ExcavationType.FEATURE.value:
                group_label = self.combo_feature_name.currentText()
            else:
                group_label = ExcavationType.GRID.value
            pname, branch = self._get_current_point_name_and_branch()
            coords_text = "-"

        pn_display = f"{pname} {branch}".strip() if pname else ""
        self.tab2_state.point_info_summary = {
            "group": group_label or "-",
            "pointname": pn_display or "-",
            "coords": coords_text,
        }

    def _apply_next_point_number(self) -> None:
        self._update_point_name_widget_visibility()
        if self._is_sp_attribute():
            self.edit_point_name_sp.clear()
        elif self.tab2_state.autonum_mode == "auto":
            next_num = self._get_next_point_number()
            self.edit_point_name.setValue(next_num)
        self._refresh_point_info_labels()

    @pyqtSlot(str)
    def _on_branch_text_changed(self, text: str) -> None:
        if not text.strip() and self.tab2_state.has_digitized_with_branch:
            self._apply_next_point_number()
            self.tab2_state.has_digitized_with_branch = False
        self._on_point_identity_changed()

    def _on_canvas_clicked(self, map_point: QgsPointXY) -> None:
        if not self.point_layer or not self.point_layer.isValid():
            return
        if self.tab2_state.autonum_mode == "release":
            self._handle_release_mode_click(map_point)
            return

        state = self.get_digitizing_input_state()
        if not state.get("can_click", False):
            return

        if self._is_feature_name_missing() or self._check_realtime_duplicate():
            self._update_point_info_status()
            return

        drawing_name = state.get("drawing_name", "")
        is_valid, _ = self._validate_drawing_bounds(drawing_name, map_point)
        if not is_valid:
            self.tab2_state.is_out_of_bounds = True
            self._update_point_info_status()
            return
        self.tab2_state.is_out_of_bounds = False

        self._create_digitized_point_from_state(state, map_point)

    def _handle_release_mode_click(self, map_point: QgsPointXY) -> None:
        if self._is_feature_name_missing():
            self._update_point_info_status()
            return

        drawing_name = self._get_target_drawing_name()
        if drawing_name == UILabels.DRAWING_UNSPECIFIED:
            drawing_name = ""

        is_valid, _ = self._validate_drawing_bounds(drawing_name, map_point)
        if not is_valid:
            self.tab2_state.is_out_of_bounds = True
            self._update_point_info_status()
            return
        self.tab2_state.is_out_of_bounds = False

        excavation_type = self.combo_excavation_type.currentText()
        feature_name = self.combo_feature_name.currentText()
        if feature_name == UILabels.FEATURE_NEW_OPTION:
            feature_name = ""

        is_sp = self._is_sp_attribute()
        last_point_name = self._get_last_created_point_name(excavation_type, feature_name, is_sp)

        dlg = PointNameEntryDialog(
            self.point_layer,
            excavation_type,
            feature_name,
            drawing_name,
            is_sp,
            self,
            initial_point_name=last_point_name,
        )
        UIStyleHelper.apply_theme(dlg)
        self._position_dialog_near_map_point(dlg, map_point)
        if dlg.exec_() != QDialog.Accepted:
            return

        point_name, branch_no = dlg.get_values()
        state = {
            "drawing_name": drawing_name,
            "excavation_type": excavation_type,
            "feature_name": feature_name,
            "color_code": self.tab2_state.current_feature_color.name(),
            "attribute_type": self._get_attribute_value(),
            "point_name": point_name,
            "branch_no": branch_no,
        }
        self._create_digitized_point_from_state(state, map_point)

    def _get_last_created_point_name(self, excavation_type: str, feature_name: str, is_sp: bool) -> str:
        if not self.point_layer or not self.point_layer.isValid():
            return ""
        max_point_id = None
        latest_point_name = None
        for feat in self.point_layer.getFeatures():
            ex_type = safe_get_str(feat, "excavation_type")
            if excavation_type == ExcavationType.GRID.value:
                if ex_type != ExcavationType.GRID.value:
                    continue
            else:
                f_name = safe_get_str(feat, "feature_name")
                if ex_type != ExcavationType.FEATURE.value or f_name != feature_name:
                    continue
            feat_is_sp = safe_get_str(feat, "attribute_type") == AttributeType.SP.value
            if feat_is_sp != is_sp:
                continue
            pid = feat["point_id"]
            if pid is None or not isinstance(pid, int):
                continue
            if max_point_id is None or pid > max_point_id:
                max_point_id = pid
                latest_point_name = feat["point_name"]
        return "" if latest_point_name is None else str(latest_point_name)

    def _position_dialog_near_map_point(self, dlg: QDialog, map_point: QgsPointXY) -> None:
        if not hasattr(self, "map_tool") or not self.map_tool or not hasattr(self.map_tool, "canvas"):
            return
        canvas = self.map_tool.canvas
        try:
            from qgis.PyQt.QtCore import QPoint
            canvas_pt = canvas.getCoordinateTransform().transform(map_point)
            local_pt = QPoint(round(canvas_pt.x()), round(canvas_pt.y()))
            dlg.move(canvas.mapToGlobal(local_pt))
        except Exception:
            pass

    def _create_digitized_point_from_state(self, state: Dict[str, Any], map_point: QgsPointXY) -> None:
        drawing_name = state.get("drawing_name", "")
        if drawing_name == UILabels.DRAWING_UNSPECIFIED:
            drawing_name = ""
        excavation_type = state["excavation_type"]
        feature_name = state["feature_name"]
        color_code = state["color_code"]
        attribute_type = state["attribute_type"]
        point_name = state["point_name"]
        branch_no = state["branch_no"]

        next_point_id = get_next_point_id(self.point_layer)
        _, coords = self._validate_drawing_bounds(drawing_name, map_point)
        pixel_coords = coords if coords is not None else (0.0, 0.0)

        new_feat = build_digitized_feature(
            self.point_layer,
            next_point_id,
            map_point,
            {
                "drawing_name": drawing_name,
                "excavation_type": excavation_type,
                "feature_name": feature_name if excavation_type == ExcavationType.FEATURE.value else "",
                "color_code": color_code if excavation_type == ExcavationType.FEATURE.value else "",
                "attribute_type": attribute_type,
                "point_name": point_name,
                "branch_no": branch_no,
            },
            pixel_coords=pixel_coords,
        )

        with (self.busy_interaction_guard() if hasattr(self, "busy_interaction_guard") else nullcontext()):
            insert_feature_to_layer(self.point_layer, new_feat)
            self._on_point_digitized({
                "point_id": next_point_id,
                "drawing_name": drawing_name,
                "point_name": point_name,
                "branch_no": branch_no,
                "excavation_type": excavation_type,
                "feature_name": feature_name,
            })

    def _on_point_digitized(self, data: dict) -> None:
        branch_no = data.get("branch_no", "")
        if branch_no:
            self.tab2_state.has_digitized_with_branch = True
        else:
            self.tab2_state.has_digitized_with_branch = False
            self._apply_next_point_number()
        self._refresh_point_info_labels()
        self._update_point_info_status()

    _CATEGORY_LOCK_WIDGET_NAMES = ()

    def _set_category_widgets_locked(self, locked: bool) -> None:
        for name in self._CATEGORY_LOCK_WIDGET_NAMES:
            widget = getattr(self, name, None)
            if widget is not None:
                widget.setEnabled(not locked)

    @pyqtSlot(dict)
    def _on_existing_point_selected(self, data: dict) -> None:
        from ..dialogs import PointEditDialog
        
        if getattr(self, "map_tool", None) and hasattr(self.map_tool, "set_interaction_locked"):
            self.map_tool.set_interaction_locked(True)
            
        dialog = PointEditDialog(
            layer_manager=self.layer_manager,
            feature_data=data,
            drawing_names=self._get_drawing_layer_names(),
            parent=self
        )
        
        result = dialog.exec_()
        
        if getattr(self, "map_tool", None) and hasattr(self.map_tool, "set_interaction_locked"):
            self.map_tool.set_interaction_locked(False)
            
        if result == QDialog.Accepted:
            if dialog.dialog_action == "delete":
                self.tab2_state.selected_edit_point_id = data.get("feature_id")
                self._on_delete_selected_point()
            elif dialog.dialog_action == "confirm" and self.point_layer:
                fid = data.get("feature_id")
                updates = {
                    "drawing_name": dialog.feature_data["drawing_name"],
                    "excavation_type": dialog.feature_data["excavation_type"],
                    "feature_name": dialog.feature_data["feature_name"],
                    "attribute_type": dialog.feature_data["attribute_type"],
                    "point_name": dialog.feature_data["point_name"],
                    "branch_no": dialog.feature_data["branch_no"],
                }
                
                with (self.busy_interaction_guard() if hasattr(self, "busy_interaction_guard") else nullcontext()):
                    field_names = self.point_layer.fields().names()
                    self.point_layer.startEditing()
                    for field_name, value in updates.items():
                        if field_name in field_names:
                            idx = field_names.index(field_name)
                            self.point_layer.changeAttributeValue(fid, idx, value)
                    self.point_layer.commitChanges()
                    
                    if self.is_focus_mode_active():
                        self.update_symbology_opacity()
                        
                    self.canvas.refresh()
                    
        self._reset_point_selection()

    @pyqtSlot()
    def _on_blank_click_in_edit_mode(self) -> None:
        if self.tab2_state.selected_edit_point_id is None:
            return
        self._reset_point_selection()

    def _reset_point_selection(self) -> None:
        self.tab2_state.reset_selection()
        
        self._set_category_widgets_locked(False)
        self._apply_next_point_number()
        self.edit_branch_no.clear()
        self._refresh_point_info_labels()
        self._update_point_info_status()

        if getattr(self, "map_tool", None) is not None:
            self.map_tool.clear_selected_marker()

    def _on_delete_selected_point(self) -> None:
        if self.tab2_state.selected_edit_point_id is None or not self.point_layer:
            return

        with (self.busy_interaction_guard() if hasattr(self, "busy_interaction_guard") else nullcontext()):
            self.point_layer.startEditing()
            self.point_layer.deleteFeature(self.tab2_state.selected_edit_point_id)
            self.point_layer.commitChanges()

            self.iface.messageBar().pushMessage(
                UIMessages.MSG_DELETE_SUCCESS_TITLE,
                UIMessages.MSG_DELETE_SUCCESS,
                level=Qgis.MessageLevel.Success,
                duration=3,
            )
            self._reset_point_selection()