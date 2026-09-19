"""
/***************************************************************************
 PointerGeocoding Plugin - Main Dock Standalone Dialog Classes
 ***************************************************************************/

Stage B split (mechanical, logic-preserving): extracted from main_dock.py.
Contains the independent dialog/widget classes used by MainDockWidget:
ModelessSectionDialog, ImageDialog, TwoDigitSpinBox and GridInputDialog.

T-0024 (UI restructure: left dock removal, top 4-button row + modeless
dialogs): the former left-dock icon rail + collapsible side panel (T-0020/
T-0021) has been replaced by three independent modeless dialogs opened from
buttons on the right dock's (MainDockWidget's) own top row: 画像 (image),
設定 (settings) and 出力 (CSV export). 設定/出力 are thin
ModelessSectionDialog wrappers around the content widgets tab3_settings_mixin.py
/ tab2_digitizing_mixin.py already build (_create_tab3_ui / _create_tab4_ui,
the latter renamed from _create_output_ui in T-0034).
画像 is the dedicated ImageDialog class below, which also absorbs the former
standalone PreviewDialog: the reference-point preview QgsMapCanvas (and its
setup_raster/add_marker/clear_markers/clean_up API, used by
tab1_georef_mixin.py) is now embedded directly inside the same window as the
画像管理 form, instead of opening as a second popup. All three dialogs are
modeless (multiple can be open at once) and report their show/close events
back to MainDockWidget via on_show/on_close callbacks, which it uses to
suspend/restore the main canvas digitizing tool (map_tool) while any of them
is open (see MainDockWidget._update_main_map_tool_state).
"""
# 【変更不可侵の絶対的ルール】 測量座標系（X軸=南北, Y軸=東西）を採用。QGISキャンバス上のX座標(東西)はSurvey Y、Y座標(南北)はSurvey Xに対応する。

import re
from typing import Optional, Dict, Any, List, Callable, Tuple

from qgis.core import QgsRasterLayer
from qgis.gui import QgsMapCanvas
from qgis.PyQt.QtCore import Qt, pyqtSlot, QRegExp
from qgis.PyQt.QtGui import QRegExpValidator, QColor
from qgis.PyQt.QtWidgets import (
    QDialog,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QSpinBox,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QColorDialog,
    QCheckBox,
    QRadioButton,
    QButtonGroup,
    QListWidget,
    QListWidgetItem,
    QGroupBox,
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
from ..logic.core import (
    to_survey_coords,
    check_point_duplicate,
    build_point_ident,
    ExcavationType,
    AttributeType,
)
from .constants import UIConfig, UILabels, UIMessages, UIPlaceholders, UIDialogSizes, UIDialogTitles
from .core import CoreUIBuilder
from .core.validators import RequiredValidator, DuplicateValidator
from .schemas import (
    GRID_INPUT_ACTIONS_SPEC,
    FEATURE_CREATE_INPUT_SPEC,
    FEATURE_CREATE_ACTIONS_SPEC,
    POINT_NAME_ENTRY_SPEC,
    POINT_NAME_ENTRY_ACTIONS_SPEC,
)


class ModelessSectionDialog(QDialog):
    """Generic modeless dialog hosting a single pre-built content widget (T-0024).

    Used for the 設定 (settings) and 出力 (CSV export) dialogs: the dialog
    itself owns no business logic, it simply presents a content widget built
    by the corresponding tab mixin (tab3_settings_mixin.py's
    ``_create_tab3_ui`` / tab2_digitizing_mixin.py's ``_create_tab4_ui``,
    renamed from ``_create_output_ui`` in T-0034)
    and, since it is modeless and reopenable, notifies MainDockWidget of its
    show/close events via the optional ``on_show``/``on_close`` callbacks so
    the main canvas digitizing tool can be suspended while it is open and
    restored once no such dialog remains open.
    """

    def __init__(
        self,
        title: str,
        content_widget: QWidget,
        on_show: Optional[Callable[[], None]] = None,
        on_close: Optional[Callable[[], None]] = None,
        parent: Optional[QWidget] = None,
        # 【ローカル編集】ModelessSectionDialoもサイズ指定反映
        width: Optional[int] = None,
        height: Optional[int] = None,
    ) -> None:
        """Initialize the dialog.

        :param title: Window title.
        :type title: str
        :param content_widget: Pre-built content widget to embed.
        :type content_widget: QWidget
        :param on_show: Optional callback invoked after the dialog is shown.
        :type on_show: Optional[Callable[[], None]]
        :param on_close: Optional callback invoked after the dialog is hidden/closed.
        :type on_close: Optional[Callable[[], None]]
        :param parent: Optional parent QWidget.
        :type parent: Optional[QWidget]
        """
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint)
        # 【ローカル編集】オプションでサイズ指定されている場合はリサイズする
        if width is not None and height is not None:
            self.resize(width, height)
        self._on_show = on_show
        self._on_close = on_close

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            UIConfig.COMMON_MARGIN_LR,
            UIConfig.DIALOG_MARGIN,
            UIConfig.COMMON_MARGIN_LR,
            UIConfig.DIALOG_MARGIN,
        )
        layout.addWidget(content_widget)

    def showEvent(self, event: Any) -> None:
        """Notify on_show after the dialog becomes visible."""
        super().showEvent(event)
        if self._on_show is not None:
            self._on_show()

    def closeEvent(self, event: Any) -> None:
        """Hide (rather than destroy) so the dialog can be reopened, then notify on_close."""
        self.hide()
        event.accept()
        if self._on_close is not None:
            self._on_close()


class ImageDialog(QDialog):
    """Modeless dialog hosting the 画像管理 (Tab 1) form, with the
    reference-point preview canvas embedded directly beside it (T-0024).

    Replaces the former separate PreviewDialog popup (see module docstring):
    the QgsMapCanvas preview and its setup_raster/add_marker/clear_markers/
    clean_up API now live on this class, alongside the 画像管理 form widget
    (tab1_georef_mixin.py's ``_create_tab1_ui``) passed in as
    ``content_widget``.
    """

    def __init__(
        self,
        content_widget: QWidget,
        on_show: Optional[Callable[[], None]] = None,
        on_close: Optional[Callable[[], None]] = None,
        parent: Optional[QWidget] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
    ) -> None:
        """Initialize the image dialog.

        :param content_widget: Pre-built 画像管理 form widget (Tab 1 content).
        :type content_widget: QWidget
        :param on_show: Optional callback invoked after the dialog is shown.
        :type on_show: Optional[Callable[[], None]]
        :param on_close: Optional callback invoked after the dialog is hidden/closed.
        :type on_close: Optional[Callable[[], None]]
        :param parent: Optional parent QWidget.
        :type parent: Optional[QWidget]
        """
        super().__init__(parent)
        self.setWindowTitle(UILabels.TAB_1_TITLE)
        self.resize(UIDialogSizes.IMAGE_DIALOG_WIDTH, UIDialogSizes.IMAGE_DIALOG_HEIGHT)
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint)
        if width is not None and height is not None: self.resize(width, height)
        self._on_show = on_show
        self._on_close = on_close

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            UIConfig.COMMON_MARGIN_LR,
            UIConfig.DIALOG_MARGIN,
            UIConfig.COMMON_MARGIN_LR,
            UIConfig.DIALOG_MARGIN,
        )
        layout.setSpacing(UIConfig.DIALOG_MARGIN)

        # Left: 画像管理 form (image add/edit, reference point table, transform)
        layout.addWidget(content_widget, 1)

        # Right: embedded reference-point preview canvas (formerly PreviewDialog)
        preview_container = QWidget(self)
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(4)

        lbl_hint = QLabel(UILabels.PREVIEW_HINT, preview_container)
        lbl_hint.setWordWrap(True)
        preview_layout.addWidget(lbl_hint)

        self.canvas = QgsMapCanvas(preview_container)
        self.canvas.setMinimumSize(400, 300)
        preview_layout.addWidget(self.canvas, 1)

        layout.addWidget(preview_container, 1)

        self.raster_layer: Optional[QgsRasterLayer] = None
        self.georef_tool: Optional[ImageGeorefTool] = None

    def setup_raster(
        self,
        raster_layer: QgsRasterLayer,
        point_clicked_callback: Any,
        ref_points_data: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Set up raster layer and georeferencing map tool on the preview canvas.

        :param raster_layer: Loaded temporary raster layer.
        :type raster_layer: QgsRasterLayer
        :param point_clicked_callback: Callback slot for point_clicked signal.
        :type point_clicked_callback: Any
        :param ref_points_data: Optional list of existing reference points for snap detection.
        :type ref_points_data: Optional[List[Dict[str, Any]]]
        """
        self.clean_up()

        self.raster_layer = raster_layer
        self.canvas.setLayers([self.raster_layer])
        self.canvas.setExtent(self.raster_layer.extent())
        self.canvas.refresh()

        self.georef_tool = ImageGeorefTool(self.canvas, self.raster_layer)
        if ref_points_data:
            self.georef_tool.set_ref_points_data(ref_points_data)
        self.canvas.setMapTool(self.georef_tool)
        self.georef_tool.point_clicked.connect(point_clicked_callback)

    def set_ref_points_data(self, ref_points_data: List[Dict[str, Any]]) -> None:
        """Update reference points list in georef tool for hover snap detection.

        :param ref_points_data: List of reference points.
        :type ref_points_data: List[Dict[str, Any]]
        """
        if self.georef_tool:
            self.georef_tool.set_ref_points_data(ref_points_data)

    def add_marker(self, pixel_x: float, pixel_y: float, name: str = "") -> None:
        """Add a vertex marker at given image pixel coordinate.

        :param pixel_x: Pixel X coordinate.
        :type pixel_x: float
        :param pixel_y: Pixel Y coordinate.
        :type pixel_y: float
        :param name: Label text for the point.
        :type name: str
        """
        if self.georef_tool:
            self.georef_tool.add_point_marker(pixel_x, pixel_y, name)

    def clear_markers(self) -> None:
        """Clear all vertex markers from preview canvas."""
        if self.georef_tool:
            self.georef_tool.clear_markers()

    def clean_up(self) -> None:
        """Clean up map tool and canvas layers."""
        if self.georef_tool is not None:
            self.georef_tool.clean_up()
            self.georef_tool = None
        if self.canvas is not None:
            self.canvas.setMapTool(None)
            self.canvas.setLayers([])
        self.raster_layer = None

    def showEvent(self, event: Any) -> None:
        """Notify on_show after the dialog becomes visible."""
        super().showEvent(event)
        if self._on_show is not None:
            self._on_show()

    def closeEvent(self, event: Any) -> None:
        """Handle dialog close event by hiding to allow reopening without reload."""
        self.hide()
        event.accept()
        if self._on_close is not None:
            self._on_close()


class TwoDigitSpinBox(QSpinBox):
    """QSpinBox displaying two-digit integer numbers (00 to 99)."""

    def textFromValue(self, val: int) -> str:
        """Format integer value as two-digit string."""
        return f"{val:02d}"

    def valueFromText(self, text: str) -> int:
        """Parse two-digit string into integer."""
        try:
            return int(text)
        except ValueError:
            return 0


class GridInputDialog(QDialog):
    """Modal dialog for inputting and validating grid indices against PointGeo_grid.csv.
    # 【変更不可侵の絶対的ルール】 測量座標系（X軸=南北, Y軸=東西）を採用。QGISキャンバス上のX座標(東西)はSurvey Y、Y座標(南北)はSurvey Xに対応する。
    """

    def __init__(
        self,
        layer_manager: Any,
        existing_point: Optional[Dict[str, Any]] = None,
        existing_names: Optional[List[str]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        """Initialize grid input modal dialog.
        # 【変更不可侵の絶対的ルール】 測量座標系（X軸=南北, Y軸=東西）を採用。QGISキャンバス上のX座標(東西)はSurvey Y、Y座標(南北)はSurvey Xに対応する。

        :param layer_manager: LayerManager instance containing grid memory cache.
        :type layer_manager: Any
        :param existing_point: Optional reference point dictionary if editing an existing point.
        :type existing_point: Optional[Dict[str, Any]]
        :param existing_names: List of names of other existing points to prevent duplication.
        :type existing_names: Optional[List[str]]
        :param parent: Optional parent QWidget.
        :type parent: Optional[QWidget]
        """
        super().__init__(parent)
        self.layer_manager = layer_manager
        self.existing_point = existing_point
        self.existing_names = existing_names or []

        self.dialog_action: str = "cancel"  # "confirm", "delete", "cancel"
        self.result_grid_name: str = ""
        self.result_real_x: Optional[float] = None
        self.result_real_y: Optional[float] = None

        self.setWindowTitle(UILabels.GRID_DIALOG_TITLE)
        self.setModal(True)
        self.setMinimumWidth(UIDialogSizes.GRID_DIALOG_MIN_WIDTH)

        self._init_ui()
        UIStyleHelper.apply_theme(self)
        self._populate_initial_values()

    def _init_ui(self) -> None:
        """Construct the 4-tier dialog interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            UIConfig.COMMON_MARGIN_LR,
            UIConfig.DIALOG_MARGIN,
            UIConfig.COMMON_MARGIN_LR,
            UIConfig.DIALOG_MARGIN,
        )
        layout.setSpacing(UIConfig.DIALOG_MARGIN)

        # -------------------------------------------------------------
        # Tier 1: [Xグリッド (数値SpinBox)] - [Yグリッド (英字のみテキスト入力)] - [小グリッド (00-99 数値SpinBox)]
        # -------------------------------------------------------------
        tier1_box = QWidget(self)
        tier1_vlayout = QVBoxLayout(tier1_box)
        tier1_vlayout.setContentsMargins(0, 0, 0, 0)
        tier1_vlayout.setSpacing(4)

        # Labels header row
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)

        lbl_header_x = QLabel(UILabels.GRID_X_LABEL, tier1_box)
        lbl_header_x.setStyleSheet("font-weight: bold; font-size: 8.5pt;")
        lbl_header_x.setAlignment(Qt.AlignCenter)

        lbl_header_y = QLabel(UILabels.GRID_Y_LABEL, tier1_box)
        lbl_header_y.setStyleSheet("font-weight: bold; font-size: 8.5pt;")
        lbl_header_y.setAlignment(Qt.AlignCenter)

        lbl_header_sub = QLabel(UILabels.GRID_SUB_LABEL, tier1_box)
        lbl_header_sub.setStyleSheet("font-weight: bold; font-size: 8.5pt;")
        lbl_header_sub.setAlignment(Qt.AlignCenter)

        header_layout.addWidget(lbl_header_x, 1)
        header_layout.addSpacing(16)
        header_layout.addWidget(lbl_header_y, 1)
        header_layout.addSpacing(16)
        header_layout.addWidget(lbl_header_sub, 1)
        tier1_vlayout.addLayout(header_layout)

        # Inputs row
        inputs_layout = QHBoxLayout()
        inputs_layout.setContentsMargins(0, 0, 0, 0)
        inputs_layout.setSpacing(4)

        max_gx = max(1, getattr(self.layer_manager, "max_gx", 100))
        self.spin_x = UIStyleHelper.create_spinbox(1, max_gx, 1, tier1_box)
        self.spin_x.setMinimumWidth(70)
        self.spin_x.valueChanged.connect(self._validate_and_lookup)

        lbl_sep1 = QLabel("-", tier1_box)
        lbl_sep1.setStyleSheet("font-weight: bold; padding: 0 4px;")
        lbl_sep1.setAlignment(Qt.AlignCenter)

        self.edit_y = QLineEdit(tier1_box)
        self.edit_y.setPlaceholderText("A")
        self.edit_y.setMaxLength(10)
        self.edit_y.setMinimumWidth(70)
        self.edit_y.setAlignment(Qt.AlignCenter)
        self.edit_y.setValidator(QRegExpValidator(QRegExp(r"[A-Za-z]+"), self.edit_y))
        self.edit_y.textChanged.connect(self._on_y_changed)

        lbl_sep2 = QLabel("-", tier1_box)
        lbl_sep2.setStyleSheet("font-weight: bold; padding: 0 4px;")
        lbl_sep2.setAlignment(Qt.AlignCenter)

        self.spin_sub = TwoDigitSpinBox(tier1_box)
        self.spin_sub.setRange(0, 99)
        self.spin_sub.setValue(0)
        self.spin_sub.setMinimumWidth(70)
        self.spin_sub.valueChanged.connect(self._validate_and_lookup)

        inputs_layout.addWidget(self.spin_x, 1)
        inputs_layout.addWidget(lbl_sep1, 0)
        inputs_layout.addWidget(self.edit_y, 1)
        inputs_layout.addWidget(lbl_sep2, 0)
        inputs_layout.addWidget(self.spin_sub, 1)
        tier1_vlayout.addLayout(inputs_layout)

        layout.addWidget(tier1_box)

        # -------------------------------------------------------------
        # Tier 2: [選択点を削除] ボタン（既存点選択時のみ表示/有効化）
        # -------------------------------------------------------------
        self.btn_delete_point = QPushButton(UILabels.BTN_DELETE_SELECTED_POINT, self)
        self.btn_delete_point.setStyleSheet(
            "background-color: #D32F2F; color: #FFFFFF; font-weight: bold; border-radius: 4px;"
        )
        self.btn_delete_point.clicked.connect(self._on_delete_point_clicked)
        if self.existing_point is None:
            self.btn_delete_point.setVisible(False)
        layout.addWidget(self.btn_delete_point)

        # -------------------------------------------------------------
        # Tier 3: [確定] [キャンセル] ボタン (T-0047: CoreUI BUTTON_ROW with
        # centered=True, replacing the former direct
        # UIStyleHelper.build_centered_button_row() call; see
        # GRID_INPUT_ACTIONS_SPEC in schemas.py).
        # -------------------------------------------------------------
        actions_panel = CoreUIBuilder.build(GRID_INPUT_ACTIONS_SPEC, parent=self)
        self._actions_panel = actions_panel
        self.btn_confirm = actions_panel.get("confirm")
        self.btn_cancel = actions_panel.get("cancel")
        actions_panel.bind("confirm_clicked", self._on_confirm_clicked)
        actions_panel.bind("cancel_clicked", self.reject)
        layout.addWidget(actions_panel.widget)

        # -------------------------------------------------------------
        # Tier 4: ステータス・エラー表示パネル
        # -------------------------------------------------------------
        self.panel_status, self.lbl_status = UIStyleHelper.create_status_panel(
            "", status_type="info", parent=self
        )
        layout.addWidget(self.panel_status)

    def _populate_initial_values(self) -> None:
        """Pre-populate inputs if editing an existing reference point."""
        if self.existing_point:
            name = str(self.existing_point.get("name", "")).strip()
            m = re.match(r"^(\d+)-?([A-Za-z]+)-?(\d{1,2})$", name)
            if m:
                self.spin_x.setValue(int(m.group(1)))
                self.edit_y.setText(m.group(2).upper())
                self.spin_sub.setValue(int(m.group(3)))
            else:
                self.edit_y.setText("A")
        else:
            default_y = "A"
            unique_gy = getattr(self.layer_manager, "unique_gy", set())
            if unique_gy:
                sorted_gy = sorted(list(unique_gy))
                if sorted_gy:
                    default_y = sorted_gy[0]
            self.edit_y.setText(default_y)

        self._validate_and_lookup()

    @pyqtSlot(str)
    def _on_y_changed(self, text: str) -> None:
        """Enforce uppercase on Y grid text input and trigger validation."""
        upper = text.upper()
        if upper != text:
            pos = self.edit_y.cursorPosition()
            self.edit_y.setText(upper)
            self.edit_y.setCursorPosition(pos)
        self._validate_and_lookup()

    def _validate_and_lookup(self) -> None:
        """Perform real-time lookup and validation against LayerManager's grid cache."""
        gx = self.spin_x.value()
        gy = self.edit_y.text().strip().upper()
        sub_grid = f"{self.spin_sub.value():02d}"
        grid_name = f"{gx}-{gy}-{sub_grid}"

        if not gy:
            UIStyleHelper.update_status_panel(
                self.panel_status,
                self.lbl_status,
                "大グリッドＹを入力してください (英字)。",
                status_type="info",
            )
            self.btn_confirm.setEnabled(False)
            return

        # Check duplicate name
        if grid_name in self.existing_names:
            UIStyleHelper.update_status_panel(
                self.panel_status,
                self.lbl_status,
                UILabels.ERR_GRID_DUPLICATE.format(grid=grid_name),
                status_type="error",
            )
            self.btn_confirm.setEnabled(False)
            return

        # Check unique_gy
        unique_gy = getattr(self.layer_manager, "unique_gy", set())
        if unique_gy and gy not in unique_gy:
            UIStyleHelper.update_status_panel(
                self.panel_status,
                self.lbl_status,
                UILabels.ERR_GY_NOT_FOUND.format(gy=gy),
                status_type="error",
            )
            self.btn_confirm.setEnabled(False)
            return

        # Lookup in grid_data
        grid_data = getattr(self.layer_manager, "grid_data", {})
        key = (gx, gy, sub_grid)

        if key in grid_data:
            math_x, math_y = grid_data[key]
            self.result_grid_name = grid_name
            self.result_real_x = float(math_x)
            self.result_real_y = float(math_y)

            # Apply to_survey_coords adapter for UI display in survey coordinate system
            survey_x, survey_y = to_survey_coords(math_x, math_y)
            msg = UILabels.STATUS_GRID_FOUND.format(
                grid=grid_name, rx=survey_x, ry=survey_y
            )
            UIStyleHelper.update_status_panel(
                self.panel_status,
                self.lbl_status,
                msg,
                status_type="success",
            )
            self.btn_confirm.setEnabled(True)
        else:
            UIStyleHelper.update_status_panel(
                self.panel_status,
                self.lbl_status,
                UILabels.ERR_GRID_NOT_FOUND.format(grid=grid_name),
                status_type="error",
            )
            self.btn_confirm.setEnabled(False)

    def _on_delete_point_clicked(self) -> None:
        """Handle deletion of the selected reference point."""
        reply = QMessageBox.question(
            self,
            UIMessages.MSG_CONFIRM_TITLE,
            UIMessages.MSG_CONFIRM_DELETE_REF,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.dialog_action = "delete"
            self.accept()

    def _on_confirm_clicked(self) -> None:
        """Handle confirmation and accept dialog."""
        self.dialog_action = "confirm"
        self.accept()


class FeatureManageDialog(QDialog):
    """FEAT-01: Modal dialog for managing 遺構名 (feature names) and their colors.

    Provides a 1-column list of features (row 0: 新規作成, rows 1+: existing features),
    allowing creating a new feature name or editing/recoloring existing features.
    """

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        feature_colors: Optional[Dict[str, str]] = None,
        on_update_callback: Optional[Callable[[str, str, str], None]] = None,
        initial_feature: Optional[str] = None,
    ) -> None:
        """Initialize the feature management dialog.

        :param parent: Optional parent QWidget.
        :param feature_colors: Dict mapping existing feature names to their hex color codes.
        :param on_update_callback: Callback function (old_name, new_name, new_color) -> None.
        :param initial_feature: Optional feature name to select initially.
        """
        super().__init__(parent)
        self.feature_colors: Dict[str, str] = dict(feature_colors) if feature_colors else {}
        self.on_update_callback: Optional[Callable[[str, str, str], None]] = on_update_callback
        self.result_text: str = ""
        self.result_feature_name: str = ""
        self.result_color: str = "#FF5722"
        self.current_selected_mode: str = "new"
        self.current_selected_feature: str = ""
        self.current_color: str = "#FF5722"

        self.setWindowTitle(UILabels.FEATURE_MANAGE_DIALOG_TITLE)
        self.setModal(True)
        self.resize(360, 440)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(
            UIConfig.COMMON_MARGIN_LR,
            UIConfig.DIALOG_MARGIN,
            UIConfig.COMMON_MARGIN_LR,
            UIConfig.DIALOG_MARGIN,
        )
        main_layout.setSpacing(UIConfig.DIALOG_MARGIN)

        # 1. Header / Box title
        self.lbl_header = QLabel("遺構名作成・編集", self)
        font = self.lbl_header.font()
        font.setBold(True)
        self.lbl_header.setFont(font)
        main_layout.addWidget(self.lbl_header)

        # 2. QTableWidget: 1-column list (Row 0: 新規作成, Rows 1+: existing features)
        self.table_features = QTableWidget(self)
        self.table_features.setColumnCount(1)
        self.table_features.setHorizontalHeaderLabels(["遺構名リスト"])
        self.table_features.horizontalHeader().setStretchLastSection(True)
        self.table_features.verticalHeader().setVisible(False)
        self.table_features.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_features.setSelectionMode(QTableWidget.SingleSelection)
        self.table_features.setMinimumHeight(140)
        self.table_features.itemSelectionChanged.connect(self._on_table_selection_changed)
        main_layout.addWidget(self.table_features)

        # 3. Form: 遺構名 (QLineEdit with FEAT-05 validator)
        lbl_name = QLabel("遺構名:", self)
        self.edit_name = QLineEdit(self)
        self.edit_name.setPlaceholderText(UIPlaceholders.NEW_FEATURE)
        if HAS_QT_REGEX:
            self.edit_name.setValidator(
                QRegularExpressionValidator(
                    QRegularExpression(r"^[A-Za-z0-9_-]+$"), self.edit_name
                )
            )
        else:
            self.edit_name.setValidator(
                QRegExpValidator(QRegExp(r"^[A-Za-z0-9_-]+$"), self.edit_name)
            )
        row_name = UIStyleHelper.build_flex_row(
            lbl_name, [(self.edit_name, 1)], main_ratio=(3, 7)
        )
        main_layout.addWidget(row_name)

        # 4. Form: カラーピッカー (QPushButton with label "カラー:")
        lbl_color = QLabel("カラー:", self)
        self.btn_color = QPushButton("カラー選択", self)
        self.btn_color.clicked.connect(self._on_pick_color)
        row_color = UIStyleHelper.build_flex_row(
            lbl_color, [(self.btn_color, 1)], main_ratio=(3, 7)
        )
        main_layout.addWidget(row_color)

        # 5. Status panel
        self.panel_status, self.lbl_status = UIStyleHelper.create_status_panel(
            "", status_type="info", parent=self
        )
        main_layout.addWidget(self.panel_status)

        # 6. Action buttons (btn_confirm, btn_cancel)
        self.row_actions = QWidget(self)
        actions_layout = QHBoxLayout(self.row_actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(8)
        actions_layout.addStretch(1)

        self.btn_confirm = QPushButton(UILabels.BTN_CONFIRM, self.row_actions)
        UIStyleHelper.set_primary_button(self.btn_confirm)
        self.btn_confirm.clicked.connect(self._on_confirm_clicked)
        actions_layout.addWidget(self.btn_confirm)

        self.btn_cancel = QPushButton(UILabels.BTN_CANCEL, self.row_actions)
        self.btn_cancel.clicked.connect(self.reject)
        actions_layout.addWidget(self.btn_cancel)

        actions_layout.addStretch(1)
        main_layout.addWidget(self.row_actions)

        # Backward compatibility aliases
        self.btn_ok = self.btn_confirm

        # Connect live validation
        self.edit_name.textChanged.connect(self._on_realtime_validate)
        self.edit_name.textEdited.connect(self._on_realtime_validate)

        # Initial populate
        self._populate_table(select_feature=initial_feature)

    def _populate_table(self, select_feature: Optional[str] = None) -> None:
        """Populate table with '新規作成' on row 0 and existing features below.

        Suppresses itemSelectionChanged signals during population to prevent premature events.
        """
        self.table_features.blockSignals(True)
        try:
            self.table_features.setRowCount(0)
            # Row 0: 新規作成
            self.table_features.insertRow(0)
            item_new = QTableWidgetItem("新規作成")
            item_new.setFlags(item_new.flags() & ~Qt.ItemIsEditable)
            self.table_features.setItem(0, 0, item_new)

            feature_names = sorted(self.feature_colors.keys())
            target_row = 0
            for i, feat_name in enumerate(feature_names, start=1):
                self.table_features.insertRow(i)
                item = QTableWidgetItem(feat_name)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table_features.setItem(i, 0, item)
                if select_feature is not None and feat_name == select_feature:
                    target_row = i

            self.table_features.setCurrentCell(target_row, 0)
        finally:
            self.table_features.blockSignals(False)

        self._on_table_selection_changed()

    def _update_color_button(self) -> None:
        """Update color button appearance based on current_color."""
        hex_val = self.current_color or "#FF5722"
        self.btn_color.setStyleSheet(
            f"background-color: {hex_val}; color: #FFFFFF; font-weight: bold; border-radius: 4px; padding: 4px;"
        )
        self.btn_color.setText(hex_val)

    def _on_pick_color(self) -> None:
        """Open QColorDialog to select a feature color."""
        initial = QColor(self.current_color) if self.current_color else QColor("#FF5722")
        color = QColorDialog.getColor(initial, self, UIDialogTitles.COLOR_PICKER)
        if color.isValid():
            self.current_color = color.name()
            self._update_color_button()
            self._on_realtime_validate()

    def _on_table_selection_changed(self) -> None:
        """Handle item selection changes in the feature table."""
        current_row = self.table_features.currentRow()
        if current_row <= 0:
            # "新規作成" selected
            self.current_selected_mode = "new"
            self.current_selected_feature = ""
            self.edit_name.blockSignals(True)
            self.edit_name.clear()
            self.edit_name.blockSignals(False)
            self.current_color = "#FF5722"
            self._update_color_button()
            self._on_realtime_validate()
        else:
            # Existing feature selected
            item = self.table_features.item(current_row, 0)
            feat_name = item.text() if item else ""
            self.current_selected_mode = "existing"
            self.current_selected_feature = feat_name
            self.edit_name.blockSignals(True)
            self.edit_name.setText(feat_name)
            self.edit_name.blockSignals(False)
            self.current_color = self.feature_colors.get(feat_name, "#FF5722")
            self._update_color_button()
            self._on_realtime_validate()

    def _on_realtime_validate(self, *args: Any) -> None:
        """Validate input name and update status panel in real time."""
        text = self.edit_name.text().strip()
        if not text:
            UIStyleHelper.update_status_panel(
                self.panel_status,
                self.lbl_status,
                UIMessages.ERR_NEW_FEATURE_REQUIRED,
                status_type="error",
            )
            self.btn_confirm.setEnabled(False)
            return

        if text in (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成")):
            UIStyleHelper.update_status_panel(
                self.panel_status,
                self.lbl_status,
                f"エラー: '{text}' は遺構名として使用できません。",
                status_type="error",
            )
            self.btn_confirm.setEnabled(False)
            return

        if self.current_selected_mode == "new":
            if text in self.feature_colors:
                UIStyleHelper.update_status_panel(
                    self.panel_status,
                    self.lbl_status,
                    f"エラー: 遺構名 '{text}' は既に登録されています。",
                    status_type="error",
                )
                self.btn_confirm.setEnabled(False)
                return
            msg = UILabels.STATUS_MSG_NEW_FEATURE.format(feature=text)
            UIStyleHelper.update_status_panel(
                self.panel_status, self.lbl_status, msg, status_type="info"
            )
            self.btn_confirm.setEnabled(True)
        else:
            # Mode: existing
            if text in self.feature_colors and text != self.current_selected_feature:
                UIStyleHelper.update_status_panel(
                    self.panel_status,
                    self.lbl_status,
                    f"エラー: 遺構名 '{text}' は既に登録されています。",
                    status_type="error",
                )
                self.btn_confirm.setEnabled(False)
                return
            msg = UILabels.STATUS_MSG_EDIT_FEATURE.format(feature=text)
            UIStyleHelper.update_status_panel(
                self.panel_status, self.lbl_status, msg, status_type="success"
            )
            self.btn_confirm.setEnabled(True)

    def _on_confirm_clicked(self) -> None:
        """Handle confirm button click.

        If "新規作成": returns input values and closes dialog via accept().
        If existing feature: updates all features via callback, refreshes internal list,
        and keeps dialog open.
        """
        text = self.edit_name.text().strip()
        if not text:
            return
        if text in (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成")):
            return

        if self.current_selected_mode == "new":
            if text in self.feature_colors:
                return
            self.result_text = text
            self.result_feature_name = text
            self.result_color = self.current_color
            self.accept()
        else:
            old_name = self.current_selected_feature
            new_name = text
            new_color = self.current_color
            if new_name in self.feature_colors and new_name != old_name:
                return

            if self.on_update_callback:
                self.on_update_callback(old_name, new_name, new_color)

            if old_name in self.feature_colors:
                del self.feature_colors[old_name]
            self.feature_colors[new_name] = new_color
            self.current_selected_feature = new_name

            # Reload table with new_name selected; dialog remains open
            self._populate_table(select_feature=new_name)


FeatureCreateDialog = FeatureManageDialog


class PointNameEntryDialog(QDialog):
    """T-0040: Modal dialog for entering a 点名/枝番 at click time while the
    新規モード点情報パネルの自動連番/解除トグル is set to 解除 (or while it is
    forced to 解除 by an SP attribute selection, see
    Tab2DigitizingMixin._update_autonum_toggle_for_sp).

    While 解除 is active, edit_point_name (QSpinBox) is left untouched by
    _apply_next_point_number and edit_point_name_sp is cleared for SP, so
    neither panel widget reliably holds the value the user actually wants
    at the moment of a canvas click. This dialog pops up at click time
    (positioned near the click via Tab2DigitizingMixin._on_canvas_clicked)
    to collect 点名/枝番 explicitly.

    T-0047 fix: validation feedback is now shown inline in
    ``self.panel_status``/``self.lbl_status`` (UIStyleHelper's
    create_status_panel/update_status_panel, matching GridInputDialog's
    Tier4 ステータス・エラー表示パネル), replacing the former OK-time
    QMessageBox.warning() prompts. The SP-required check
    (RequiredValidator) runs live as the user types (_on_realtime_validate).

    T-0047 followup2 fix: the duplicate check (DuplicateValidator wrapping
    core_logic.check_point_duplicate, via _check_duplicate) also now runs
    live from _on_realtime_validate, for both SP and non-SP 属性 -- 点名
    (spin_point_name.valueChanged / edit_point_name_sp.textChanged) and 枝番
    (edit_branch_no.textChanged) changes all trigger it. A prior revision
    left this OK-click-only for perceived per-keystroke layer-query overhead
    reasons; actual QGIS usage showed non-SP 属性 (S/P/C) never wired up
    live validation at all (実装スコープの見落とし), so that constraint is
    withdrawn. On success, ``result_point_name``/``result_branch_no`` hold
    the validated values for the caller to build the digitized feature with.
    """

    def __init__(
        self,
        point_layer,
        excavation_type: str,
        feature_name: str,
        drawing_name: str = "",
        is_sp_attribute: bool = False,
        parent: Optional[QWidget] = None,
        initial_point_name: str = "",
    ) -> None:
        """Initialize the point-name/branch-number entry dialog.

        :param point_layer: Vector layer to check for duplicate point identities against.
        :type point_layer: QgsVectorLayer
        :param excavation_type: ExcavationType.GRID.value or ExcavationType.FEATURE.value,
            taken from the 点情報パネル's current selection.
        :type excavation_type: str
        :param feature_name: Current 遺構名 selection (empty when excavation_type is グリッド).
        :type feature_name: str
        :param drawing_name: Current 対象図面 選択.
        :type drawing_name: str
        :param is_sp_attribute: True when the panel's currently selected 属性
            is SP (Tab2DigitizingMixin._is_sp_attribute()). SP点名は英数字の
            自由記述（edit_point_name_sp と同じバリデーション）で入力させ、
            それ以外は従来通り整数QSpinBoxで入力させる (see T-0040 followup
            fix: SP属性は解除モード固定のため、このダイアログ経由でしか
            SP点名を入力できない).
        :type is_sp_attribute: bool
        :param parent: Optional parent QWidget.
        :type parent: Optional[QWidget]
        :param initial_point_name: T-0041: Preset value for the 点名 input
            (直前に作成した点名), typically obtained via
            Tab2DigitizingMixin._get_last_created_point_name(). For the
            QSpinBox (non-SP) case this must be a string parseable as an
            int; non-numeric/empty values are ignored and the spinbox keeps
            its default. Presetting a value that turns out to be a
            duplicate is allowed -- OK still runs the normal duplicate
            check and shows an error, leaving it to the user to edit the
            value.
        :type initial_point_name: str
        """
        super().__init__(parent)
        self._point_layer = point_layer
        self._excavation_type = excavation_type
        self._feature_name = feature_name
        self._drawing_name = drawing_name
        self._is_sp_attribute = is_sp_attribute
        self.result_point_name: str = ""
        self.result_branch_no: str = ""

        self.setWindowTitle(UILabels.POINT_NAME_ENTRY_DIALOG_TITLE)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            UIConfig.COMMON_MARGIN_LR,
            UIConfig.DIALOG_MARGIN,
            UIConfig.COMMON_MARGIN_LR,
            UIConfig.DIALOG_MARGIN,
        )
        layout.setSpacing(UIConfig.DIALOG_MARGIN)

        # T-0047: 点名 (numeric or SP free-text)/枝番 inputs + OK/キャンセル
        # row built declaratively via CoreUI (see POINT_NAME_ENTRY_SPEC /
        # POINT_NAME_ENTRY_ACTIONS_SPEC in schemas.py). Both the numeric
        # "point_name" (SPINBOX_ROW) and free-text "point_name_sp"
        # (LINEEDIT_ROW) fields are always built; only the one matching
        # is_sp_attribute is shown, since CoreUI schemas stay static and this
        # choice is fixed per dialog instance.
        input_panel = CoreUIBuilder.build(POINT_NAME_ENTRY_SPEC, parent=self)
        self._input_panel = input_panel
        self.spin_point_name: QSpinBox = input_panel.get("point_name")
        self.edit_point_name_sp: QLineEdit = input_panel.get("point_name_sp")
        self.edit_branch_no: QLineEdit = input_panel.get("branch_no")

        if self._is_sp_attribute:
            # SP属性: edit_point_name_sp (tab2_digitizing_mixin.py) と同じ
            # 英数字・ハイフン・アンダースコアのみ許可のバリデータを踏襲する。
            self.edit_point_name_sp.setValidator(
                QRegExpValidator(QRegExp(r"^[A-Za-z0-9_-]+$"), self.edit_point_name_sp)
            )
            if initial_point_name:
                self.edit_point_name_sp.setText(initial_point_name)
            input_panel.get_row("point_name").hide()
        else:
            if initial_point_name and initial_point_name.isdigit():
                preset_value = int(initial_point_name)
                if self.spin_point_name.minimum() <= preset_value <= self.spin_point_name.maximum():
                    self.spin_point_name.setValue(preset_value)
            input_panel.get_row("point_name_sp").hide()

        layout.addWidget(input_panel.widget)

        # T-0047 fix: inline status panel replacing the former OK-time
        # QMessageBox error dialog (see _on_realtime_validate /
        # _on_ok_clicked below). Placed directly under the 点名/枝番 inputs,
        # mirroring GridInputDialog's Tier4 ステータス・エラー表示パネル
        # pattern (UIStyleHelper.create_status_panel/update_status_panel).
        self.panel_status, self.lbl_status = UIStyleHelper.create_status_panel(
            "", status_type="info", parent=self
        )
        layout.addWidget(self.panel_status)

        actions_panel = CoreUIBuilder.build(POINT_NAME_ENTRY_ACTIONS_SPEC, parent=self)
        self._actions_panel = actions_panel
        self.btn_ok = actions_panel.get("ok")
        self.btn_cancel = actions_panel.get("cancel")
        actions_panel.bind("ok_clicked", self._on_ok_clicked)
        actions_panel.bind("cancel_clicked", self.reject)
        layout.addWidget(actions_panel.widget)

        # T-0047 followup2 fix: real-time feedback now covers both the
        # SP-required check AND the point_name+branch_no duplicate check
        # (DuplicateValidator), for both SP and non-SP 属性. A prior revision
        # left the duplicate check OK-click-only under the assumption that
        # running it live would add avoidable per-keystroke overhead; actual
        # QGIS usage confirmed non-SP 属性 (S/P/C) never got ANY live
        # feedback at all (the QSpinBox/枝番 inputs were never wired to
        # _on_realtime_validate), so that assumption is withdrawn in favor of
        # matching the user-visible behavior already working correctly for
        # SP 属性. See _check_duplicate()/_on_realtime_validate() below.
        if self._is_sp_attribute:
            self.edit_point_name_sp.textChanged.connect(self._on_realtime_validate)
            self.edit_point_name_sp.textEdited.connect(self._on_realtime_validate)
        else:
            self.spin_point_name.valueChanged.connect(self._on_realtime_validate)
        self.edit_branch_no.textChanged.connect(self._on_realtime_validate)
        self._on_realtime_validate()

    def _check_duplicate(self, point_name: str, branch_no: str):
        """Build the point identity and run DuplicateValidator against it.

        T-0047 followup2 fix: factored out of _on_ok_clicked so the same
        duplicate-check logic can also run live from _on_realtime_validate.

        :param point_name: Candidate 点名 (already stripped by the caller).
        :type point_name: str
        :param branch_no: Candidate 枝番 (already stripped by the caller).
        :type branch_no: str
        :return: The DuplicateValidator's ValidationResult.
        """
        ident = build_point_ident(
            self._excavation_type,
            self._feature_name,
            point_name,
            branch_no,
            self._drawing_name,
        )
        return DuplicateValidator(
            lambda v: check_point_duplicate(
                self._point_layer,
                self._excavation_type,
                self._feature_name,
                v,
                branch_no,
                self._drawing_name,
            ),
            message=UIMessages.ERR_POINT_NAME_DUPLICATE.format(ident=ident),
        ).validate(point_name)

    def _on_realtime_validate(self, *args: Any) -> None:
        """Run the required/duplicate checks live and reflect them in panel_status.

        T-0047 followup2 fix: previously this only ran the SP-required check
        (RequiredValidator) and only when ``self._is_sp_attribute`` was True,
        leaving non-SP 属性 (S/P/C) with no live feedback at all for either
        点名 (QSpinBox) or 枝番 changes. It now also runs the duplicate check
        (DuplicateValidator, via _check_duplicate) live for both SP and
        non-SP 属性, connected from both 点名 and 枝番 inputs in __init__.
        The OK button is disabled while either check fails.
        """
        point_name = self._get_point_name_text()
        branch_no = self.edit_branch_no.text().strip()

        if self._is_sp_attribute:
            required_result = RequiredValidator(UIMessages.ERR_POINT_NAME_REQUIRED).validate(
                point_name
            )
            if not required_result.is_valid:
                UIStyleHelper.update_status_panel(
                    self.panel_status, self.lbl_status, required_result.message, status_type="error"
                )
                self.btn_ok.setEnabled(False)
                return

        dup_result = self._check_duplicate(point_name, branch_no)
        if not dup_result.is_valid:
            UIStyleHelper.update_status_panel(
                self.panel_status, self.lbl_status, dup_result.message, status_type="error"
            )
            self.btn_ok.setEnabled(False)
            return

        UIStyleHelper.update_status_panel(
            self.panel_status, self.lbl_status, "", status_type="info"
        )
        self.btn_ok.setEnabled(True)

    def _get_point_name_text(self) -> str:
        """Return the currently entered 点名 as a string, regardless of which
        input widget (spin_point_name / edit_point_name_sp) is active for the
        current 属性 (SP or not, see __init__'s is_sp_attribute).

        :return: 点名 as a string (e.g. "123" for non-SP, "SP-1" for SP).
        :rtype: str
        """
        if self._is_sp_attribute:
            return self.edit_point_name_sp.text().strip()
        return str(self.spin_point_name.value())

    def _on_ok_clicked(self) -> None:
        """Validate (required + duplicate) the entered 点名/枝番 and accept if unique.

        T-0047 followup2 fix: both the SP-required check and the duplicate
        check now run live via _on_realtime_validate as the user types and
        already keep btn_ok disabled while either fails, so both are
        re-checked here only defensively (should not normally be reachable
        in a failing state). Failures are shown inline in
        panel_status/lbl_status, matching GridInputDialog's ステータス・
        エラー表示パネル pattern.
        """
        point_name = self._get_point_name_text()
        branch_no = self.edit_branch_no.text().strip()

        if self._is_sp_attribute:
            required_result = RequiredValidator(UIMessages.ERR_POINT_NAME_REQUIRED).validate(
                point_name
            )
            if not required_result.is_valid:
                UIStyleHelper.update_status_panel(
                    self.panel_status,
                    self.lbl_status,
                    required_result.message,
                    status_type="error",
                )
                self.btn_ok.setEnabled(False)
                return

        dup_result = self._check_duplicate(point_name, branch_no)
        if not dup_result.is_valid:
            UIStyleHelper.update_status_panel(
                self.panel_status, self.lbl_status, dup_result.message, status_type="error"
            )
            return

        self.result_point_name = point_name
        self.result_branch_no = branch_no
        self.accept()

    def get_values(self) -> Tuple[str, str]:
        """Return the validated (point_name, branch_no) pair after an accepted dialog.

        :return: Tuple of (point_name, branch_no) strings.
        :rtype: Tuple[str, str]
        """
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

