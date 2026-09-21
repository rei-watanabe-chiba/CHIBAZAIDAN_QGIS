"""
/***************************************************************************
 PointerGeocoding Plugin - Main Output (View)
 ***************************************************************************/

Tab 4 (出力) のUI構築に専念する純粋なViewモジュールです。
ボタン操作等を UIAction へマッピングし、EventDispatcher へ委譲します。
"""
import os
from qgis.PyQt.QtWidgets import QWidget, QVBoxLayout, QScrollArea, QFrame, QFileDialog

from .constants import UIConfig, UILabels, UIPlaceholders, UIDialogTitles
from .core.builder import CoreUIBuilder
from .core.field_spec import FieldSpec, PanelSpec, WidgetType, ButtonDef
from ..uilogic.output_logic import OutputLogic
from .core.state import UpdateOutputSettingsAction, ExportCsvAction

# =========================================================================
# CoreUI Schemas for Tab 4 (Co-location)
# =========================================================================

TAB4_OUTPUT_SPEC = PanelSpec(
    panel_id="tab4_output",
    spacing=6,
    fields=[
        FieldSpec(
            field_id="csv_section", 
            widget_type=WidgetType.SECTION_HEADER, 
            label=UILabels.GROUP_CSV
        ),
        FieldSpec(
            field_id="encoding",
            widget_type=WidgetType.RADIO_ROW,
            label=UILabels.ENCODING,
            options=[UILabels.RADIO_UTF8, UILabels.RADIO_SJIS],
            default_index=0,
            on_change="encoding_changed",
        ),
        FieldSpec(
            field_id="csv_path",
            widget_type=WidgetType.LINEEDIT_ROW,
            label=UILabels.CSV_DESTINATION,
            placeholder=UIPlaceholders.CSV_PATH,
            trailing_button=ButtonDef(
                field_id="browse_csv", text=UILabels.BTN_BROWSE, on_click="browse_csv_clicked"
            ),
            on_change="csv_path_changed",
        ),
        FieldSpec(
            field_id="export_action",
            widget_type=WidgetType.BUTTON_ROW,
            centered=False,
            buttons=[
                ButtonDef(
                    field_id="export_csv",
                    text=UILabels.BTN_EXPORT_CSV,
                    style_variant="accent",
                    on_click="export_csv_clicked",
                )
            ]
        )
    ]
)

def create_tab4_ui(dock_widget) -> QWidget:
    """Construct the 出力 (CSV export) dialog content."""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)

    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(
        UIConfig.COMMON_MARGIN_LR, UIConfig.DIALOG_MARGIN,
        UIConfig.COMMON_MARGIN_LR, UIConfig.DIALOG_MARGIN,
    )
    layout.setSpacing(UIConfig.DIALOG_MARGIN)

    # 宣言的スキーマからのビルド
    panel = CoreUIBuilder.build(TAB4_OUTPUT_SPEC, parent=container)
    layout.addWidget(panel.widget)
    layout.addStretch()

    scroll.setWidget(container)

    # --- Controllerの初期化 (ディスパッチャーを渡す) ---
    dock_widget.output_logic = OutputLogic(
        state_store=dock_widget.state_store,
        layer_manager=dock_widget.layer_manager,
        dispatcher=dock_widget.dispatcher,
        iface=dock_widget.iface,
        parent=dock_widget
    )

    # --- 副作用のあるUI操作（ファイル選択ダイアログ）はView層で実行し、結果をActionにする ---
    def handle_browse_csv():
        start_dir = dock_widget.layer_manager.session_dir if dock_widget.layer_manager.session_dir else os.path.expanduser("~")
        filepath, _ = QFileDialog.getSaveFileName(
            dock_widget, UIDialogTitles.BROWSE_CSV, start_dir, UIDialogTitles.CSV_FILTER
        )
        if filepath:
            return UpdateOutputSettingsAction(csv_path=os.path.normpath(filepath))
        return None

    # --- イベントと Action のマッピング辞書 ---
    action_mapping = {
        "encoding_changed": lambda idx: UpdateOutputSettingsAction(encoding=idx),
        "csv_path_changed": lambda text: UpdateOutputSettingsAction(csv_path=text),
        "browse_csv_clicked": handle_browse_csv,
        "export_csv_clicked": lambda: ExportCsvAction(),
    }
    
    # 結線を自動化して Dispatcher に流す
    panel.auto_bind(dock_widget.dispatcher, action_mapping)

    # --- View側でのUI状態のリアクティブ同期 ---
    def on_state_changed(state, diff):
        if "output_encoding" in diff:
            widget = panel.get("encoding")
            widget.blockSignals(True)
            panel.set_value("encoding", state.output_encoding)
            widget.blockSignals(False)
            
        if "output_csv_path" in diff:
            widget = panel.get("csv_path")
            widget.blockSignals(True)
            panel.set_value("csv_path", state.output_csv_path)
            widget.blockSignals(False)

    dock_widget.state_store.state_changed.connect(on_state_changed)

    return scroll