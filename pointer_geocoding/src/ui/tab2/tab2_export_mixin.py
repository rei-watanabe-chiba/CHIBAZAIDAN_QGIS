"""
/***************************************************************************
 PointerGeocoding Plugin - Tab 2 (Export) Mixin
 ***************************************************************************/
"""
import os
from qgis.PyQt.QtWidgets import QWidget, QGroupBox, QVBoxLayout, QLabel, QRadioButton, QPushButton, QFileDialog
from qgis.core import Qgis
from qgis.gui import QgsFilterLineEdit

from ...logic.transform import export_points_to_csv
from ..style import UIStyleHelper
from ..constants import UIConfig, UILabels, UIPlaceholders, MAIN_RATIO, UIDialogTitles, UIMessages


class Tab2ExportMixin:
    """Mixin providing Tab 2 (CSV Export) behavior for MainDockWidget."""

    def _create_tab4_ui(self) -> QWidget:
        """Construct the 出力 (CSV export) dialog content (T-0024)."""
        csv_group = QGroupBox()
        csv_layout = QVBoxLayout(csv_group)
        csv_layout.setContentsMargins(
            UIConfig.COMMON_MARGIN_LR,
            UIConfig.DIALOG_MARGIN,
            UIConfig.COMMON_MARGIN_LR,
            UIConfig.DIALOG_MARGIN,
        )
        csv_layout.setSpacing(UIConfig.DIALOG_MARGIN)
        csv_layout.addWidget(
            UIStyleHelper.build_separator(csv_group, title_text=UILabels.GROUP_CSV)
        )

        self.lbl_encoding = QLabel(UILabels.ENCODING, csv_group)
        self.radio_utf8 = QRadioButton(UILabels.RADIO_UTF8, csv_group)
        self.radio_utf8.setChecked(True)
        self.radio_sjis = QRadioButton(UILabels.RADIO_SJIS, csv_group)
        row_encoding = UIStyleHelper.build_flex_row(
            self.lbl_encoding,
            [(self.radio_utf8, 1), (self.radio_sjis, 1), (None, 1)],
            main_ratio=MAIN_RATIO,
            row_height=UIConfig.ROW_HEIGHT,
        )
        csv_layout.addWidget(row_encoding)

        self.lbl_csv_path = QLabel(UILabels.CSV_DESTINATION, csv_group)
        self.edit_csv_path = QgsFilterLineEdit(csv_group)
        self.edit_csv_path.setShowClearButton(True)
        self.edit_csv_path.setPlaceholderText(UIPlaceholders.CSV_PATH)
        self.btn_browse_csv = QPushButton(UILabels.BTN_BROWSE, csv_group)
        self.btn_browse_csv.clicked.connect(self._browse_csv_path)
        row_csv = UIStyleHelper.build_flex_row(
            self.lbl_csv_path,
            [(self.edit_csv_path, 1), (self.btn_browse_csv, 0)],
            main_ratio=MAIN_RATIO,
            row_height=UIConfig.ROW_HEIGHT,
        )
        csv_layout.addWidget(row_csv)

        self.btn_export_csv = QPushButton(UILabels.BTN_EXPORT_CSV, csv_group)
        UIStyleHelper.set_accent_button(self.btn_export_csv)
        self.btn_export_csv.clicked.connect(self._on_export_csv_clicked)
        csv_layout.addWidget(self.btn_export_csv)

        return csv_group

    def _browse_csv_path(self) -> None:
        """Browse destination path for CSV export."""
        default_dir = self.layers_dict.get("session_dir", os.path.expanduser("~"))
        filepath, _ = QFileDialog.getSaveFileName(
            self,
            UIDialogTitles.BROWSE_CSV,
            default_dir,
            UIDialogTitles.CSV_FILTER,
        )
        if filepath:
            self.edit_csv_path.setText(os.path.normpath(filepath))

    def _on_export_csv_clicked(self) -> None:
        """Export digitized points directly to CSV."""
        filepath = self.edit_csv_path.text().strip()
        if not filepath:
            self._browse_csv_path()
            filepath = self.edit_csv_path.text().strip()
            if not filepath:
                return

        encoding = "utf-8-sig" if self.radio_utf8.isChecked() else "cp932"
        success, msg = export_points_to_csv(
            self.point_layer, filepath, encoding=encoding, parent=self
        )

        if success:
            self.iface.messageBar().pushMessage(
                UIMessages.MSG_EXPORT_CSV_TITLE,
                msg,
                level=Qgis.MessageLevel.Success,
                duration=5,
            )