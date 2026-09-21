"""
/***************************************************************************
 PointerGeocoding Plugin - Main Settings (View)
 ***************************************************************************/

Tab 3 (環境設定) のUI構築に専念する純粋なViewモジュールです。
UI固有の振る舞い（カラーピッカー展開など）を内部で処理し、設定の保存を
UIAction へマッピングして EventDispatcher へ委譲します。
"""
from qgis.PyQt.QtWidgets import QWidget, QVBoxLayout, QPushButton, QScrollArea, QFrame, QColorDialog
from qgis.PyQt.QtGui import QColor

from .style import UIStyleHelper
from .constants import UIConfig, UILabels
from .core.builder import CoreUIBuilder
from .core.field_spec import FieldSpec, PanelSpec, WidgetType
from ..uilogic.settings_logic import SettingsLogic
from .core.state import SaveSettingsAction

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
        UIConfig.COMMON_MARGIN_LR, UIConfig.DIALOG_MARGIN,
        UIConfig.COMMON_MARGIN_LR, UIConfig.DIALOG_MARGIN,
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
    # Controllerの初期化 (ディスパッチャーを渡す)
    # -----------------------------------------------------------------
    dock_widget.settings_logic = SettingsLogic(
        state_store=dock_widget.state_store,
        layer_manager=dock_widget.layer_manager,
        dispatcher=dock_widget.dispatcher,
        iface=dock_widget.iface,
        parent=dock_widget
    )

    # --- View層固有の副作用（UI操作） ---
    def handle_color_pick(field_id: str):
        current_color_hex = panel.get_value(field_id) or "#FFFFFF"
        if current_color_hex == "transparent":
            current_color_hex = "#FFFFFF"

        color = QColorDialog.getColor(QColor(current_color_hex), dock_widget, UILabels.TAB3_BTN_COLOR)
        if color.isValid():
            panel.set_value(field_id, color.name())

    def handle_major_scale(idx: int):
        panel.get("major_scale_value").setEnabled(idx == 1)

    def handle_minor_scale(idx: int):
        panel.get("minor_scale_value").setEnabled(idx == 1)

    # --- イベントと Action のマッピング辞書 ---
    action_mapping = {
        # これらのイベントは直接 Action を生成せず、UI内部の副作用を処理するだけなので None を返す
        "ref_line_color_clicked": lambda: handle_color_pick("ref_line_color") or None,
        "point_line_color_clicked": lambda: handle_color_pick("point_line_color") or None,
        "major_scale_mode_changed": lambda idx: handle_major_scale(idx) or None,
        "minor_scale_mode_changed": lambda idx: handle_minor_scale(idx) or None,
    }
    panel.auto_bind(dock_widget.dispatcher, action_mapping)

    # 適用ボタンは明示的にActionを生成して Dispatch する
    def dispatch_apply():
        values = panel.collect_values()
        scale_major = -1 if values["major_scale_mode"] == 0 else values["major_scale_value"]
        scale_minor = -1 if values["minor_scale_mode"] == 0 else values["minor_scale_value"]

        new_settings = {
            "ref_symbol_size":           values["ref_sym_size"],
            "ref_symbol_line_width":     values["ref_sym_linewidth"],
            "ref_symbol_line_color":     values["ref_line_color"],
            "point_symbol_size":         values["point_sym_size"],
            "point_symbol_line_width":   values["point_sym_linewidth"],
            "point_symbol_fill_enabled": values["point_fill_toggle"] == 0,
            "point_symbol_line_color":   values["point_line_color"],
            "label_size":                values["lbl_size"],
            "label_halo":                values["halo_toggle"] == 0,
            "label_offset":              values["lbl_offset"],
            "scale_major_grid":          scale_major,
            "scale_minor_grid":          scale_minor,
        }
        dock_widget.dispatcher.dispatch(SaveSettingsAction(settings=new_settings))

    btn_settings_apply.clicked.connect(dispatch_apply)

    # --- ダイアログ表示時（外部起因）のUI状態同期関数 ---
    def update_ui_from_settings():
        if not dock_widget.layer_manager or not hasattr(dock_widget.layer_manager, "load_settings"):
            return
        settings = dock_widget.layer_manager.load_settings()

        sc_maj = int(settings.get("scale_major_grid", -1))
        sc_min = int(settings.get("scale_minor_grid", UIConfig.SCALE_THRESHOLD))

        values = {
            "ref_sym_size": float(settings.get("ref_symbol_size", 4.0)),
            "ref_sym_linewidth": float(settings.get("ref_symbol_line_width", 1.2)),
            "ref_line_color": str(settings.get("ref_symbol_line_color", settings.get("ref_symbol_color", "#D32F2F"))),
            "point_sym_size": float(settings.get("point_symbol_size", 6.0)),
            "point_sym_linewidth": float(settings.get("point_symbol_line_width", 0.9)),
            "point_line_color": str(settings.get("point_symbol_line_color", settings.get("point_symbol_color", "#E53935"))),
            "point_fill_toggle": 0 if bool(settings.get("point_symbol_fill_enabled", False)) else 1,
            "lbl_size": int(settings.get("label_size", UIConfig.LABEL_SIZE_REF)),
            "halo_toggle": 0 if bool(settings.get("label_halo", True)) else 1,
            "lbl_offset": float(settings.get("label_offset", 1.0)),
            "major_scale_mode": 0 if sc_maj <= 0 else 1,
            "minor_scale_mode": 0 if sc_min <= 0 else 1,
        }
        if sc_maj > 0:
            values["major_scale_value"] = sc_maj
        if sc_min > 0:
            values["minor_scale_value"] = sc_min

        panel.set_values(values)

    # メインドックウィジェット側に更新関数をバインド（ダイアログ起動時に呼び出される）
    dock_widget.update_settings_ui = update_ui_from_settings

    return scroll