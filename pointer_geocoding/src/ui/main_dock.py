"""
/***************************************************************************
 PointerGeocoding Plugin - Main Operation Dock Panel
 ***************************************************************************/
"""
# 【変更不可侵の絶対的ルール】 測量座標系（X軸=南北, Y軸=東西）を採用。QGISキャンバス上のX座標(東西)はSurvey Y、Y座標(南北)はSurvey Xに対応する。

import os
from contextlib import contextmanager
from typing import Optional, Dict, Any, List, Tuple

from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsRasterLayer,
    Qgis,
)
from qgis.gui import (
    QgisInterface,
    QgsMapCanvas,
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QIcon
from qgis.PyQt.QtWidgets import (
    QDockWidget,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QApplication,
    QTableWidgetItem,
    QScrollArea,
    QFrame,
    QLabel,
    QTableWidget,
    QDialog
)

from ..canvas.map_tool import CanvasDigitizingTool, ImageGeorefTool
from .style import UIStyleHelper
from .constants import UIConfig, UILabels, UIMessages, UIDialogSizes, UIPlaceholders
from .dialogs import ImageDialog, ModelessSectionDialog, DisplayFilterDialog, FeatureManageDialog
from .tab1_image import Tab1GeorefMixin
from .tab3_settings import Tab3SettingsMixin

# --- 新設・同元化する状態管理とUI基盤 ---
from .core.state import (
    UIStateStore, ChangeTab2ModeAction, ChangeAutonumModeAction, 
    SetFocusModeAction, ResetSelectionAction, SetFeatureCacheAction,
    SetPointInfoSummaryAction, SetDigitizedWithBranchAction, SetSuppressCommitAction
)
from .core.field_spec import ButtonDef, FieldSpec, PanelSpec, WidgetType
from .core.builder import CoreUIBuilder

# --- Controller (ロジック層) のインポート ---
from ..uilogic.digitizing_logic import DigitizingLogic
from ..uilogic.filter_logic import FilterLogic
from ..logic.core import AttributeType, ExcavationType, get_next_point_number, safe_get_str

# --- 分離された Tab4 (出力) のUI構築メソッド ---
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


class MainDockWidget(QDockWidget, Tab1GeorefMixin, Tab3SettingsMixin):
    
    INVALID_CHARS_PATTERN = r'[\\/:*?"<>|]'

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
        self.current_copied_image_path: Optional[str] = None
        self.confirmed_layer_name: Optional[str] = None
        self.calculated_affine_params: Optional[Tuple[float, float, float, float, float, float]] = None
        self.ref_points_data: List[Dict[str, Any]] = []

        # Tab 2: Digitizing state (Stateオブジェクトへ一括集約)
        self.state_store = UIStateStore(self)

        # -----------------------------------------------------------------
        # Step C: Controller (DigitizingLogic) の初期化とViewコールバックの登録
        # -----------------------------------------------------------------
        self.digitizing_logic = DigitizingLogic(
            self.state_store, self.layer_manager, self.layers_dict, self.iface, parent=self
        )
        
        self.filter_logic = FilterLogic(
            self.state_store, self.layer_manager, self.iface, parent=self
        )

        self.map_tool = CanvasDigitizingTool(
            self.canvas, self.point_layer, dock_widget=self, layer_manager=self.layer_manager
        )
        
        # キャンバスのイベントをControllerへ転送
        self.map_tool.canvas_clicked.connect(self.digitizing_logic.handle_canvas_click)
        self.map_tool.existing_point_selected.connect(self.digitizing_logic.handle_existing_point_selected)
        self.map_tool.blank_click_in_edit_mode.connect(
            lambda: self.state_store.dispatch(ResetSelectionAction())
        )
        
        self.layer_manager.settings_changed.connect(self._on_layer_manager_settings_changed)

        self._init_ui()
        UIStyleHelper.apply_theme(self)
        UIStyleHelper.apply_theme(self.image_dialog)
        UIStyleHelper.apply_theme(self.settings_dialog)
        UIStyleHelper.apply_theme(self.output_dialog)

        # ViewコールバックをControllerへバインド
        callbacks = {
            "get_digitizing_input_state": self.get_digitizing_input_state,
            "get_target_drawing_name": self._get_target_drawing_name,
            "is_sp_attribute": self._is_sp_attribute,
            "get_attribute_value": self._get_attribute_value,
            "get_current_point_name_and_branch": self._get_current_point_name_and_branch,
            "is_feature_name_missing": self._is_feature_name_missing,
            "busy_interaction_guard": self.busy_interaction_guard,
            "update_symbology_opacity": self.update_symbology_opacity,
            "get_drawing_layer_names": self._get_drawing_layer_names,
            "apply_next_point_number": self._apply_next_point_number,
            "refresh_point_info_labels": self._refresh_point_info_labels,
            "category_changed": self._category_changed_cb,
            "excavation_type_changed": self._excavation_type_changed_cb,
            "map_tool": self.map_tool,
            "parent_widget": self
        }
        self.digitizing_logic.bind_view_callbacks(callbacks)

        # BuiltPanel インスタンスをControllerへDI（イベントバインドはControllerで行う）
        self.digitizing_logic.bind_ui_panels(
            self.panel_mode, self.panel_point_info, self.panel_attribute, self.panel_display
        )
        self.filter_logic.bind_ui_panels(self.panel_display)

        # StateStoreの変更を監視してUIを自動同期
        self.state_store.state_changed.connect(self._on_state_changed)

        # View初期化
        self._init_tab2_comboboxes()
        self._restore_feature_names()
        self._update_drawing_combo()
        self.update_settings_ui_from_dict()

        project = QgsProject.instance()
        if project is not None:
            project.layersAdded.connect(self._update_drawing_combo)
            project.layersRemoved.connect(self._update_drawing_combo)

        if self.point_layer and self.point_layer.isValid() and self.layer_manager:
            current_settings = (
                self.layer_manager.load_settings()
                if hasattr(self.layer_manager, "load_settings")
                else None
            )
            self.layer_manager.apply_point_symbology(self.point_layer, current_settings)
        self.update_symbology_opacity()

        try:
            layer_tree_dock = self.iface.mainWindow().findChild(QDockWidget, "Layer Tree")
            if layer_tree_dock:
                layer_tree_dock.hide()
        except Exception:
            pass

        self._update_main_map_tool_state()

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
        self.btn_top_image.setObjectName("btnTopImage")
        self.btn_top_image.setIcon(self._load_icon("image.svg"))
        self.btn_top_image.clicked.connect(self._show_image_dialog)
        top_layout.addWidget(self.btn_top_image)

        self.btn_top_settings = QPushButton(UILabels.BTN_TOP_SETTINGS, top_row)
        self.btn_top_settings.setObjectName("btnTopSettings")
        self.btn_top_settings.setIcon(self._load_icon("setting.svg"))
        self.btn_top_settings.clicked.connect(self._show_settings_dialog)
        top_layout.addWidget(self.btn_top_settings)

        self.btn_top_output = QPushButton(UILabels.BTN_TOP_OUTPUT, top_row)
        self.btn_top_output.setObjectName("btnTopOutput")
        self.btn_top_output.setIcon(self._load_icon("output.svg"))
        self.btn_top_output.clicked.connect(self._show_output_dialog)
        top_layout.addWidget(self.btn_top_output)

        self.btn_save_project = QPushButton(UILabels.BTN_TOP_SAVE, top_row)
        self.btn_save_project.setObjectName("btnTopSave")
        self.btn_save_project.setIcon(self._load_icon("save.svg"))
        UIStyleHelper.set_success_button(self.btn_save_project)
        self.btn_save_project.clicked.connect(self._save_project)
        top_layout.addWidget(self.btn_save_project)

        root_layout.addWidget(top_row)
        root_layout.addWidget(UIStyleHelper.build_separator(root_widget))

        # 2. 画像 dialog
        self.tab1_container = self._create_tab1_ui()
        self.image_dialog = ImageDialog(
            self.tab1_container, on_show=self._update_main_map_tool_state,
            on_close=self._update_main_map_tool_state, parent=self,
        )

        # 3. 設定 dialog
        self.tab3_container = self._create_tab3_ui()
        self.settings_dialog = ModelessSectionDialog(
            UILabels.TAB_3_TITLE, self.tab3_container,
            on_show=self._update_main_map_tool_state,
            on_close=self._update_main_map_tool_state,
            parent=self, width=UIDialogSizes.SETTINGS_DIALOG_WIDTH, height=UIDialogSizes.SETTINGS_DIALOG_HEIGHT,
        )

        # 4. 出力 dialog
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
    # MainDockWidget メソッド (Tab2 UI構築)
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

        # 1. モード切替パネル (バインドはControllerで行う)
        self.panel_mode = CoreUIBuilder.build(TAB2_MODE_TOGGLE_SPEC, parent=container)
        layout.addWidget(self.panel_mode.widget)
        layout.addSpacing(UIConfig.PANEL_MARGIN)

        # 2. 点情報パネル
        self.panel_point_info = CoreUIBuilder.build(TAB2_POINT_INFO_SPEC, parent=container)
        self.lbl_point_info_status = QLabel(self.panel_point_info.get("point_info_summary"))
        self.lbl_point_info_status.setWordWrap(True)
        self.panel_point_info.get("point_info_summary").layout().addWidget(self.lbl_point_info_status)
        UIStyleHelper.update_status_panel(
            self.panel_point_info.get("point_info_summary"), 
            self.lbl_point_info_status, 
            UILabels.STATUS_NEW_POINT, 
            "info"
        )
        layout.addWidget(self.panel_point_info.widget)
        layout.addWidget(UIStyleHelper.build_separator(container))

        # 3. 属性パネル
        self.panel_attribute = CoreUIBuilder.build(TAB2_ATTRIBUTE_SPEC, parent=container)
        self.panel_attribute.bind("manage_feature_clicked", self._on_manage_feature_clicked)  # Viewの責務
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
        table_drawing_list.setStyleSheet(
            "QTableView::indicator { subcontrol-position: center; }"
            "QTableView { border: none; }"
            "QTableView::item:focus { border: none; outline: none; }"
        )
        table_drawing_list.verticalHeader().setVisible(False)
        table_drawing_list.verticalHeader().setMinimumSectionSize(20)
        table_drawing_list.verticalHeader().setDefaultSectionSize(20)
        header = table_drawing_list.horizontalHeader()
        header.setStretchLastSection(True)
        header.resizeSection(0, 40)
        table_drawing_list.setColumnWidth(0, 40)
        
        layout.addWidget(self.panel_display.widget)
        layout.addStretch()

        scroll.setWidget(container)
        return scroll

    def _init_tab2_comboboxes(self) -> None:
        """UI初期化として、コンボボックスの選択肢（定数）だけをロードする"""
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
    # View State Sync & Helper Methods (旧 Mixin から復元)
    # =========================================================================

    def _on_state_changed(self, new_state, diff: Dict[str, Any]) -> None:
        """UIStateStoreの変更を検知し、UIの表示状態をリアクティブに同期する"""
        if "tab2_mode" in diff:
            is_new = (new_state.tab2_mode == "new")
            self.panel_point_info.get_row("autonum_mode").setVisible(is_new)
            self.panel_point_info.get_row("edit_mode_actions").setVisible(not is_new)
            self.panel_point_info.get_row("point_name").setEnabled(is_new)
            self.panel_point_info.get_row("point_name_sp").setEnabled(is_new)
            self.panel_point_info.get_row("branch_no").setEnabled(is_new)
            self.panel_attribute.widget.setEnabled(is_new)

        if "selected_point_id" in diff and new_state.selected_point_id is None:
            if self.map_tool:
                self.map_tool.clear_selected_marker()

        if "focus_active" in diff or "display_filters" in diff:
            self._push_focus_state_to_tool()
            self.update_symbology_opacity()

        if any(k in diff for k in ("point_info_summary", "point_info_has_error", "is_out_of_bounds", "status_message", "selected_point_id")):
            self._update_point_info_status_ui(new_state)

    def _update_point_info_status_ui(self, state):
        summary = state.point_info_summary
        status_text = state.status_message
        status_type = "info"
        
        if state.point_info_has_error:
            status_type = "error"
        elif state.selected_point_id is not None:
            status_type = "warning"
            if not status_text:
                status_text = UILabels.STATUS_EDIT_POINT
        else:
            if not status_text:
                status_text = UILabels.STATUS_NEW_POINT
                
        full_text = f"{status_text}\n" \
                    f"{UILabels.LBL_INFO_GROUP_OR_FEATURE} {summary.get('group', '-')}\n" \
                    f"{UILabels.LBL_INFO_POINT_BRANCH} {summary.get('pointname', '-')}\n" \
                    f"{UILabels.LBL_INFO_COORDS} {summary.get('coords', '-')}"
                    
        UIStyleHelper.update_status_panel(
            self.panel_point_info.get("point_info_summary"), 
            self.lbl_point_info_status, 
            full_text, 
            status_type
        )
        
        is_feat_missing = self._is_feature_name_missing()
        is_dup = state.point_info_has_error and status_text == UILabels.STATUS_ERR_DUPLICATE
        
        UIStyleHelper.set_error_border(self.panel_attribute.get("feature_name"), is_feat_missing)
        is_sp = self._is_sp_attribute()
        UIStyleHelper.set_error_border(self.panel_point_info.get("point_name"), is_dup and not is_sp)
        UIStyleHelper.set_error_border(self.panel_point_info.get("point_name_sp"), is_dup and is_sp)

    def _update_point_name_widget_visibility(self):
        is_sp = self._is_sp_attribute()
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

    def _apply_next_point_number(self):
        self._update_point_name_widget_visibility()
        if self._is_sp_attribute():
            self.panel_point_info.set_value("point_name_sp", "")
        elif self.state_store.state.autonum_mode == "auto":
            ex_type = self.panel_attribute.get_value("excavation_type")
            feat_name = self.panel_attribute.get_value("feature_name")
            if feat_name in (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成")):
                feat_name = ""
            next_num = get_next_point_number(self.point_layer, ex_type, feat_name)
            self.panel_point_info.set_value("point_name", next_num)
        self._refresh_point_info_labels()

    def _refresh_point_info_labels(self):
        ex_type = self.panel_attribute.get_value("excavation_type")
        if ex_type == ExcavationType.FEATURE.value:
            group_label = self.panel_attribute.get_value("feature_name")
        else:
            group_label = ExcavationType.GRID.value
        
        pname, branch = self._get_current_point_name_and_branch()
        pn_display = f"{pname} {branch}".strip() if pname else ""
        
        summary = {
            "group": group_label or "-",
            "pointname": pn_display or "-",
            "coords": "-",
        }
        self.state_store.dispatch_silent(SetPointInfoSummaryAction(summary))

    def _category_changed_cb(self):
        self._update_point_name_widget_visibility()
        if self.state_store.state.selected_point_id is None:
            self._apply_next_point_number()
        self._push_focus_state_to_tool()
        if self.state_store.state.focus_active:
            self.update_symbology_opacity()

    def _excavation_type_changed_cb(self):
        is_feat = self.panel_attribute.get_value("excavation_type") == ExcavationType.FEATURE.value
        self.panel_attribute.get_row("feature_name").setVisible(is_feat)
        self.panel_attribute.get_row("feature_actions").setVisible(is_feat)
        self._category_changed_cb()

    def _on_manage_feature_clicked(self) -> None:
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

        dlg = FeatureManageDialog(parent=self, feature_colors=feature_colors, on_update_callback=self._rename_and_recolor_feature)
        UIStyleHelper.apply_theme(dlg)
        if dlg.exec_() == QDialog.Accepted:
            new_name = dlg.result_text.strip()
            if new_name:
                if hasattr(dlg, "result_color") and dlg.result_color:
                    self.state_store.dispatch_silent(SetFeatureCacheAction(color_hex=dlg.result_color))
                if new_name not in self.state_store.state.feature_name_list:
                    temp_list = list(self.state_store.state.feature_name_list)
                    temp_list.append(new_name)
                    self.panel_attribute.get("feature_name").addItem(new_name)
                    self.state_store.dispatch(SetFeatureCacheAction(feature_list=temp_list))
                idx = self.panel_attribute.get("feature_name").findText(new_name)
                if idx >= 0:
                    self.panel_attribute.get("feature_name").setCurrentIndex(idx)

    def _rename_and_recolor_feature(self, old_name: str, new_name: str, new_color: str) -> None:
        if not self.point_layer or not self.point_layer.isValid():
            return
        fields = self.point_layer.fields()
        feat_idx = fields.indexFromName("feature_name")
        color_idx = fields.indexFromName("color_code")
        if feat_idx == -1 or color_idx == -1:
            return

        self.point_layer.startEditing()
        for feat in self.point_layer.getFeatures():
            if safe_get_str(feat, "feature_name") == old_name:
                self.point_layer.changeAttributeValue(feat.id(), feat_idx, new_name)
                self.point_layer.changeAttributeValue(feat.id(), color_idx, new_color)
        self.point_layer.commitChanges()

        self.state_store.dispatch_silent(SetSuppressCommitAction(True))
        try:
            temp_list = list(self.state_store.state.feature_name_list)
            if old_name in temp_list:
                temp_list[temp_list.index(old_name)] = new_name
            elif new_name not in temp_list:
                temp_list.append(new_name)
            
            combo = self.panel_attribute.get("feature_name")
            cur_text = combo.currentText()
            found_idx = combo.findText(old_name)
            if found_idx >= 0:
                combo.setItemText(found_idx, new_name)
                if cur_text == old_name:
                    combo.setCurrentIndex(found_idx)
            else:
                new_idx = combo.findText(new_name)
                if new_idx < 0:
                    combo.addItem(new_name)
                    new_idx = combo.findText(new_name)
                if cur_text == old_name:
                    combo.setCurrentIndex(new_idx)

            if combo.currentText() == new_name:
                self.state_store.dispatch_silent(SetFeatureCacheAction(color_hex=new_color, feature_list=temp_list))
            else:
                self.state_store.dispatch_silent(SetFeatureCacheAction(feature_list=temp_list))
        finally:
            self.state_store.dispatch_silent(SetSuppressCommitAction(False))

        self.digitizing_logic.validate_and_sync()

    def _restore_feature_names(self) -> None:
        if not self.point_layer or not self.point_layer.isValid():
            return
        combo = self.panel_attribute.get("feature_name")
        temp_list = []
        UIStyleHelper.populate_combo_from_layer_field(
            combo, self.point_layer, "feature_name", leading_item=UILabels.UNREGISTERED, target_list=temp_list
        )
        self.state_store.dispatch_silent(SetFeatureCacheAction(feature_list=temp_list))

    # --- Controllerに提供する View値の取得コールバック群 ---

    def _is_sp_attribute(self) -> bool:
        return self._get_attribute_value() == AttributeType.SP.value

    def _get_attribute_value(self) -> str:
        combo = self.panel_attribute.get("attribute_code")
        return combo.currentData() or combo.currentText()

    def _get_current_point_name_and_branch(self) -> Tuple[str, str]:
        if self._is_sp_attribute():
            pname = self.panel_point_info.get("point_name_sp").text().strip()
        else:
            pname = str(self.panel_point_info.get("point_name").value())
        branch = self.panel_point_info.get("branch_no").text().strip()
        return pname, branch

    def _is_feature_name_missing(self) -> bool:
        if self.panel_attribute.get("excavation_type").currentText() != ExcavationType.FEATURE.value:
            return False
        feat = self.panel_attribute.get("feature_name").currentText().strip()
        return not feat or feat in (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成"))

    def get_digitizing_input_state(self) -> Dict[str, Any]:
        pname, branch = self._get_current_point_name_and_branch()
        ex_type = self.panel_attribute.get_value("excavation_type")
        feat_name = self.panel_attribute.get_value("feature_name")
        is_feat = (ex_type == ExcavationType.FEATURE.value)
        is_missing = is_feat and (not feat_name or feat_name in (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成")))
        
        can_click = True
        error_msg = ""
        if not pname:
            can_click = False
            error_msg = UIMessages.ERR_POINT_NAME_REQUIRED
        elif is_missing:
            can_click = False
            error_msg = UIMessages.ERR_NEW_FEATURE_REQUIRED
            
        return {
            "can_click": can_click,
            "error_message": error_msg,
            "drawing_name": self._get_target_drawing_name(),
            "excavation_type": ex_type,
            "feature_name": feat_name,
            "color_code": self.state_store.state.current_feature_color,
            "attribute_type": self._get_attribute_value(),
            "point_name": pname,
            "branch_no": branch
        }

    # --- 図面リスト（描画テーブル）の制御ロジック ---

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
        item_col0 = QTableWidgetItem()
        item_col0.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        item_col0.setCheckState(Qt.Unchecked)
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

    def _push_focus_state_to_tool(self) -> None:
        if self.map_tool is not None:
            state = self.state_store.state
            self.map_tool.update_focus_state(state.focus_active, state.display_filters)

    def _show_image_dialog(self) -> None:
        self.image_dialog.show()
        self.image_dialog.raise_()
        self.image_dialog.activateWindow()

    def _show_settings_dialog(self) -> None:
        self.update_settings_ui_from_dict()
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

    @contextmanager
    def busy_interaction_guard(self):
        tool = getattr(self, "map_tool", None)
        if tool and hasattr(tool, "set_interaction_locked"):
            tool.set_interaction_locked(True)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        
        original_title = self.windowTitle()
        self.setWindowTitle(f"{original_title} - [処理中...]")
        self.setEnabled(False)
        try:
            yield
        finally:
            self.setEnabled(True)
            self.setWindowTitle(original_title)
            QApplication.restoreOverrideCursor()
            if tool and hasattr(tool, "set_interaction_locked"):
                tool.set_interaction_locked(False)

    def update_symbology_opacity(self) -> None:
        if not self.point_layer or not self.point_layer.isValid():
            return

        with self.busy_interaction_guard():
            state = self.state_store.state
            is_focus_on = state.focus_active
            filters = state.display_filters if is_focus_on else {}

            expr = self.layer_manager.build_opacity_expression(is_focus_on, filters, 0)
            self.layer_manager.apply_opacity_expression(self.point_layer, expr)

            if hasattr(self, "canvas") and self.canvas:
                self.canvas.refresh()

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

        self._destroy_preview_canvas()
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