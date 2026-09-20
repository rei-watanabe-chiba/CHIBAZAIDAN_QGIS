"""
/***************************************************************************
 PointerGeocoding Plugin - Main Image (View)
 ***************************************************************************/

Tab 1 (画像管理・事前配置) のUI構築に専念する純粋なViewモジュールです。
構築したUI要素（BuiltPanel）は Controller (GeorefLogic) に DI され、
イベント処理を一方向依存で委譲します。
"""
from contextlib import nullcontext
from qgis.PyQt.QtWidgets import QWidget, QVBoxLayout, QScrollArea, QFrame

from .constants import UIConfig, UILabels, UIPlaceholders
from .core.builder import CoreUIBuilder
from .core.field_spec import ButtonDef, FieldSpec, InfoLine, PanelSpec, WidgetType
from ..uilogic.georef_logic import GeorefLogic

# =========================================================================
# CoreUI Schemas for Tab 1 (Co-location)
# =========================================================================

TAB1_INFO_PANEL_SPEC = PanelSpec(
    panel_id="tab1_info_panel",
    fields=[
        FieldSpec(
            field_id="tab1_info",
            widget_type=WidgetType.INFO_PANEL,
            info_lines=[
                InfoLine(
                    kind="bold",
                    field_id="line1",
                    text=UILabels.TAB1_INFO_IMAGE_REF.format(name=UILabels.UNLOADED, count=0),
                ),
                InfoLine(kind="separator"),
                InfoLine(kind="plain", field_id="line2", text=UILabels.TRANSFORM_INIT_STATUS),
                InfoLine(
                    kind="wrap",
                    field_id="line3_6",
                    text=UILabels.TAB1_INFO_RESIDUAL_INIT,
                    min_height=14 * 4,
                ),
            ],
        ),
    ],
)

TAB1_MODE_TOGGLE_SPEC = PanelSpec(
    panel_id="tab1_mode_toggle",
    fields=[
        FieldSpec(
            field_id="tab1_mode",
            widget_type=WidgetType.SEGMENTED_TOGGLE,
            options=["新規追加", "編集削除"],
            default_index=0,
            main_ratio=(0, 10),
            on_change="mode_changed",
        ),
    ],
)

TAB1_IMAGE_SECTION_SPEC = PanelSpec(
    panel_id="tab1_image_section",
    spacing=6,
    fields=[
        FieldSpec(
            field_id="image_path",
            widget_type=WidgetType.LINEEDIT_ROW,
            label=UILabels.IMAGE_FILE,
            placeholder=UIPlaceholders.IMAGE_PATH,
            trailing_button=ButtonDef(
                field_id="browse_image", text=UILabels.BTN_BROWSE, on_click="browse_image"
            ),
        ),
        FieldSpec(
            field_id="edit_layer",
            widget_type=WidgetType.COMBOBOX_ROW,
            label="編集レイヤ:",
            on_change="edit_layer_changed",
            visible=False,
        ),
        FieldSpec(
            field_id="image_name",
            widget_type=WidgetType.LINEEDIT_ROW,
            label=UILabels.LAYER_NAME,
            placeholder=UIPlaceholders.IMAGE_NAME,
        ),
        FieldSpec(
            field_id="rename_delete",
            widget_type=WidgetType.BUTTON_ROW,
            visible=False,
            buttons=[
                ButtonDef(field_id="rename_layer", text="レイヤ名変更", on_click="rename_layer"),
                ButtonDef(field_id="delete_layer", text="削除", on_click="delete_layer"),
            ],
        ),
        FieldSpec(
            field_id="confirm_image",
            widget_type=WidgetType.BUTTON,
            label="基準点設置",
            style_variant="primary",
            on_click="confirm_image",
        ),
        FieldSpec(
            field_id="ref_points_table",
            widget_type=WidgetType.TABLE,
            table_headers=UILabels.REF_TABLE_HEADERS,
            table_col_resize_modes=["contents", "contents", "stretch", "stretch"],
            table_min_height=130,
            on_change="ref_table_cell_changed",
        ),
    ],
)

TAB1_TRANSFORM_SECTION_SPEC = PanelSpec(
    panel_id="tab1_transform_section",
    spacing=6,
    fields=[
        FieldSpec(
            field_id="transform_actions",
            widget_type=WidgetType.BUTTON_ROW,
            buttons=[
                ButtonDef(
                    field_id="transform",
                    text=UILabels.BTN_TRANSFORM,
                    style_variant="primary",
                    on_click="transform_clicked",
                    enabled=False,
                ),
                ButtonDef(
                    field_id="export_layer",
                    text=UILabels.BTN_EXPORT_LAYER,
                    style_variant="accent",
                    on_click="export_layer_clicked",
                    enabled=False,
                ),
            ],
        ),
    ],
)

def create_tab1_ui(dock_widget) -> QWidget:
    """Construct Tab 1: Image Addition & Pre-Georeferencing."""
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

    # UI パネル構築
    info_panel = CoreUIBuilder.build(TAB1_INFO_PANEL_SPEC, parent=container)
    mode_panel = CoreUIBuilder.build(TAB1_MODE_TOGGLE_SPEC, parent=container)
    image_panel = CoreUIBuilder.build(TAB1_IMAGE_SECTION_SPEC, parent=container)
    transform_panel = CoreUIBuilder.build(TAB1_TRANSFORM_SECTION_SPEC, parent=container)

    # レイアウトに配置
    layout.addWidget(mode_panel.widget)
    layout.addWidget(image_panel.widget)
    layout.addWidget(transform_panel.widget)
    layout.addWidget(info_panel.widget)
    layout.addStretch()

    scroll.setWidget(container)

    # -----------------------------------------------------------------
    # Controller (GeorefLogic) の初期化と UIコンポーネントの依存性注入 (DI)
    # -----------------------------------------------------------------
    logic = GeorefLogic(
        layer_manager=dock_widget.layer_manager,
        layers_dict=dock_widget.layers_dict,
        iface=dock_widget.iface,
        parent=dock_widget
    )

    # View のコールバック群を Controller へ DI
    callbacks = {
        # ImageDialog の生成は create_tab1_ui() よりも後になるため、遅延評価 (lambda) で取得する
        "get_image_dialog": lambda: getattr(dock_widget, "image_dialog", None),
        "is_focus_mode_active": lambda: dock_widget.state_store.state.focus_active if hasattr(dock_widget, "state_store") else False,
        "update_symbology_opacity": lambda: dock_widget.update_symbology_opacity() if hasattr(dock_widget, "update_symbology_opacity") else None,
        "ensure_drawing_selected": lambda name: dock_widget._ensure_drawing_selected(name) if hasattr(dock_widget, "_ensure_drawing_selected") else None,
        "ensure_drawing_visible": lambda name: dock_widget._ensure_drawing_visible(name) if hasattr(dock_widget, "_ensure_drawing_visible") else None,
        "update_drawing_combo": lambda: dock_widget._update_drawing_combo() if hasattr(dock_widget, "_update_drawing_combo") else None,
        "busy_interaction_guard": lambda: dock_widget.busy_interaction_guard() if hasattr(dock_widget, "busy_interaction_guard") else nullcontext(),
    }
    logic.bind_view_callbacks(callbacks)

    # 構築済みの BuiltPanel インスタンスを Controller へ DI
    logic.bind_ui_panels(info_panel, mode_panel, image_panel, transform_panel)

    # ガベージコレクション回避のために DockWidget へインスタンスを保持させる
    dock_widget.georef_logic = logic

    return scroll