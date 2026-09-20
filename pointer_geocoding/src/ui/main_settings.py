"""
/***************************************************************************
 PointerGeocoding Plugin - Main Settings (View)
 ***************************************************************************/

Tab 3 (環境設定) のUI構築に専念する純粋なViewモジュールです。
構築したUI要素（BuiltPanel）は Controller (SettingsLogic) に DI され、
イベント処理や設定保存のロジックを一方向依存で委譲します。
"""
from qgis.PyQt.QtWidgets import QWidget, QVBoxLayout, QPushButton, QScrollArea, QFrame

from .style import UIStyleHelper
from .constants import UIConfig, UILabels
from .core.builder import CoreUIBuilder
from .core.field_spec import FieldSpec, PanelSpec, WidgetType
from ..uilogic.settings_logic import SettingsLogic

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


def create_tab3_ui(dock_widget) -> QWidget:
    """Construct Tab 3: Display & Symbol Settings."""
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

    panel = CoreUIBuilder.build(TAB3_SETTINGS_SPEC, parent=container)
    layout.addWidget(panel.widget)

    btn_settings_apply = QPushButton(UILabels.TAB3_BTN_APPLY, container)
    UIStyleHelper.set_primary_button(btn_settings_apply)
    layout.addWidget(btn_settings_apply)

    layout.addStretch()
    scroll.setWidget(container)

    # -----------------------------------------------------------------
    # Controller (SettingsLogic) の初期化と UIコンポーネントの依存性注入 (DI)
    # -----------------------------------------------------------------
    logic = SettingsLogic(
        layer_manager=dock_widget.layer_manager,
        iface=dock_widget.iface,
        parent=dock_widget
    )

    # View のコールバック群を Controller へ DI
    callbacks = {
        "is_focus_mode_active": lambda: dock_widget.state_store.state.focus_active if hasattr(dock_widget, "state_store") else False,
        "update_symbology_opacity": lambda: dock_widget.update_symbology_opacity() if hasattr(dock_widget, "update_symbology_opacity") else None,
    }
    logic.bind_view_callbacks(callbacks)

    # 構築済みの BuiltPanel と適用ボタンを Controller へ DI
    logic.bind_ui_panels(panel, btn_settings_apply)

    # ガベージコレクション回避のために DockWidget へインスタンスを保持させる
    dock_widget.settings_logic = logic

    return scroll