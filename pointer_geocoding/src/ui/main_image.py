"""
/***************************************************************************
 PointerGeocoding Plugin - Main Image (View)
 ***************************************************************************/

Tab 1 (画像管理・事前配置) のUI構築に専念する純粋なViewモジュールです。
副作用（OSのファイル選択ダイアログ等）は最小限に留め、意図をUIActionへ変換して
EventDispatcherへ委譲します。
"""
import os
from contextlib import nullcontext
from qgis.PyQt.QtWidgets import QWidget, QVBoxLayout, QScrollArea, QFrame, QFileDialog, QMessageBox
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsPointXY

from .style import UIStyleHelper
from .constants import UIConfig, UILabels, UIPlaceholders, UIDialogTitles, UIMessages
from .core.builder import CoreUIBuilder
from .core.field_spec import ButtonDef, FieldSpec, InfoLine, PanelSpec, WidgetType
from ..uilogic.georef_logic import GeorefLogic
from .core.state import (
    ChangeTab1ModeAction, ConfirmImageAction, DeleteLayerAction, RenameLayerAction,
    TransformAction, ExportLayerAction, SetGeorefStateAction, PreviewCanvasClickedAction,
    SelectEditLayerAction, UpdateRefTableCellAction, SetValidationAction
)
from ..logic.core import from_survey_coords, to_survey_coords

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
        UIConfig.COMMON_MARGIN_LR, UIConfig.DIALOG_MARGIN,
        UIConfig.COMMON_MARGIN_LR, UIConfig.DIALOG_MARGIN,
    )
    layout.setSpacing(UIConfig.DIALOG_MARGIN)

    info_panel = CoreUIBuilder.build(TAB1_INFO_PANEL_SPEC, parent=container)
    mode_panel = CoreUIBuilder.build(TAB1_MODE_TOGGLE_SPEC, parent=container)
    image_panel = CoreUIBuilder.build(TAB1_IMAGE_SECTION_SPEC, parent=container)
    transform_panel = CoreUIBuilder.build(TAB1_TRANSFORM_SECTION_SPEC, parent=container)

    layout.addWidget(mode_panel.widget)
    layout.addWidget(image_panel.widget)
    layout.addWidget(transform_panel.widget)
    layout.addWidget(info_panel.widget)
    layout.addStretch()
    scroll.setWidget(container)

    # -----------------------------------------------------------------
    # Controllerの初期化 (ディスパッチャーを渡す)
    # -----------------------------------------------------------------
    dock_widget.georef_logic = GeorefLogic(
        state_store=dock_widget.state_store,
        layer_manager=dock_widget.layer_manager,
        layers_dict=dock_widget.layers_dict,
        dispatcher=dock_widget.dispatcher,
        iface=dock_widget.iface,
        parent=dock_widget
    )

    # =========================================================================
    # 副作用のあるUI操作 (OSネイティブのダイアログ等はViewで実行し、結果をActionにする)
    # =========================================================================
    def handle_browse_image():
        start_dir = dock_widget.layers_dict.get("session_dir", os.path.expanduser("~"))
        filepath, _ = QFileDialog.getOpenFileName(
            dock_widget, UIDialogTitles.BROWSE_IMAGE, start_dir, UIDialogTitles.IMAGE_FILTER
        )
        if filepath:
            norm_path = os.path.normpath(filepath)
            base_name, _ = os.path.splitext(os.path.basename(norm_path))
            return SetGeorefStateAction(image_path=norm_path, layer_name=base_name, clear_ref_points=True, affine_params=None, residual_summary="")
        return None

    def handle_preview_click(pixel_x: float, pixel_y: float):
        # Viewは座標計算やスナップ判定を行わず、単にクリックされた事実をDispatchする
        dock_widget.dispatcher.dispatch(PreviewCanvasClickedAction(pixel_x=pixel_x, pixel_y=pixel_y))

    # =========================================================================
    # コールバックDI
    # =========================================================================
    callbacks = {
        "get_image_dialog": lambda: getattr(dock_widget, "image_dialog", None),
        "is_focus_mode_active": lambda: dock_widget.state_store.state.focus_active if hasattr(dock_widget, "state_store") else False,
        "update_symbology_opacity": lambda: dock_widget.update_symbology_opacity() if hasattr(dock_widget, "update_symbology_opacity") else None,
        "ensure_drawing_selected": lambda name: dock_widget._ensure_drawing_selected(name) if hasattr(dock_widget, "_ensure_drawing_selected") else None,
        "ensure_drawing_visible": lambda name: dock_widget._ensure_drawing_visible(name) if hasattr(dock_widget, "_ensure_drawing_visible") else None,
        "update_drawing_combo": lambda: dock_widget._update_drawing_combo() if hasattr(dock_widget, "_update_drawing_combo") else None,
        "busy_interaction_guard": lambda: dock_widget.busy_interaction_guard() if hasattr(dock_widget, "busy_interaction_guard") else nullcontext(),
        "preview_click_handler": handle_preview_click,
    }
    dock_widget.georef_logic.bind_view_callbacks(callbacks)
    dock_widget.georef_logic.bind_ui_panels(info_panel, mode_panel, image_panel, transform_panel)

    # =========================================================================
    # イベントマッピング (auto_bind)
    # =========================================================================
    def get_table_text(row, col):
        table = image_panel.get("ref_points_table")
        item = table.item(row, col)
        return item.text().strip() if item else ""

    action_mapping = {
        "mode_changed": lambda idx: ChangeTab1ModeAction(mode="new" if idx == 0 else "edit"),
        "browse_image": handle_browse_image,
        "edit_layer_changed": lambda: SelectEditLayerAction(layer_name=image_panel.get_value("edit_layer")),
        "rename_layer": lambda: RenameLayerAction(old_name=image_panel.get_value("edit_layer"), new_name=image_panel.get_value("image_name").strip()),
        "delete_layer": lambda: DeleteLayerAction(layer_name=image_panel.get_value("edit_layer")),
        "confirm_image": lambda: ConfirmImageAction(layer_name=image_panel.get_value("image_name").strip(), image_path=image_panel.get_value("image_path").strip()),
        "ref_table_cell_changed": lambda row, col: UpdateRefTableCellAction(row=row, column=col, text_x=get_table_text(row, 2), text_y=get_table_text(row, 3)),
        "transform_clicked": lambda: TransformAction(),
        "export_layer_clicked": lambda: ExportLayerAction(layer_name=dock_widget.state_store.state.confirmed_layer_name or image_panel.get_value("image_name").strip()),
    }
    
    mode_panel.auto_bind(dock_widget.dispatcher, action_mapping)
    image_panel.auto_bind(dock_widget.dispatcher, action_mapping)
    transform_panel.auto_bind(dock_widget.dispatcher, action_mapping)

    # =========================================================================
    # UI状態のリアクティブ同期
    # =========================================================================
    def build_ref_row(i: int):
        rdata = dock_widget.state_store.state.ref_points_data[i]
        name_item = QTableWidgetItem(rdata["name"])
        name_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        pix_item = QTableWidgetItem(f"({rdata['pixel_x']:.1f}, {rdata['pixel_y']:.1f})")
        pix_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)

        if rdata["real_x"] is not None and rdata["real_y"] is not None:
            sx, sy = to_survey_coords(float(rdata["real_x"]), float(rdata["real_y"]))
            rx_str, ry_str = f"{sx:.3f}", f"{sy:.3f}"
        else:
            rx_str, ry_str = "", ""
            
        if dock_widget.image_dialog:
            dock_widget.image_dialog.add_marker(rdata["pixel_x"], rdata["pixel_y"], rdata["name"])
            
        return (name_item, pix_item, QTableWidgetItem(rx_str), QTableWidgetItem(ry_str))

    def on_state_changed(state, diff):
        # バリデーションエラーの汎用表示
        if "has_input_error" in diff and state.has_input_error and state.status_message:
            QMessageBox.warning(dock_widget, UIMessages.ERR_TITLE_INPUT, state.status_message)
            # エラー表示後、フラグをリセット（無限ループ防止）
            dock_widget.state_store.dispatch_silent(SetValidationAction(has_error=False, message=""))

        # モードの切り替え
        is_new = (state.tab1_mode == "new")
        if "tab1_mode" in diff:
            image_panel.get_row("image_path").setVisible(is_new)
            image_panel.get_row("edit_layer").setVisible(not is_new)
            image_panel.get_row("rename_delete").setVisible(not is_new)
            image_panel.get("confirm_image").setText("基準点設置" if is_new else "プレビュー再表示")

            if not is_new:
                # 編集レイヤのコンボボックスを再構築
                meta = dock_widget.layer_manager.load_image_metadata()
                combo = image_panel.get("edit_layer")
                UIStyleHelper.repopulate_combo_box(combo, list(meta.keys()), preserve_current=False)
                if combo.count() > 0:
                    dock_widget.dispatcher.dispatch(SelectEditLayerAction(layer_name=combo.currentText()))
                else:
                    dock_widget.dispatcher.dispatch(SetGeorefStateAction(image_path="", layer_name="", clear_ref_points=True, affine_params=None, residual_summary=""))
            
            has_images = bool(dock_widget.layer_manager.load_image_metadata())
            image_panel.get("rename_layer").setEnabled(has_images if not is_new else False)
            image_panel.get("delete_layer").setEnabled(has_images if not is_new else False)

        # パス・レイヤ名の同期
        if "current_copied_image_path" in diff or "confirmed_layer_name" in diff:
            w_path = image_panel.get("image_path")
            w_path.blockSignals(True)
            w_path.setText(state.current_copied_image_path or "")
            w_path.blockSignals(False)

            w_name = image_panel.get("image_name")
            w_name.blockSignals(True)
            w_name.setText(state.confirmed_layer_name or "")
            w_name.blockSignals(False)

        # 基準点テーブルと情報の同期
        keys_to_check = ("ref_points_data", "calculated_affine_params", "current_copied_image_path", "confirmed_layer_name")
        if any(k in diff for k in keys_to_check):
            if dock_widget.image_dialog:
                dock_widget.image_dialog.clear_markers()
                dock_widget.image_dialog.set_ref_points_data(state.ref_points_data)
                
            table = image_panel.get("ref_points_table")
            UIStyleHelper.rebuild_table_rows(table, len(state.ref_points_data), build_ref_row)

            count = len(state.ref_points_data)
            fname = state.confirmed_layer_name or (os.path.basename(state.current_copied_image_path) if state.current_copied_image_path else UILabels.UNLOADED)
            info_panel.get("tab1_info.line1").setText(UILabels.TAB1_INFO_IMAGE_REF.format(name=fname, count=count))

            if state.tab1_residual_summary:
                info_panel.get("tab1_info.line3_6").setText(state.tab1_residual_summary)
            else:
                info_panel.get("tab1_info.line3_6").setText(UILabels.TAB1_INFO_RESIDUAL_INIT)

            all_valid = count >= 2 and all(r["real_x"] is not None and r["real_y"] is not None for r in state.ref_points_data)
            t_btn, e_btn = transform_panel.get("transform"), transform_panel.get("export_layer")
            
            if count < 2:
                t_btn.setEnabled(False)
                e_btn.setEnabled(False)
                UIStyleHelper.update_status_panel(info_panel.get("tab1_info"), info_panel.get("tab1_info.line2"), UILabels.STATUS_NEED_MORE_REFS.format(count=count), "warning")
            elif not all_valid:
                t_btn.setEnabled(False)
                e_btn.setEnabled(False)
                UIStyleHelper.update_status_panel(info_panel.get("tab1_info"), info_panel.get("tab1_info.line2"), UILabels.STATUS_INPUT_COORDS.format(count=count), "info")
            else:
                t_btn.setEnabled(True)
                mode_str = UILabels.TRANSFORM_HELMERT if count == 2 else UILabels.TRANSFORM_AFFINE.format(count=count)
                if state.calculated_affine_params is None:
                    e_btn.setEnabled(False)
                    UIStyleHelper.update_status_panel(info_panel.get("tab1_info"), info_panel.get("tab1_info.line2"), UILabels.STATUS_READY_TRANSFORM.format(count=count, mode=mode_str), "info")
                else:
                    e_btn.setEnabled(True)
                    UIStyleHelper.update_status_panel(info_panel.get("tab1_info"), info_panel.get("tab1_info.line2"), UILabels.TAB1_INFO_TRANSFORM_DONE, "success")

    dock_widget.state_store.state_changed.connect(on_state_changed)
    return scroll