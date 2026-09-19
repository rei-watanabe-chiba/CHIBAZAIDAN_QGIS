"""
/***************************************************************************
 PointerGeocoding Plugin - Start / Session Selection Dialog
 ***************************************************************************/
"""
# 【変更不可侵の絶対的ルール】 測量座標系（X軸=南北, Y軸=東西）を採用。QGISキャンバス上のX座標(東西)はSurvey Y、Y座標(南北)はSurvey Xに対応する。

import csv
import os
import re
from typing import Dict, Any, Optional, Tuple, List

from qgis.core import Qgis
from qgis.gui import QgsFilterLineEdit
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QFileDialog,
    QWidget,
    QFrame,
    QLineEdit,
    QSpinBox,
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

from ..logic.core import from_excel_column, to_excel_column
from .style import UIStyleHelper
from .constants import UIConfig
from .core import CoreUIBuilder
from .schemas import START_DIALOG_SESSION_SPEC, START_DIALOG_GRID_CSV_SPEC

# UI Configuration dictionary and layout ratios
UI_CONFIG = {
    "MAIN_RATIO": (2, 8),
    "ROW_HEIGHT": 32,
    "LABELS": {
        "WINDOW_TITLE": "点群座標取得 - セッション選択",
        "GROUP_SESSION": "セッション管理基盤",
        "GROUP_GRID": "基準点グリッド設定",
        "FOLDER_PARENT": "親ディレクトリ:",
        "FOLDER_EXISTING": "セッションフォルダ:",
        "ORIGIN_GROUP": "原点 (1A-00):",
        "RANGE_X_GROUP": "X範囲:",
        "RANGE_Y_GROUP": "Y範囲:",
        "RANGE_MIN": "最小:",
        "RANGE_MAX": "最大:",
        "PREVIEW_TITLE": "グリッドプレビュー:",
        "COORD_X": "X:",
        "COORD_Y": "Y:",
        "BTN_OK": "セッションを開始",
        "BTN_CANCEL": "キャンセル",
        "BTN_CONFIRM": "確認",
    },
    "PLACEHOLDERS": {
        "FOLDER_NEW": "セッションフォルダを新規作成する親ディレクトリを選択してください",
        "FOLDER_EXISTING": "既存のセッションフォルダ（.qgzが存在するフォルダ）を選択してください",
        "PREVIEW_Y": "A",
    },
    "DIALOG_TITLES": {
        "BROWSE_FOLDER_NEW": "親保存先フォルダを選択",
        "BROWSE_FOLDER_EXISTING": "既存セッションフォルダを選択",
        "BROWSE_GRID_CSV": "グリッドCSVファイルを選択",
        "CSV_FILTER": "CSVファイル (*.csv);;すべてのファイル (*.*)",
    },
    "MESSAGES": {
        "OUT_OF_BOUNDS": "範囲外",
        "ERR_TITLE_INPUT": "入力エラー",
        "ERR_TITLE_PATH": "パスエラー",
        "ERR_TITLE_DUPLICATE": "重複エラー",
        "ERR_TITLE_GENERIC": "エラー",
        "ERR_FOLDER_REQUIRED_NEW": "親ディレクトリを指定してください。",
        "ERR_FOLDER_REQUIRED_EXISTING": "既存セッションフォルダを指定してください。",
        "ERR_FOLDER_NOT_FOUND": "指定されたフォルダが存在しません:\n{path}",
        "ERR_SESSION_NAME_REQUIRED": "セッション名を入力してください。",
        "ERR_SESSION_NAME_INVALID": "セッション名に使用できない文字 (\\ / : * ? \" < > |) が含まれています。\n適切な名称を入力してください。",
        "ERR_SESSION_EXISTS": "指定された親ディレクトリ内に同名のフォルダが既に存在します:\n{name}\n別のセッション名を指定してください。",
        "ERR_NO_QGZ": "選択されたフォルダ内にQGISプロジェクトファイル (.qgz) が見つかりません:\n{path}\n有効なセッションフォルダを選択してください。",
        "ERR_RANGE_INVALID": "X範囲・Y範囲は、それぞれ最小値が最大値以下になるように指定してください。",
        "WARN_CSV_INVALID": "グリッドCSVを読み込めませんでした。「確認」を押すとCSV選択欄をクリアします。",
        "WARN_ROW_COUNT_EXCEEDED": "基準点数が上限を超えています（{count}件）",
    },
    "LIMITS": {
        "RANGE_X_MIN_VALUE": 1,
        "RANGE_X_MAX_VALUE": 300,
        "RANGE_X_DEFAULT_MIN": 1,
        "RANGE_X_DEFAULT_MAX": 10,
        "RANGE_Y_DEFAULT_MIN": 1,
        "RANGE_Y_DEFAULT_MAX": 10,
        "ROW_COUNT_WARNING_THRESHOLD": 10000,
    },
}

MAIN_RATIO = UI_CONFIG["MAIN_RATIO"]


class ExcelColumnSpinBox(QSpinBox):
    """QSpinBox variant that displays/accepts an Excel-style column letter
    (A, B, ..., Z, AA, AB, ..., ZZ) while internally storing the equivalent
    1-based integer index (1..702). Used for the Y-axis grid range inputs,
    where the large-grid axis is identified by a 1-2 character uppercase
    alphabetic label (see grid_csv_mixin.generate_grid_csv / core_logic.
    to_excel_column / from_excel_column)."""

    MIN_VALUE = 1
    MAX_VALUE = 702  # 'ZZ'

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """Initialize the spinbox with a fixed 'A'..'ZZ' range.

        :param parent: Optional parent QWidget.
        :type parent: Optional[QWidget]
        """
        super().__init__(parent)
        if HAS_QT_REGEX:
            self._validator = QRegularExpressionValidator(
                QRegularExpression(r"^[A-Za-z]{1,2}$"), self
            )
        else:
            self._validator = QRegExpValidator(QRegExp(r"^[A-Za-z]{1,2}$"), self)
        self.setRange(self.MIN_VALUE, self.MAX_VALUE)

    def textFromValue(self, value: int) -> str:
        """Render the internal integer as an Excel-style column letter.

        :param value: 1-based integer value.
        :type value: int
        :return: Excel-style column letter representation.
        :rtype: str
        """
        return to_excel_column(value)

    def valueFromText(self, text: str) -> int:
        """Parse an Excel-style column letter back into a 1-based integer.

        :param text: Excel-style column letter string.
        :type text: str
        :return: 1-based integer value (clamped to the valid range).
        :rtype: int
        """
        value = from_excel_column(text)
        if value <= 0:
            return self.MIN_VALUE
        return min(value, self.MAX_VALUE)

    def validate(self, text: str, pos: int):
        """Restrict input to 1-2 half-width uppercase (or lowercase) letters.

        :param text: Current editor text.
        :type text: str
        :param pos: Cursor position within the text.
        :type pos: int
        :return: Validation result tuple (state, text, pos).
        """
        return self._validator.validate(text, pos)


class StartDialog(QDialog):
    """Dialog for creating a new digitizing session or loading an existing one."""

    # Pattern to detect invalid characters in directory or file names on Windows and UNIX
    INVALID_CHARS_PATTERN = r'[\\/:*?"<>|]'

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """Initialize the session startup dialog.

        :param parent: Optional parent QWidget.
        :type parent: Optional[QWidget]
        """
        super().__init__(parent)
        self.setWindowTitle(UI_CONFIG["LABELS"]["WINDOW_TITLE"])
        self.setModal(True)
        self.setMinimumWidth(600)

        # Grid-configuration warning state (see _refresh_grid_status_panel).
        # '_active_grid_warning' is one of None / "csv_invalid" / "range_invalid" /
        # "row_count", reflecting the currently displayed panel_preview_status content.
        self._active_grid_warning: Optional[str] = None
        self._csv_invalid: bool = False
        self._csv_row_count: Optional[int] = None
        self._range_invalid: bool = False
        self._row_count_ack: bool = False

        self._init_ui()
        UIStyleHelper.apply_theme(self)
        self._on_session_type_changed()
        self._apply_grid_mode_state()

    def _init_ui(self) -> None:
        """Construct the user interface programmatically using native QGIS widgets and flexbox builders."""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(UIConfig.DIALOG_MARGIN)
        main_layout.setContentsMargins(
            UIConfig.COMMON_MARGIN_LR,
            UIConfig.DIALOG_MARGIN,
            UIConfig.COMMON_MARGIN_LR,
            UIConfig.DIALOG_MARGIN,
        )

        # 1. Configuration Parameters Group (QGroupBox)
        # T-0046: session type / folder path / session name are built
        # declaratively via CoreUIBuilder against START_DIALOG_SESSION_SPEC
        # (see schemas.py); this method wires the built widgets to the
        # instance attributes used throughout this class and binds each
        # field's event hooks to the actual handlers below.
        config_group = QGroupBox(self)
        config_layout = QVBoxLayout(config_group)
        config_layout.setSpacing(10)
        config_layout.addWidget(
            UIStyleHelper.build_separator(
                config_group, title_text=UI_CONFIG["LABELS"]["GROUP_SESSION"]
            )
        )

        session_panel = CoreUIBuilder.build(START_DIALOG_SESSION_SPEC, parent=config_group)
        self._session_panel = session_panel
        self.radio_new, self.radio_existing = session_panel.get_buttons("session_type")
        self.lbl_folder = session_panel.get("folder.label")
        self.edit_folder = session_panel.get("folder")
        self.btn_browse_folder = session_panel.get("browse_folder")
        self.lbl_session_name = session_panel.get("session_name.label")
        self.edit_session_name = session_panel.get("session_name")

        session_panel.bind("session_type_changed", self._on_session_type_changed)
        session_panel.bind("browse_folder", self._browse_folder)

        config_layout.addWidget(session_panel.widget)
        config_layout.addStretch()

        main_layout.addWidget(config_group)

        # 2. Grid Configuration Group (QGroupBox)
        self.grid_group = QGroupBox(self)
        grid_group_layout = QVBoxLayout(self.grid_group)
        grid_group_layout.setSpacing(10)
        grid_group_layout.addWidget(
            UIStyleHelper.build_separator(
                self.grid_group, title_text=UI_CONFIG["LABELS"]["GROUP_GRID"]
            )
        )

        # Row 0/0.5: Grid CSV Selection + Grid Mode Selection (New/Update vs.
        # Use existing CSV as-is). T-0046: built declaratively via
        # CoreUIBuilder against START_DIALOG_GRID_CSV_SPEC (see schemas.py).
        grid_csv_panel = CoreUIBuilder.build(START_DIALOG_GRID_CSV_SPEC, parent=self.grid_group)
        self._grid_csv_panel = grid_csv_panel
        self.edit_grid_csv = grid_csv_panel.get("grid_csv")
        self.btn_browse_grid_csv = grid_csv_panel.get("browse_grid_csv")
        self.radio_grid_mode_new, self.radio_grid_mode_use_csv = grid_csv_panel.get_buttons(
            "grid_mode"
        )

        grid_csv_panel.bind("browse_grid_csv", self._browse_grid_csv)
        grid_csv_panel.bind("grid_csv_changed", self._on_grid_csv_changed)
        grid_csv_panel.bind("grid_mode_changed", self._on_grid_mode_changed)

        grid_group_layout.addWidget(grid_csv_panel.widget)

        # Row 1: Flat Status Panel containing Origin and Grid Count Settings in 2 rows
        self.panel_grid_settings = QFrame(self.grid_group)
        UIStyleHelper.set_status_panel(self.panel_grid_settings)
        panel_settings_layout = QVBoxLayout(self.panel_grid_settings)
        panel_settings_layout.setContentsMargins(8, 6, 8, 6)
        panel_settings_layout.setSpacing(8)

        # 1st Row: Origin Coordinates (1A-00)
        self.lbl_origin_group = QLabel(UI_CONFIG["LABELS"]["ORIGIN_GROUP"], self.panel_grid_settings)
        self.lbl_origin_group.setStyleSheet("font-weight: bold;")
        self.lbl_origin_x = QLabel(UI_CONFIG["LABELS"]["COORD_X"], self.panel_grid_settings)
        self.spin_origin_x = UIStyleHelper.create_spinbox(-9999999, 9999999, 0, self.panel_grid_settings)
        child_origin_x = UIStyleHelper.build_child_container(self.lbl_origin_x, self.spin_origin_x)

        self.lbl_origin_y = QLabel(UI_CONFIG["LABELS"]["COORD_Y"], self.panel_grid_settings)
        self.spin_origin_y = UIStyleHelper.create_spinbox(-9999999, 9999999, 0, self.panel_grid_settings)
        child_origin_y = UIStyleHelper.build_child_container(self.lbl_origin_y, self.spin_origin_y)

        row_origin = UIStyleHelper.build_flex_row(
            self.lbl_origin_group,
            [(child_origin_x, 1), (child_origin_y, 1), (None, 1)],
            main_ratio=MAIN_RATIO,
            row_height=UI_CONFIG["ROW_HEIGHT"],
        )
        panel_settings_layout.addWidget(row_origin)

        # 2nd Row: X-axis Grid Range (numeric, min/max, both ends inclusive)
        limits = UI_CONFIG["LIMITS"]
        self.lbl_range_x_group = QLabel(UI_CONFIG["LABELS"]["RANGE_X_GROUP"], self.panel_grid_settings)
        self.lbl_range_x_group.setStyleSheet("font-weight: bold;")
        self.lbl_range_x_min = QLabel(UI_CONFIG["LABELS"]["RANGE_MIN"], self.panel_grid_settings)
        self.spin_range_x_min = UIStyleHelper.create_spinbox(
            limits["RANGE_X_MIN_VALUE"], limits["RANGE_X_MAX_VALUE"], limits["RANGE_X_DEFAULT_MIN"],
            self.panel_grid_settings,
        )
        child_range_x_min = UIStyleHelper.build_child_container(self.lbl_range_x_min, self.spin_range_x_min)

        self.lbl_range_x_max = QLabel(UI_CONFIG["LABELS"]["RANGE_MAX"], self.panel_grid_settings)
        self.spin_range_x_max = UIStyleHelper.create_spinbox(
            limits["RANGE_X_MIN_VALUE"], limits["RANGE_X_MAX_VALUE"], limits["RANGE_X_DEFAULT_MAX"],
            self.panel_grid_settings,
        )
        child_range_x_max = UIStyleHelper.build_child_container(self.lbl_range_x_max, self.spin_range_x_max)

        row_range_x = UIStyleHelper.build_flex_row(
            self.lbl_range_x_group,
            [(child_range_x_min, 1), (child_range_x_max, 1), (None, 1)],
            main_ratio=MAIN_RATIO,
            row_height=UI_CONFIG["ROW_HEIGHT"],
        )
        panel_settings_layout.addWidget(row_range_x)

        # 3rd Row: Y-axis Grid Range (alphabetic 'A'..'ZZ', min/max, both ends inclusive)
        self.lbl_range_y_group = QLabel(UI_CONFIG["LABELS"]["RANGE_Y_GROUP"], self.panel_grid_settings)
        self.lbl_range_y_group.setStyleSheet("font-weight: bold;")
        self.lbl_range_y_min = QLabel(UI_CONFIG["LABELS"]["RANGE_MIN"], self.panel_grid_settings)
        self.spin_range_y_min = ExcelColumnSpinBox(self.panel_grid_settings)
        self.spin_range_y_min.setValue(limits["RANGE_Y_DEFAULT_MIN"])
        child_range_y_min = UIStyleHelper.build_child_container(self.lbl_range_y_min, self.spin_range_y_min)

        self.lbl_range_y_max = QLabel(UI_CONFIG["LABELS"]["RANGE_MAX"], self.panel_grid_settings)
        self.spin_range_y_max = ExcelColumnSpinBox(self.panel_grid_settings)
        self.spin_range_y_max.setValue(limits["RANGE_Y_DEFAULT_MAX"])
        child_range_y_max = UIStyleHelper.build_child_container(self.lbl_range_y_max, self.spin_range_y_max)

        row_range_y = UIStyleHelper.build_flex_row(
            self.lbl_range_y_group,
            [(child_range_y_min, 1), (child_range_y_max, 1), (None, 1)],
            main_ratio=MAIN_RATIO,
            row_height=UI_CONFIG["ROW_HEIGHT"],
        )
        panel_settings_layout.addWidget(row_range_y)

        # 4th Row: Grid Preview Section
        self.lbl_preview_title = QLabel(UI_CONFIG["LABELS"]["PREVIEW_TITLE"], self.panel_grid_settings)
        self.lbl_preview_title.setStyleSheet("font-weight: bold;")

        self.lbl_preview_x = QLabel(UI_CONFIG["LABELS"]["COORD_X"], self.panel_grid_settings)
        self.spin_preview_x = UIStyleHelper.create_spinbox(1, 9999, 1, self.panel_grid_settings)
        child_preview_x = UIStyleHelper.build_child_container(self.lbl_preview_x, self.spin_preview_x)

        self.lbl_preview_y = QLabel(UI_CONFIG["LABELS"]["COORD_Y"], self.panel_grid_settings)
        self.edit_preview_y = QLineEdit(self.panel_grid_settings)
        self.edit_preview_y.setMaxLength(5)
        self.edit_preview_y.setPlaceholderText(UI_CONFIG["PLACEHOLDERS"]["PREVIEW_Y"])
        self.edit_preview_y.setText(UI_CONFIG["PLACEHOLDERS"]["PREVIEW_Y"])
        if HAS_QT_REGEX:
            self.edit_preview_y.setValidator(
                QRegularExpressionValidator(QRegularExpression(r"^[A-Za-z]+$"), self.edit_preview_y)
            )
        else:
            self.edit_preview_y.setValidator(
                QRegExpValidator(QRegExp(r"^[A-Za-z]+$"), self.edit_preview_y)
            )
        child_preview_y = UIStyleHelper.build_child_container(self.lbl_preview_y, self.edit_preview_y)

        row_preview_input = UIStyleHelper.build_flex_row(
            self.lbl_preview_title,
            [(child_preview_x, 1), (child_preview_y, 1), (None, 1)],
            main_ratio=MAIN_RATIO,
            row_height=UI_CONFIG["ROW_HEIGHT"],
        )
        panel_settings_layout.addWidget(row_preview_input)
        panel_settings_layout.addStretch()

        grid_group_layout.addWidget(self.panel_grid_settings)

        # Dynamic Coordinate Result Panel (green success / red error / orange warning
        # status panel). Also used to display grid-configuration warnings (invalid CSV,
        # invalid X/Y range, expected row count over the threshold) alongside a
        # right-aligned "confirm" button (see _refresh_grid_status_panel).
        self.panel_preview_status, self.lbl_preview_status = UIStyleHelper.create_status_panel(
            "", status_type="success", parent=self.grid_group
        )
        status_panel_layout = self.panel_preview_status.layout()
        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(8)
        status_panel_layout.removeWidget(self.lbl_preview_status)
        status_row.addWidget(self.lbl_preview_status, 1)
        self.btn_grid_warning_confirm = QPushButton(
            UI_CONFIG["LABELS"]["BTN_CONFIRM"], self.panel_preview_status
        )
        self.btn_grid_warning_confirm.setVisible(False)
        self.btn_grid_warning_confirm.clicked.connect(self._on_grid_warning_confirm_clicked)
        status_row.addWidget(self.btn_grid_warning_confirm, 0)
        status_panel_layout.addLayout(status_row)

        grid_group_layout.addWidget(self.panel_preview_status)
        grid_group_layout.addStretch()

        # Connect signals for dynamic preview calculation. Origin/preview inputs only
        # affect the coordinate preview text; X/Y range inputs additionally affect the
        # expected row-count / range-validity warning and therefore reset the
        # acknowledgement state on every change (see _on_grid_inputs_changed).
        self.spin_origin_x.valueChanged.connect(self._update_grid_coordinate_preview)
        self.spin_origin_y.valueChanged.connect(self._update_grid_coordinate_preview)
        self.spin_range_x_min.valueChanged.connect(self._on_grid_inputs_changed)
        self.spin_range_x_max.valueChanged.connect(self._on_grid_inputs_changed)
        self.spin_range_y_min.valueChanged.connect(self._on_grid_inputs_changed)
        self.spin_range_y_max.valueChanged.connect(self._on_grid_inputs_changed)
        self.spin_preview_x.valueChanged.connect(self._update_grid_coordinate_preview)
        self.edit_preview_y.textChanged.connect(self._update_grid_coordinate_preview)

        main_layout.addWidget(self.grid_group)
        main_layout.addStretch()

        # 3. Action Buttons (Equal width & centered: stretch 1 : btn_ok 1 : btn_cancel 1 : stretch 1)
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        self.btn_ok = QPushButton(UI_CONFIG["LABELS"]["BTN_OK"], self)
        self.btn_ok.setDefault(True)
        self.btn_ok.setFixedHeight(UI_CONFIG["ROW_HEIGHT"])
        UIStyleHelper.set_primary_button(self.btn_ok)
        self.btn_ok.clicked.connect(self._validate_and_accept)

        self.btn_cancel = QPushButton(UI_CONFIG["LABELS"]["BTN_CANCEL"], self)
        self.btn_cancel.setFixedHeight(UI_CONFIG["ROW_HEIGHT"])
        self.btn_cancel.clicked.connect(self.reject)

        btn_layout.addStretch(1)
        btn_layout.addWidget(self.btn_ok, 1)
        btn_layout.addWidget(self.btn_cancel, 1)
        btn_layout.addStretch(1)

        main_layout.addLayout(btn_layout)

    def _on_session_type_changed(self, _index: int = 0) -> None:
        """Handle interlock toggling between New and Existing session modes.

        :param _index: Checked segment index passed by the RADIO_ROW
            "session_type_changed" hook (see START_DIALOG_SESSION_SPEC in
            schemas.py); unused, since the final state is always re-read
            fresh from ``self.radio_new.isChecked()`` below.
        :type _index: int
        """
        match self.radio_new.isChecked():
            case True:
                self.lbl_folder.setText(UI_CONFIG["LABELS"]["FOLDER_PARENT"])
                self.edit_folder.setPlaceholderText(UI_CONFIG["PLACEHOLDERS"]["FOLDER_NEW"])
                self.lbl_session_name.setEnabled(True)
                self.edit_session_name.setEnabled(True)
            case False:
                self.lbl_folder.setText(UI_CONFIG["LABELS"]["FOLDER_EXISTING"])
                self.edit_folder.setPlaceholderText(UI_CONFIG["PLACEHOLDERS"]["FOLDER_EXISTING"])
                self.lbl_session_name.setEnabled(False)
                self.edit_session_name.setEnabled(False)

                # Auto-detect existing PointGeo_grid.csv if folder is already selected
                if (folder_path := self.edit_folder.text().strip()) and os.path.isdir(folder_path):
                    potential_csv = os.path.join(folder_path, "PointGeo_grid.csv")
                    if os.path.isfile(potential_csv) and not self.edit_grid_csv.text().strip():
                        self.edit_grid_csv.setText(os.path.normpath(potential_csv))

    def _browse_folder(self) -> None:
        """Open a directory browser dialog based on the selected session mode."""
        is_new = self.radio_new.isChecked()
        match is_new:
            case True:
                dialog_title = UI_CONFIG["DIALOG_TITLES"]["BROWSE_FOLDER_NEW"]
            case False:
                dialog_title = UI_CONFIG["DIALOG_TITLES"]["BROWSE_FOLDER_EXISTING"]

        start_dir = self.edit_folder.text().strip() or os.path.expanduser("~")

        selected_dir = QFileDialog.getExistingDirectory(
            self, dialog_title, start_dir, QFileDialog.ShowDirsOnly
        )
        if selected_dir:
            norm_path = os.path.normpath(selected_dir)
            self.edit_folder.setText(norm_path)
            if not is_new:
                potential_csv = os.path.join(norm_path, "PointGeo_grid.csv")
                if os.path.isfile(potential_csv):
                    self.edit_grid_csv.setText(potential_csv)

    def _browse_grid_csv(self) -> None:
        """Open a file dialog to select an existing PointGeo_grid.csv file."""
        current_csv = self.edit_grid_csv.text().strip()
        start_dir = ""
        if current_csv and os.path.isfile(current_csv):
            start_dir = os.path.dirname(current_csv)
        elif self.edit_folder.text().strip() and os.path.isdir(self.edit_folder.text().strip()):
            start_dir = self.edit_folder.text().strip()
        else:
            start_dir = os.path.expanduser("~")

        selected_file, _ = QFileDialog.getOpenFileName(
            self,
            UI_CONFIG["DIALOG_TITLES"]["BROWSE_GRID_CSV"],
            start_dir,
            UI_CONFIG["DIALOG_TITLES"]["CSV_FILTER"],
        )
        if selected_file:
            self.edit_grid_csv.setText(os.path.normpath(selected_file))

    def _extract_csv_metadata(self, csv_path: str) -> Optional[Dict[str, int]]:
        """Extract origin coordinates and grid range from an existing PointGeo_grid.csv.

        Supports UTF-8 (with or without BOM) and CP932 / Shift-JIS with automatic fallback.
        The origin (1A-00) is back-calculated from any encountered small-grid "00" row
        (upper-left corner of a large grid) using the same offset formula as
        grid_csv_mixin.generate_grid_csv, since the grid range may not start at 1/A.
        Min/max grid range is calculated across all data rows.

        :param csv_path: Absolute path to the grid CSV file.
        :type csv_path: str
        :return: Dictionary with keys 'origin_x', 'origin_y', 'range_x_min', 'range_x_max',
            'range_y_min', 'range_y_max', 'row_count' (total number of parsed data rows),
            or None on failure.
        :rtype: Optional[Dict[str, int]]
        """
        if not os.path.isfile(csv_path):
            return None

        for encoding in ("utf-8-sig", "cp932"):
            try:
                with open(csv_path, mode="r", encoding=encoding, newline="") as f:
                    reader = csv.reader(f)
                    derived_origin: Optional[Tuple[int, int]] = None
                    min_gx: Optional[int] = None
                    max_gx: int = 0
                    min_gy: Optional[int] = None
                    max_gy: int = 0
                    data_row_count: int = 0

                    col_gx, col_gy, col_sub, col_x, col_y = 0, 1, 2, 3, 4
                    header_parsed: bool = False

                    for row in reader:
                        if not row or not any(field.strip() for field in row):
                            continue

                        # Detect header row
                        if not header_parsed:
                            try:
                                int(row[0].strip())
                            except ValueError:
                                # First element is not integer -> header row
                                for idx, col_name in enumerate(row):
                                    clean_name = col_name.strip()
                                    match clean_name:
                                        case name if "大グリッド" in name and ("Ｘ" in name or "X" in name):
                                            col_gx = idx
                                        case name if "大グリッド" in name and ("Ｙ" in name or "Y" in name):
                                            col_gy = idx
                                        case name if "小グリッド" in name:
                                            col_sub = idx
                                        case name if "Ｘ座標" in name or "X座標" in name or name.upper() == "X":
                                            col_x = idx
                                        case name if "Ｙ座標" in name or "Y座標" in name or name.upper() == "Y":
                                            col_y = idx
                                header_parsed = True
                                continue
                            header_parsed = True

                        # Parse data row
                        try:
                            gx = int(row[col_gx].strip())
                            gy = from_excel_column(row[col_gy].strip())
                            data_row_count += 1
                            if min_gx is None or gx < min_gx:
                                min_gx = gx
                            if gx > max_gx:
                                max_gx = gx
                            if min_gy is None or gy < min_gy:
                                min_gy = gy
                            if gy > max_gy:
                                max_gy = gy

                            if derived_origin is None:
                                # Back-calculate the theoretical 1A-00 origin from this row's
                                # own small-grid offset (sx, sy), so it works even when the
                                # CSV's grid range does not start at gx=1 / gy=A.
                                sub_grid = row[col_sub].strip() if len(row) > col_sub else ""
                                if len(sub_grid) == 2 and sub_grid.isdigit():
                                    sx = int(sub_grid[0])
                                    sy = int(sub_grid[1])
                                    coord_x = float(row[col_x].strip())
                                    coord_y = float(row[col_y].strip())
                                    ox = int(round(coord_x + (gx - 1) * 40 + sx * 4))
                                    oy = int(round(coord_y - (gy - 1) * 40 - sy * 4))
                                    derived_origin = (ox, oy)
                        except (ValueError, IndexError):
                            continue

                    if derived_origin is not None and min_gx is not None and min_gy is not None:
                        return {
                            "origin_x": derived_origin[0],
                            "origin_y": derived_origin[1],
                            "range_x_min": min_gx,
                            "range_x_max": max_gx,
                            "range_y_min": min_gy,
                            "range_y_max": max_gy,
                            "row_count": data_row_count,
                        }
            except (UnicodeDecodeError, OSError):
                continue

        return None

    def _on_grid_csv_changed(self, text: str) -> None:
        """Handle grid CSV path changes by refreshing the grid input state.

        :param text: Current text in the grid CSV line edit (unused; the
            authoritative value is re-read from the widget inside
            :meth:`_apply_grid_mode_state`).
        :type text: str
        """
        self._apply_grid_mode_state()

    def _on_grid_mode_changed(self, _index: int = 0) -> None:
        """Handle toggling between the 'new/update' and 'use existing CSV' grid modes.

        :param _index: Checked segment index passed by the RADIO_ROW
            "grid_mode_changed" hook (see START_DIALOG_GRID_CSV_SPEC in
            schemas.py); unused, since :meth:`_apply_grid_mode_state`
            re-reads the final state fresh from the radio button widgets.
        :type _index: int
        """
        self._apply_grid_mode_state()

    def _apply_grid_mode_state(self) -> None:
        """Refresh origin/range input enabled state and reflect CSV metadata.

        Two grid modes are supported (see ``self.radio_grid_mode_new`` /
        ``self.radio_grid_mode_use_csv``):

        - "新規作成・更新" (new/update): origin and range inputs remain always
          editable. If a grid CSV path is set, its metadata is loaded and
          used to overwrite the inputs every time the path changes, acting
          as a one-shot template that the user may further adjust by hand.
        - "CSVファイル利用" (use existing CSV as-is): origin and range inputs
          are always disabled (display-only). Valid CSV metadata is reflected
          into them; when no valid CSV is selected, the inputs stay disabled
          with their last known values.

        When the selected grid CSV cannot be read (missing path, unreadable
        file, or unparsable content), the "CSVファイル利用" radio button is
        disabled outright, and, if it was the active selection, the mode is
        forced back to "新規作成・更新". This forced switch never touches the
        origin/range spinbox values -- their previous values are left as-is.
        Once a valid CSV is selected again, the radio button is re-enabled.

        Preview UI elements remain always enabled regardless of grid mode.
        """
        csv_path = self.edit_grid_csv.text().strip()

        metadata: Optional[Dict[str, int]] = None
        if csv_path and os.path.isfile(csv_path):
            metadata = self._extract_csv_metadata(csv_path)
        csv_valid = metadata is not None

        self.radio_grid_mode_use_csv.setEnabled(csv_valid)
        if not csv_valid and self.radio_grid_mode_use_csv.isChecked():
            # Force back to "new/update" mode without letting the resulting
            # toggled signal re-enter this method (values must stay untouched).
            self.radio_grid_mode_new.blockSignals(True)
            self.radio_grid_mode_use_csv.blockSignals(True)
            self.radio_grid_mode_new.setChecked(True)
            self.radio_grid_mode_use_csv.blockSignals(False)
            self.radio_grid_mode_new.blockSignals(False)

        use_csv_mode = self.radio_grid_mode_use_csv.isChecked()
        enable_inputs = not use_csv_mode

        # Origin inputs: editable only in "new/update" mode
        self.lbl_origin_group.setEnabled(enable_inputs)
        self.lbl_origin_x.setEnabled(enable_inputs)
        self.spin_origin_x.setEnabled(enable_inputs)
        self.lbl_origin_y.setEnabled(enable_inputs)
        self.spin_origin_y.setEnabled(enable_inputs)

        # Range inputs: editable only in "new/update" mode
        self.lbl_range_x_group.setEnabled(enable_inputs)
        self.lbl_range_x_min.setEnabled(enable_inputs)
        self.spin_range_x_min.setEnabled(enable_inputs)
        self.lbl_range_x_max.setEnabled(enable_inputs)
        self.spin_range_x_max.setEnabled(enable_inputs)
        self.lbl_range_y_group.setEnabled(enable_inputs)
        self.lbl_range_y_min.setEnabled(enable_inputs)
        self.spin_range_y_min.setEnabled(enable_inputs)
        self.lbl_range_y_max.setEnabled(enable_inputs)
        self.spin_range_y_max.setEnabled(enable_inputs)

        # Preview inputs are ALWAYS enabled regardless of grid mode / CSV selection
        self.lbl_preview_title.setEnabled(True)
        self.lbl_preview_x.setEnabled(True)
        self.spin_preview_x.setEnabled(True)
        self.lbl_preview_y.setEnabled(True)
        self.edit_preview_y.setEnabled(True)
        self.panel_preview_status.setEnabled(True)

        # Reflect metadata already extracted above, in either mode. In
        # "new/update" mode this overwrites the (still-editable) inputs as a
        # template; in "use existing CSV" mode it populates the display-only
        # inputs. An invalid/missing CSV leaves prior values untouched.
        if metadata:
            # Extend the X-axis numeric spinbox maxima if the CSV exceeds current limits.
            # (Y-axis ExcelColumnSpinBox already covers the full 'A'..'ZZ' range.)
            if metadata["range_x_max"] > self.spin_range_x_max.maximum():
                self.spin_range_x_max.setMaximum(metadata["range_x_max"])
            if metadata["range_x_min"] > self.spin_range_x_min.maximum():
                self.spin_range_x_min.setMaximum(metadata["range_x_min"])

            # Block signals while batch-applying metadata so that the intermediate
            # (partially-updated) spinbox states never reach _on_grid_inputs_changed /
            # _update_grid_coordinate_preview; a single consistent refresh is triggered
            # explicitly once below, after every value has been applied.
            range_spinboxes = (
                self.spin_origin_x,
                self.spin_origin_y,
                self.spin_range_x_min,
                self.spin_range_x_max,
                self.spin_range_y_min,
                self.spin_range_y_max,
            )
            for spin in range_spinboxes:
                spin.blockSignals(True)
            try:
                self.spin_origin_x.setValue(metadata["origin_x"])
                self.spin_origin_y.setValue(metadata["origin_y"])
                self.spin_range_x_min.setValue(metadata["range_x_min"])
                self.spin_range_x_max.setValue(metadata["range_x_max"])
                self.spin_range_y_min.setValue(metadata["range_y_min"])
                self.spin_range_y_max.setValue(metadata["range_y_max"])
            finally:
                for spin in range_spinboxes:
                    spin.blockSignals(False)

        # CSV validity: only meaningful when a non-empty path was actually specified
        # (an empty path is the normal "no CSV selected" state, not an error).
        self._csv_invalid = bool(csv_path) and not csv_valid
        self._csv_row_count = metadata.get("row_count") if metadata else None
        self._on_grid_inputs_changed()

    def _update_grid_coordinate_preview(self) -> None:
        """Dynamically compute and display coordinates for the preview grid input.
        # 【変更不可侵の絶対的ルール】 測量座標系（X軸=南北, Y軸=東西）を採用。QGISキャンバス上のX座標(東西)はSurvey Y、Y座標(南北)はSurvey Xに対応する。

        If within bounds, marks panel as success and shows '{gx}{display_y}-00座標: X: {px}, Y: {py}'.
        If out of bounds, marks panel as error and shows '{gx}{display_y}-00座標: 範囲外'.

        Does nothing while a grid-configuration warning (invalid CSV / invalid range /
        row-count-over-threshold) is currently displayed on panel_preview_status, so
        that unrelated preview-input changes never overwrite the warning message.
        """
        if self._active_grid_warning is not None:
            return

        gx = self.spin_preview_x.value()
        y_text = self.edit_preview_y.text().strip().upper()
        gy = from_excel_column(y_text)

        display_y = y_text if y_text else "?"
        grid_prefix = f"{gx}{display_y}-00座標"

        rx_min = self.spin_range_x_min.value()
        rx_max = self.spin_range_x_max.value()
        ry_min = self.spin_range_y_min.value()
        ry_max = self.spin_range_y_max.value()
        ox = self.spin_origin_x.value()
        oy = self.spin_origin_y.value()

        # Check if coordinates are strictly within configured grid range
        # px is Survey X (南北), py is Survey Y (東西)
        if rx_min <= gx <= rx_max and ry_min <= gy <= ry_max:
            px = ox - (gx - 1) * 40
            py = oy + (gy - 1) * 40
            UIStyleHelper.update_status_panel(
                self.panel_preview_status,
                self.lbl_preview_status,
                f"{grid_prefix}: X: {px}, Y: {py}",
                status_type="success",
            )
        else:
            UIStyleHelper.update_status_panel(
                self.panel_preview_status,
                self.lbl_preview_status,
                f"{grid_prefix}: {UI_CONFIG['MESSAGES']['OUT_OF_BOUNDS']}",
                status_type="error",
            )

    def _is_range_invalid(self) -> bool:
        """Determine whether the configured X/Y grid range is invalid (min > max).

        Skipped (never considered invalid) when trusting an existing grid CSV's
        values as-is (i.e. "CSVファイル利用" mode with a CSV path set), mirroring the
        equivalent skip condition previously enforced in :meth:`_validate_and_accept`.

        :return: True if the range is invalid and must block session start.
        :rtype: bool
        """
        if self.radio_grid_mode_use_csv.isChecked() and self.edit_grid_csv.text().strip():
            return False
        return (
            self.spin_range_x_min.value() > self.spin_range_x_max.value()
            or self.spin_range_y_min.value() > self.spin_range_y_max.value()
        )

    def _compute_expected_row_count(self) -> int:
        """Compute the expected number of grid rows for the current configuration.

        In "CSVファイル利用" mode with a valid CSV selected, this is the actual number
        of data rows parsed from the CSV (see ``self._csv_row_count``, refreshed by
        :meth:`_apply_grid_mode_state`). Otherwise (new/update mode), it is the
        theoretical row count generated by ``grid_csv_mixin.generate_grid_csv`` for
        the currently configured X/Y range: (x_count) x (y_count) x 100 small grids.

        :return: Expected row count (0 when the range is invalid or unknown).
        :rtype: int
        """
        if self.radio_grid_mode_use_csv.isChecked() and self.edit_grid_csv.text().strip():
            return self._csv_row_count if self._csv_row_count is not None else 0

        x_min = self.spin_range_x_min.value()
        x_max = self.spin_range_x_max.value()
        y_min = self.spin_range_y_min.value()
        y_max = self.spin_range_y_max.value()
        if x_min > x_max or y_min > y_max:
            return 0
        return (x_max - x_min + 1) * (y_max - y_min + 1) * 100

    def _on_grid_inputs_changed(self) -> None:
        """Reset the row-count warning acknowledgement and refresh the status panel.

        Called whenever an input that affects grid-configuration validity or the
        expected row count changes (X/Y range spinboxes, grid CSV path), so that a
        previously-acknowledged row-count warning is re-evaluated from scratch.
        """
        self._row_count_ack = False
        self._refresh_grid_status_panel()

    def _refresh_grid_status_panel(self) -> None:
        """Recompute and display the grid-configuration warning (if any) with priority
        csv_invalid > range_invalid > row_count_exceeded > normal coordinate preview.

        csv_invalid / range_invalid are hard-blocking conditions: the "セッションを開始"
        button (``self.btn_ok``) stays disabled regardless of the confirm button, since
        clicking confirm cannot make an invalid CSV or an invalid range valid by itself
        (csv_invalid's confirm handler resolves it by clearing the CSV field; range_invalid
        requires the user to actually change the spinbox values). row_count_exceeded is a
        soft/advisory warning: clicking confirm acknowledges it and re-enables btn_ok until
        the range or CSV selection changes again.
        """
        if self._csv_invalid:
            self._active_grid_warning = "csv_invalid"
            self._show_grid_warning(UI_CONFIG["MESSAGES"]["WARN_CSV_INVALID"])
            self._update_ok_button_state()
            return

        self._range_invalid = self._is_range_invalid()
        if self._range_invalid:
            self._active_grid_warning = "range_invalid"
            self._show_grid_warning(UI_CONFIG["MESSAGES"]["ERR_RANGE_INVALID"])
            self._update_ok_button_state()
            return

        row_count = self._compute_expected_row_count()
        threshold = UI_CONFIG["LIMITS"]["ROW_COUNT_WARNING_THRESHOLD"]
        if row_count > threshold and not self._row_count_ack:
            self._active_grid_warning = "row_count"
            self._show_grid_warning(
                UI_CONFIG["MESSAGES"]["WARN_ROW_COUNT_EXCEEDED"].format(count=row_count)
            )
            self._update_ok_button_state()
            return

        self._active_grid_warning = None
        self.btn_grid_warning_confirm.setVisible(False)
        self._update_grid_coordinate_preview()
        self._update_ok_button_state()

    def _show_grid_warning(self, text: str) -> None:
        """Switch panel_preview_status to warning style and reveal the confirm button.

        :param text: Warning message to display.
        :type text: str
        """
        UIStyleHelper.update_status_panel(
            self.panel_preview_status, self.lbl_preview_status, text, status_type="warning"
        )
        self.btn_grid_warning_confirm.setVisible(True)

    def _on_grid_warning_confirm_clicked(self) -> None:
        """Handle a click on the shared grid-warning confirm button.

        Behavior depends on ``self._active_grid_warning``:

        - "csv_invalid": clears the grid CSV path (origin/range values are left
          untouched), which re-triggers :meth:`_apply_grid_mode_state` and therefore
          a full panel refresh.
        - "range_invalid": simply hides the confirm button; ``btn_ok`` remains
          disabled until the user actually corrects the X/Y range values.
        - "row_count": acknowledges the warning so that btn_ok is re-enabled until
          the range or CSV selection changes again.
        """
        match self._active_grid_warning:
            case "csv_invalid":
                self.edit_grid_csv.setText("")
            case "range_invalid":
                self.btn_grid_warning_confirm.setVisible(False)
            case "row_count":
                self._row_count_ack = True
                self._refresh_grid_status_panel()

    def _update_ok_button_state(self) -> None:
        """Enable/disable ``self.btn_ok`` based on the current grid-configuration state.

        csv_invalid and range_invalid always block session start. row_count_exceeded
        only blocks it until the warning has been acknowledged via the confirm button.
        """
        blocked = (
            self._csv_invalid
            or self._range_invalid
            or (self._active_grid_warning == "row_count" and not self._row_count_ack)
        )
        self.btn_ok.setEnabled(not blocked)

    def _validate_and_accept(self) -> None:
        """Validate all required inputs according to business constraints before accepting."""
        folder_path = self.edit_folder.text().strip()

        # Check directory input
        if not folder_path:
            msg = (
                UI_CONFIG["MESSAGES"]["ERR_FOLDER_REQUIRED_NEW"]
                if self.radio_new.isChecked()
                else UI_CONFIG["MESSAGES"]["ERR_FOLDER_REQUIRED_EXISTING"]
            )
            UIStyleHelper.show_warning_dialog(self, UI_CONFIG["MESSAGES"]["ERR_TITLE_INPUT"], msg)
            self.edit_folder.setFocus()
            return

        if not os.path.isdir(folder_path):
            UIStyleHelper.show_warning_dialog(
                self,
                UI_CONFIG["MESSAGES"]["ERR_TITLE_PATH"],
                UI_CONFIG["MESSAGES"]["ERR_FOLDER_NOT_FOUND"].format(path=folder_path),
            )
            self.edit_folder.setFocus()
            return

        match self.radio_new.isChecked():
            case True:
                session_name = self.edit_session_name.text().strip()

                # 1. Validate session name
                if not session_name:
                    UIStyleHelper.show_warning_dialog(
                        self,
                        UI_CONFIG["MESSAGES"]["ERR_TITLE_INPUT"],
                        UI_CONFIG["MESSAGES"]["ERR_SESSION_NAME_REQUIRED"],
                    )
                    self.edit_session_name.setFocus()
                    return

                if re.search(self.INVALID_CHARS_PATTERN, session_name):
                    UIStyleHelper.show_warning_dialog(
                        self,
                        UI_CONFIG["MESSAGES"]["ERR_TITLE_INPUT"],
                        UI_CONFIG["MESSAGES"]["ERR_SESSION_NAME_INVALID"],
                    )
                    self.edit_session_name.setFocus()
                    return

                # Check if session folder already exists in the parent directory
                target_session_dir = os.path.join(folder_path, session_name)
                if os.path.exists(target_session_dir):
                    UIStyleHelper.show_warning_dialog(
                        self,
                        UI_CONFIG["MESSAGES"]["ERR_TITLE_DUPLICATE"],
                        UI_CONFIG["MESSAGES"]["ERR_SESSION_EXISTS"].format(name=session_name),
                    )
                    self.edit_session_name.setFocus()
                    return

            case False:
                # Existing session validation: verify that a .qgz file exists
                qgz_files = [f for f in os.listdir(folder_path) if f.endswith(".qgz")]
                if not qgz_files:
                    UIStyleHelper.show_warning_dialog(
                        self,
                        UI_CONFIG["MESSAGES"]["ERR_TITLE_GENERIC"],
                        UI_CONFIG["MESSAGES"]["ERR_NO_QGZ"].format(path=folder_path),
                    )
                    self.edit_folder.setFocus()
                    return

        # Grid CSV validity and X/Y range validity (min <= max) are no longer validated
        # here via QMessageBox: they are enforced reactively through panel_preview_status
        # (see _refresh_grid_status_panel / _update_ok_button_state), which disables
        # self.btn_ok whenever either condition is violated. This method therefore
        # cannot be reached in either of those invalid states through normal UI use.

        self.accept()

    def get_session_data(self) -> Dict[str, Any]:
        """Retrieve the validated session configuration parameters.

        :return: Dictionary containing session parameters.
        :rtype: Dict[str, Any]
        """
        is_new = self.radio_new.isChecked()
        folder_path = self.edit_folder.text().strip()
        grid_csv = self.edit_grid_csv.text().strip()
        use_csv_mode = self.radio_grid_mode_use_csv.isChecked()

        grid_config: Dict[str, Any] = {
            "grid_mode": "USE_CSV" if use_csv_mode else "NEW",
            "use_existing_csv": bool(use_csv_mode and grid_csv),
            "csv_path": grid_csv,
            "origin_x": self.spin_origin_x.value(),
            "origin_y": self.spin_origin_y.value(),
            "range_x_min": self.spin_range_x_min.value(),
            "range_x_max": self.spin_range_x_max.value(),
            "range_y_min": self.spin_range_y_min.value(),
            "range_y_max": self.spin_range_y_max.value(),
        }

        match is_new:
            case True:
                session_name = self.edit_session_name.text().strip()
                return {
                    "session_type": "NEW",
                    "parent_dir_path": folder_path,
                    "session_name": session_name,
                    "image_file_path": "",
                    "session_dir_path": os.path.join(folder_path, session_name),
                    "grid_config": grid_config,
                    "grid_csv_path": grid_csv,
                    "grid_origin_x": grid_config["origin_x"],
                    "grid_origin_y": grid_config["origin_y"],
                    "grid_range_x_min": grid_config["range_x_min"],
                    "grid_range_x_max": grid_config["range_x_max"],
                    "grid_range_y_min": grid_config["range_y_min"],
                    "grid_range_y_max": grid_config["range_y_max"],
                }
            case False:
                return {
                    "session_type": "EXISTING",
                    "parent_dir_path": "",
                    "session_name": os.path.basename(folder_path),
                    "image_file_path": "",
                    "session_dir_path": folder_path,
                    "grid_config": grid_config,
                    "grid_csv_path": grid_csv,
                    "grid_origin_x": grid_config["origin_x"],
                    "grid_origin_y": grid_config["origin_y"],
                    "grid_range_x_min": grid_config["range_x_min"],
                    "grid_range_x_max": grid_config["range_x_max"],
                    "grid_range_y_min": grid_config["range_y_min"],
                    "grid_range_y_max": grid_config["range_y_max"],
                }
