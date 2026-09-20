"""
/***************************************************************************
 PointerGeocoding Plugin - Main Output (View)
 ***************************************************************************/

Tab 4 (出力) のUI構築に専念する純粋なViewモジュールです。
構築したUI要素は Controller (OutputLogic) に DI され、イベント処理を委譲します。
"""
from qgis.PyQt.QtWidgets import QWidget, QGroupBox, QVBoxLayout, QLabel, QRadioButton, QPushButton
from qgis.gui import QgsFilterLineEdit

from .style import UIStyleHelper
from .constants import UIConfig, UILabels, UIPlaceholders, MAIN_RATIO
from ..uilogic.output_logic import OutputLogic


def create_tab4_ui(dock_widget) -> QWidget:
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

    lbl_encoding = QLabel(UILabels.ENCODING, csv_group)
    radio_utf8 = QRadioButton(UILabels.RADIO_UTF8, csv_group)
    radio_utf8.setChecked(True)
    radio_sjis = QRadioButton(UILabels.RADIO_SJIS, csv_group)
    row_encoding = UIStyleHelper.build_flex_row(
        lbl_encoding,
        [(radio_utf8, 1), (radio_sjis, 1), (None, 1)],
        main_ratio=MAIN_RATIO,
        row_height=UIConfig.ROW_HEIGHT,
    )
    csv_layout.addWidget(row_encoding)

    lbl_csv_path = QLabel(UILabels.CSV_DESTINATION, csv_group)
    edit_csv_path = QgsFilterLineEdit(csv_group)
    edit_csv_path.setShowClearButton(True)
    edit_csv_path.setPlaceholderText(UIPlaceholders.CSV_PATH)
    btn_browse_csv = QPushButton(UILabels.BTN_BROWSE, csv_group)
    row_csv = UIStyleHelper.build_flex_row(
        lbl_csv_path,
        [(edit_csv_path, 1), (btn_browse_csv, 0)],
        main_ratio=MAIN_RATIO,
        row_height=UIConfig.ROW_HEIGHT,
    )
    csv_layout.addWidget(row_csv)

    btn_export_csv = QPushButton(UILabels.BTN_EXPORT_CSV, csv_group)
    UIStyleHelper.set_accent_button(btn_export_csv)
    csv_layout.addWidget(btn_export_csv)

    # -----------------------------------------------------------------
    # Controller (OutputLogic) の初期化と UIコンポーネントの依存性注入 (DI)
    # -----------------------------------------------------------------
    # dock_widget を親(QObject)に指定してガベージコレクションから保護
    logic = OutputLogic(
        layer_manager=dock_widget.layer_manager,
        layers_dict=dock_widget.layers_dict,
        iface=dock_widget.iface,
        parent=dock_widget
    )
    
    # イベントバインド用の参照を注入
    logic.bind_ui(
        edit_csv_path=edit_csv_path,
        radio_utf8=radio_utf8,
        btn_browse_csv=btn_browse_csv,
        btn_export_csv=btn_export_csv
    )

    return csv_group