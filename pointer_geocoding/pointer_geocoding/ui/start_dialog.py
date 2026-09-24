"""
/***************************************************************************
 PointerGeocoding Plugin - Start / Session Selection Dialog (View)
 ***************************************************************************/

セッション開始ダイアログのUI構築に専念する純粋なViewモジュールです。
ビジネスロジックは Controller (StartDialogLogic) へ委譲し、DIにより循環参照を防ぎます。
※ このファイルが main_dock.py を呼び出す起点となります。
"""
# 【変更不可侵の絶対的ルール】 測量座標系（X軸=南北, Y軸=東西）を採用。QGISキャンバス上のX座標(東西)はSurvey Y、Y座標(南北)はSurvey Xに対応する。

import os
from typing import Dict, Any, Optional

from qgis.PyQt.QtCore import Qt, QRegExp
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget, QFrame,
    QLineEdit, QSpinBox, QGroupBox
)

try:
    from qgis.PyQt.QtGui import QRegularExpressionValidator
    from qgis.PyQt.QtCore import QRegularExpression
    HAS_QT_REGEX = True
except ImportError:
    from qgis.PyQt.QtGui import QRegExpValidator
    HAS_QT_REGEX = False

from ..logic.core import from_excel_column, to_excel_column
from .style import UIStyleHelper
from .core.builder import CoreUIBuilder
from .core.field_spec import ButtonDef, FieldSpec, PanelSpec, WidgetType
from ..uilogic.start_dialog_logic import StartDialogLogic


# =========================================================================
# 画面固有の定数 (Co-location)
# =========================================================================
class DialogConfig:
    DIALOG_MARGIN = 12
    COMMON_MARGIN_LR = 12
    MAIN_RATIO = (2, 8)

class DialogLabels:
    BTN_OK = "セッションを開始"
    BTN_CANCEL = "キャンセル"
    BTN_CONFIRM = "確認"
    BTN_BROWSE = "参照..."

class DialogMessages:
    WARN_CSV_INVALID = "グリッドCSVを読み込めませんでした。「確認」を押すとCSV選択欄をクリアします。"
    WARN_ROW_COUNT_EXCEEDED = "基準点数が上限を超えています（{count}件）"
    ERR_RANGE_INVALID = "X範囲・Y範囲は、それぞれ最小値が最大値以下になるように指定してください。"


# =========================================================================
# 画面固有のスキーマ (Co-location)
# =========================================================================
START_DIALOG_SESSION_SPEC = PanelSpec(
    panel_id="start_dialog_session",
    spacing=10,
    fields=[
        FieldSpec(
            field_id="session_type",
            widget_type=WidgetType.SEGMENTED_TOGGLE,
            label="セッション種別:",
            options=["新規セッション", "既存セッション"],
            default_index=0,
            on_change="session_type_changed",
        ),
        FieldSpec(
            field_id="folder",
            widget_type=WidgetType.LINEEDIT_ROW,
            label="親ディレクトリ:",
            placeholder="セッションフォルダを新規作成する親ディレクトリを選択してください",
            trailing_button=ButtonDef(
                field_id="browse_folder", text=DialogLabels.BTN_BROWSE, on_click="browse_folder"
            ),
        ),
        FieldSpec(
            field_id="session_name",
            widget_type=WidgetType.LINEEDIT_ROW,
            label="セッション名:",
            placeholder="例: session_01 (半角英数推奨)",
        ),
    ],
)

START_DIALOG_GRID_CSV_SPEC = PanelSpec(
    panel_id="start_dialog_grid_csv",
    spacing=10,
    fields=[
        FieldSpec(
            field_id="grid_csv",
            widget_type=WidgetType.LINEEDIT_ROW,
            label="グリッドCSV選択:",
            placeholder=(
                "既存のPointGeo_grid.csvを選択"
                "（下のモードにより新規作成の初期値、または利用CSVとして扱われます）"
            ),
            trailing_button=ButtonDef(
                field_id="browse_grid_csv", text=DialogLabels.BTN_BROWSE, on_click="browse_grid_csv"
            ),
            on_change="grid_csv_changed",
        ),
        FieldSpec(
            field_id="grid_mode",
            widget_type=WidgetType.SEGMENTED_TOGGLE,
            label="グリッドモード:",
            options=["新規作成・更新", "CSVファイル利用"],
            default_index=0,
            on_change="grid_mode_changed",
        ),
    ],
)


class ExcelColumnSpinBox(QSpinBox):
    MIN_VALUE = 1
    MAX_VALUE = 702

    # Excel列記法(A, B, ..., Z, AA, ...)の入力用バリデータと値域の初期化。
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        if HAS_QT_REGEX:
            self._validator = QRegularExpressionValidator(QRegularExpression(r"^[A-Za-z]{1,2}$"), self)
        else:
            self._validator = QRegExpValidator(QRegExp(r"^[A-Za-z]{1,2}$"), self)
        self.setRange(self.MIN_VALUE, self.MAX_VALUE)

    # 数値を表示用のExcel列表記文字列に変換する。
    def textFromValue(self, value: int) -> str:
        return to_excel_column(value)

    # Excel列表記文字列を数値に変換し、値域内にクランプする。
    def valueFromText(self, text: str) -> int:
        value = from_excel_column(text)
        if value <= 0: return self.MIN_VALUE
        return min(value, self.MAX_VALUE)

    # 入力中のテキストが英字1〜2文字の正規表現に適合するか検証する。
    def validate(self, text: str, pos: int):
        return self._validator.validate(text, pos)


class StartDialog(QDialog):
    """Dialog for creating a new digitizing session or loading an existing one."""

    # ダイアログの初期化、UI構築、ロジックコントローラへのUI参照バインドと初期状態の反映。
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("点群座標取得 - セッション選択")
        self.setModal(True)
        self.setMinimumWidth(600)

        self._active_grid_warning: Optional[str] = None
        self._csv_invalid: bool = False
        self._csv_row_count: Optional[int] = None
        self._range_invalid: bool = False
        self._row_count_ack: bool = False

        self.logic = StartDialogLogic(self)

        self._init_ui()
        UIStyleHelper.apply_theme(self)
        
        # UI参照のインジェクション
        ui_refs = {
            "radio_new": self.radio_new,
            "radio_existing": self.radio_existing,
            "lbl_folder": self.lbl_folder,
            "edit_folder": self.edit_folder,
            "lbl_session_name": self.lbl_session_name,
            "edit_session_name": self.edit_session_name,
            "edit_grid_csv": self.edit_grid_csv,
            "radio_grid_mode_use_csv": self.radio_grid_mode_use_csv,
            "radio_grid_mode_new": self.radio_grid_mode_new,
            "spin_range_x_min": self.spin_range_x_min,
            "spin_range_x_max": self.spin_range_x_max,
            "spin_range_y_min": self.spin_range_y_min,
            "spin_range_y_max": self.spin_range_y_max,
        }
        callbacks = {
            "apply_grid_mode_state": self._apply_grid_mode_state,
            "show_warning_dialog": lambda title, msg: UIStyleHelper.show_warning_dialog(self, title, msg)
        }
        self.logic.bind_ui(ui_refs, callbacks)

        self._on_session_type_changed()
        self._apply_grid_mode_state()

    # セッション管理・グリッド設定・操作ボタンを含むダイアログ全体のレイアウトを構築する。
    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(DialogConfig.DIALOG_MARGIN)
        main_layout.setContentsMargins(
            DialogConfig.COMMON_MARGIN_LR, DialogConfig.DIALOG_MARGIN,
            DialogConfig.COMMON_MARGIN_LR, DialogConfig.DIALOG_MARGIN,
        )

        # 1. Session Group
        config_group = QGroupBox(self)
        config_layout = QVBoxLayout(config_group)
        config_layout.setSpacing(10)
        config_layout.addWidget(UIStyleHelper.build_separator(config_group, title_text="セッション管理基盤"))

        session_panel = CoreUIBuilder.build(START_DIALOG_SESSION_SPEC, parent=config_group)
        self._session_panel = session_panel
        self.radio_new, self.radio_existing = session_panel.get_buttons("session_type")
        self.lbl_folder = session_panel.get("folder.label")
        self.edit_folder = session_panel.get("folder")
        self.btn_browse_folder = session_panel.get("browse_folder")
        self.lbl_session_name = session_panel.get("session_name.label")
        self.edit_session_name = session_panel.get("session_name")

        # コールバック引数不一致回避のための *args を付与
        session_panel.bind("session_type_changed", self._on_session_type_changed)
        session_panel.bind("browse_folder", lambda *args: self.logic.handle_browse_folder())

        config_layout.addWidget(session_panel.widget)
        config_layout.addStretch()
        main_layout.addWidget(config_group)

        # 2. Grid Group
        self.grid_group = QGroupBox(self)
        grid_group_layout = QVBoxLayout(self.grid_group)
        grid_group_layout.setSpacing(10)
        grid_group_layout.addWidget(UIStyleHelper.build_separator(self.grid_group, title_text="基準点グリッド設定"))

        grid_csv_panel = CoreUIBuilder.build(START_DIALOG_GRID_CSV_SPEC, parent=self.grid_group)
        self._grid_csv_panel = grid_csv_panel
        self.edit_grid_csv = grid_csv_panel.get("grid_csv")
        self.btn_browse_grid_csv = grid_csv_panel.get("browse_grid_csv")
        self.radio_grid_mode_new, self.radio_grid_mode_use_csv = grid_csv_panel.get_buttons("grid_mode")

        grid_csv_panel.bind("browse_grid_csv", lambda *args: self.logic.handle_browse_grid_csv())
        grid_csv_panel.bind("grid_csv_changed", lambda *args: self._apply_grid_mode_state())
        grid_csv_panel.bind("grid_mode_changed", lambda *args: self._apply_grid_mode_state())

        grid_group_layout.addWidget(grid_csv_panel.widget)

        self.panel_grid_settings = QFrame(self.grid_group)
        UIStyleHelper.set_status_panel(self.panel_grid_settings)
        panel_settings_layout = QVBoxLayout(self.panel_grid_settings)
        panel_settings_layout.setContentsMargins(8, 6, 8, 6)
        panel_settings_layout.setSpacing(8)

        # Origins
        self.lbl_origin_group = QLabel("原点 (1A-00):", self.panel_grid_settings)
        self.lbl_origin_group.setStyleSheet("font-weight: bold;")
        self.lbl_origin_x = QLabel("X:", self.panel_grid_settings)
        self.spin_origin_x = UIStyleHelper.create_spinbox(-9999999, 9999999, 0, self.panel_grid_settings)
        child_origin_x = UIStyleHelper.build_child_container(self.lbl_origin_x, self.spin_origin_x)

        self.lbl_origin_y = QLabel("Y:", self.panel_grid_settings)
        self.spin_origin_y = UIStyleHelper.create_spinbox(-9999999, 9999999, 0, self.panel_grid_settings)
        child_origin_y = UIStyleHelper.build_child_container(self.lbl_origin_y, self.spin_origin_y)

        panel_settings_layout.addWidget(UIStyleHelper.build_flex_row(
            self.lbl_origin_group, [(child_origin_x, 1), (child_origin_y, 1), (None, 1)], main_ratio=DialogConfig.MAIN_RATIO
        ))

        # Ranges
        self.lbl_range_x_group = QLabel("X範囲:", self.panel_grid_settings)
        self.lbl_range_x_group.setStyleSheet("font-weight: bold;")
        self.lbl_range_x_min = QLabel("最小:", self.panel_grid_settings)
        self.spin_range_x_min = UIStyleHelper.create_spinbox(1, 300, 1, self.panel_grid_settings)
        child_range_x_min = UIStyleHelper.build_child_container(self.lbl_range_x_min, self.spin_range_x_min)

        self.lbl_range_x_max = QLabel("最大:", self.panel_grid_settings)
        self.spin_range_x_max = UIStyleHelper.create_spinbox(1, 300, 10, self.panel_grid_settings)
        child_range_x_max = UIStyleHelper.build_child_container(self.lbl_range_x_max, self.spin_range_x_max)

        panel_settings_layout.addWidget(UIStyleHelper.build_flex_row(
            self.lbl_range_x_group, [(child_range_x_min, 1), (child_range_x_max, 1), (None, 1)], main_ratio=DialogConfig.MAIN_RATIO
        ))

        self.lbl_range_y_group = QLabel("Y範囲:", self.panel_grid_settings)
        self.lbl_range_y_group.setStyleSheet("font-weight: bold;")
        self.lbl_range_y_min = QLabel("最小:", self.panel_grid_settings)
        self.spin_range_y_min = ExcelColumnSpinBox(self.panel_grid_settings)
        self.spin_range_y_min.setValue(1)
        child_range_y_min = UIStyleHelper.build_child_container(self.lbl_range_y_min, self.spin_range_y_min)

        self.lbl_range_y_max = QLabel("最大:", self.panel_grid_settings)
        self.spin_range_y_max = ExcelColumnSpinBox(self.panel_grid_settings)
        self.spin_range_y_max.setValue(10)
        child_range_y_max = UIStyleHelper.build_child_container(self.lbl_range_y_max, self.spin_range_y_max)

        panel_settings_layout.addWidget(UIStyleHelper.build_flex_row(
            self.lbl_range_y_group, [(child_range_y_min, 1), (child_range_y_max, 1), (None, 1)], main_ratio=DialogConfig.MAIN_RATIO
        ))

        # Preview
        self.lbl_preview_title = QLabel("グリッドプレビュー:", self.panel_grid_settings)
        self.lbl_preview_title.setStyleSheet("font-weight: bold;")

        self.lbl_preview_x = QLabel("X:", self.panel_grid_settings)
        self.spin_preview_x = UIStyleHelper.create_spinbox(1, 9999, 1, self.panel_grid_settings)
        child_preview_x = UIStyleHelper.build_child_container(self.lbl_preview_x, self.spin_preview_x)

        self.lbl_preview_y = QLabel("Y:", self.panel_grid_settings)
        self.edit_preview_y = QLineEdit(self.panel_grid_settings)
        self.edit_preview_y.setMaxLength(5)
        self.edit_preview_y.setText("A")
        if HAS_QT_REGEX:
            self.edit_preview_y.setValidator(QRegularExpressionValidator(QRegularExpression(r"^[A-Za-z]+$"), self.edit_preview_y))
        else:
            self.edit_preview_y.setValidator(QRegExpValidator(QRegExp(r"^[A-Za-z]+$"), self.edit_preview_y))
        child_preview_y = UIStyleHelper.build_child_container(self.lbl_preview_y, self.edit_preview_y)

        panel_settings_layout.addWidget(UIStyleHelper.build_flex_row(
            self.lbl_preview_title, [(child_preview_x, 1), (child_preview_y, 1), (None, 1)], main_ratio=DialogConfig.MAIN_RATIO
        ))
        
        grid_group_layout.addWidget(self.panel_grid_settings)

        self.panel_preview_status, self.lbl_preview_status = UIStyleHelper.create_status_panel("", "success", self.grid_group)
        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(8)
        self.panel_preview_status.layout().removeWidget(self.lbl_preview_status)
        status_row.addWidget(self.lbl_preview_status, 1)
        self.btn_grid_warning_confirm = QPushButton(DialogLabels.BTN_CONFIRM, self.panel_preview_status)
        self.btn_grid_warning_confirm.setVisible(False)
        self.btn_grid_warning_confirm.clicked.connect(self._on_grid_warning_confirm_clicked)
        status_row.addWidget(self.btn_grid_warning_confirm, 0)
        self.panel_preview_status.layout().addLayout(status_row)

        grid_group_layout.addWidget(self.panel_preview_status)
        main_layout.addWidget(self.grid_group)

        self.spin_origin_x.valueChanged.connect(self._update_grid_coordinate_preview)
        self.spin_origin_y.valueChanged.connect(self._update_grid_coordinate_preview)
        self.spin_range_x_min.valueChanged.connect(self._on_range_x_min_changed)
        self.spin_range_x_max.valueChanged.connect(self._on_grid_inputs_changed)
        self.spin_range_y_min.valueChanged.connect(self._on_range_y_min_changed)
        self.spin_range_y_max.valueChanged.connect(self._on_grid_inputs_changed)
        self.spin_preview_x.valueChanged.connect(self._update_grid_coordinate_preview)
        self.edit_preview_y.textChanged.connect(self._update_grid_coordinate_preview)

        # Action Buttons
        btn_layout = QHBoxLayout()
        self.btn_ok = QPushButton(DialogLabels.BTN_OK, self)
        self.btn_ok.setDefault(True)
        UIStyleHelper.set_primary_button(self.btn_ok)
        self.btn_ok.clicked.connect(self._validate_and_accept)
        self.btn_cancel = QPushButton(DialogLabels.BTN_CANCEL, self)
        self.btn_cancel.clicked.connect(self.reject)
        
        btn_layout.addStretch(1)
        btn_layout.addWidget(self.btn_ok, 1)
        btn_layout.addWidget(self.btn_cancel, 1)
        btn_layout.addStretch(1)
        main_layout.addLayout(btn_layout)

    # セッション種別(新規/既存)の切り替えをロジックコントローラへ委譲する。
    def _on_session_type_changed(self, _index: int = 0) -> None:
        self.logic.handle_session_type_changed()

    # グリッドCSVの有効性・モードに応じて入力欄の有効化状態とメタデータ反映を行う。
    def _apply_grid_mode_state(self) -> None:
        csv_path = self.edit_grid_csv.text().strip()
        metadata = self.logic.extract_csv_metadata(csv_path) if csv_path else None
        csv_valid = metadata is not None

        self.radio_grid_mode_use_csv.setEnabled(csv_valid)
        if not csv_valid and self.radio_grid_mode_use_csv.isChecked():
            self.radio_grid_mode_new.blockSignals(True)
            self.radio_grid_mode_use_csv.blockSignals(True)
            self.radio_grid_mode_new.setChecked(True)
            self.radio_grid_mode_use_csv.blockSignals(False)
            self.radio_grid_mode_new.blockSignals(False)

        enable_inputs = not self.radio_grid_mode_use_csv.isChecked()
        self.lbl_origin_group.setEnabled(enable_inputs)
        self.lbl_origin_x.setEnabled(enable_inputs)
        self.spin_origin_x.setEnabled(enable_inputs)
        self.lbl_origin_y.setEnabled(enable_inputs)
        self.spin_origin_y.setEnabled(enable_inputs)
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

        if metadata:
            if metadata["range_x_max"] > self.spin_range_x_max.maximum():
                self.spin_range_x_max.setMaximum(metadata["range_x_max"])
            if metadata["range_x_min"] > self.spin_range_x_min.maximum():
                self.spin_range_x_min.setMaximum(metadata["range_x_min"])

            range_spinboxes = (self.spin_origin_x, self.spin_origin_y, self.spin_range_x_min, self.spin_range_x_max, self.spin_range_y_min, self.spin_range_y_max)
            for spin in range_spinboxes: spin.blockSignals(True)
            try:
                self.spin_origin_x.setValue(metadata["origin_x"])
                self.spin_origin_y.setValue(metadata["origin_y"])
                self.spin_range_x_min.setValue(metadata["range_x_min"])
                self.spin_range_x_max.setValue(metadata["range_x_max"])
                self.spin_range_y_min.setValue(metadata["range_y_min"])
                self.spin_range_y_max.setValue(metadata["range_y_max"])
            finally:
                for spin in range_spinboxes: spin.blockSignals(False)
            self._sync_preview_x_to_range_min()
            self._sync_preview_y_to_range_min()

        self._csv_invalid = bool(csv_path) and not csv_valid
        self._csv_row_count = metadata.get("row_count") if metadata else None
        self._on_grid_inputs_changed()

    # プレビューX入力をX範囲の最小値に合わせる(シグナルはブロックし再評価の連鎖を防ぐ)。
    def _sync_preview_x_to_range_min(self) -> None:
        self.spin_preview_x.blockSignals(True)
        try:
            self.spin_preview_x.setValue(self.spin_range_x_min.value())
        finally:
            self.spin_preview_x.blockSignals(False)

    # プレビューY入力をY範囲の最小値のExcel列表記に合わせる(シグナルはブロックし再評価の連鎖を防ぐ)。
    def _sync_preview_y_to_range_min(self) -> None:
        self.edit_preview_y.blockSignals(True)
        try:
            self.edit_preview_y.setText(to_excel_column(self.spin_range_y_min.value()))
        finally:
            self.edit_preview_y.blockSignals(False)

    # X範囲の最小値変更時にプレビューXを追従させてから状態パネルを再評価する。
    def _on_range_x_min_changed(self, *_args) -> None:
        self._sync_preview_x_to_range_min()
        self._on_grid_inputs_changed()

    # Y範囲の最小値変更時にプレビューYを追従させてから状態パネルを再評価する。
    def _on_range_y_min_changed(self, *_args) -> None:
        self._sync_preview_y_to_range_min()
        self._on_grid_inputs_changed()

    # プレビュー用グリッド座標(基準点X/Y)の測地座標への変換結果をステータスパネルに表示する。
    def _update_grid_coordinate_preview(self) -> None:
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

        if rx_min <= gx <= rx_max and ry_min <= gy <= ry_max:
            px = ox - (gx - 1) * 40
            py = oy + (gy - 1) * 40
            UIStyleHelper.update_status_panel(
                self.panel_preview_status, self.lbl_preview_status,
                f"{grid_prefix}: X: {px}, Y: {py}", "success"
            )
        else:
            UIStyleHelper.update_status_panel(
                self.panel_preview_status, self.lbl_preview_status,
                f"{grid_prefix}: 範囲外", "error"
            )

    # グリッド範囲入力変更時に基準点数超過の確認済みフラグをリセットし、状態パネルを再評価する。
    def _on_grid_inputs_changed(self) -> None:
        self._row_count_ack = False
        self._refresh_grid_status_panel()

    # CSV不正・範囲不正・基準点数超過の順に警告条件を判定し、ステータスパネルとOKボタンを更新する。
    def _refresh_grid_status_panel(self) -> None:
        if self._csv_invalid:
            self._active_grid_warning = "csv_invalid"
            self._show_grid_warning(DialogMessages.WARN_CSV_INVALID)
            self._update_ok_button_state()
            return

        self._range_invalid = self.logic.is_range_invalid()
        if self._range_invalid:
            self._active_grid_warning = "range_invalid"
            self._show_grid_warning(DialogMessages.ERR_RANGE_INVALID)
            self._update_ok_button_state()
            return

        row_count = self.logic.compute_expected_row_count(self._csv_row_count)
        if row_count > 10000 and not self._row_count_ack:
            self._active_grid_warning = "row_count"
            self._show_grid_warning(DialogMessages.WARN_ROW_COUNT_EXCEEDED.format(count=row_count))
            self._update_ok_button_state()
            return

        self._active_grid_warning = None
        self.btn_grid_warning_confirm.setVisible(False)
        self._update_grid_coordinate_preview()
        self._update_ok_button_state()

    # ステータスパネルに警告メッセージを表示し、確認ボタンを表示状態にする。
    def _show_grid_warning(self, text: str) -> None:
        UIStyleHelper.update_status_panel(self.panel_preview_status, self.lbl_preview_status, text, "warning")
        self.btn_grid_warning_confirm.setVisible(True)

    # 現在表示中の警告種別に応じてCSVクリア・確認ボタン非表示・基準点数超過の確認済み化を行う。
    def _on_grid_warning_confirm_clicked(self) -> None:
        if self._active_grid_warning == "csv_invalid":
            self.edit_grid_csv.setText("")
        elif self._active_grid_warning == "range_invalid":
            self.btn_grid_warning_confirm.setVisible(False)
        elif self._active_grid_warning == "row_count":
            self._row_count_ack = True
            self._refresh_grid_status_panel()

    # CSV不正・範囲不正・未確認の基準点数超過のいずれかがあればOKボタンを無効化する。
    def _update_ok_button_state(self) -> None:
        blocked = (self._csv_invalid or self._range_invalid or (self._active_grid_warning == "row_count" and not self._row_count_ack))
        self.btn_ok.setEnabled(not blocked)

    # ロジックコントローラで入力値を検証し、問題なければダイアログを受理(accept)する。
    def _validate_and_accept(self) -> None:
        if self.logic.validate_inputs():
            self.accept()

    # 新規/既存セッションの種別に応じて、フォームの入力内容をセッション生成用の辞書にまとめて返す。
    def get_session_data(self) -> Dict[str, Any]:
        is_new = self.radio_new.isChecked()
        folder_path = self.edit_folder.text().strip()
        grid_csv = self.edit_grid_csv.text().strip()
        use_csv_mode = self.radio_grid_mode_use_csv.isChecked()

        grid_config = {
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

        if is_new:
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
        else:
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