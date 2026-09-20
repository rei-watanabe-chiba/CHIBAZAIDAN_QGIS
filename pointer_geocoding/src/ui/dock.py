"""
/***************************************************************************
 PointerGeocoding Plugin - Main Operation Dock Panel
 ***************************************************************************/

Stage B split (mechanical, logic-preserving): the UI-construction and
event-handling code for each tab previously lived directly in this file.
It has been extracted, without any logic changes, into per-tab mixin
modules (tab1_georef_mixin.py, tab2_digitizing_mixin.py,
tab3_settings_mixin.py) plus shared constant/dialog modules
(main_dock_constants.py, main_dock_dialogs.py). MainDockWidget now mixes
those tab mixins in and keeps only the shared/common members: __init__,
the preview_* backward-compatible properties, _init_ui,
_update_main_map_tool_state (formerly _on_tab_changed / _on_panel_changed;
see T-0020/T-0024 notes below), _save_project, closeEvent, and
update_symbology_opacity (shared by Tab 2's Focus Mode and Tab 3's
settings-apply flow).

Stage E split (logic-preserving relocation): update_symbology_opacity()'s
expression-construction and renderer-mutation logic now lives in
SymbologyMixin (symbology_mixin.py) as build_opacity_expression()/
apply_opacity_expression(), reached here via self.layer_manager (which
mixes SymbologyMixin in). update_symbology_opacity() itself remains as a
thin delegator that only gathers current UI state, so its name/signature
and all call sites (tab2_digitizing_mixin.py, and
_update_main_map_tool_state below) are unchanged.

T-0020 (UI restructure, superseded by T-0021/T-0024, kept for history): the
former QTabWidget (Tab1/Tab2/Tab3) was replaced with a left icon rail +
collapsible side panel layout. Tab 2 (遺物点作成) became a permanently
visible main area rather than a tab.

T-0021 (dock split, superseded by T-0024, kept for history): the icon rail
+ collapsible side panel was moved out of this class's own QDockWidget
layout into a second, independent QDockWidget (self.left_dock), registered
by plugin.py in Qt.LeftDockWidgetArea.

T-0024 (left dock removal, top 4-button row + modeless dialogs): the left
dock (self.left_dock) and its icon rail / collapsible side panel
(self.side_panel / self.side_stack / self.nav_btn_drawing /
self.nav_btn_settings) have been removed entirely. self (the single
remaining dock, Qt.RightDockWidgetArea) now starts with a top row of four
buttons -- 画像 / 設定 / 出力 / 保存 -- built by _init_ui(), followed by the
always-visible main digitizing area (self.tab2_container, former Tab 2,
unchanged). 画像/設定/出力 each open their own independent modeless dialog
(self.image_dialog / self.settings_dialog / self.output_dialog, see
main_dock_dialogs.py's ImageDialog / ModelessSectionDialog) hosting the
content Tab1GeorefMixin/Tab3SettingsMixin/Tab2DigitizingMixin's
_create_tab1_ui() / _create_tab3_ui() / _create_tab4_ui() build (T-0034:
renamed from _create_output_ui() to align with the tab1/tab2/tab3 naming
pattern); 保存
keeps calling _save_project() directly as before, just relocated into the
button row. Since all three dialogs are modeless and independently
reopenable, the former single side-panel-driven digitizing-tool
suspend/resume logic (_on_nav_button_clicked / _on_panel_changed /
_close_side_panel / self._active_panel) has been replaced by
_update_main_map_tool_state(), which any dialog's on_show/on_close callback
invokes: the main canvas digitizing tool (self.map_tool) is suspended while
at least one of the three dialogs is open, and restored once none remain
open. self.tab1_container / self.tab2_container / self.tab3_container
attribute names are kept unchanged for backward compatibility with
tab*_mixin.py.
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
)

from ..canvas.map_tool import CanvasDigitizingTool, ImageGeorefTool
from .style import UIStyleHelper
# NOTE: UIConfig is not used directly in this module's own body, but is
# re-exported here (rather than only via main_dock_constants) because
# layer_manager.py and map_tool.py perform ``from .main_dock import UIConfig``
# at call time. Keeping this import preserves that existing cross-module
# contract unchanged after the Stage B mechanical split.
from .constants import UIConfig, UILabels, UIMessages, UIDialogSizes
from .dialogs import ImageDialog, ModelessSectionDialog
from .tab1_image import Tab1GeorefMixin
from .tab2_plot import Tab2DigitizingMixin
from .tab3_settings import Tab3SettingsMixin
from .tab2.tab2_state import Tab2State


class MainDockWidget(QDockWidget, Tab1GeorefMixin, Tab2DigitizingMixin, Tab3SettingsMixin):
    """Main dock widget hosting Tab 1 (Image Add & Pre-Georeferencing)
    and Tab 2 (Artifact Point Digitizing & CSV Export)."""

    INVALID_CHARS_PATTERN = r'[\\/:*?"<>|]'

    def __init__(
        self,
        iface: QgisInterface,
        layer_manager: Any,
        layers_dict: Optional[Dict[str, Any]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        """Initialize the main dock widget.

        :param iface: QGIS interface reference.
        :type iface: QgisInterface
        :param layer_manager: LayerManager instance.
        :type layer_manager: Any
        :param layers_dict: Dictionary containing active layer references.
        :type layers_dict: Optional[Dict[str, Any]]
        :param parent: Optional parent QWidget.
        :type parent: Optional[QWidget]
        """
        super().__init__(UILabels.DOCK_TITLE, parent)
        self.iface = iface
        self.layer_manager = layer_manager
        self.layers_dict = layers_dict or {}

        self.point_layer: Optional[QgsVectorLayer] = self.layers_dict.get("point_layer")
        self.ref_point_layer: Optional[QgsVectorLayer] = self.layers_dict.get("ref_point_layer")
        self.canvas: QgsMapCanvas = self.iface.mapCanvas()

        # Tab 1: Georeferencing preview state
        self.image_dialog: Optional[ImageDialog] = None
        self.current_copied_image_path: Optional[str] = None
        self.confirmed_layer_name: Optional[str] = None
        self.calculated_affine_params: Optional[Tuple[float, float, float, float, float, float]] = None
        # Reference points in memory: [{'name': str, 'pixel_x': float, 'pixel_y': float, 'real_x': float, 'real_y': float}]
        self.ref_points_data: List[Dict[str, Any]] = []

        # Tab 2: Digitizing state (Stateオブジェクトへ一括集約)
        self.tab2_state = Tab2State()

        # Main digitizing tool for real-world canvas
        self.map_tool = CanvasDigitizingTool(
            self.canvas, self.point_layer, dock_widget=self, layer_manager=self.layer_manager
        )
        self.map_tool.canvas_clicked.connect(self._on_canvas_clicked)
        self.map_tool.existing_point_selected.connect(self._on_existing_point_selected)
        self.map_tool.blank_click_in_edit_mode.connect(self._on_blank_click_in_edit_mode)
        
        self.layer_manager.settings_changed.connect(self._on_layer_manager_settings_changed)

        self._init_ui()
        UIStyleHelper.apply_theme(self)
        UIStyleHelper.apply_theme(self.image_dialog)
        UIStyleHelper.apply_theme(self.settings_dialog)
        UIStyleHelper.apply_theme(self.output_dialog)
        self._restore_feature_names()
        self._update_drawing_combo()
        self.update_settings_ui_from_dict()
        # Step3: push initial Focus Mode state now that the category widgets exist,
        # so map_tool's cache is valid before any canvas interaction.
        self._push_focus_state_to_tool()

        # Connect project layer additions/removals to dynamically update drawing combo box & list
        project = QgsProject.instance()
        if project is not None:
            project.layersAdded.connect(self._update_drawing_combo)
            project.layersRemoved.connect(self._update_drawing_combo)

        # Force initial reset of symbology and opacity to guarantee clean state (Option ①)
        if self.point_layer and self.point_layer.isValid() and self.layer_manager:
            current_settings = (
                self.layer_manager.load_settings()
                if hasattr(self.layer_manager, "load_settings")
                else None
            )
            self.layer_manager.apply_point_symbology(self.point_layer, current_settings)
        self.update_symbology_opacity()

        # Phase 1: Hide QGIS Layer Panel to prevent external operations
        try:
            layer_tree_dock = self.iface.mainWindow().findChild(QDockWidget, "Layer Tree")
            if layer_tree_dock:
                layer_tree_dock.hide()
        except Exception:
            pass

        # Initial map tool state (T-0024): no dialog is open by default, so
        # the digitizing main area (former Tab 2) is active immediately.
        self._update_main_map_tool_state()

    @property
    def preview_canvas(self) -> Optional[QgsMapCanvas]:
        """Backward compatible preview canvas reference."""
        return self.image_dialog.canvas if self.image_dialog else None

    @property
    def preview_raster_layer(self) -> Optional[QgsRasterLayer]:
        """Backward compatible preview raster layer reference."""
        return self.image_dialog.raster_layer if self.image_dialog else None

    @property
    def georef_tool(self) -> Optional[ImageGeorefTool]:
        """Backward compatible preview georef tool reference."""
        return self.image_dialog.georef_tool if self.image_dialog else None

    def _load_icon(self, filename: str) -> QIcon:
        """Load a top-row button icon from src/icon/<filename> (T-0024).

        :param filename: SVG file name under the plugin's icon/ directory.
        :type filename: str
        :return: QIcon instance (empty/null icon if the file is missing).
        :rtype: QIcon
        """
        icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "icon", filename)
        return QIcon(icon_path)

    def _init_ui(self) -> None:
        """Construct the single right-dock interface programmatically (T-0024).

        Builds a top row of four buttons (画像/設定/出力/保存) followed by the
        always-visible main digitizing area (self.tab2_container, former
        Tab 2). 画像/設定/出力 each own an independent modeless dialog
        (self.image_dialog / self.settings_dialog / self.output_dialog)
        hosting the content the corresponding tab mixin builds; see the
        T-0024 module-docstring note above.
        """
        root_widget = QWidget(self)
        root_layout = QVBoxLayout(root_widget)
        root_layout.setContentsMargins(
            UIConfig.PANEL_MARGIN,
            UIConfig.PANEL_MARGIN,
            UIConfig.PANEL_MARGIN,
            UIConfig.PANEL_MARGIN,
        )
        root_layout.setSpacing(0)

        # 1. Top button row: 画像 / 設定 / 出力 / 保存
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

        # T-0034: lightweight HLine separator visually distinguishing the
        # top button row from the always-visible main digitizing area below
        # it (self.tab2_container), matching the panel separators
        # Tab2DigitizingMixin uses internally (UIStyleHelper.build_separator).
        root_layout.addWidget(UIStyleHelper.build_separator(root_widget))

        # 2. 画像 dialog content (former Tab 1) + embedded preview canvas
        self.tab1_container = self._create_tab1_ui()
        self.image_dialog = ImageDialog(
            self.tab1_container,
            on_show=self._update_main_map_tool_state,
            on_close=self._update_main_map_tool_state,
            parent=self,
        )

        # 3. 設定 dialog content (former Tab 3)
        self.tab3_container = self._create_tab3_ui()
        self.settings_dialog = ModelessSectionDialog(
            UILabels.TAB_3_TITLE,
            self.tab3_container,
            on_show=self._update_main_map_tool_state,
            on_close=self._update_main_map_tool_state,
            parent=self,
            # 【ローカル編集】サイズ指定反映
            width=UIDialogSizes.SETTINGS_DIALOG_WIDTH,
            height=UIDialogSizes.SETTINGS_DIALOG_HEIGHT,
        )

        # 4. 出力 dialog content (CSV export, split out of former Tab 2)
        self.tab4_container = self._create_tab4_ui()
        self.output_dialog = ModelessSectionDialog(
            UILabels.TAB_4_TITLE,
            self.tab4_container,
            on_show=self._update_main_map_tool_state,
            on_close=self._update_main_map_tool_state,
            parent=self,
            # 【ローカル編集】サイズ指定反映
            width=UIDialogSizes.OUT_DIALOG_WIDTH,
            height=UIDialogSizes.OUT_DIALOG_HEIGHT,
        )

        # 5. Main area: 遺物点作成 (former Tab 2), always visible, no tab chrome
        self.tab2_container = self._create_tab2_ui()
        root_layout.addWidget(self.tab2_container, 1)

        # T-0025: fix the right dock's width instead of relying on QGIS's
        # default dock sizing.
        root_widget.setFixedWidth(UIConfig.DOCK_WIDTH)

        self.setWidget(root_widget)

    def _show_image_dialog(self) -> None:
        """Show (or raise) the 画像 (image management) dialog."""
        self.image_dialog.show()
        self.image_dialog.raise_()
        self.image_dialog.activateWindow()

    def _show_settings_dialog(self) -> None:
        """Show (or raise) the 設定 (settings) dialog, refreshing it from disk first."""
        self.update_settings_ui_from_dict()
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def _show_output_dialog(self) -> None:
        """Show (or raise) the 出力 (CSV export) dialog."""
        self.output_dialog.show()
        self.output_dialog.raise_()
        self.output_dialog.activateWindow()

    def _update_main_map_tool_state(self) -> None:
        """Suspend/restore the main canvas digitizing tool based on open dialogs (T-0024).

        Invoked as the on_show/on_close callback of all three modeless
        dialogs (self.image_dialog / self.settings_dialog /
        self.output_dialog). Since they are independently reopenable, the
        main digitizing tool (self.map_tool) is kept suspended as long as at
        least one of them is open, and only restored (plus a drawing-combo
        refresh, selection reset and Focus Mode re-application, mirroring
        the former _on_panel_changed()'s "both panels closed" branch) once
        none remain open.
        """
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
            self._reset_point_selection()

    @contextmanager
    def busy_interaction_guard(self):
        """Disable canvas hover and clicks, set Wait cursor, and disable UI during critical operations."""
        tool = getattr(self, "map_tool", None)
        if tool and hasattr(tool, "set_interaction_locked"):
            tool.set_interaction_locked(True)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        
        # Phase 1: Lock UI and show processing status
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
        """Update point layer symbol opacity dynamically using QgsProperty expression override.

        When Filter Mode is ON:
            Points and labels matching the filter criteria (attributes, excavation_types,
            feature_names, and drawing_name if selected) have 100% opacity,
            while non-matching points and labels have 0% opacity (completely hidden).
        When Filter Mode is OFF:
            All points and labels have 100% opacity.
        """
        if not self.point_layer or not self.point_layer.isValid():
            return

        with self.busy_interaction_guard():
            is_focus_on = self.is_focus_mode_active()
            filters: Dict[str, Any] = self.get_focus_category_filter() if is_focus_on else {}

            expr = self.layer_manager.build_opacity_expression(is_focus_on, filters, 0)
            self.layer_manager.apply_opacity_expression(self.point_layer, expr)

            if hasattr(self, "canvas") and self.canvas:
                self.canvas.refresh()


    def _save_project(self) -> None:
        """Save project state through LayerManager and display notification."""
        success = self.layer_manager.save_project()
        if success:
            self.iface.messageBar().pushMessage(
                UIMessages.MSG_SAVE_TITLE,
                UIMessages.MSG_SAVE_SUCCESS,
                level=Qgis.MessageLevel.Success,
                duration=4,
            )
        else:
            self.iface.messageBar().pushMessage(
                UIMessages.MSG_SAVE_TITLE,
                UIMessages.MSG_SAVE_FAILED,
                level=Qgis.MessageLevel.Warning,
                duration=5,
            )

    def closeEvent(self, event: Any) -> None:
        """Clean up map tools, canvases and auxiliary dialogs when dock is closed (T-0024)."""
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
            
        # Phase 1: Force save project on close and clear it (close project)
        try:
            if QgsProject.instance().fileName():
                QgsProject.instance().write()
                QgsProject.instance().clear()
        except Exception:
            pass
        super().closeEvent(event)
