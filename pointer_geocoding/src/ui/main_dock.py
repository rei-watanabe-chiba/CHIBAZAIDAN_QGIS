"""
/***************************************************************************
 PointerGeocoding Plugin - Main Operation Dock Panel
 ***************************************************************************/
"""
import os
from typing import Optional, Dict, Any, List, Tuple

from qgis.core import QgsProject, QgsVectorLayer, QgsRasterLayer, Qgis
from qgis.gui import QgisInterface, QgsMapCanvas
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QIcon
from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidgetItem, QScrollArea, QFrame, QLabel, QTableWidget, QMessageBox, QDialog
)

from ..canvas.map_tool import CanvasDigitizingTool
from .style import UIStyleHelper
from .constants import UIConfig, UILabels, UIMessages, UIDialogSizes, UIPlaceholders
from .dialogs import ImageDialog, ModelessSectionDialog, DisplayFilterDialog
from ..uilogic.dispatcher import EventDispatcher
from ..uilogic.digitizing_logic import DigitizingLogic
from ..uilogic.filter_logic import FilterLogic
from ..logic.core import AttributeType, ExcavationType

from .core.state import (
    UIStateStore, ResetSelectionAction, SetFeatureCacheAction, SelectDrawingAction,
    SetDisplayFiltersAction, ChangeTab2ModeAction, ChangeAutonumModeAction,
    SetFocusModeAction, CanvasDigitizeAction, DeletePointAction,
    UpdateDigitizingInputsAction, SetRefLayerVisibilityAction, SetDrawingLayerVisibilityAction,
    ToggleAllDrawingsVisibilityAction, SetValidationAction, OpenFeatureManageAction,
    OpenPointEditAction
)
from .core.field_spec import ButtonDef, FieldSpec, PanelSpec, WidgetType
from .core.builder import CoreUIBuilder

from .main_image import create_tab1_ui
from .main_settings import create_tab3_ui
from .main_output import create_tab4_ui

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
        FieldSpec(field_id="edit_mode_actions", widget_type=WidgetType.BUTTON_ROW, centered=False, visible=False, buttons=[
            ButtonDef(field_id="delete_point", text=UILabels.BTN_DELETE_POINT, on_click="delete_point_clicked"),
        ]),
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
    
    def __init__(self, iface: QgisInterface, layer_manager: Any, layers_dict: Optional[Dict[str, Any]] = None, parent: Optional[QWidget] = None):
        super().__init__(UILabels.DOCK_TITLE, parent)
        self.iface = iface
        self.layer_manager = layer_manager
        self.layers_dict = layers_dict or {}

        self.point_layer = self.layers_dict.get("point_layer")
        self.canvas = self.iface.mapCanvas()

        self.state_store = UIStateStore(self)
        self.dispatcher = EventDispatcher(self.state_store, self.layer_manager, self)

        # Controllers (Tab2)
        self.digitizing_logic = DigitizingLogic(self.state_store, self.layer_manager, self.layers_dict, self.dispatcher, self.iface, parent=self)
        self.filter_logic = FilterLogic(self.state_store, self.layer_manager, self.dispatcher, self.iface, parent=self)

        self.map_tool = CanvasDigitizingTool(self.canvas, self.point_layer, dock_widget=self, layer_manager=self.layer_manager)
        
        # キャンバス起因のイベントをActionとして直接Dispatcherへ投げる（ロジック層への委譲）
        self.map_tool.canvas_clicked.connect(lambda pt: self.dispatcher.dispatch(CanvasDigitizeAction(map_point=pt)))
        self.map_tool.existing_point_selected.connect(lambda data: self.dispatcher.dispatch(OpenPointEditAction(point_data=data)))
        self.map_tool.blank_click_in_edit_mode.connect(lambda: self.dispatcher.dispatch(ResetSelectionAction()))

        self._init_ui()
        UIStyleHelper.apply_theme(self)
        if self.image_dialog: UIStyleHelper.apply_theme(self.image_dialog)
        if self.settings_dialog: UIStyleHelper.apply_theme(self.settings_dialog)
        if self.output_dialog: UIStyleHelper.apply_theme(self.output_dialog)

        self.digitizing_logic.bind_view_callbacks({
            "update_symbology_opacity": self.update_symbology_opacity,
            "get_drawing_layer_names": self._get_drawing_layer_names,
        })

        self.state_store.state_changed.connect(self._on_state_changed)

        self._init_tab2_comboboxes()
        
        initial_filters = {
            "attributes": [AttributeType.S.value, AttributeType.P.value, AttributeType.C.value, AttributeType.SP.value],
            "excavation_types": [ExcavationType.FEATURE.value, ExcavationType.GRID.value],
            "feature_names": list(self.state_store.state.feature_name_list),
            "target_drawing": UILabels.FILTER_DRAWING_SELECTED,
        }
        self.dispatcher.dispatch(SetDisplayFiltersAction(initial_filters))
        self._update_drawing_combo()

        project = QgsProject.instance()
        if project is not None:
            project.layersAdded.connect(self._update_drawing_combo)
            project.layersRemoved.connect(self._update_drawing_combo)

        if self.point_layer and self.point_layer.isValid() and self.layer_manager:
            current_settings = self.layer_manager.load_settings() if hasattr(self.layer_manager, "load_settings") else None
            self.layer_manager.apply_point_symbology(self.point_layer, current_settings)
        self.update_symbology_opacity()

        self._update_main_map_tool_state()
        self._sync_inputs_to_state()

        # UI強制同期
        all_keys = self.state_store.state.__dict__.keys()
        fake_diff = {k: getattr(self.state_store.state, k) for k in all_keys}
        self._on_state_changed(self.state_store.state, fake_diff)

    def _init_ui(self) -> None:
        root_widget = QWidget(self)
        root_layout = QVBoxLayout(root_widget)
        root_layout.setContentsMargins(UIConfig.PANEL_MARGIN, UIConfig.PANEL_MARGIN, UIConfig.PANEL_MARGIN, UIConfig.PANEL_MARGIN)
        root_layout.setSpacing(0)

        # 1. Top button row
        top_row = QWidget(root_widget)
        top_layout = QHBoxLayout(top_row)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(UIConfig.TOP_ROW_BUTTON_SPACING)

        self.btn_top_image = QPushButton(UILabels.BTN_TOP_IMAGE, top_row)
        self.btn_top_image.clicked.connect(lambda: self.image_dialog.show() if self.image_dialog else None)
        top_layout.addWidget(self.btn_top_image)

        self.btn_top_settings = QPushButton(UILabels.BTN_TOP_SETTINGS, top_row)
        self.btn_top_settings.clicked.connect(lambda: self.settings_dialog.show() if self.settings_dialog else None)
        top_layout.addWidget(self.btn_top_settings)

        self.btn_top_output = QPushButton(UILabels.BTN_TOP_OUTPUT, top_row)
        self.btn_top_output.clicked.connect(lambda: self.output_dialog.show() if self.output_dialog else None)
        top_layout.addWidget(self.btn_top_output)

        self.btn_save_project = QPushButton(UILabels.BTN_TOP_SAVE, top_row)
        UIStyleHelper.set_success_button(self.btn_save_project)
        self.btn_save_project.clicked.connect(self._save_project)
        top_layout.addWidget(self.btn_save_project)

        root_layout.addWidget(top_row)
        root_layout.addWidget(UIStyleHelper.build_separator(root_widget))

        # Sub dialogs
        self.tab1_container = create_tab1_ui(self)
        self.image_dialog = ImageDialog(self.tab1_container, on_show=self._update_main_map_tool_state, on_close=self._update_main_map_tool_state, parent=self)

        self.tab3_container = create_tab3_ui(self)
        self.settings_dialog = ModelessSectionDialog(UILabels.TAB_3_TITLE, self.tab3_container, on_show=self._update_main_map_tool_state, on_close=self._update_main_map_tool_state, parent=self, width=UIDialogSizes.SETTINGS_DIALOG_WIDTH, height=UIDialogSizes.SETTINGS_DIALOG_HEIGHT)

        self.tab4_container = create_tab4_ui(self)
        self.output_dialog = ModelessSectionDialog(UILabels.TAB_4_TITLE, self.tab4_container, on_show=self._update_main_map_tool_state, on_close=self._update_main_map_tool_state, parent=self, width=UIDialogSizes.OUT_DIALOG_WIDTH, height=UIDialogSizes.OUT_DIALOG_HEIGHT)

        # Tab2 Main container
        self.tab2_container = self._create_tab2_ui()
        root_layout.addWidget(self.tab2_container, 1)

        root_widget.setFixedWidth(UIConfig.DOCK_WIDTH)
        self.setWidget(root_widget)

    def _create_tab2_ui(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(UIConfig.PANEL_CONTAINER_MARGIN_LEFT, 0, UIConfig.PANEL_CONTAINER_MARGIN_RIGHT, UIConfig.PANEL_MARGIN)
        layout.setSpacing(0)

        self.panel_mode = CoreUIBuilder.build(TAB2_MODE_TOGGLE_SPEC, parent=container)
        layout.addWidget(self.panel_mode.widget)
        layout.addSpacing(UIConfig.PANEL_MARGIN)

        self.panel_point_info = CoreUIBuilder.build(TAB2_POINT_INFO_SPEC, parent=container)
        self.lbl_point_info_status = QLabel(self.panel_point_info.get("point_info_summary"))
        self.lbl_point_info_status.setWordWrap(True)
        self.panel_point_info.get("point_info_summary").layout().addWidget(self.lbl_point_info_status)
        layout.addWidget(self.panel_point_info.widget)
        layout.addWidget(UIStyleHelper.build_separator(container))

        self.panel_attribute = CoreUIBuilder.build(TAB2_ATTRIBUTE_SPEC, parent=container)
        layout.addWidget(self.panel_attribute.widget)
        layout.addWidget(UIStyleHelper.build_separator(container))

        self.panel_display = CoreUIBuilder.build(TAB2_DISPLAY_FILTER_SPEC, parent=container)
        btn_filter = self.panel_display.get("filter_toggle")
        btn_filter.setCheckable(True)
        
        table_drawing = self.panel_display.get("drawing_list_table")
        table_drawing.setSelectionBehavior(QTableWidget.SelectRows)
        table_drawing.setSelectionMode(QTableWidget.SingleSelection)
        table_drawing.verticalHeader().setVisible(False)
        table_drawing.horizontalHeader().setStretchLastSection(True)
        table_drawing.setColumnWidth(0, 40)
        table_drawing.itemSelectionChanged.connect(self._on_drawing_table_selection_changed)
        table_drawing.horizontalHeader().sectionClicked.connect(self._on_drawing_table_header_clicked)
        
        layout.addWidget(self.panel_display.widget)
        layout.addStretch()

        # =========================================================================
        # イベントマッピング (auto_bind)
        # =========================================================================
        def update_inputs_action(*args):
            return UpdateDigitizingInputsAction(inputs=self._collect_tab2_inputs())
            
        def table_cell_changed_action(row, col):
            item = self.panel_display.get("drawing_list_table").item(row, col)
            if item and col == 0:
                layer_id = item.data(Qt.UserRole)
                if layer_id:
                    return SetDrawingLayerVisibilityAction(layer_id=layer_id, visible=(item.checkState() == Qt.Checked))
            return None

        # パネルイベントのバインド
        self.panel_mode.auto_bind(self.dispatcher, {
            "mode_changed": lambda idx: ChangeTab2ModeAction(mode="new" if idx == 0 else "edit")
        })

        self.panel_point_info.auto_bind(self.dispatcher, {
            "autonum_mode_changed": lambda idx: ChangeAutonumModeAction(mode="auto" if idx == 0 else "release"),
            "point_identity_changed": update_inputs_action,
            "branch_text_changed": update_inputs_action,
            "delete_point_clicked": lambda: DeletePointAction(point_id=self.state_store.state.selected_point_id) if self.state_store.state.selected_point_id is not None else None,
        })

        self.panel_attribute.auto_bind(self.dispatcher, {
            "category_changed": update_inputs_action,
            "excavation_type_changed": update_inputs_action,
            "feature_combo_changed": update_inputs_action,
            "manage_feature_clicked": lambda: OpenFeatureManageAction(),
        })

        self.panel_display.auto_bind(self.dispatcher, {
            "filter_toggled": lambda checked: SetFocusModeAction(active=checked),
            "filter_settings_clicked": lambda: self._show_display_filter_dialog() or None,
            "ref_point_visibility_changed": lambda idx: SetRefLayerVisibilityAction(visible=(idx == 0)),
            "drawing_table_cell_changed": table_cell_changed_action,
        })

        scroll.setWidget(container)
        return scroll

    def _collect_tab2_inputs(self) -> Dict[str, Any]:
        """UIから現在入力されている値を抽出する"""
        combo_attr = self.panel_attribute.get("attribute_code")
        attr_val = combo_attr.currentData() or combo_attr.currentText()
        is_sp = (attr_val == AttributeType.SP.value)
        pname = self.panel_point_info.get_value("point_name_sp") if is_sp else str(self.panel_point_info.get_value("point_name"))
        
        return {
            "attribute_code": attr_val,
            "excavation_type": self.panel_attribute.get_value("excavation_type"),
            "feature_name": self.panel_attribute.get_value("feature_name"),
            "point_name": pname,
            "branch_no": self.panel_point_info.get_value("branch_no"),
        }

    def _sync_inputs_to_state(self):
        """初期化時や必要なタイミングでUIの値をStateに反映させる"""
        self.dispatcher.dispatch(UpdateDigitizingInputsAction(inputs=self._collect_tab2_inputs()))

    # =========================================================================
    # 副作用のあるUIダイアログ表示 (Viewの責務)
    # =========================================================================
    def _show_display_filter_dialog(self):
        """表示設定のOSネイティブダイアログを開き、結果をActionに変換する"""
        dlg = DisplayFilterDialog(parent=self, feature_names=self.state_store.state.feature_name_list, initial_filters=self.state_store.state.display_filters)
        if dlg.exec_() == QDialog.Accepted:
            self.dispatcher.dispatch(SetDisplayFiltersAction(filters=dlg.get_filters()))
            self.dispatcher.dispatch(SetFocusModeAction(active=True))

    # =========================================================================
    # UI 同期と状態管理 (on_state_changed)
    # =========================================================================
    def _on_state_changed(self, new_state, diff: Dict[str, Any]) -> None:
        if "tab2_mode" in diff:
            is_new = (new_state.tab2_mode == "new")
            self.panel_point_info.get_row("autonum_mode").setVisible(is_new)
            self.panel_point_info.get_row("edit_mode_actions").setVisible(not is_new)
            self.panel_point_info.get_row("point_name").setEnabled(is_new)
            self.panel_point_info.get_row("point_name_sp").setEnabled(is_new)
            self.panel_point_info.get_row("branch_no").setEnabled(is_new)
            self.panel_attribute.widget.setEnabled(is_new)

        if "selected_point_id" in diff and new_state.selected_point_id is None:
            if self.map_tool: self.map_tool.clear_selected_marker()

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
            
            self.update_symbology_opacity()
            self._update_map_tool_focus_state()

        if "has_input_error" in diff and new_state.has_input_error and new_state.status_message:
            QMessageBox.warning(self, UIMessages.ERR_TITLE_INPUT, new_state.status_message)
            self.dispatcher.dispatch(SetValidationAction(has_error=False, message=""))

        if "feature_name_list" in diff:
            combo = self.panel_attribute.get("feature_name")
            current_text = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(UILabels.UNREGISTERED)
            combo.addItems([name for name in new_state.feature_name_list if name != UILabels.UNREGISTERED])
            idx = combo.findText(current_text)
            if idx >= 0: combo.setCurrentIndex(idx)
            combo.blockSignals(False)

        if "digitizing_inputs" in diff:
            for field_id, value in new_state.digitizing_inputs.items():
                panel = self.panel_point_info if field_id in ["point_name", "point_name_sp", "branch_no"] else self.panel_attribute if field_id in ["attribute_code", "excavation_type", "feature_name"] else None
                if panel:
                    widget = panel.get(field_id)
                    widget.blockSignals(True)
                    panel.set_value(field_id, value)
                    widget.blockSignals(False)
                    
            # 属性によって入力ウィジェットの表示切り替え
            is_sp = (new_state.digitizing_inputs.get("attribute_code") == AttributeType.SP.value)
            self.panel_point_info.get_row("point_name").setVisible(not is_sp)
            self.panel_point_info.get_row("point_name_sp").setVisible(is_sp)
            buttons = self.panel_point_info.get_buttons("autonum_mode")
            if is_sp:
                if not buttons[1].isChecked(): buttons[1].setChecked(True)
                buttons[0].setEnabled(False); buttons[1].setEnabled(False)
            else:
                buttons[0].setEnabled(True); buttons[1].setEnabled(True)
                
            is_feat = (new_state.digitizing_inputs.get("excavation_type") == ExcavationType.FEATURE.value)
            self.panel_attribute.get_row("feature_name").setVisible(is_feat)
            self.panel_attribute.get_row("feature_actions").setVisible(is_feat)

        if "is_processing" in diff:
            if new_state.is_processing:
                from qgis.PyQt.QtWidgets import QApplication
                QApplication.setOverrideCursor(Qt.WaitCursor)
                self.setEnabled(False)
                if self.map_tool: self.map_tool.set_interaction_locked(True)
            else:
                from qgis.PyQt.QtWidgets import QApplication
                self.setEnabled(True)
                QApplication.restoreOverrideCursor()
                if self.map_tool: self.map_tool.set_interaction_locked(False)
                
        # 連番のUI表示とエラーハイライト
        if any(k in diff for k in ("digitizing_inputs", "point_info_has_error", "is_out_of_bounds", "status_message")):
            inputs = new_state.digitizing_inputs
            pname = inputs.get("point_name_sp") if self.panel_attribute.get_value("attribute_code") == AttributeType.SP.value else str(inputs.get("point_name", ""))
            status_type = "error" if new_state.point_info_has_error else "info"
            
            # Controller から渡された status_message があれば優先、なければデフォルト
            status_text = new_state.status_message if new_state.status_message else (
                UILabels.STATUS_ERR_OUT_OF_BOUNDS if new_state.is_out_of_bounds else (
                    UILabels.STATUS_ERR_DUPLICATE if new_state.point_info_has_error else UILabels.STATUS_NEW_POINT
                )
            )
            
            summary_text = f"{status_text}\n出土形態: {inputs.get('excavation_type', '-')}\n点名/枝番: {pname} {inputs.get('branch_no', '')}\nXY座標: -"
            UIStyleHelper.update_status_panel(self.panel_point_info.get("point_info_summary"), self.lbl_point_info_status, summary_text, status_type)
            
            is_dup = new_state.point_info_has_error and not new_state.is_out_of_bounds
            is_sp = (inputs.get("attribute_code") == AttributeType.SP.value)
            UIStyleHelper.set_error_border(self.panel_point_info.get("point_name"), is_dup and not is_sp)
            UIStyleHelper.set_error_border(self.panel_point_info.get("point_name_sp"), is_dup and is_sp)

    # =========================================================================
    # ヘルパー (図面リスト・レイヤ制御等)
    # =========================================================================
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

    def _restore_feature_names(self) -> None:
        if not self.point_layer or not self.point_layer.isValid(): return
        temp_list = []
        UIStyleHelper.populate_combo_from_layer_field(self.panel_attribute.get("feature_name"), self.point_layer, "feature_name", leading_item=UILabels.UNREGISTERED, target_list=temp_list)
        self.dispatcher.dispatch(SetFeatureCacheAction(feature_list=temp_list))

    def _get_drawing_layers(self) -> List[Tuple[str, str, bool]]:
        root = QgsProject.instance().layerTreeRoot()
        if not root: return []
        image_group = root.findGroup("画像ファイル")
        if not image_group: return []
        return [(l.layer().name(), l.layer().id(), l.itemVisibilityChecked()) for l in image_group.findLayers() if l.layer() and l.layer().isValid()]

    def _get_drawing_layer_names(self) -> List[str]:
        return [info[0] for info in self._get_drawing_layers()]

    def _update_drawing_combo(self, *args: Any) -> None:
        table = self.panel_display.get("drawing_list_table")
        current_selection = self.state_store.state.selected_drawing_name
        
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
        
        target_row = 0
        if current_selection and current_selection != UILabels.DRAWING_UNSPECIFIED:
            for r in range(1, table.rowCount()):
                if table.item(r, 1) and table.item(r, 1).text() == current_selection:
                    target_row = r
                    break
        table.selectRow(target_row)

    def _on_drawing_table_selection_changed(self) -> None:
        table = self.panel_display.get("drawing_list_table")
        sel_model = table.selectionModel()
        row = sel_model.selectedRows()[0].row() if sel_model and sel_model.selectedRows() else table.currentRow()
        d_name = table.item(row, 1).text().strip() if row > 0 and table.item(row, 1) else UILabels.DRAWING_UNSPECIFIED
        self.dispatcher.dispatch(SelectDrawingAction(drawing_name=d_name if d_name != UILabels.DRAWING_UNSPECIFIED else ""))

    def _on_drawing_table_header_clicked(self, logical_index: int) -> None:
        if logical_index != 0: return
        table = self.panel_display.get("drawing_list_table")
        if table.rowCount() <= 1: return
        first_item = table.item(1, 0)
        if not first_item: return
        
        new_state = (first_item.checkState() == Qt.Unchecked)
        self.dispatcher.dispatch(ToggleAllDrawingsVisibilityAction(visible=new_state))
        
        table.blockSignals(True)
        for row in range(1, table.rowCount()):
            if table.item(row, 0): table.item(row, 0).setCheckState(Qt.Checked if new_state else Qt.Unchecked)
        table.blockSignals(False)

    def update_symbology_opacity(self) -> None:
        if not self.point_layer or not self.point_layer.isValid(): return
        state = self.state_store.state
        is_focus_on = state.focus_active
        filters = dict(state.display_filters) if is_focus_on else {}
        if is_focus_on:
            filters["target_drawing_name"] = state.selected_drawing_name if filters.get("target_drawing") == UILabels.FILTER_DRAWING_SELECTED else None

        expr = self.layer_manager.build_opacity_expression(is_focus_on, filters, 0)
        self.layer_manager.apply_opacity_expression(self.point_layer, expr)
        if self.canvas: self.canvas.refresh()
    
    def _update_map_tool_focus_state(self) -> None:
        if not self.map_tool: return
        state = self.state_store.state
        filters = dict(state.display_filters) if state.display_filters else {}
        filters["target_drawing_name"] = state.selected_drawing_name if filters.get("target_drawing") == UILabels.FILTER_DRAWING_SELECTED else None
        self.map_tool.update_focus_state(state.focus_active, filters)

    def _update_main_map_tool_state(self) -> None:
        any_open = any(d is not None and d.isVisible() for d in (self.image_dialog, self.settings_dialog, self.output_dialog))
        if any_open:
            self.canvas.unsetMapTool(self.map_tool)
        else:
            self._update_drawing_combo()
            self.canvas.setMapTool(self.map_tool)

    def _save_project(self) -> None:
        if self.layer_manager.save_project():
            self.iface.messageBar().pushMessage(UIMessages.MSG_SAVE_TITLE, UIMessages.MSG_SAVE_SUCCESS, level=Qgis.MessageLevel.Success, duration=4)
        else:
            self.iface.messageBar().pushMessage(UIMessages.MSG_SAVE_TITLE, UIMessages.MSG_SAVE_FAILED, level=Qgis.MessageLevel.Warning, duration=5)

    def closeEvent(self, event: Any) -> None:
        try:
            if QgsProject.instance():
                QgsProject.instance().layersAdded.disconnect(self._update_drawing_combo)
                QgsProject.instance().layersRemoved.disconnect(self._update_drawing_combo)
        except Exception: pass
        for d in (self.image_dialog, self.settings_dialog, self.output_dialog):
            if d: d.close()
        if self.map_tool:
            self.canvas.unsetMapTool(self.map_tool)
            self.map_tool.clean_up()
        try:
            if QgsProject.instance().fileName():
                QgsProject.instance().write()
                QgsProject.instance().clear()
        except Exception: pass
        super().closeEvent(event)