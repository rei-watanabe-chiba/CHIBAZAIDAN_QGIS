"""
/***************************************************************************
 PointerGeocoding Plugin - Main Dock Standalone Dialog Classes (View)
 ***************************************************************************/

各種ダイアログのUI構築モジュールです。ビジネスロジックは dialogs_logic.py へ分離されています。
"""
# 【変更不可侵の絶対的ルール】 測量座標系（X軸=南北, Y軸=東西）を採用。QGISキャンバス上のX座標(東西)はSurvey Y、Y座標(南北)はSurvey Xに対応する。

import re
from typing import Optional, Dict, Any, List, Callable, Tuple

from qgis.core import QgsRasterLayer
from qgis.gui import QgsMapCanvas
from qgis.PyQt.QtCore import Qt, pyqtSlot, QRegExp
from qgis.PyQt.QtGui import QRegExpValidator, QColor
from qgis.PyQt.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QSpinBox, QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QColorDialog, QCheckBox, QRadioButton, QButtonGroup, QListWidget,
    QListWidgetItem, QGroupBox, QComboBox
)

try:
    from qgis.PyQt.QtGui import QRegularExpressionValidator
    from qgis.PyQt.QtCore import QRegularExpression
    HAS_QT_REGEX = True
except ImportError:
    from qgis.PyQt.QtGui import QRegExpValidator
    from qgis.PyQt.QtCore import QRegExp
    HAS_QT_REGEX = False

from ..canvas.map_tool import ImageGeorefTool
from .style import UIStyleHelper
from ..logic.core import ExcavationType, AttributeType
from .constants import UIConfig, UILabels, UIMessages, UIPlaceholders, UIDialogSizes, UIDialogTitles
from .core.builder import CoreUIBuilder
from .core.field_spec import ButtonDef, FieldSpec, PanelSpec, WidgetType
from ..uilogic.dialogs_logic import GridInputLogic, PointNameEntryLogic, FeatureManageLogic

# =========================================================================
# CoreUI Schemas for Dialogs (Co-location)
# =========================================================================

GRID_INPUT_ACTIONS_SPEC = PanelSpec(
    panel_id="grid_input_actions",
    fields=[
        FieldSpec(
            field_id="dialog_actions",
            widget_type=WidgetType.BUTTON_ROW,
            centered=True,
            buttons=[
                ButtonDef(
                    field_id="confirm",
                    text=UILabels.BTN_CONFIRM,
                    style_variant="primary",
                    on_click="confirm_clicked",
                    enabled=False,
                ),
                ButtonDef(field_id="cancel", text=UILabels.BTN_CANCEL, on_click="cancel_clicked"),
            ],
        ),
    ],
)

POINT_NAME_ENTRY_SPEC = PanelSpec(
    panel_id="point_name_entry",
    fields=[
        FieldSpec(
            field_id="point_name",
            widget_type=WidgetType.SPINBOX_ROW,
            label=UILabels.POINT_NAME,
            spin_min=1,
            spin_max=999999,
            spin_default=1,
        ),
        FieldSpec(
            field_id="point_name_sp",
            widget_type=WidgetType.LINEEDIT_ROW,
            label=UILabels.POINT_NAME,
            placeholder=UIPlaceholders.POINT_NAME_SP,
        ),
        FieldSpec(
            field_id="branch_no",
            widget_type=WidgetType.LINEEDIT_ROW,
            label=UILabels.BRANCH_NO,
            placeholder=UIPlaceholders.BRANCH_NO,
        ),
    ],
)

POINT_NAME_ENTRY_ACTIONS_SPEC = PanelSpec(
    panel_id="point_name_entry_actions",
    fields=[
        FieldSpec(
            field_id="dialog_actions",
            widget_type=WidgetType.BUTTON_ROW,
            centered=True,
            buttons=[
                ButtonDef(
                    field_id="ok", text=UILabels.BTN_CONFIRM, style_variant="primary", on_click="ok_clicked"
                ),
                ButtonDef(field_id="cancel", text=UILabels.BTN_CANCEL, on_click="cancel_clicked"),
            ],
        ),
    ],
)

class ModelessSectionDialog(QDialog):
    def __init__(self, title: str, content_widget: QWidget, on_show=None, on_close=None, parent=None, width=None, height=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint)
        if width is not None and height is not None: self.resize(width, height)
        self._on_show = on_show
        self._on_close = on_close

        layout = QVBoxLayout(self)
        layout.setContentsMargins(UIConfig.COMMON_MARGIN_LR, UIConfig.DIALOG_MARGIN, UIConfig.COMMON_MARGIN_LR, UIConfig.DIALOG_MARGIN)
        layout.addWidget(content_widget)

    def showEvent(self, event):
        super().showEvent(event)
        if self._on_show: self._on_show()

    def closeEvent(self, event):
        self.hide()
        event.accept()
        if self._on_close: self._on_close()


class ImageDialog(QDialog):
    def __init__(self, content_widget: QWidget, on_show=None, on_close=None, parent=None, width=None, height=None):
        super().__init__(parent)
        self.setWindowTitle(UILabels.TAB_1_TITLE)
        self.resize(UIDialogSizes.IMAGE_DIALOG_WIDTH, UIDialogSizes.IMAGE_DIALOG_HEIGHT)
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint)
        if width is not None and height is not None: self.resize(width, height)
        self._on_show = on_show
        self._on_close = on_close

        layout = QHBoxLayout(self)
        layout.setContentsMargins(UIConfig.COMMON_MARGIN_LR, UIConfig.DIALOG_MARGIN, UIConfig.COMMON_MARGIN_LR, UIConfig.DIALOG_MARGIN)
        layout.setSpacing(UIConfig.DIALOG_MARGIN)

        layout.addWidget(content_widget, 1)

        preview_container = QWidget(self)
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        lbl_hint = QLabel(UILabels.PREVIEW_HINT, preview_container)
        lbl_hint.setWordWrap(True)
        preview_layout.addWidget(lbl_hint)

        self.canvas = QgsMapCanvas(preview_container)
        self.canvas.setMinimumSize(400, 300)
        preview_layout.addWidget(self.canvas, 1)

        layout.addWidget(preview_container, 1)
        self.raster_layer = None
        self.georef_tool = None

    def setup_raster(self, raster_layer, point_clicked_callback, ref_points_data=None):
        self.clean_up()
        self.raster_layer = raster_layer
        self.canvas.setLayers([self.raster_layer])
        self.canvas.setExtent(self.raster_layer.extent())
        self.canvas.refresh()
        self.georef_tool = ImageGeorefTool(self.canvas, self.raster_layer)
        if ref_points_data: self.georef_tool.set_ref_points_data(ref_points_data)
        self.canvas.setMapTool(self.georef_tool)
        self.georef_tool.point_clicked.connect(point_clicked_callback)

    def set_ref_points_data(self, ref_points_data):
        if self.georef_tool: self.georef_tool.set_ref_points_data(ref_points_data)

    def add_marker(self, pixel_x, pixel_y, name=""):
        if self.georef_tool: self.georef_tool.add_point_marker(pixel_x, pixel_y, name)

    def clear_markers(self):
        if self.georef_tool: self.georef_tool.clear_markers()

    def clean_up(self):
        if self.georef_tool:
            self.georef_tool.clean_up()
            self.georef_tool = None
        if self.canvas:
            self.canvas.setMapTool(None)
            self.canvas.setLayers([])
        self.raster_layer = None

    def showEvent(self, event):
        super().showEvent(event)
        if self._on_show: self._on_show()

    def closeEvent(self, event):
        self.hide()
        event.accept()
        if self._on_close: self._on_close()


class TwoDigitSpinBox(QSpinBox):
    def textFromValue(self, val: int) -> str: return f"{val:02d}"
    def valueFromText(self, text: str) -> int:
        try: return int(text)
        except ValueError: return 0


class GridInputDialog(QDialog):
    def __init__(self, layer_manager, existing_point=None, existing_names=None, parent=None):
        super().__init__(parent)
        self.layer_manager = layer_manager
        self.existing_point = existing_point
        self.existing_names = existing_names or []
        self.dialog_action = "cancel"
        self.result_grid_name = ""
        self.result_real_x = None
        self.result_real_y = None

        self.logic = GridInputLogic(layer_manager, self.existing_names, self)

        self.setWindowTitle(UILabels.GRID_DIALOG_TITLE)
        self.setModal(True)
        self.setMinimumWidth(UIDialogSizes.GRID_DIALOG_MIN_WIDTH)

        self._init_ui()
        UIStyleHelper.apply_theme(self)
        self._populate_initial_values()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(UIConfig.COMMON_MARGIN_LR, UIConfig.DIALOG_MARGIN, UIConfig.COMMON_MARGIN_LR, UIConfig.DIALOG_MARGIN)
        
        tier1_box = QWidget(self)
        tier1_vlayout = QVBoxLayout(tier1_box)
        header_layout = QHBoxLayout()
        for lbl in (UILabels.GRID_X_LABEL, UILabels.GRID_Y_LABEL, UILabels.GRID_SUB_LABEL):
            w = QLabel(lbl, tier1_box)
            w.setStyleSheet("font-weight: bold; font-size: 8.5pt;")
            w.setAlignment(Qt.AlignCenter)
            header_layout.addWidget(w, 1)
        tier1_vlayout.addLayout(header_layout)

        inputs_layout = QHBoxLayout()
        
        # --- グリッドデータのX座標(数値)の最小値・最大値を取得 ---
        grid_data = getattr(self.layer_manager, "grid_data", {})
        if grid_data:
            gxs = [k[0] for k in grid_data.keys()]
            min_gx = min(gxs)
            max_gx = max(gxs)
        else:
            min_gx = 1
            max_gx = max(1, getattr(self.layer_manager, "max_gx", 100))
            
        self.spin_x = UIStyleHelper.create_spinbox(min_gx, max_gx, min_gx, tier1_box)
        self.spin_x.valueChanged.connect(self._validate_and_lookup)

        self.edit_y = QLineEdit(tier1_box)
        self.edit_y.setPlaceholderText("A")
        self.edit_y.setAlignment(Qt.AlignCenter)
        if HAS_QT_REGEX:
            self.edit_y.setValidator(QRegularExpressionValidator(QRegularExpression(r"[A-Za-z]+"), self.edit_y))
        else:
            self.edit_y.setValidator(QRegExpValidator(QRegExp(r"[A-Za-z]+"), self.edit_y))
        self.edit_y.textChanged.connect(self._on_y_changed)

        self.spin_sub = TwoDigitSpinBox(tier1_box)
        self.spin_sub.setRange(0, 99)
        self.spin_sub.valueChanged.connect(self._validate_and_lookup)

        inputs_layout.addWidget(self.spin_x, 1)
        inputs_layout.addWidget(self.edit_y, 1)
        inputs_layout.addWidget(self.spin_sub, 1)
        tier1_vlayout.addLayout(inputs_layout)
        layout.addWidget(tier1_box)

        self.btn_delete_point = QPushButton(UILabels.BTN_DELETE_SELECTED_POINT, self)
        self.btn_delete_point.setStyleSheet("background-color: #D32F2F; color: #FFFFFF; font-weight: bold; border-radius: 4px;")
        self.btn_delete_point.clicked.connect(self._on_delete_point_clicked)
        if not self.existing_point: self.btn_delete_point.hide()
        layout.addWidget(self.btn_delete_point)

        actions_panel = CoreUIBuilder.build(GRID_INPUT_ACTIONS_SPEC, parent=self)
        self.btn_confirm = actions_panel.get("confirm")
        actions_panel.bind("confirm_clicked", self._on_confirm_clicked)
        actions_panel.bind("cancel_clicked", self.reject)
        layout.addWidget(actions_panel.widget)

        self.panel_status, self.lbl_status = UIStyleHelper.create_status_panel("", "info", self)
        layout.addWidget(self.panel_status)

    def _populate_initial_values(self):
        if self.existing_point:
            name = str(self.existing_point.get("name", "")).strip()
            m = re.match(r"^(\d+)-?([A-Za-z]+)-?(\d{1,2})$", name)
            if m:
                self.spin_x.setValue(int(m.group(1)))
                self.edit_y.setText(m.group(2).upper())
                self.spin_sub.setValue(int(m.group(3)))
        else:
            default_y = "A"
            unique_gy = getattr(self.layer_manager, "unique_gy", set())
            if unique_gy: default_y = sorted(list(unique_gy))[0]
            self.edit_y.setText(default_y)
            
            # --- 初期値としてX座標の最小値をセット ---
            grid_data = getattr(self.layer_manager, "grid_data", {})
            if grid_data:
                gxs = [k[0] for k in grid_data.keys()]
                self.spin_x.setValue(min(gxs))
                
        self._validate_and_lookup()

    @pyqtSlot(str)
    def _on_y_changed(self, text):
        upper = text.upper()
        if upper != text:
            pos = self.edit_y.cursorPosition()
            self.edit_y.setText(upper)
            self.edit_y.setCursorPosition(pos)
        self._validate_and_lookup()

    def _validate_and_lookup(self):
        gx = self.spin_x.value()
        gy = self.edit_y.text().strip().upper()
        sub_grid = self.spin_sub.value()
        
        is_valid, msg, status, real_x, real_y = self.logic.validate_and_lookup(gx, gy, sub_grid)
        
        UIStyleHelper.update_status_panel(self.panel_status, self.lbl_status, msg, status)
        self.btn_confirm.setEnabled(is_valid)
        
        if is_valid:
            self.result_grid_name = f"{gx}-{gy}-{sub_grid:02d}"
            self.result_real_x = real_x
            self.result_real_y = real_y

    def _on_delete_point_clicked(self):
        if QMessageBox.question(self, UIMessages.MSG_CONFIRM_TITLE, UIMessages.MSG_CONFIRM_DELETE_REF, QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self.dialog_action = "delete"
            self.accept()

    def _on_confirm_clicked(self):
        self.dialog_action = "confirm"
        self.accept()


class FeatureManageDialog(QDialog):
    def __init__(self, parent=None, feature_colors=None, on_update_callback=None, initial_feature=None):
        super().__init__(parent)
        self.feature_colors = dict(feature_colors) if feature_colors else {}
        self.on_update_callback = on_update_callback
        self.result_text = ""
        self.result_feature_name = ""
        self.result_color = "#FF5722"
        self.current_selected_mode = "new"
        self.current_selected_feature = ""
        self.current_color = "#FF5722"

        self.logic = FeatureManageLogic(self.feature_colors, self)

        self.setWindowTitle(UILabels.FEATURE_MANAGE_DIALOG_TITLE)
        self.setModal(True)
        self.resize(360, 440)
        
        self._init_ui()
        self._populate_table(select_feature=initial_feature)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        self.lbl_header = QLabel("遺構名作成・編集", self)
        f = self.lbl_header.font()
        f.setBold(True)
        self.lbl_header.setFont(f)
        layout.addWidget(self.lbl_header)

        self.table_features = QTableWidget(self)
        self.table_features.setColumnCount(1)
        self.table_features.setHorizontalHeaderLabels(["遺構名リスト"])
        self.table_features.horizontalHeader().setStretchLastSection(True)
        self.table_features.verticalHeader().setVisible(False)
        self.table_features.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_features.setSelectionMode(QTableWidget.SingleSelection)
        self.table_features.itemSelectionChanged.connect(self._on_table_selection_changed)
        layout.addWidget(self.table_features)

        self.edit_name = QLineEdit(self)
        self.edit_name.setPlaceholderText(UIPlaceholders.NEW_FEATURE)
        if HAS_QT_REGEX:
            self.edit_name.setValidator(QRegularExpressionValidator(QRegularExpression(r"^[A-Za-z0-9_-]+$"), self.edit_name))
        else:
            self.edit_name.setValidator(QRegExpValidator(QRegExp(r"^[A-Za-z0-9_-]+$"), self.edit_name))
        layout.addWidget(UIStyleHelper.build_flex_row(QLabel("遺構名:", self), [(self.edit_name, 1)], (3, 7)))

        self.btn_color = QPushButton("カラー選択", self)
        self.btn_color.clicked.connect(self._on_pick_color)
        layout.addWidget(UIStyleHelper.build_flex_row(QLabel("カラー:", self), [(self.btn_color, 1)], (3, 7)))

        self.panel_status, self.lbl_status = UIStyleHelper.create_status_panel("", "info", self)
        layout.addWidget(self.panel_status)

        actions_layout = QHBoxLayout()
        self.btn_confirm = QPushButton(UILabels.BTN_CONFIRM, self)
        UIStyleHelper.set_primary_button(self.btn_confirm)
        self.btn_confirm.clicked.connect(self._on_confirm_clicked)
        self.btn_cancel = QPushButton(UILabels.BTN_CANCEL, self)
        self.btn_cancel.clicked.connect(self.reject)
        actions_layout.addStretch(1)
        actions_layout.addWidget(self.btn_confirm)
        actions_layout.addWidget(self.btn_cancel)
        actions_layout.addStretch(1)
        layout.addLayout(actions_layout)

        self.edit_name.textChanged.connect(self._on_realtime_validate)

    def _populate_table(self, select_feature=None):
        self.table_features.blockSignals(True)
        try:
            self.table_features.setRowCount(0)
            self.table_features.insertRow(0)
            item_new = QTableWidgetItem("新規作成")
            item_new.setFlags(item_new.flags() & ~Qt.ItemIsEditable)
            self.table_features.setItem(0, 0, item_new)

            target_row = 0
            for i, feat_name in enumerate(sorted(self.feature_colors.keys()), start=1):
                self.table_features.insertRow(i)
                item = QTableWidgetItem(feat_name)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table_features.setItem(i, 0, item)
                if select_feature == feat_name: target_row = i
            self.table_features.setCurrentCell(target_row, 0)
        finally:
            self.table_features.blockSignals(False)
        self._on_table_selection_changed()

    def _update_color_button(self):
        h = self.current_color or "#FF5722"
        self.btn_color.setStyleSheet(f"background-color: {h}; color: #FFFFFF; font-weight: bold; border-radius: 4px; padding: 4px;")
        self.btn_color.setText(h)

    def _on_pick_color(self):
        c = QColorDialog.getColor(QColor(self.current_color or "#FF5722"), self, UIDialogTitles.COLOR_PICKER)
        if c.isValid():
            self.current_color = c.name()
            self._update_color_button()
            self._on_realtime_validate()

    def _on_table_selection_changed(self):
        row = self.table_features.currentRow()
        if row <= 0:
            self.current_selected_mode = "new"
            self.current_selected_feature = ""
            self.edit_name.blockSignals(True)
            self.edit_name.clear()
            self.edit_name.blockSignals(False)
            self.current_color = "#FF5722"
        else:
            item = self.table_features.item(row, 0)
            feat_name = item.text() if item else ""
            self.current_selected_mode = "existing"
            self.current_selected_feature = feat_name
            self.edit_name.blockSignals(True)
            self.edit_name.setText(feat_name)
            self.edit_name.blockSignals(False)
            self.current_color = self.feature_colors.get(feat_name, "#FF5722")
            
        self._update_color_button()
        self._on_realtime_validate()

    def _on_realtime_validate(self, *args):
        text = self.edit_name.text().strip()
        is_valid, msg, status = self.logic.validate_feature_name(text, self.current_selected_mode, self.current_selected_feature)
        UIStyleHelper.update_status_panel(self.panel_status, self.lbl_status, msg, status)
        self.btn_confirm.setEnabled(is_valid)

    def _on_confirm_clicked(self):
        text = self.edit_name.text().strip()
        if self.current_selected_mode == "new":
            self.result_text = text
            self.result_feature_name = text
            self.result_color = self.current_color
            self.accept()
        else:
            old_name = self.current_selected_feature
            new_color = self.current_color
            if self.on_update_callback:
                self.on_update_callback(old_name, text, new_color)
            if old_name in self.feature_colors: del self.feature_colors[old_name]
            self.feature_colors[text] = new_color
            self.current_selected_feature = text
            self._populate_table(select_feature=text)

FeatureCreateDialog = FeatureManageDialog


class PointNameEntryDialog(QDialog):
    def __init__(self, point_layer, excavation_type, feature_name, drawing_name="", is_sp_attribute=False, parent=None, initial_point_name=""):
        super().__init__(parent)
        self.is_sp_attribute = is_sp_attribute
        self.result_point_name = ""
        self.result_branch_no = ""

        self.logic = PointNameEntryLogic(point_layer, excavation_type, feature_name, drawing_name, is_sp_attribute, self)

        self.setWindowTitle(UILabels.POINT_NAME_ENTRY_DIALOG_TITLE)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(UIConfig.COMMON_MARGIN_LR, UIConfig.DIALOG_MARGIN, UIConfig.COMMON_MARGIN_LR, UIConfig.DIALOG_MARGIN)
        
        self.input_panel = CoreUIBuilder.build(POINT_NAME_ENTRY_SPEC, parent=self)
        self.spin_point_name = self.input_panel.get("point_name")
        self.edit_point_name_sp = self.input_panel.get("point_name_sp")
        self.edit_branch_no = self.input_panel.get("branch_no")

        if self.is_sp_attribute:
            self.edit_point_name_sp.setValidator(QRegExpValidator(QRegExp(r"^[A-Za-z0-9_-]+$"), self.edit_point_name_sp))
            if initial_point_name: self.edit_point_name_sp.setText(initial_point_name)
            self.input_panel.get_row("point_name").hide()
            self.edit_point_name_sp.textChanged.connect(self._on_realtime_validate)
        else:
            if initial_point_name and initial_point_name.isdigit():
                self.spin_point_name.setValue(int(initial_point_name))
            self.input_panel.get_row("point_name_sp").hide()
            self.spin_point_name.valueChanged.connect(self._on_realtime_validate)

        self.edit_branch_no.textChanged.connect(self._on_realtime_validate)
        layout.addWidget(self.input_panel.widget)

        self.panel_status, self.lbl_status = UIStyleHelper.create_status_panel("", "info", self)
        layout.addWidget(self.panel_status)

        actions_panel = CoreUIBuilder.build(POINT_NAME_ENTRY_ACTIONS_SPEC, parent=self)
        self.btn_ok = actions_panel.get("ok")
        actions_panel.bind("ok_clicked", self._on_ok_clicked)
        actions_panel.bind("cancel_clicked", self.reject)
        layout.addWidget(actions_panel.widget)

        self._on_realtime_validate()

    def _get_point_name_text(self):
        return self.edit_point_name_sp.text().strip() if self.is_sp_attribute else str(self.spin_point_name.value())

    def _on_realtime_validate(self, *args):
        pname = self._get_point_name_text()
        branch = self.edit_branch_no.text().strip()
        
        is_valid, msg = self.logic.validate_inputs(pname, branch)
        if not is_valid:
            UIStyleHelper.update_status_panel(self.panel_status, self.lbl_status, msg, "error")
            self.btn_ok.setEnabled(False)
        else:
            UIStyleHelper.update_status_panel(self.panel_status, self.lbl_status, "", "info")
            self.btn_ok.setEnabled(True)

    def _on_ok_clicked(self):
        pname = self._get_point_name_text()
        branch = self.edit_branch_no.text().strip()
        is_valid, msg = self.logic.validate_inputs(pname, branch)
        
        if is_valid:
            self.result_point_name = pname
            self.result_branch_no = branch
            self.accept()
        else:
            UIStyleHelper.update_status_panel(self.panel_status, self.lbl_status, msg, "error")

    def get_values(self):
        return self.result_point_name, self.result_branch_no

class DisplayFilterDialog(QDialog):
    """Modal dialog for configuring display filters (FEAT-05).

    Allows filtering points and labels by:
    - Attribute (S, P, C, SP)
    - Excavation type (遺構, グリッド)
    - Feature names (QListWidget with user-checkable items)
    - Target drawing scope (選択図面 / 全図面)
    """

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        feature_names: Optional[List[str]] = None,
        initial_filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(UILabels.FILTER_DIALOG_TITLE)
        self.setModal(True)
        self.resize(320, 460)

        self._all_feature_names: List[str] = list(feature_names or [])
        self._init_ui()
        UIStyleHelper.apply_theme(self)

        if initial_filters:
            self.set_filters(initial_filters)
        else:
            default_filters = {
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
                "feature_names": list(self._all_feature_names),
                "target_drawing": UILabels.FILTER_DRAWING_SELECTED,
            }
            self.set_filters(default_filters)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            UIConfig.COMMON_MARGIN_LR,
            UIConfig.DIALOG_MARGIN,
            UIConfig.COMMON_MARGIN_LR,
            UIConfig.DIALOG_MARGIN,
        )
        layout.setSpacing(0)

        # 1. 属性 (Attributes)
        layout.addWidget(UIStyleHelper.build_separator(self, title_text=UILabels.FILTER_ATTRIBUTES))
        container_attr = QWidget(self)
        layout_attr = QHBoxLayout(container_attr)
        layout_attr.setContentsMargins(0, 0, 0, 0)
        layout_attr.setSpacing(8)

        self.cb_attr_s = QCheckBox(AttributeType.S.value, container_attr)
        self.cb_attr_p = QCheckBox(AttributeType.P.value, container_attr)
        self.cb_attr_c = QCheckBox(AttributeType.C.value, container_attr)
        self.cb_attr_sp = QCheckBox(AttributeType.SP.value, container_attr)

        layout_attr.addWidget(self.cb_attr_s)
        layout_attr.addWidget(self.cb_attr_p)
        layout_attr.addWidget(self.cb_attr_c)
        layout_attr.addWidget(self.cb_attr_sp)
        layout_attr.addStretch(1)
        layout.addWidget(container_attr)

        # 2. 出土形態 (Excavation Types)
        layout.addWidget(UIStyleHelper.build_separator(self, title_text=UILabels.FILTER_EXCAVATION))
        container_excav = QWidget(self)
        layout_excav = QHBoxLayout(container_excav)
        layout_excav.setContentsMargins(0, 0, 0, 0)
        layout_excav.setSpacing(8)

        self.cb_excav_feat = QCheckBox(ExcavationType.FEATURE.value, container_excav)
        self.cb_excav_grid = QCheckBox(ExcavationType.GRID.value, container_excav)

        layout_excav.addWidget(self.cb_excav_feat)
        layout_excav.addWidget(self.cb_excav_grid)
        layout_excav.addStretch(1)
        layout.addWidget(container_excav)

        # 3. 遺構名 (Feature Names)
        layout.addWidget(UIStyleHelper.build_separator(self, title_text=UILabels.FILTER_FEATURE))
        container_feat = QWidget(self)
        layout_feat = QVBoxLayout(container_feat)
        layout_feat.setContentsMargins(0, 0, 0, 0)
        layout_feat.setSpacing(4)

        self.list_features = QListWidget(container_feat)
        self.list_features.setSelectionMode(QListWidget.NoSelection)
        self._populate_feature_list(self._all_feature_names)
        layout_feat.addWidget(self.list_features)
        layout.addWidget(container_feat)

        # 4. 対象図面 (Target Drawing)
        layout.addWidget(UIStyleHelper.build_separator(self, title_text=UILabels.FILTER_TARGET_DRAWING))
        container_drawing = QWidget(self)
        layout_drawing = QHBoxLayout(container_drawing)
        layout_drawing.setContentsMargins(0, 0, 0, 0)
        layout_drawing.setSpacing(16)

        self.radio_drawing_selected = QRadioButton(UILabels.FILTER_DRAWING_SELECTED, container_drawing)
        self.radio_drawing_all = QRadioButton(UILabels.FILTER_DRAWING_ALL, container_drawing)
        self.drawing_btn_group = QButtonGroup(container_drawing)
        self.drawing_btn_group.addButton(self.radio_drawing_selected)
        self.drawing_btn_group.addButton(self.radio_drawing_all)
        self.radio_drawing_selected.setChecked(True)

        layout_drawing.addWidget(self.radio_drawing_selected)
        layout_drawing.addWidget(self.radio_drawing_all)
        layout_drawing.addStretch(1)
        layout.addWidget(container_drawing)

        layout.addSpacing(UIConfig.SEPARATOR_MARGIN)

        # 5. アクションボタン (すべてクリア・確定・キャンセル)
        row_actions = QWidget(self)
        actions_layout = QHBoxLayout(row_actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(8)

        self.btn_clear_all = QPushButton(UILabels.BTN_CLEAR_ALL, row_actions)
        self.btn_clear_all.clicked.connect(self._on_clear_all_clicked)
        actions_layout.addWidget(self.btn_clear_all)

        actions_layout.addStretch(1)

        self.btn_confirm = QPushButton(UILabels.BTN_CONFIRM, row_actions)
        UIStyleHelper.set_primary_button(self.btn_confirm)
        self.btn_confirm.clicked.connect(self.accept)
        actions_layout.addWidget(self.btn_confirm)

        self.btn_cancel = QPushButton(UILabels.BTN_CANCEL, row_actions)
        self.btn_cancel.clicked.connect(self.reject)
        actions_layout.addWidget(self.btn_cancel)

        layout.addWidget(row_actions)

    def _on_clear_all_clicked(self) -> None:
        """Reset all filters to default select all state."""
        self.cb_attr_s.setChecked(True)
        self.cb_attr_p.setChecked(True)
        self.cb_attr_c.setChecked(True)
        self.cb_attr_sp.setChecked(True)
        
        self.cb_excav_feat.setChecked(True)
        self.cb_excav_grid.setChecked(True)
        
        for i in range(self.list_features.count()):
            self.list_features.item(i).setCheckState(Qt.Checked)
            
        self.radio_drawing_selected.setChecked(True)

    def _populate_feature_list(self, feature_names: List[str]) -> None:
        self.list_features.clear()
        for name in sorted(feature_names):
            item = QListWidgetItem(name, self.list_features)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)

    def set_feature_names(self, feature_names: List[str]) -> None:
        """Update the list of selectable features."""
        self._all_feature_names = list(feature_names)
        self._populate_feature_list(self._all_feature_names)

    def set_filters(self, filters: Dict[str, Any]) -> None:
        """Apply filter configuration dictionary to UI controls."""
        attrs = filters.get("attributes")
        if attrs is not None:
            attr_set = set(attrs)
            self.cb_attr_s.setChecked(AttributeType.S.value in attr_set)
            self.cb_attr_p.setChecked(AttributeType.P.value in attr_set)
            self.cb_attr_c.setChecked(AttributeType.C.value in attr_set)
            self.cb_attr_sp.setChecked(AttributeType.SP.value in attr_set)
        else:
            self.cb_attr_s.setChecked(True)
            self.cb_attr_p.setChecked(True)
            self.cb_attr_c.setChecked(True)
            self.cb_attr_sp.setChecked(True)

        excs = filters.get("excavation_types")
        if excs is not None:
            exc_set = set(excs)
            self.cb_excav_feat.setChecked(ExcavationType.FEATURE.value in exc_set)
            self.cb_excav_grid.setChecked(ExcavationType.GRID.value in exc_set)
        else:
            self.cb_excav_feat.setChecked(True)
            self.cb_excav_grid.setChecked(True)

        target_features = filters.get("feature_names")
        if target_features is not None:
            feat_set = set(target_features)
            for i in range(self.list_features.count()):
                item = self.list_features.item(i)
                item.setCheckState(Qt.Checked if item.text() in feat_set else Qt.Unchecked)
        else:
            for i in range(self.list_features.count()):
                self.list_features.item(i).setCheckState(Qt.Checked)

        target_drawing = filters.get("target_drawing", UILabels.FILTER_DRAWING_SELECTED)
        if target_drawing == UILabels.FILTER_DRAWING_ALL:
            self.radio_drawing_all.setChecked(True)
        else:
            self.radio_drawing_selected.setChecked(True)

    def get_filters(self) -> Dict[str, Any]:
        """Extract current filter configuration dictionary from UI controls."""
        attributes: List[str] = []
        if self.cb_attr_s.isChecked():
            attributes.append(AttributeType.S.value)
        if self.cb_attr_p.isChecked():
            attributes.append(AttributeType.P.value)
        if self.cb_attr_c.isChecked():
            attributes.append(AttributeType.C.value)
        if self.cb_attr_sp.isChecked():
            attributes.append(AttributeType.SP.value)

        excavation_types: List[str] = []
        if self.cb_excav_feat.isChecked():
            excavation_types.append(ExcavationType.FEATURE.value)
        if self.cb_excav_grid.isChecked():
            excavation_types.append(ExcavationType.GRID.value)

        feature_names: List[str] = []
        for i in range(self.list_features.count()):
            item = self.list_features.item(i)
            if item.checkState() == Qt.Checked:
                feature_names.append(item.text())

        target_drawing = (
            UILabels.FILTER_DRAWING_ALL
            if self.radio_drawing_all.isChecked()
            else UILabels.FILTER_DRAWING_SELECTED
        )

        return {
            "attributes": attributes,
            "excavation_types": excavation_types,
            "feature_names": feature_names,
            "target_drawing": target_drawing,
        }



class PointEditDialog(QDialog):
    """FEAT-01: Modal dialog for Point Editing"""
    def __init__(self, layer_manager, feature_data, drawing_names, parent=None):
        super().__init__(parent)
        self.layer_manager = layer_manager
        self.feature_data = dict(feature_data)
        self.drawing_names = drawing_names
        self.dialog_action = "cancel"  # "confirm", "delete", "cancel"
        
        self.setWindowTitle("点情報編集")
        self.setModal(True)
        self.setMinimumWidth(360)
        
        self._init_ui()
        UIStyleHelper.apply_theme(self)
        self._populate_initial_values()
        
    def _init_ui(self):
        layout = QVBoxLayout(self)
        
        # Status panel
        self.panel_status, self.lbl_status = UIStyleHelper.create_status_panel("入力値で更新", "info", self)
        layout.addWidget(self.panel_status)
        
        # Form
        form_layout = QVBoxLayout()
        
        # Attribute
        self.combo_attribute = QComboBox(self)
        for value in UILabels.ATTRIBUTE_OPTIONS:
            self.combo_attribute.addItem(UILabels.ATTRIBUTE_DISPLAY_MAP.get(value, value), value)
        self.combo_attribute.currentIndexChanged.connect(self._on_category_changed)
        form_layout.addWidget(UIStyleHelper.build_flex_row(QLabel(UILabels.ATTRIBUTE_CODE, self), [(self.combo_attribute, 1)], (3, 7)))
        
        # Excavation Type
        self.combo_excavation_type = QComboBox(self)
        self.combo_excavation_type.addItems(UILabels.EXCAVATION_OPTIONS)
        self.combo_excavation_type.currentIndexChanged.connect(self._on_excavation_type_changed)
        form_layout.addWidget(UIStyleHelper.build_flex_row(QLabel(UILabels.EXCAVATION_TYPE, self), [(self.combo_excavation_type, 1)], (3, 7)))
        
        # Feature Name
        self.combo_feature_name = QComboBox(self)
        self.combo_feature_name.addItem(UILabels.UNREGISTERED)
        self.combo_feature_name.currentTextChanged.connect(self._validate)
        self.row_feature_selector = UIStyleHelper.build_flex_row(QLabel(UILabels.FEATURE_SELECTOR, self), [(self.combo_feature_name, 1)], (3, 7))
        form_layout.addWidget(self.row_feature_selector)
        
        # Point Name
        self.edit_point_name = UIStyleHelper.create_spinbox(1, 999999, 1, self)
        self.edit_point_name.valueChanged.connect(self._validate)
        
        self.edit_point_name_sp = QLineEdit(self)
        self.edit_point_name_sp.setPlaceholderText(UIPlaceholders.POINT_NAME_SP)
        if HAS_QT_REGEX:
            self.edit_point_name_sp.setValidator(QRegularExpressionValidator(QRegularExpression(r"^[A-Za-z0-9_-]+$"), self.edit_point_name_sp))
        else:
            self.edit_point_name_sp.setValidator(QRegExpValidator(QRegExp(r"^[A-Za-z0-9_-]+$"), self.edit_point_name_sp))
        self.edit_point_name_sp.hide()
        self.edit_point_name_sp.textChanged.connect(self._validate)
        
        form_layout.addWidget(UIStyleHelper.build_flex_row(QLabel(UILabels.POINT_NAME, self), [(self.edit_point_name, 1), (self.edit_point_name_sp, 1)], (3, 7)))
        
        # Branch No
        self.edit_branch_no = QLineEdit(self)
        self.edit_branch_no.setPlaceholderText(UIPlaceholders.BRANCH_NO)
        self.edit_branch_no.textChanged.connect(self._validate)
        form_layout.addWidget(UIStyleHelper.build_flex_row(QLabel(UILabels.BRANCH_NO, self), [(self.edit_branch_no, 1)], (3, 7)))
        
        # Target Drawing
        self.combo_drawing_name = QComboBox(self)
        self.combo_drawing_name.addItem(UILabels.DRAWING_UNSPECIFIED)
        for name in self.drawing_names:
            if name != UILabels.DRAWING_UNSPECIFIED:
                self.combo_drawing_name.addItem(name)
        form_layout.addWidget(UIStyleHelper.build_flex_row(QLabel("対象図面", self), [(self.combo_drawing_name, 1)], (3, 7)))
        
        layout.addLayout(form_layout)
        
        # Actions
        actions_layout = QHBoxLayout()
        self.btn_delete = QPushButton(UILabels.BTN_DELETE_POINT, self)
        self.btn_delete.setStyleSheet("background-color: #D32F2F; color: #FFFFFF; font-weight: bold; border-radius: 4px;")
        self.btn_delete.clicked.connect(self._on_delete_clicked)
        
        self.btn_confirm = QPushButton(UILabels.BTN_CONFIRM, self)
        UIStyleHelper.set_primary_button(self.btn_confirm)
        self.btn_confirm.clicked.connect(self._on_confirm_clicked)
        
        self.btn_cancel = QPushButton(UILabels.BTN_CANCEL, self)
        self.btn_cancel.clicked.connect(self.reject)
        
        # For double-confirmation of delete
        self.btn_confirm_delete = QPushButton("削除を実行", self)
        self.btn_confirm_delete.setStyleSheet("background-color: #D32F2F; color: #FFFFFF; font-weight: bold; border-radius: 4px;")
        self.btn_confirm_delete.hide()
        self.btn_confirm_delete.clicked.connect(self._on_confirm_delete_clicked)
        
        actions_layout.addWidget(self.btn_delete)
        actions_layout.addWidget(self.btn_confirm_delete)
        actions_layout.addStretch()
        actions_layout.addWidget(self.btn_confirm)
        actions_layout.addWidget(self.btn_cancel)
        layout.addLayout(actions_layout)
        
    def _populate_initial_values(self):
        # drawing name
        d_name = self.feature_data.get("drawing_name", "").strip()
        target_name = d_name if d_name else UILabels.DRAWING_UNSPECIFIED
        idx = self.combo_drawing_name.findText(target_name)
        if idx >= 0: self.combo_drawing_name.setCurrentIndex(idx)
        
        # Feature names
        if self.layer_manager and hasattr(self.layer_manager, "point_layer"):
            layer = self.layer_manager.point_layer
            if layer and layer.isValid():
                idx = layer.fields().indexOf("feature_name")
                if idx >= 0:
                    names = set(layer.uniqueValues(idx))
                    for name in sorted(names):
                        if str(name).strip() and str(name).strip() not in (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成")):
                            self.combo_feature_name.addItem(str(name).strip())
        
        ex_type = str(self.feature_data.get("excavation_type") or ExcavationType.GRID.value)
        self.combo_excavation_type.setCurrentText(ex_type)
        
        if ex_type == ExcavationType.FEATURE.value:
            feat_name = str(self.feature_data.get("feature_name") or "")
            if feat_name and self.combo_feature_name.findText(feat_name) < 0:
                self.combo_feature_name.addItem(feat_name)
            self.combo_feature_name.setCurrentText(feat_name if feat_name else UILabels.UNREGISTERED)
            
        attr_type = str(self.feature_data.get("attribute_type") or AttributeType.S.value)
        idx = self.combo_attribute.findData(attr_type)
        if idx >= 0: self.combo_attribute.setCurrentIndex(idx)
        
        pname_raw = str(self.feature_data.get("point_name") or "")
        if attr_type == AttributeType.SP.value:
            self.edit_point_name_sp.setText(pname_raw)
        else:
            try: p_val = int(pname_raw or 1)
            except ValueError: p_val = 1
            self.edit_point_name.setValue(p_val)
            
        self.edit_branch_no.setText(str(self.feature_data.get("branch_no") or ""))
        
        self._on_category_changed()
        self._on_excavation_type_changed()
        self._validate()

    def _on_category_changed(self, *args):
        is_sp = (self.combo_attribute.currentData() == AttributeType.SP.value)
        self.edit_point_name.setVisible(not is_sp)
        self.edit_point_name_sp.setVisible(is_sp)
        self._validate()
        
    def _on_excavation_type_changed(self, *args):
        is_feature = (self.combo_excavation_type.currentText() == ExcavationType.FEATURE.value)
        self.row_feature_selector.setVisible(is_feature)
        self._validate()

    def _get_current_point_name(self) -> str:
        if self.combo_attribute.currentData() == AttributeType.SP.value:
            return self.edit_point_name_sp.text().strip()
        else:
            return str(self.edit_point_name.value())

    def _validate(self, *args):
        if self.btn_confirm_delete.isVisible():
            return
            
        point_name = self._get_current_point_name()
        branch_no = self.edit_branch_no.text().strip()
        ex_type = self.combo_excavation_type.currentText()
        feat_name = self.combo_feature_name.currentText().strip()
        if feat_name in (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成")):
            feat_name = ""
        drawing_name = self.combo_drawing_name.currentText().strip()
        if drawing_name == UILabels.DRAWING_UNSPECIFIED:
            drawing_name = ""
            
        has_error = False
        msg = "入力値で更新"
        status = "info"
        
        if ex_type == ExcavationType.FEATURE.value and not feat_name:
            has_error = True
            msg = UILabels.STATUS_ERR_FEATURE_REQUIRED
            status = "error"
            self.combo_feature_name.setStyleSheet("border: 1px solid red;")
        else:
            self.combo_feature_name.setStyleSheet("")
            
        if not has_error:
            # duplicate check
            if self.layer_manager and hasattr(self.layer_manager, "point_layer"):
                layer = self.layer_manager.point_layer
                if layer and layer.isValid():
                    from ..logic.core import check_point_duplicate
                    dup = check_point_duplicate(
                        layer, ex_type, feat_name,
                        point_name, branch_no, drawing_name, self.feature_data.get("feature_id")
                    )
                    if dup:
                        has_error = True
                        msg = UILabels.STATUS_ERR_DUPLICATE
                        status = "error"
                        if self.combo_attribute.currentData() == AttributeType.SP.value:
                            self.edit_point_name_sp.setStyleSheet("border: 1px solid red;")
                        else:
                            self.edit_point_name.setStyleSheet("border: 1px solid red;")
                        self.edit_branch_no.setStyleSheet("border: 1px solid red;")
                    else:
                        self.edit_point_name_sp.setStyleSheet("")
                        self.edit_point_name.setStyleSheet("")
                        self.edit_branch_no.setStyleSheet("")
        
        UIStyleHelper.update_status_panel(self.panel_status, self.lbl_status, msg, status)
        self.btn_confirm.setEnabled(not has_error)
        
    def _on_delete_clicked(self):
        self.btn_delete.hide()
        self.btn_confirm.hide()
        self.btn_confirm_delete.show()
        UIStyleHelper.update_status_panel(self.panel_status, self.lbl_status, "削除してよろしいですか？", "warning")
        
    def _on_confirm_delete_clicked(self):
        self.dialog_action = "delete"
        self.accept()
        
    def _on_confirm_clicked(self):
        self.dialog_action = "confirm"
        self.feature_data["attribute_type"] = self.combo_attribute.currentData()
        self.feature_data["excavation_type"] = self.combo_excavation_type.currentText()
        feat_name = self.combo_feature_name.currentText().strip()
        if feat_name in (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成")):
            feat_name = ""
        self.feature_data["feature_name"] = feat_name if self.feature_data["excavation_type"] == ExcavationType.FEATURE.value else ""
        self.feature_data["point_name"] = self._get_current_point_name()
        self.feature_data["branch_no"] = self.edit_branch_no.text().strip()
        d_name = self.combo_drawing_name.currentText().strip()
        if d_name == UILabels.DRAWING_UNSPECIFIED: d_name = ""
        self.feature_data["drawing_name"] = d_name
        self.accept()