"""
/***************************************************************************
 PointerGeocoding Plugin - Output Logic (Controller)
 ***************************************************************************/

Tab 4 (出力) のUIイベントを受容し、ビジネスロジック（CSVエクスポート等）
を処理するController層です。View層からは UIコンポーネント を注入（DI）されることで
直接イベントをバインドし、循環参照（Circular Import）を防ぎます。
"""
import os
from qgis.PyQt.QtCore import QObject
from qgis.PyQt.QtWidgets import QFileDialog
from qgis.core import Qgis

from ..logic.transform import export_points_to_csv
from ..ui.constants import UIDialogTitles, UIMessages


class OutputLogic(QObject):
    """
    CSV出力制御を担うControllerクラス。
    """
    def __init__(self, layer_manager, layers_dict, iface, parent=None):
        super().__init__(parent)
        self.layer_manager = layer_manager
        self.layers_dict = layers_dict
        self.iface = iface
        self.point_layer = layers_dict.get("point_layer")
        self.parent_widget = parent

        self.edit_csv_path = None
        self.radio_utf8 = None

    def bind_ui(self, edit_csv_path, radio_utf8, btn_browse_csv, btn_export_csv):
        """ViewからUIコンポーネントを受け取り、シグナルをバインドする"""
        self.edit_csv_path = edit_csv_path
        self.radio_utf8 = radio_utf8
        
        # Controller自身でイベントをバインド
        btn_browse_csv.clicked.connect(self._browse_csv_path)
        btn_export_csv.clicked.connect(self._on_export_csv_clicked)

    def _browse_csv_path(self) -> None:
        """Browse destination path for CSV export."""
        default_dir = self.layers_dict.get("session_dir", os.path.expanduser("~"))
        filepath, _ = QFileDialog.getSaveFileName(
            self.parent_widget,
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
        
        # FEAT-04: SURVEY_CSV_EXPORT 制約に基づくエクスポート処理
        # 未計算のハードブロック制約などは logic/transform.py 側で処理される
        success, msg = export_points_to_csv(
            self.point_layer, filepath, encoding=encoding, parent=self.parent_widget
        )

        if success:
            self.iface.messageBar().pushMessage(
                UIMessages.MSG_EXPORT_CSV_TITLE,
                msg,
                level=Qgis.MessageLevel.Success,
                duration=5,
            )