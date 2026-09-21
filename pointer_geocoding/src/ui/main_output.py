"""
/***************************************************************************
 PointerGeocoding Plugin - Main Output (View)
 ***************************************************************************/

Tab 4 (出力) のUI構築に専念する純粋なViewモジュールです。
CoreUIBuilderで構築したUIから、ユーザー操作をUIActionとしてEventDispatcherへ発行します。
UIの更新は、UIStateStoreの state_changed シグナルを受け取り、blockSignals 保護下で行われます。
"""
import os
from typing import Any, Dict
from qgis.PyQt.QtWidgets import QWidget, QVBoxLayout, QScrollArea, QFrame, QFileDialog
from qgis.core import Qgis

from .constants import UIConfig, UILabels, UIPlaceholders, UIDialogTitles
from .core.builder import CoreUIBuilder
from .core.field_spec import FieldSpec, PanelSpec, WidgetType, ButtonDef
from .core.state import UpdateOutputSettingsAction
from ..uilogic.output_logic import OutputLogic, ExportCsvAction

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

def create_tab4_ui(dock_widget: Any) -> QWidget:
    """
    Tab 4 (出力) のUIを構築し、シグナルとアクションのバインディングを行う。
    
    Args:
        dock_widget: メインのDockWidgetインスタンス (state_store, layer_manager, dispatcher等を保持)
        
    Returns:
        構築された Tab 4 用のQWidget (QScrollArea)
    """
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
    # アクション発行 (View -> Dispatcher)
    # -----------------------------------------------------------------
    
    # 宣言的なアクションマッピング (auto_bind)
    panel.auto_bind(dock_widget.dispatcher, {
        "encoding_changed": lambda idx: UpdateOutputSettingsAction(encoding=idx),
        "csv_path_changed": lambda: UpdateOutputSettingsAction(csv_path=panel.get_value("csv_path").strip()),
        "export_csv_clicked": lambda: ExportCsvAction()
    })

    # ファイルダイアログ等のView固有のUI操作は、View内で完結させてから Action を発行する
    def _on_browse_csv() -> None:
        start_dir = dock_widget.layer_manager.session_dir if dock_widget.layer_manager.session_dir else os.path.expanduser("~")
        filepath, _ = QFileDialog.getSaveFileName(
            dock_widget,
            UIDialogTitles.BROWSE_CSV,
            start_dir,
            UIDialogTitles.CSV_FILTER,
        )
        if filepath:
            norm_path = os.path.normpath(filepath)
            dock_widget.dispatcher.dispatch(UpdateOutputSettingsAction(csv_path=norm_path))
            
    panel.bind("browse_csv_clicked", _on_browse_csv)

    # -----------------------------------------------------------------
    # 状態の同期 (StateStore -> View) [RULE-UI-02]
    # -----------------------------------------------------------------
    
    def _on_state_changed(new_state: Any, diff: Dict[str, Any]) -> None:
        """UIStateStoreの変更を検知し、Tab4のUIを安全に同期する"""
        if "output_encoding" in diff:
            widget = panel.get("encoding")
            # シグナルループを防ぐため blockSignals で保護
            widget.blockSignals(True)
            panel.set_value("encoding", new_state.output_encoding)
            widget.blockSignals(False)
            
        if "output_csv_path" in diff:
            widget = panel.get("csv_path")
            widget.blockSignals(True)
            panel.set_value("csv_path", new_state.output_csv_path)
            widget.blockSignals(False)

        # エラー発生時のフィールドフォーカス制御
        if diff.get("has_input_error") and new_state.error_focus_field:
            if new_state.error_focus_field == "csv_path":
                panel.get("csv_path").setFocus()

    dock_widget.state_store.state_changed.connect(_on_state_changed)

    # -----------------------------------------------------------------
    # Controller (OutputLogic) の初期化とハンドラ登録
    # -----------------------------------------------------------------
    
    def show_message_bar(title: str, msg: str, level: int, duration: int) -> None:
        if dock_widget.iface:
            dock_widget.iface.messageBar().pushMessage(title, msg, level=level, duration=duration)

    logic = OutputLogic(
        state_store=dock_widget.state_store,
        layer_manager=dock_widget.layer_manager,
        dispatcher=dock_widget.dispatcher,
        parent=dock_widget
    )
    
    logic.bind_view_callbacks({"show_message_bar": show_message_bar})
    logic.register_handlers()
    
    dock_widget.output_logic = logic

    return scroll