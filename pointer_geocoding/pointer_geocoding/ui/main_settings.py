"""
/***************************************************************************
 PointerGeocoding Plugin - Main Settings (View)
 ***************************************************************************/

Tab 3 (環境設定) のUI構築に専念する純粋なViewモジュールです。
構築したUI要素（BuiltPanel）から発行されるイベントをUIActionへ変換し、
EventDispatcherを通じて単一方向データフローでControllerへ処理を委譲します。
"""
from typing import Optional, Any
from qgis.PyQt.QtWidgets import QWidget, QVBoxLayout, QPushButton, QScrollArea, QFrame, QColorDialog
from qgis.PyQt.QtGui import QColor

from .style import UIStyleHelper
from .constants import UIConfig, UILabels
from .core.builder import CoreUIBuilder
from .core.field_spec import FieldSpec, PanelSpec, WidgetType
from ..uilogic.settings_logic import SettingsLogic, ApplySettingsAction, PickColorAction, ChangeScaleModeAction
from ..layer.models import PluginSettings

# =========================================================================
# CoreUI Schemas for Tab 3 (Co-location)
# =========================================================================

TAB3_SETTINGS_SPEC = PanelSpec(
    panel_id="tab3_settings",
    spacing=6,
    fields=[
        # ── 基準点 ──────────────────────────────────────────────────────
        FieldSpec(field_id="ref_section", widget_type=WidgetType.SECTION_HEADER, label=UILabels.TAB3_SECTION_REF_SYMBOL),
        FieldSpec(
            field_id="ref_row1",
            widget_type=WidgetType.ROW_GROUP,
            sub_fields=[
                FieldSpec(
                    field_id="ref_sym_size", widget_type=WidgetType.DOUBLE_SPINBOX_ROW,
                    label=UILabels.TAB3_LBL_SIZE, dspin_min=0.5, dspin_max=20.0, dspin_step=0.5, dspin_default=4.0,
                    label_width=UIConfig.TAB3_ROW_LABEL_WIDTH,
                ),
                FieldSpec(
                    field_id="ref_sym_linewidth", widget_type=WidgetType.DOUBLE_SPINBOX_ROW,
                    label=UILabels.TAB3_LBL_LINEWIDTH, dspin_min=0.1, dspin_max=5.0, dspin_step=0.1, dspin_default=1.2,
                    label_width=UIConfig.TAB3_ROW_LABEL_WIDTH,
                ),
            ],
        ),
        FieldSpec(
            field_id="ref_row2",
            widget_type=WidgetType.ROW_GROUP,
            sub_fields=[
                FieldSpec(
                    field_id="ref_line_color", widget_type=WidgetType.COLOR_BUTTON_ROW,
                    label=UILabels.TAB3_LBL_LINECOLOR, color_default="#D32F2F",
                    on_click="ref_line_color_clicked", label_width=UIConfig.TAB3_ROW_LABEL_WIDTH,
                    stretch=1,
                ),
                FieldSpec(field_id="ref_row2_spacer", widget_type=WidgetType.SPACER, stretch=1),
            ],
        ),

        # ── 遺物点 ──────────────────────────────────────────────────────
        FieldSpec(field_id="point_section", widget_type=WidgetType.SECTION_HEADER, label=UILabels.TAB3_SECTION_POINT_SYMBOL),
        FieldSpec(
            field_id="point_row1",
            widget_type=WidgetType.ROW_GROUP,
            sub_fields=[
                FieldSpec(
                    field_id="point_sym_size", widget_type=WidgetType.DOUBLE_SPINBOX_ROW,
                    label=UILabels.TAB3_LBL_SIZE, dspin_min=0.5, dspin_max=20.0, dspin_step=0.5, dspin_default=6.0,
                    label_width=UIConfig.TAB3_ROW_LABEL_WIDTH,
                ),
                FieldSpec(
                    field_id="point_sym_linewidth", widget_type=WidgetType.DOUBLE_SPINBOX_ROW,
                    label=UILabels.TAB3_LBL_LINEWIDTH, dspin_min=0.1, dspin_max=5.0, dspin_step=0.1, dspin_default=0.9,
                    label_width=UIConfig.TAB3_ROW_LABEL_WIDTH,
                ),
            ],
        ),
        FieldSpec(
            field_id="point_row2",
            widget_type=WidgetType.ROW_GROUP,
            sub_fields=[
                FieldSpec(
                    field_id="point_line_color", widget_type=WidgetType.COLOR_BUTTON_ROW,
                    label=UILabels.TAB3_LBL_LINECOLOR, color_default="#E53935",
                    on_click="point_line_color_clicked", label_width=UIConfig.TAB3_ROW_LABEL_WIDTH,
                    stretch=1,
                ),
                FieldSpec(
                    field_id="point_fill_toggle", widget_type=WidgetType.RADIO_ROW,
                    options=[UILabels.TAB3_POINT_FILL_ON, UILabels.TAB3_POINT_FILL_OFF],
                    default_index=1, stretch=1,
                ),
            ],
        ),

        # ── ラベル ──────────────────────────────────────────────────────
        FieldSpec(field_id="label_section", widget_type=WidgetType.SECTION_HEADER, label=UILabels.TAB3_SECTION_LABEL_SYMBOL),
        FieldSpec(
            field_id="lbl_row1",
            widget_type=WidgetType.ROW_GROUP,
            sub_fields=[
                FieldSpec(
                    field_id="lbl_size", widget_type=WidgetType.SPINBOX_ROW,
                    label=UILabels.TAB3_LBL_SIZE, spin_min=6, spin_max=36, spin_default=UIConfig.LABEL_SIZE_REF,
                    label_width=UIConfig.TAB3_ROW_LABEL_WIDTH,
                ),
                FieldSpec(
                    field_id="lbl_offset", widget_type=WidgetType.DOUBLE_SPINBOX_ROW,
                    label=UILabels.TAB3_LABEL_OFFSET, dspin_min=0.0, dspin_max=20.0, dspin_step=0.5, dspin_default=1.0,
                    label_width=UIConfig.TAB3_ROW_LABEL_WIDTH,
                ),
            ],
        ),
        FieldSpec(
            field_id="lbl_row2",
            widget_type=WidgetType.ROW_GROUP,
            sub_fields=[
                FieldSpec(
                    field_id="halo_toggle", widget_type=WidgetType.RADIO_ROW,
                    options=[UILabels.TAB3_LABEL_HALO_ON, UILabels.TAB3_LABEL_HALO_OFF], default_index=0,
                    stretch=1,
                ),
                FieldSpec(field_id="lbl_row2_spacer", widget_type=WidgetType.SPACER, stretch=1),
            ],
        ),

        # ── 表示縮尺 ─────────────────────────────────────────────────────
        FieldSpec(field_id="scale_section", widget_type=WidgetType.SECTION_HEADER, label=UILabels.TAB3_SECTION_SCALE),
        FieldSpec(
            field_id="scale_major_row",
            widget_type=WidgetType.ROW_GROUP,
            sub_fields=[
                FieldSpec(
                    field_id="major_scale_mode", widget_type=WidgetType.RADIO_ROW,
                    label=UILabels.TAB3_SCALE_MAJOR,
                    options=[UILabels.TAB3_SCALE_ALWAYS, UILabels.TAB3_SCALE_SPECIFY],
                    default_index=0, on_change="major_scale_mode_changed",
                ),
                FieldSpec(
                    field_id="major_scale_value", widget_type=WidgetType.SPINBOX_ROW,
                    spin_min=1, spin_max=99999, spin_default=500, enabled=False,
                ),
            ],
        ),
        FieldSpec(
            field_id="scale_minor_row",
            widget_type=WidgetType.ROW_GROUP,
            sub_fields=[
                FieldSpec(
                    field_id="minor_scale_mode", widget_type=WidgetType.RADIO_ROW,
                    label=UILabels.TAB3_SCALE_MINOR,
                    options=[UILabels.TAB3_SCALE_ALWAYS, UILabels.TAB3_SCALE_SPECIFY],
                    default_index=1, on_change="minor_scale_mode_changed",
                ),
                FieldSpec(
                    field_id="minor_scale_value", widget_type=WidgetType.SPINBOX_ROW,
                    spin_min=1, spin_max=99999, spin_default=UIConfig.SCALE_THRESHOLD, enabled=True,
                ),
            ],
        ),
    ],
)


def create_tab3_ui(dock_widget: Any) -> QWidget:
    """
    Tab 3 (環境設定) のUIを構築し、シグナルとアクションのバインディングを行う。
    
    Args:
        dock_widget: メインのDockWidgetインスタンス (layer_manager, iface, dispatcher等を保持)
        
    Returns:
        構築された Tab 3 用のQWidget (QScrollArea)
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
    panel = CoreUIBuilder.build(TAB3_SETTINGS_SPEC, parent=container)
    layout.addWidget(panel.widget)

    btn_settings_apply = QPushButton(UILabels.TAB3_BTN_APPLY, container)
    UIStyleHelper.set_primary_button(btn_settings_apply)
    layout.addWidget(btn_settings_apply)

    layout.addStretch()
    scroll.setWidget(container)

    # -----------------------------------------------------------------
    # View -> Controller のコールバック定義 (GUI操作およびUI状態更新の委譲)
    # -----------------------------------------------------------------
    def _open_color_dialog(current_color: str) -> Optional[str]:
        """GUIダイアログ (QColorDialog) の表示を View 層で完結させる"""
        if current_color == "transparent":
            current_color = "#FFFFFF"
        color = QColorDialog.getColor(QColor(current_color), dock_widget, UILabels.TAB3_BTN_COLOR)
        if color.isValid():
            return color.name()
        return None

    def _set_panel_value(field_id: str, value: Any) -> None:
        """ControllerからのUI更新要求を、シグナルループを防止して安全に適用する"""
        widget = panel.get(field_id)
        if hasattr(widget, "blockSignals"):
            widget.blockSignals(True)
        panel.set_value(field_id, value)
        if hasattr(widget, "blockSignals"):
            widget.blockSignals(False)

    def _set_widget_enabled(field_id: str, enabled: bool) -> None:
        """ControllerからのUI有効/無効の切り替え要求を適用する"""
        widget = panel.get(field_id)
        widget.setEnabled(enabled)

    # -----------------------------------------------------------------
    # アクション発行 (View -> Dispatcher)
    # -----------------------------------------------------------------
    # カラーピッカーのアクション発行
    panel.bind("ref_line_color_clicked", lambda: dock_widget.dispatcher.dispatch(
        PickColorAction(field_id="ref_line_color", current_color=panel.get_value("ref_line_color") or "#FFFFFF")
    ))
    panel.bind("point_line_color_clicked", lambda: dock_widget.dispatcher.dispatch(
        PickColorAction(field_id="point_line_color", current_color=panel.get_value("point_line_color") or "#FFFFFF")
    ))
    
    # スケールモードの切り替えアクション発行 (auto_bind 活用)
    panel.auto_bind(dock_widget.dispatcher, {
        "major_scale_mode_changed": lambda idx: ChangeScaleModeAction(scale_type="major", is_active=(idx == 1)),
        "minor_scale_mode_changed": lambda idx: ChangeScaleModeAction(scale_type="minor", is_active=(idx == 1)),
    })

    # 「適用」ボタンのアクション発行
    def _on_apply_clicked() -> None:
        values = panel.collect_values()
        
        # UI用のインデックス値をドメイン用の値へ即時翻訳 [RULE-TYPE-03]
        scale_major = -1 if values["major_scale_mode"] == 0 else values["major_scale_value"]
        scale_minor = -1 if values["minor_scale_mode"] == 0 else values["minor_scale_value"]
        
        # データを DTO (PluginSettings) へ一元化
        settings = PluginSettings(
            ref_symbol_size=float(values["ref_sym_size"]),
            ref_symbol_line_width=float(values["ref_sym_linewidth"]),
            ref_symbol_line_color=values["ref_line_color"],
            point_symbol_size=float(values["point_sym_size"]),
            point_symbol_line_width=float(values["point_sym_linewidth"]),
            point_symbol_fill_enabled=(values["point_fill_toggle"] == 0),
            point_symbol_line_color=values["point_line_color"],
            label_size=int(values["lbl_size"]),
            label_halo=(values["halo_toggle"] == 0),
            label_offset=float(values["lbl_offset"]),
            scale_major_grid=scale_major,
            scale_minor_grid=scale_minor,
        )
        
        dock_widget.dispatcher.dispatch(ApplySettingsAction(settings=settings))

    btn_settings_apply.clicked.connect(_on_apply_clicked)

    # -----------------------------------------------------------------
    # Controller (SettingsLogic) の初期化とハンドラ登録
    # -----------------------------------------------------------------
    logic = SettingsLogic(
        layer_manager=dock_widget.layer_manager,
        iface=dock_widget.iface,
        dispatcher=dock_widget.dispatcher,
        parent=dock_widget
    )

    callbacks = {
        "is_focus_mode_active": lambda: dock_widget.state_store.state.focus_active if hasattr(dock_widget, "state_store") else False,
        "update_symbology_opacity": lambda: dock_widget.update_symbology_opacity() if hasattr(dock_widget, "update_symbology_opacity") else None,
        "open_color_dialog": _open_color_dialog,
        "set_panel_value": _set_panel_value,
        "set_widget_enabled": _set_widget_enabled
    }
    logic.bind_view_callbacks(callbacks)
    logic.register_handlers()

    dock_widget.settings_logic = logic
    
    # 既存呼び出し元の互換性維持のため、初期ロード用メソッドをエイリアス
    logic.update_settings_ui_from_dict = logic.load_initial_settings

    return scroll