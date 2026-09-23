"""
/***************************************************************************
 PointerGeocoding Plugin - Start Dialog Logic (Controller)
 ***************************************************************************/

セッション開始ダイアログのUIイベントを受容し、ビジネスロジック（入力検証、CSVメタデータ抽出、
期待行数計算）を処理するController層です。循環参照を防ぐため、Viewのコンポーネントは
DI (依存性注入) によってバインドされます。
"""
import os
import csv
import re
from typing import Dict, Any, Optional, Tuple, Callable

from qgis.PyQt.QtCore import QObject
from qgis.PyQt.QtWidgets import QFileDialog

from ..logic.core import from_excel_column


# =========================================================================
# ロジック固有の定数 (Controller側への逆インポート防止)
# =========================================================================
class LogicConstants:
    FOLDER_PARENT = "親ディレクトリ:"
    FOLDER_EXISTING = "セッションフォルダ:"
    PLACEHOLDER_FOLDER_NEW = "セッションフォルダを新規作成する親ディレクトリを選択してください"
    PLACEHOLDER_FOLDER_EXISTING = "既存のセッションフォルダ（.qgzが存在するフォルダ）を選択してください"
    
    BROWSE_FOLDER_NEW = "親保存先フォルダを選択"
    BROWSE_FOLDER_EXISTING = "既存セッションフォルダを選択"
    BROWSE_GRID_CSV = "グリッドCSVファイルを選択"
    CSV_FILTER = "CSVファイル (*.csv);;すべてのファイル (*.*)"
    
    ERR_TITLE_INPUT = "入力エラー"
    ERR_TITLE_PATH = "パスエラー"
    ERR_TITLE_DUPLICATE = "重複エラー"
    ERR_TITLE_GENERIC = "エラー"
    
    ERR_FOLDER_REQUIRED_NEW = "親ディレクトリを指定してください。"
    ERR_FOLDER_REQUIRED_EXISTING = "既存セッションフォルダを指定してください。"
    ERR_FOLDER_NOT_FOUND = "指定されたフォルダが存在しません:\n{path}"
    ERR_SESSION_NAME_REQUIRED = "セッション名を入力してください。"
    ERR_SESSION_NAME_INVALID = "セッション名に使用できない文字 (\\ / : * ? \" < > |) が含まれています。\n適切な名称を入力してください。"
    ERR_SESSION_EXISTS = "指定された親ディレクトリ内に同名のフォルダが既に存在します:\n{name}\n別のセッション名を指定してください。"
    ERR_NO_QGZ = "選択されたフォルダ内にQGISプロジェクトファイル (.qgz) が見つかりません:\n{path}\n有効なセッションフォルダを選択してください。"


class StartDialogLogic(QObject):
    """
    セッション開始ダイアログの制御・バリデーションを担うControllerクラス。
    """
    INVALID_CHARS_PATTERN = r'[\\/:*?"<>|]'

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.parent_widget = parent

        # UIコンポーネント参照
        self.radio_new = None
        self.radio_existing = None
        self.lbl_folder = None
        self.edit_folder = None
        self.lbl_session_name = None
        self.edit_session_name = None
        self.edit_grid_csv = None
        self.radio_grid_mode_use_csv = None
        self.radio_grid_mode_new = None
        self.spin_range_x_min = None
        self.spin_range_x_max = None
        self.spin_range_y_min = None
        self.spin_range_y_max = None
        
        # コールバック
        self.apply_grid_mode_state_cb = lambda: None
        self.show_warning_dialog_cb = lambda title, msg: None

    def bind_ui(self, ui_refs: Dict[str, Any], callbacks: Dict[str, Callable]) -> None:
        """View層のUIコンポーネントとコールバックをバインドする"""
        self.radio_new = ui_refs.get("radio_new")
        self.radio_existing = ui_refs.get("radio_existing")
        self.lbl_folder = ui_refs.get("lbl_folder")
        self.edit_folder = ui_refs.get("edit_folder")
        self.lbl_session_name = ui_refs.get("lbl_session_name")
        self.edit_session_name = ui_refs.get("edit_session_name")
        self.edit_grid_csv = ui_refs.get("edit_grid_csv")
        self.radio_grid_mode_use_csv = ui_refs.get("radio_grid_mode_use_csv")
        self.radio_grid_mode_new = ui_refs.get("radio_grid_mode_new")
        self.spin_range_x_min = ui_refs.get("spin_range_x_min")
        self.spin_range_x_max = ui_refs.get("spin_range_x_max")
        self.spin_range_y_min = ui_refs.get("spin_range_y_min")
        self.spin_range_y_max = ui_refs.get("spin_range_y_max")

        self.apply_grid_mode_state_cb = callbacks.get("apply_grid_mode_state", self.apply_grid_mode_state_cb)
        self.show_warning_dialog_cb = callbacks.get("show_warning_dialog", self.show_warning_dialog_cb)

    # =========================================================================
    # イベントハンドラ
    # =========================================================================

    def handle_session_type_changed(self) -> None:
        is_new = self.radio_new.isChecked()
        if is_new:
            self.lbl_folder.setText(LogicConstants.FOLDER_PARENT)
            self.edit_folder.setPlaceholderText(LogicConstants.PLACEHOLDER_FOLDER_NEW)
            self.lbl_session_name.setEnabled(True)
            self.edit_session_name.setEnabled(True)
        else:
            self.lbl_folder.setText(LogicConstants.FOLDER_EXISTING)
            self.edit_folder.setPlaceholderText(LogicConstants.PLACEHOLDER_FOLDER_EXISTING)
            self.lbl_session_name.setEnabled(False)
            self.edit_session_name.setEnabled(False)

            folder_path = self.edit_folder.text().strip()
            if folder_path and os.path.isdir(folder_path):
                potential_csv = os.path.join(folder_path, "PointGeo_grid.csv")
                if os.path.isfile(potential_csv) and not self.edit_grid_csv.text().strip():
                    self.edit_grid_csv.setText(os.path.normpath(potential_csv))

    def handle_browse_folder(self) -> None:
        is_new = self.radio_new.isChecked()
        dialog_title = LogicConstants.BROWSE_FOLDER_NEW if is_new else LogicConstants.BROWSE_FOLDER_EXISTING
        start_dir = self.edit_folder.text().strip() or os.path.expanduser("~")

        selected_dir = QFileDialog.getExistingDirectory(
            self.parent_widget, dialog_title, start_dir, QFileDialog.ShowDirsOnly
        )
        if selected_dir:
            norm_path = os.path.normpath(selected_dir)
            self.edit_folder.setText(norm_path)
            if not is_new:
                potential_csv = os.path.join(norm_path, "PointGeo_grid.csv")
                if os.path.isfile(potential_csv):
                    self.edit_grid_csv.setText(potential_csv)

    def handle_browse_grid_csv(self) -> None:
        current_csv = self.edit_grid_csv.text().strip()
        start_dir = ""
        if current_csv and os.path.isfile(current_csv):
            start_dir = os.path.dirname(current_csv)
        elif self.edit_folder.text().strip() and os.path.isdir(self.edit_folder.text().strip()):
            start_dir = self.edit_folder.text().strip()
        else:
            start_dir = os.path.expanduser("~")

        selected_file, _ = QFileDialog.getOpenFileName(
            self.parent_widget,
            LogicConstants.BROWSE_GRID_CSV,
            start_dir,
            LogicConstants.CSV_FILTER,
        )
        if selected_file:
            self.edit_grid_csv.setText(os.path.normpath(selected_file))

    # =========================================================================
    # ロジック計算
    # =========================================================================

    def extract_csv_metadata(self, csv_path: str) -> Optional[Dict[str, int]]:
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

                        if not header_parsed:
                            try:
                                int(row[0].strip())
                            except ValueError:
                                for idx, col_name in enumerate(row):
                                    clean_name = col_name.strip()
                                    if "大グリッド" in clean_name and ("Ｘ" in clean_name or "X" in clean_name):
                                        col_gx = idx
                                    elif "大グリッド" in clean_name and ("Ｙ" in clean_name or "Y" in clean_name):
                                        col_gy = idx
                                    elif "小グリッド" in clean_name:
                                        col_sub = idx
                                    elif "Ｘ座標" in clean_name or "X座標" in clean_name or clean_name.upper() == "X":
                                        col_x = idx
                                    elif "Ｙ座標" in clean_name or "Y座標" in clean_name or clean_name.upper() == "Y":
                                        col_y = idx
                                header_parsed = True
                                continue
                            header_parsed = True

                        try:
                            gx = int(row[col_gx].strip())
                            gy = from_excel_column(row[col_gy].strip())
                            data_row_count += 1
                            if min_gx is None or gx < min_gx: min_gx = gx
                            if gx > max_gx: max_gx = gx
                            if min_gy is None or gy < min_gy: min_gy = gy
                            if gy > max_gy: max_gy = gy

                            if derived_origin is None:
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

    def is_range_invalid(self) -> bool:
        if self.radio_grid_mode_use_csv.isChecked() and self.edit_grid_csv.text().strip():
            return False
        return (
            self.spin_range_x_min.value() > self.spin_range_x_max.value()
            or self.spin_range_y_min.value() > self.spin_range_y_max.value()
        )

    def compute_expected_row_count(self, csv_row_count: Optional[int]) -> int:
        if self.radio_grid_mode_use_csv.isChecked() and self.edit_grid_csv.text().strip():
            return csv_row_count if csv_row_count is not None else 0

        x_min = self.spin_range_x_min.value()
        x_max = self.spin_range_x_max.value()
        y_min = self.spin_range_y_min.value()
        y_max = self.spin_range_y_max.value()
        if x_min > x_max or y_min > y_max:
            return 0
        return (x_max - x_min + 1) * (y_max - y_min + 1) * 100

    def validate_inputs(self) -> bool:
        folder_path = self.edit_folder.text().strip()

        if not folder_path:
            msg = LogicConstants.ERR_FOLDER_REQUIRED_NEW if self.radio_new.isChecked() else LogicConstants.ERR_FOLDER_REQUIRED_EXISTING
            self.show_warning_dialog_cb(LogicConstants.ERR_TITLE_INPUT, msg)
            self.edit_folder.setFocus()
            return False

        if not os.path.isdir(folder_path):
            self.show_warning_dialog_cb(LogicConstants.ERR_TITLE_PATH, LogicConstants.ERR_FOLDER_NOT_FOUND.format(path=folder_path))
            self.edit_folder.setFocus()
            return False

        if self.radio_new.isChecked():
            session_name = self.edit_session_name.text().strip()
            if not session_name:
                self.show_warning_dialog_cb(LogicConstants.ERR_TITLE_INPUT, LogicConstants.ERR_SESSION_NAME_REQUIRED)
                self.edit_session_name.setFocus()
                return False

            if re.search(self.INVALID_CHARS_PATTERN, session_name):
                self.show_warning_dialog_cb(LogicConstants.ERR_TITLE_INPUT, LogicConstants.ERR_SESSION_NAME_INVALID)
                self.edit_session_name.setFocus()
                return False

            target_session_dir = os.path.join(folder_path, session_name)
            if os.path.exists(target_session_dir):
                self.show_warning_dialog_cb(LogicConstants.ERR_TITLE_DUPLICATE, LogicConstants.ERR_SESSION_EXISTS.format(name=session_name))
                self.edit_session_name.setFocus()
                return False

        else:
            qgz_files = [f for f in os.listdir(folder_path) if f.endswith(".qgz")]
            if not qgz_files:
                self.show_warning_dialog_cb(LogicConstants.ERR_TITLE_GENERIC, LogicConstants.ERR_NO_QGZ.format(path=folder_path))
                self.edit_folder.setFocus()
                return False

        return True