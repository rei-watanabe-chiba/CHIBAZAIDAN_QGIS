"""
/***************************************************************************
 PointerGeocoding Plugin - Main Operation Dock Panel
 ***************************************************************************/
"""
# 【変更不可侵の絶対的ルール】 測量座標系（X軸=南北, Y軸=東西）を採用。QGISキャンバス上のX座標(東西)はSurvey Y、Y座標(南北)はSurvey Xに対応する。

import os
from typing import Optional, Dict, Any, List, Tuple

from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsPointXY,
    Qgis,
)
from qgis.gui import (
    QgisInterface,
    QgsMapCanvas,
)
from qgis.PyQt.QtCore import Qt, QPoint
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QDockWidget,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTableWidgetItem,
    QScrollArea,
    QFrame,
    QLabel,
    QTableWidget,
    QDialog,
    QApplication,
)

from ..canvas.map_tool import CanvasDigitizingTool, ImageGeorefTool
from .style import UIStyleHelper
from .constants import UIConfig, UILabels, UIMessages, UIDialogSizes, UIPlaceholders
from .dialogs import ImageDialog, ModelessSectionDialog, FeatureManageDialog, PointNameEntryDialog, PointEditDialog, DisplayFilterDialog
from .main_image import create_tab1_ui
from .main_settings import create_tab3_ui
from .main_output import create_tab4_ui

# --- 新設・同元化する状態管理とUI基盤 ---
from .core.state import (
    UIStateStore, ResetSelectionAction, SetFeatureCacheAction,
    SelectDrawingAction, SetDisplayFiltersAction, ChangeTab2ModeAction,
    ChangeAutonumModeAction, SetFocusModeAction, UpdateDigitizingInputsAction,
    SetPointInfoErrorAction, CanvasClickAction,
    AddManualDigitizedPointAction, DeletePointAction, UpdatePointAttributesAction,
    UpdateFeatureCategoryAction, ChangeRefPointVisibilityAction, ChangeDrawingVisibilityAction
)
from .core.field_spec import ButtonDef, FieldSpec, PanelSpec, WidgetType
from .core.builder import CoreUIBuilder
from ..uilogic.dispatcher import EventDispatcher

# --- Controller (ロジック層) のインポート ---
from ..uilogic.digitizing_logic import DigitizingLogic
from ..uilogic.filter_logic import FilterLogic
from ..logic.core import AttributeType, ExcavationType, safe_get_str


# =========================================================================
# CoreUI Schemas for Tab 2
# =========================================================================

TAB2_MODE_TOGGLE_SPEC = PanelSpec(
    panel_id="tab2_mode_toggle",
    fields=[
        FieldSpec(
            field_id="tab2_mode",
            widget_type=WidgetType.SEGMENTED_TOGGLE,
            options=[UILabels.TAB2_MODE_NEW, UILabels.TAB2_MODE_EDIT],
            default_index=0,
            main_ratio=(0, 10),
            on_change="mode_changed",
        ),
    ],
)

TAB2_POINT_INFO_SPEC = PanelSpec(
    panel_id="tab2_point_info",
    spacing=UIConfig.PANEL_MARGIN,
    fields=[
        FieldSpec(field_id="point_info_summary", widget_type=WidgetType.INFO_PANEL, info_lines=[]),
        FieldSpec(field_id="point_name", widget_type=WidgetType.SPINBOX_ROW, label=UILabels.POINT_NAME, spin_min=1, spin_max=999999, spin_default=1, on_change="point_identity_changed"),
        FieldSpec(field_id="point_name_sp", widget_type=WidgetType.LINEEDIT_ROW, label=UILabels.POINT_NAME, placeholder=UIPlaceholders.POINT_NAME_SP, on_change="point_identity_changed", visible=False),
        FieldSpec(field_id="branch_no", widget_type=WidgetType.LINEEDIT_ROW, label=UILabels.BRANCH_NO, placeholder=UIPlaceholders.BRANCH_NO, on_change="branch_text_changed"),
        FieldSpec(field_id="autonum_mode", widget_type=WidgetType.SEGMENTED_TOGGLE, options=[UILabels.AUTONUM_MODE_AUTO, UILabels.AUTONUM_MODE_RELEASE], default_index=0, on_change="autonum_mode_changed"),
    ],
)

TAB2_ATTRIBUTE_SPEC = PanelSpec(
    panel_id="tab2_attribute",
    spacing=UIConfig.PANEL_MARGIN,
    fields=[
        FieldSpec(field_id="attribute_code", widget_type=WidgetType.COMBOBOX_ROW, label=UILabels.ATTRIBUTE_CODE, on_change="category_changed"),
        FieldSpec(field_id="excavation_type", widget_type=WidgetType.COMBOBOX_ROW, label=UILabels.EXCAVATION_TYPE, on_change="excavation_type_changed"),
        FieldSpec(field_id="feature_name", widget_type=WidgetType.COMBOBOX_ROW, label=UILabels.FEATURE_SELECTOR, on_change="feature_combo_changed", visible=False),
        FieldSpec(field_id="feature_actions", widget_type=WidgetType.BUTTON_ROW, centered=False, visible=False, buttons=[
            ButtonDef(field_id="manage_feature", text=UILabels.FEATURE_MANAGE, on_click="manage_feature_clicked", stretch=1),
        ]),
    ],
)

TAB2_DISPLAY_FILTER_SPEC = PanelSpec(
    panel_id="tab2_display",
    spacing=UIConfig.PANEL_MARGIN,
    fields=[
        FieldSpec(field_id="filter_actions", widget_type=WidgetType.BUTTON_ROW, centered=False, buttons=[
            ButtonDef(field_id="filter_toggle", text=UILabels.BTN_FILTER_OFF, on_click="filter_toggled", stretch=3),
            ButtonDef(field_id="filter_settings", text=UILabels.BTN_FILTER_SETTINGS, on_click="filter_settings_clicked", stretch=1),
        ]),
        FieldSpec(field_id="ref_point_visibility", widget_type=WidgetType.RADIO_ROW, label=UILabels.LBL_REF_POINT_VISIBILITY, options=[UILabels.RADIO_VISIBLE, UILabels.RADIO_HIDDEN], default_index=0, on_change="ref_point_visibility_changed"),
        FieldSpec(field_id="drawing_list_table", widget_type=WidgetType.TABLE, table_headers=["表示", "レイヤ名"], table_col_resize_modes=["contents", "stretch"], table_min_height=UIConfig.DRAWING_LIST_HEIGHT, on_change="drawing_table_cell_changed"),
    ],
)


class MainDockWidget(QDockWidget):
    
    def __init__(
        self,
        iface: QgisInterface,
        layer_manager: Any,
        layers_dict: Optional[Dict[str, Any]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(UILabels.DOCK_TITLE, parent)
        self.iface = iface
        self.layer_manager = layer_manager
        self.layers_dict = layers_dict or {}

        self.point_layer: Optional[QgsVectorLayer] = self.layers_dict.get("point_layer")
        self.ref_point_layer: Optional[QgsVectorLayer] = self.layers_dict.get("ref_point_layer")
        self.canvas: QgsMapCanvas = self.iface.mapCanvas()

        self.image_dialog: Optional[ImageDialog] = None

        # StateStore と中央 Dispatcher の初期化
        self.state_store = UIStateStore(self)
        self.dispatcher = EventDispatcher(self.state_store)

        # -----------------------------------------------------------------
        # Controller (ロジック層) の初期化とコールバックDI
        # -----------------------------------------------------------------
        self.digitizing_logic = DigitizingLogic(
            self.state_store, self.layer_manager, self.layers_dict, self.iface, self.dispatcher, parent=self
        )
        self.filter_logic = FilterLogic(
            self.state_store, self.layer_manager, self.iface, self.dispatcher, parent=self
        )

        self.map_tool = CanvasDigitizingTool(
            self.canvas, self.point_layer, dock_widget=self, layer_manager=self.layer_manager
        )
        
        # キャンバスイベントの View 側での受容と振り分け
        self.map_tool.canvas_clicked.connect(self._on_canvas_clicked)
        self.map_tool.existing_point_selected.connect(self._on_existing_point_selected)
        self.map_tool.blank_click_in_edit_mode.connect(
            lambda: self.map_tool.clear_selected_marker()
        )

        self._init_ui()
        UIStyleHelper.apply_theme(self)
        UIStyleHelper.apply_theme(self.image_dialog)
        UIStyleHelper.apply_theme(self.settings_dialog)
        UIStyleHelper.apply_theme(self.output_dialog)

        # ViewコールバックをControllerへバインド
        self.digitizing_logic.bind_view_callbacks({
            "update_symbology_opacity": self.update_symbology_opacity,
            "refresh_canvas": self.canvas.refresh,
        })

        # StateStoreの変更を監視してUIを自動同期
        self.state_store.state_changed.connect(self._on_state_changed)

        # View初期化
        self._init_tab2_comboboxes()
        self._restore_feature_names()
        initial_filters = {
            "attributes": [
                AttributeType.S.value, AttributeType.P.value, 
                AttributeType.C.value, AttributeType.SP.value
            ],
            "excavation_types": [ExcavationType.FEATURE.value, ExcavationType.GRID.value],
            "feature_names": list(self.state_store.state.feature_name_list),
            "target_drawing": UILabels.FILTER_DRAWING_SELECTED,
        }
        self.state_store.dispatch_silent(SetDisplayFiltersAction(initial_filters))
        self._update_drawing_combo()
        if hasattr(self, "settings_logic"):
            self.settings_logic.update_settings_ui_from_dict()

        project = QgsProject.instance()
        if project is not None:
            project.layersAdded.connect(self._update_drawing_combo)
            project.layersRemoved.connect(self._update_drawing_combo)

        if self.point_layer and self.point_layer.isValid() and self.layer_manager:
            current_settings = self.layer_manager.load_settings() if hasattr(self.layer_manager, "load_settings") else None
            self.layer_manager.apply_point_symbology(self.point_layer, current_settings)
        self.update_symbology_opacity()

        try:
            layer_tree_dock = self.iface.mainWindow().findChild(QDockWidget, "Layer Tree")
            if layer_tree_dock:
                layer_tree_dock.hide()
        except Exception:
            pass

        self._update_main_map_tool_state()

        # 初期バリデーション発行、起動時の最新IDに基づく自動連番計算と入力同期
        if self.point_layer and self.point_layer.isValid():
            autonum_action = self.digitizing_logic.apply_next_point_number()
            if autonum_action:
                self.dispatcher.dispatch(autonum_action)
            self._update_digitizing_inputs_to_state()
        
        # 初期化フェーズの最後に全UIを強制同期
        all_keys = self.state_store.state.__dict__.keys()
        fake_diff = {k: getattr(self.state_store.state, k) for k in all_keys}
        self._on_state_changed(self.state_store.state, fake_diff)

    @property
    def preview_canvas(self) -> Optional[QgsMapCanvas]:
        return self.image_dialog.canvas if self.image_dialog else None

    @property
    def preview_raster_layer(self) -> Optional[QgsRasterLayer]:
        return self.image_dialog.raster_layer if self.image_dialog else None

    @property
    def georef_tool(self) -> Optional[ImageGeorefTool]:
        return self.image_dialog.georef_tool if self.image_dialog else None

    def _load_icon(self, filename: str) -> QIcon:
        icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "icon", filename)
        return QIcon(icon_path)

    def _init_ui(self) -> None:
        root_widget = QWidget(self)
        root_layout = QVBoxLayout(root_widget)
        root_layout.setContentsMargins(
            UIConfig.PANEL_MARGIN, UIConfig.PANEL_MARGIN,
            UIConfig.PANEL_MARGIN, UIConfig.PANEL_MARGIN,
        )
        root_layout.setSpacing(0)

        # 1. Top button row
        top_row = QWidget(root_widget)
        top_layout = QHBoxLayout(top_row)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(UIConfig.TOP_ROW_BUTTON_SPACING)

        self.btn_top_image = QPushButton(UILabels.BTN_TOP_IMAGE, top_row)
        self.btn_top_image.setIcon(self._load_icon("image.svg"))
        self.btn_top_image.clicked.connect(self._show_image_dialog)
        top_layout.addWidget(self.btn_top_image)

        self.btn_top_settings = QPushButton(UILabels.BTN_TOP_SETTINGS, top_row)
        self.btn_top_settings.setIcon(self._load_icon("setting.svg"))
        self.btn_top_settings.clicked.connect(self._show_settings_dialog)
        top_layout.addWidget(self.btn_top_settings)

        self.btn_top_output = QPushButton(UILabels.BTN_TOP_OUTPUT, top_row)
        self.btn_top_output.setIcon(self._load_icon("output.svg"))
        self.btn_top_output.clicked.connect(self._show_output_dialog)
        top_layout.addWidget(self.btn_top_output)

        self.btn_save_project = QPushButton(UILabels.BTN_TOP_SAVE, top_row)
        self.btn_save_project.setIcon(self._load_icon("save.svg"))
        UIStyleHelper.set_success_button(self.btn_save_project)
        self.btn_save_project.clicked.connect(self._save_project)
        top_layout.addWidget(self.btn_save_project)

        root_layout.addWidget(top_row)
        root_layout.addWidget(UIStyleHelper.build_separator(root_widget))

        # 2. 外部 Dialog 構築
        self.tab1_container = create_tab1_ui(self)
        self.image_dialog = ImageDialog(
            self.tab1_container, on_show=self._update_main_map_tool_state,
            on_close=self._update_main_map_tool_state, parent=self,
        )

        self.tab3_container = create_tab3_ui(self)
        self.settings_dialog = ModelessSectionDialog(
            UILabels.TAB_3_TITLE, self.tab3_container,
            on_show=self._update_main_map_tool_state,
            on_close=self._update_main_map_tool_state,
            parent=self, width=UIDialogSizes.SETTINGS_DIALOG_WIDTH, height=UIDialogSizes.SETTINGS_DIALOG_HEIGHT,
        )

        self.tab4_container = create_tab4_ui(self)
        self.output_dialog = ModelessSectionDialog(
            UILabels.TAB_4_TITLE, self.tab4_container,
            on_show=self._update_main_map_tool_state,
            on_close=self._update_main_map_tool_state,
            parent=self, width=UIDialogSizes.OUT_DIALOG_WIDTH, height=UIDialogSizes.OUT_DIALOG_HEIGHT,
        )

        # 5. Main area: 遺物点作成
        self.tab2_container = self._create_tab2_ui()
        root_layout.addWidget(self.tab2_container, 1)

        root_widget.setFixedWidth(UIConfig.DOCK_WIDTH)
        self.setWidget(root_widget)

    # =========================================================================
    # MainDockWidget メソッド (Tab2 UI構築 & バインド)
    # =========================================================================

    def _create_tab2_ui(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(
            UIConfig.PANEL_CONTAINER_MARGIN_LEFT, 0,
            UIConfig.PANEL_CONTAINER_MARGIN_RIGHT, UIConfig.PANEL_MARGIN
        )
        layout.setSpacing(0)

        # 1. モード切替パネル
        self.panel_mode = CoreUIBuilder.build(TAB2_MODE_TOGGLE_SPEC, parent=container)
        self.panel_mode.auto_bind(self.dispatcher, {
            "mode_changed": lambda idx: ChangeTab2ModeAction("new" if idx == 0 else "edit")
        })
        layout.addWidget(self.panel_mode.widget)
        layout.addSpacing(UIConfig.PANEL_MARGIN)

        # 2. 点情報パネル
        self.panel_point_info = CoreUIBuilder.build(TAB2_POINT_INFO_SPEC, parent=container)
        self.lbl_point_info_status = QLabel(self.panel_point_info.get("point_info_summary"))
        self.lbl_point_info_status.setWordWrap(True)
        info_panel_frame = self.panel_point_info.get("point_info_summary")
        info_panel_frame.layout().addWidget(self.lbl_point_info_status)
        UIStyleHelper.update_status_panel(info_panel_frame, self.lbl_point_info_status, UILabels.STATUS_NEW_POINT, "info")

        # 自動連番/解除トグルを点情報パネルのステータスボックス内に移動する
        autonum_row = self.panel_point_info.get_row("autonum_mode")
        self.panel_point_info.widget.layout().removeWidget(autonum_row)
        info_panel_frame.layout().addSpacing(UIConfig.PANEL_MARGIN)
        info_panel_frame.layout().addWidget(autonum_row)

        self.panel_point_info.auto_bind(self.dispatcher, {
            "autonum_mode_changed": lambda idx: ChangeAutonumModeAction("auto" if idx == 0 else "release"),
        })
        self.panel_point_info.bind("point_identity_changed", self._update_digitizing_inputs_to_state)
        self.panel_point_info.bind("branch_text_changed", self._update_digitizing_inputs_to_state)
        layout.addWidget(self.panel_point_info.widget)
        layout.addSpacing(UIConfig.PANEL_MARGIN)

        # 3. 属性パネル
        self.panel_attribute = CoreUIBuilder.build(TAB2_ATTRIBUTE_SPEC, parent=container)
        self.panel_attribute.bind("category_changed", self._on_attribute_category_changed)
        self.panel_attribute.bind("excavation_type_changed", self._on_excavation_changed)
        self.panel_attribute.bind("feature_combo_changed", self._update_digitizing_inputs_to_state)
        self.panel_attribute.bind("manage_feature_clicked", self._handle_manage_feature_clicked)
        layout.addWidget(self.panel_attribute.widget)
        layout.addWidget(UIStyleHelper.build_separator(container))

        # 4. 表示設定パネル
        self.panel_display = CoreUIBuilder.build(TAB2_DISPLAY_FILTER_SPEC, parent=container)
        btn_filter = self.panel_display.get("filter_toggle")
        btn_filter.setCheckable(True)
        
        table_drawing_list = self.panel_display.get("drawing_list_table")
        table_drawing_list.setSelectionBehavior(QTableWidget.SelectRows)
        table_drawing_list.setSelectionMode(QTableWidget.SingleSelection)
        table_drawing_list.setFocusPolicy(Qt.NoFocus)
        table_drawing_list.setShowGrid(False)
        table_drawing_list.setStyleSheet("QTableView::indicator { subcontrol-position: center; } QTableView { border: none; }")
        table_drawing_list.verticalHeader().setVisible(False)
        table_drawing_list.verticalHeader().setDefaultSectionSize(20)
        table_drawing_list.horizontalHeader().setStretchLastSection(True)
        table_drawing_list.setColumnWidth(0, 40)
        
        table_drawing_list.itemSelectionChanged.connect(self._on_drawing_table_selection_changed)
        table_drawing_list.horizontalHeader().sectionClicked.connect(self._on_drawing_table_header_clicked)
        table_drawing_list.itemChanged.connect(self._on_drawing_table_cell_changed)
        
        self.panel_display.auto_bind(self.dispatcher, {
            "filter_toggled": lambda checked: SetFocusModeAction(checked),
            "ref_point_visibility_changed": lambda idx: ChangeRefPointVisibilityAction(idx == 0)
        })
        self.panel_display.bind("filter_settings_clicked", self._show_display_filter_dialog)
        layout.addWidget(self.panel_display.widget)
        layout.addStretch()

        scroll.setWidget(container)
        return scroll

    def _init_tab2_comboboxes(self) -> None:
        combo_attr = self.panel_attribute.get("attribute_code")
        combo_attr.blockSignals(True)
        for value in UILabels.ATTRIBUTE_OPTIONS:
            combo_attr.addItem(UILabels.ATTRIBUTE_DISPLAY_MAP.get(value, value), value)
        combo_attr.blockSignals(False)

        combo_excav = self.panel_attribute.get("excavation_type")
        combo_excav.blockSignals(True)
        combo_excav.addItems(UILabels.EXCAVATION_OPTIONS)
        combo_excav.blockSignals(False)

        combo_feat = self.panel_attribute.get("feature_name")
        combo_feat.blockSignals(True)
        combo_feat.addItem(UILabels.UNREGISTERED)
        combo_feat.blockSignals(False)

    # =========================================================================
    # View State Sync & Helper Methods
    # =========================================================================

    def _on_state_changed(self, new_state, diff: Dict[str, Any]) -> None:
        if "tab2_mode" in diff:
            is_new = (new_state.tab2_mode == "new")
            self.panel_point_info.get_row("autonum_mode").setVisible(is_new)
            self.panel_point_info.get_row("point_name").setEnabled(is_new)
            self.panel_point_info.get_row("point_name_sp").setEnabled(is_new)
            self.panel_point_info.get_row("branch_no").setEnabled(is_new)
            self.panel_attribute.widget.setEnabled(is_new)
            if getattr(self, "map_tool", None) and hasattr(self.map_tool, "update_tab2_mode"):
                self.map_tool.update_tab2_mode(new_state.tab2_mode)

        if "selected_point_id" in diff and new_state.selected_point_id is None:
            if getattr(self, "map_tool", None):
                self.map_tool.clear_selected_marker()

        if "focus_active" in diff or "display_filters" in diff:
            btn_filter = self.panel_display.get("filter_toggle")
            if new_state.focus_active:
                if not btn_filter.isChecked():
                    btn_filter.blockSignals(True)
                    btn_filter.setChecked(True)
                    btn_filter.blockSignals(False)
                btn_filter.setText(UILabels.BTN_FILTER_ON)
                btn_filter.setStyleSheet("background-color: #1976D2; color: #FFFFFF; font-weight: bold; border-radius: 4px; padding: 4px;")
            else:
                if btn_filter.isChecked():
                    btn_filter.blockSignals(True)
                    btn_filter.setChecked(False)
                    btn_filter.blockSignals(False)
                btn_filter.setText(UILabels.BTN_FILTER_OFF)
                btn_filter.setStyleSheet("")
            
        if any(k in diff for k in ("focus_active", "display_filters", "selected_drawing_name")):
            self.update_symbology_opacity()
            self._update_map_tool_focus_state()

        if any(k in diff for k in ("point_info_summary", "point_info_has_error", "is_out_of_bounds", "status_message", "selected_point_id", "tab2_mode")):
            self._update_point_info_status_ui(new_state)

        if "feature_name_list" in diff:
            combo = self.panel_attribute.get("feature_name")
            current_text = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(UILabels.UNREGISTERED)
            combo.addItems([name for name in new_state.feature_name_list if name != UILabels.UNREGISTERED])
            idx = combo.findText(current_text)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            combo.blockSignals(False)

        if "digitizing_inputs" in diff:
            focus_w = QApplication.focusWidget()
            for field_id, value in new_state.digitizing_inputs.items():
                panel = self.panel_point_info if field_id in ["point_name", "point_name_sp", "branch_no"] else self.panel_attribute
                if panel and panel._field_types.get(field_id):
                    widget = panel.get(field_id)
                    # 入力中のウィジェットへの強制書き戻しを回避（タイピング阻害の防止）
                    if focus_w and (focus_w == widget or widget.isAncestorOf(focus_w)):
                        continue
                    
                    widget.blockSignals(True)
                    if field_id == "attribute_code":
                        idx = widget.findData(value)
                        if idx >= 0: widget.setCurrentIndex(idx)
                    else:
                        panel.set_value(field_id, value)
                    widget.blockSignals(False)

        if "is_processing" in diff:
            if new_state.is_processing:
                QApplication.setOverrideCursor(Qt.WaitCursor)
                self.setEnabled(False)
                if getattr(self, "map_tool", None) and hasattr(self.map_tool, "set_interaction_locked"):
                    self.map_tool.set_interaction_locked(True)
            else:
                self.setEnabled(True)
                QApplication.restoreOverrideCursor()
                if getattr(self, "map_tool", None) and hasattr(self.map_tool, "set_interaction_locked"):
                    self.map_tool.set_interaction_locked(False)

    def _update_digitizing_inputs_to_state(self, *args) -> None:
        """Viewのパネル入力状態をStateの inputs に一括反映してバリデーションを発行する"""
        combo_attr = self.panel_attribute.get("attribute_code")
        inputs = {
            "attribute_code": combo_attr.currentData() or combo_attr.currentText(),
            "excavation_type": self.panel_attribute.get_value("excavation_type"),
            "feature_name": self.panel_attribute.get_value("feature_name"),
            "point_name": self.panel_point_info.get_value("point_name"),
            "point_name_sp": self.panel_point_info.get_value("point_name_sp"),
            "branch_no": self.panel_point_info.get_value("branch_no")
        }
        self.dispatcher.dispatch(UpdateDigitizingInputsAction(inputs))
        self.digitizing_logic.run_validation()

    def _on_attribute_category_changed(self, *args):
        combo_attr = self.panel_attribute.get("attribute_code")
        is_sp = ((combo_attr.currentData() or combo_attr.currentText()) == AttributeType.SP.value)
        self.panel_point_info.get_row("point_name").setVisible(not is_sp)
        self.panel_point_info.get_row("point_name_sp").setVisible(is_sp)
        
        buttons = self.panel_point_info.get_buttons("autonum_mode")
        if is_sp:
            if not buttons[1].isChecked():
                buttons[1].setChecked(True)
            buttons[0].setEnabled(False)
            buttons[1].setEnabled(False)
        else:
            buttons[0].setEnabled(True)
            buttons[1].setEnabled(True)

        autonum_action = self.digitizing_logic.apply_next_point_number()
        if autonum_action:
            self.dispatcher.dispatch(autonum_action)
        self._update_digitizing_inputs_to_state()

    def _on_excavation_changed(self, *args):
        is_feat = self.panel_attribute.get_value("excavation_type") == ExcavationType.FEATURE.value
        self.panel_attribute.get_row("feature_name").setVisible(is_feat)
        self.panel_attribute.get_row("feature_actions").setVisible(is_feat)
        autonum_action = self.digitizing_logic.apply_next_point_number()
        if autonum_action:
            self.dispatcher.dispatch(autonum_action)
        self._update_digitizing_inputs_to_state()

    def _update_point_info_status_ui(self, state):
        summary = state.point_info_summary
        status_text = state.status_message
        status_type = "error" if state.point_info_has_error else "warning" if state.tab2_mode == "edit" else "info"
        if not status_text:
            status_text = UILabels.STATUS_EDIT_POINT if state.tab2_mode == "edit" else UILabels.STATUS_NEW_POINT
                
        full_text = f"{status_text}\n" \
                    f"{UILabels.LBL_INFO_GROUP_OR_FEATURE} {summary.get('group', '-')}\n" \
                    f"{UILabels.LBL_INFO_POINT_BRANCH} {summary.get('pointname', '-')}\n" \
                    f"{UILabels.LBL_INFO_COORDS} {summary.get('coords', '-')}"
                    
        UIStyleHelper.update_status_panel(
            self.panel_point_info.get("point_info_summary"), 
            self.lbl_point_info_status, full_text, status_type
        )
        
        is_feat_missing = self.digitizing_logic.is_feature_name_missing(state.digitizing_inputs)
        is_dup = state.point_info_has_error and status_text == UILabels.STATUS_ERR_DUPLICATE
        
        UIStyleHelper.set_error_border(self.panel_attribute.get("feature_name"), is_feat_missing)
        is_sp = (state.digitizing_inputs.get("attribute_code") == AttributeType.SP.value)
        UIStyleHelper.set_error_border(self.panel_point_info.get("point_name"), is_dup and not is_sp)
        UIStyleHelper.set_error_border(self.panel_point_info.get("point_name_sp"), is_dup and is_sp)

    # =========================================================================
    # ダイアログ移管・キャンバスイベント・レイヤ制御
    # =========================================================================

    def _on_canvas_clicked(self, map_point: QgsPointXY) -> None:
        state = self.state_store.state
        if state.autonum_mode == "release":
            self._handle_release_mode_click(map_point)
        else:
            self.dispatcher.dispatch(CanvasClickAction(map_point))

    def _handle_release_mode_click(self, map_point: QgsPointXY) -> None:
        inputs = self.state_store.state.digitizing_inputs
        if self.digitizing_logic.is_feature_name_missing(inputs):
            self.dispatcher.dispatch(SetPointInfoErrorAction(has_error=True))
            return
            
        drawing_name = self.state_store.state.selected_drawing_name
        is_valid, _ = self.digitizing_logic.validate_drawing_bounds(drawing_name, map_point)
        if not is_valid:
            self.dispatcher.dispatch(SetPointInfoErrorAction(has_error=True, is_out_of_bounds=True))
            return
            
        ex_type = inputs.get("excavation_type", "")
        feat_name = inputs.get("feature_name", "")
        is_sp = (inputs.get("attribute_code") == AttributeType.SP.value)
        last_name = self.digitizing_logic.get_last_created_point_name(ex_type, feat_name, is_sp)

        device_pt = self.canvas.getCoordinateTransform().transform(map_point)
        global_pos = self.canvas.mapToGlobal(QPoint(round(device_pt.x()), round(device_pt.y())))

        dlg = PointNameEntryDialog(
            self.point_layer, ex_type, feat_name, drawing_name, is_sp,
            self, initial_point_name=last_name, popup_pos=global_pos
        )
        if dlg.exec_() == QDialog.Accepted:
            pname, bno = dlg.get_values()
            self.dispatcher.dispatch(AddManualDigitizedPointAction(map_point, pname, bno))

    def _on_existing_point_selected(self, data: dict) -> None:
        if self.map_tool and hasattr(self.map_tool, "set_interaction_locked"):
            self.map_tool.set_interaction_locked(True)
            
        drawing_names = self._get_drawing_layer_names()
        dlg = PointEditDialog(
            layer_manager=self.layer_manager,
            feature_data=data,
            drawing_names=drawing_names,
            parent=self
        )
        result = dlg.exec_()
        if self.map_tool and hasattr(self.map_tool, "set_interaction_locked"):
            self.map_tool.set_interaction_locked(False)
            
        if result == QDialog.Accepted:
            if dlg.dialog_action == "delete":
                self.dispatcher.dispatch(DeletePointAction(data.get("feature_id")))
            elif dlg.dialog_action == "confirm":
                updates = {
                    "drawing_name": dlg.feature_data["drawing_name"],
                    "excavation_type": dlg.feature_data["excavation_type"],
                    "feature_name": dlg.feature_data["feature_name"],
                    "attribute_type": dlg.feature_data["attribute_type"],
                    "point_name": dlg.feature_data["point_name"],
                    "branch_no": dlg.feature_data["branch_no"],
                }
                self.dispatcher.dispatch(UpdatePointAttributesAction(data.get("feature_id"), updates))
        
        self.dispatcher.dispatch(ResetSelectionAction())
        if self.map_tool:
            self.map_tool.clear_selected_marker()

    def _handle_manage_feature_clicked(self) -> None:
        feature_colors = {name: "#FF5722" for name in self.state_store.state.feature_name_list if name != UILabels.UNREGISTERED}
        if self.point_layer and self.point_layer.isValid():
            for feat in self.point_layer.getFeatures():
                fname = safe_get_str(feat, "feature_name").strip()
                if fname and fname not in (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成")):
                    c_code = safe_get_str(feat, "color_code").strip()
                    if c_code:
                        feature_colors[fname] = c_code
                    elif fname not in feature_colors:
                        feature_colors[fname] = "#FF5722"

        # QDialog の on_update_callback を用いて Controller にアクションを発行
        dlg = FeatureManageDialog(
            parent=self, 
            feature_colors=feature_colors, 
            on_update_callback=lambda old, new, col: self.dispatcher.dispatch(UpdateFeatureCategoryAction(old, new, col))
        )
        UIStyleHelper.apply_theme(dlg)
        
        if dlg.exec_() == QDialog.Accepted:
            new_name = dlg.result_text.strip()
            if new_name:
                if hasattr(dlg, "result_color") and dlg.result_color:
                    self.state_store.dispatch(SetFeatureCacheAction(color_hex=dlg.result_color))
                temp_list = list(self.state_store.state.feature_name_list)
                if new_name not in temp_list:
                    temp_list.append(new_name)
                    self.state_store.dispatch(SetFeatureCacheAction(feature_list=temp_list))
                self.dispatcher.dispatch(UpdateDigitizingInputsAction({"feature_name": new_name}))
                self.digitizing_logic.run_validation()

    def _show_display_filter_dialog(self) -> None:
        dlg = DisplayFilterDialog(
            parent=self,
            feature_names=self.state_store.state.feature_name_list,
            initial_filters=self.state_store.state.display_filters,
        )
        if dlg.exec_() == QDialog.Accepted:
            self.dispatcher.dispatch(SetDisplayFiltersAction(dlg.get_filters()))
            self.dispatcher.dispatch(SetFocusModeAction(True))

    def _restore_feature_names(self) -> None:
        if not self.point_layer or not self.point_layer.isValid():
            return
        combo = self.panel_attribute.get("feature_name")
        temp_list = []
        UIStyleHelper.populate_combo_from_layer_field(
            combo, self.point_layer, "feature_name", leading_item=UILabels.UNREGISTERED, target_list=temp_list
        )
        self.state_store.dispatch_silent(SetFeatureCacheAction(feature_list=temp_list))

    def _get_drawing_layers(self) -> List[Tuple[str, str, bool]]:
        root = QgsProject.instance().layerTreeRoot()
        if not root: return []
        image_group = root.findGroup("画像ファイル")
        if not image_group: return []
        result = []
        for tree_layer in image_group.findLayers():
            layer = tree_layer.layer()
            if layer and layer.isValid():
                result.append((layer.name(), layer.id(), tree_layer.itemVisibilityChecked()))
        return result

    def _get_drawing_layer_names(self) -> List[str]:
        return [info[0] for info in self._get_drawing_layers()]

    def _get_target_drawing_name(self) -> str:
        table = self.panel_display.get("drawing_list_table")
        row = -1
        sel_model = table.selectionModel()
        if sel_model and sel_model.selectedRows():
            row = sel_model.selectedRows()[0].row()
        if row < 0:
            row = table.currentRow()
        if row <= 0:
            return UILabels.DRAWING_UNSPECIFIED
        item = table.item(row, 1)
        return item.text().strip() if item else UILabels.DRAWING_UNSPECIFIED

    def _update_drawing_combo(self, *args: Any) -> None:
        table = self.panel_display.get("drawing_list_table")
        current_selection = self._get_target_drawing_name()
        table.blockSignals(True)
        table.setRowCount(0)

        table.insertRow(0)
        item_col0 = QTableWidgetItem("")
        item_col0.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        table.setItem(0, 0, item_col0)
        item_col1 = QTableWidgetItem(UILabels.DRAWING_UNSPECIFIED)
        item_col1.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        table.setItem(0, 1, item_col1)

        for r_idx, (name, layer_id, is_vis) in enumerate(self._get_drawing_layers(), start=1):
            table.insertRow(r_idx)
            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            chk_item.setCheckState(Qt.Checked if is_vis else Qt.Unchecked)
            chk_item.setData(Qt.UserRole, layer_id)
            table.setItem(r_idx, 0, chk_item)
            name_item = QTableWidgetItem(name)
            name_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            table.setItem(r_idx, 1, name_item)

        table.blockSignals(False)
        self._ensure_drawing_selected(current_selection)

    def _ensure_drawing_selected(self, layer_name: str) -> None:
        table = self.panel_display.get("drawing_list_table")
        if table.rowCount() == 0: return
        target_row = 0
        if layer_name and layer_name != UILabels.DRAWING_UNSPECIFIED:
            for r in range(1, table.rowCount()):
                item = table.item(r, 1)
                if item and item.text() == layer_name:
                    target_row = r
                    break
        table.selectRow(target_row)
        scroll_item = table.item(target_row, 1)
        if scroll_item:
            table.scrollToItem(scroll_item)
            
    def _on_drawing_table_selection_changed(self) -> None:
        d_name = self._get_target_drawing_name()
        drawing = d_name if d_name != UILabels.DRAWING_UNSPECIFIED else ""
        self.dispatcher.dispatch(SelectDrawingAction(drawing))
        self.digitizing_logic.run_validation()

    def _on_drawing_table_header_clicked(self, logical_index: int) -> None:
        if logical_index != 0:
            return
        table = self.panel_display.get("drawing_list_table")
        if table.rowCount() <= 1:
            return

        first_item = table.item(1, 0)
        if not first_item:
            return
            
        new_state = Qt.Unchecked if first_item.checkState() == Qt.Checked else Qt.Checked
        table.blockSignals(True)
        try:
            for row in range(1, table.rowCount()):
                chk_item = table.item(row, 0)
                if chk_item:
                    chk_item.setCheckState(new_state)
                    layer_id = chk_item.data(Qt.UserRole)
                    if layer_id:
                        self.dispatcher.dispatch(ChangeDrawingVisibilityAction(layer_id, new_state == Qt.Checked))
        finally:
            table.blockSignals(False)

    def _on_drawing_table_cell_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 0 or item.row() == 0:
            return
        layer_id = item.data(Qt.UserRole)
        if layer_id:
            self.dispatcher.dispatch(ChangeDrawingVisibilityAction(layer_id, item.checkState() == Qt.Checked))

    def _show_image_dialog(self) -> None:
        self.image_dialog.show()
        self.image_dialog.raise_()
        self.image_dialog.activateWindow()

    def _show_settings_dialog(self) -> None:
        if hasattr(self, "settings_logic"):
            self.settings_logic.update_settings_ui_from_dict()
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def _show_output_dialog(self) -> None:
        self.output_dialog.show()
        self.output_dialog.raise_()
        self.output_dialog.activateWindow()

    def _update_main_map_tool_state(self) -> None:
        dialogs = (
            getattr(self, "image_dialog", None),
            getattr(self, "settings_dialog", None),
            getattr(self, "output_dialog", None),
        )
        any_open = any(d is not None and d.isVisible() for d in dialogs)

        if any_open:
            self.canvas.unsetMapTool(self.map_tool)
        else:
            self._update_drawing_combo()
            self.canvas.setMapTool(self.map_tool)

    def update_symbology_opacity(self) -> None:
        if not self.point_layer or not self.point_layer.isValid():
            return

        with self.digitizing_logic.busy_interaction_guard():
            state = self.state_store.state
            is_focus_on = state.focus_active
            filters = dict(state.display_filters) if is_focus_on else {}

            if is_focus_on:
                if filters.get("target_drawing") == UILabels.FILTER_DRAWING_SELECTED:
                    filters["target_drawing_name"] = state.selected_drawing_name
                else:
                    filters["target_drawing_name"] = None

            expr = self.layer_manager.build_opacity_expression(is_focus_on, filters, 0)
            # apply_opacity_expression() already calls layer.triggerRepaint() (the
            # layer's own native redraw signal) internally, so no extra manual
            # self.canvas.refresh() is issued here — avoids a duplicate repaint
            # per data/opacity update (Core_Architecture_UIUX.md section 2).
            self.layer_manager.apply_opacity_expression(self.point_layer, expr)

    def _update_map_tool_focus_state(self) -> None:
        if self.map_tool is not None:
            state = self.state_store.state
            filters = dict(state.display_filters) if state.display_filters else {}
            if filters.get("target_drawing") == UILabels.FILTER_DRAWING_SELECTED:
                filters["target_drawing_name"] = state.selected_drawing_name
            else:
                filters["target_drawing_name"] = None
            self.map_tool.update_focus_state(state.focus_active, filters)

    def _save_project(self) -> None:
        success = self.layer_manager.save_project()
        if success:
            self.iface.messageBar().pushMessage(UIMessages.MSG_SAVE_TITLE, UIMessages.MSG_SAVE_SUCCESS, level=Qgis.MessageLevel.Success, duration=4)
        else:
            self.iface.messageBar().pushMessage(UIMessages.MSG_SAVE_TITLE, UIMessages.MSG_SAVE_FAILED, level=Qgis.MessageLevel.Warning, duration=5)

    def closeEvent(self, event: Any) -> None:
        try:
            project = QgsProject.instance()
            if project is not None:
                project.layersAdded.disconnect(self._update_drawing_combo)
                project.layersRemoved.disconnect(self._update_drawing_combo)
        except (TypeError, RuntimeError):
            pass

        for dialog in (self.image_dialog, self.settings_dialog, self.output_dialog):
            if dialog is not None:
                dialog.close()
        if self.map_tool:
            try:
                self.canvas.unsetMapTool(self.map_tool)
            except Exception:
                pass
            self.map_tool.clean_up()
            
        try:
            if QgsProject.instance().fileName():
                QgsProject.instance().write()
                QgsProject.instance().clear()
        except Exception:
            pass
        super().closeEvent(event)