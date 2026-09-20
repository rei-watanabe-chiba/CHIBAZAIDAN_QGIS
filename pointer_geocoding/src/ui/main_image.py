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

from .constants import UIConfig
from .core.builder import CoreUIBuilder
from .schemas import (
    TAB1_INFO_PANEL_SPEC, TAB1_MODE_TOGGLE_SPEC, 
    TAB1_IMAGE_SECTION_SPEC, TAB1_TRANSFORM_SECTION_SPEC
)
from ..uilogic.georef_logic import GeorefLogic


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