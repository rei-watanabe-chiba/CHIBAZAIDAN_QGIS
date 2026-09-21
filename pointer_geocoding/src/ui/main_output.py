"""
/***************************************************************************
 PointerGeocoding Plugin - Main Output (View)
 ***************************************************************************/

Tab 4 (出力) のUI構築に専念する純粋なViewモジュールです。
構築したUI要素（BuiltPanel）は Controller (OutputLogic) に DI され、
イベント処理を単一方向依存で委譲します。
"""
import os
from qgis.PyQt.QtWidgets import QWidget, QVBoxLayout, QScrollArea, QFrame, QFileDialog
from qgis.core import Qgis

from .constants import UIConfig, UILabels, UIPlaceholders, UIDialogTitles
from .core.builder import CoreUIBuilder
from .core.field_spec import FieldSpec, PanelSpec, WidgetType, ButtonDef
from ..uilogic.output_logic import OutputLogic

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
        UIConfig.COMMON_MARGIN_LR,
        UIConfig.DIALOG_MARGIN,
        UIConfig.COMMON_MARGIN_LR,
        UIConfig.DIALOG_MARGIN,
    )
    layout.setSpacing(UIConfig.DIALOG_MARGIN)

    # 宣言的スキーマからのビルド
    panel = CoreUIBuilder.build(TAB4_OUTPUT_SPEC, parent=container)
    layout.addWidget(panel.widget)
    layout.addStretch()

    scroll.setWidget(container)

    # -----------------------------------------------------------------
    # Controller (OutputLogic) の初期化と UIコンポーネントの依存性注入 (DI)
    # -----------------------------------------------------------------
    logic = OutputLogic(
        state_store=dock_widget.state_store,
        layer_manager=dock_widget.layer_manager,
        parent=dock_widget
    )

    # View層固有の振る舞い（ファイルダイアログ、メッセージバー操作）を
    # Controllerへコールバック関数としてDIする
    def browse_csv_dialog(start_dir: str) -> str:
        filepath, _ = QFileDialog.getSaveFileName(
            dock_widget,
            UIDialogTitles.BROWSE_CSV,
            start_dir,
            UIDialogTitles.CSV_FILTER,
        )
        return filepath

    def show_message_bar(title: str, msg: str, level: int, duration: int) -> None:
        if dock_widget.iface:
            dock_widget.iface.messageBar().pushMessage(title, msg, level=level, duration=duration)

    callbacks = {
        "browse_csv_dialog": browse_csv_dialog,
        "show_message_bar": show_message_bar
    }
    
    logic.bind_view_callbacks(callbacks)
    logic.bind_ui_panels(panel)

    dock_widget.output_logic = logic

    return scroll