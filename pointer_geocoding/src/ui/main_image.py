"""
/***************************************************************************
 PointerGeocoding Plugin - Main Image (View)
 ***************************************************************************/

Tab 1 (画像管理・事前配置) のUI構築に専念する純粋なViewモジュールです。
副作用（ダイアログ等）を内部で処理し、意図をUIActionへ変換してEventDispatcherへ委譲します。
"""
import os
import math
from qgis.PyQt.QtWidgets import QWidget, QVBoxLayout, QScrollArea, QFrame, QFileDialog, QMessageBox, QDialog, QTableWidgetItem
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsProject, QgsPointXY

from .style import UIStyleHelper
from .constants import UIConfig, UILabels, UIPlaceholders, UIDialogTitles, UIMessages
from .core.builder import CoreUIBuilder
from .core.field_spec import ButtonDef, FieldSpec, InfoLine, PanelSpec, WidgetType
from .core.validators import RequiredValidator, RegexValidator, show_validation_error
from ..uilogic.georef_logic import GeorefLogic
from .core.state import (
    ChangeTab1ModeAction, ConfirmImageAction, DeleteLayerAction, RenameLayerAction,
    TransformAction, ExportLayerAction, SetGeorefStateAction
)
from ..logic.core import from_survey_coords, to_survey_coords, safe_get_str
from .dialogs import GridInputDialog

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

    # UI パネル構築
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
    # View内部の副作用・イベントハンドラ
    # =========================================================================
    
    def refresh_edit_layer_combo():
        meta = dock_widget.layer_manager.load_image_metadata()
        combo = image_panel.get("edit_layer")
        UIStyleHelper.repopulate_combo_box(combo, list(meta.keys()), preserve_current=False)
        return combo

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

    def handle_confirm_image():
        state = dock_widget.state_store.state
        if state.tab1_mode == "edit":
            open_preview_canvas()
            return None

        layer_name = image_panel.get_value("image_name").strip()
        img_path = image_panel.get_value("image_path").strip()
        
        # View側での簡易な必須・正規表現チェック（MessageBoxを出すため）
        result = RequiredValidator(UIMessages.ERR_REQUIRED_IMAGE_NAME).validate(layer_name)
        if not result.is_valid:
            show_validation_error(dock_widget, UIMessages.ERR_TITLE_INPUT, result, focus_widget=image_panel.get("image_name"))
            return None

        result = RegexValidator(r'[\\/:*?"<>|]', message=UIMessages.ERR_INVALID_IMAGE_NAME).validate(layer_name)
        if not result.is_valid:
            show_validation_error(dock_widget, UIMessages.ERR_TITLE_INPUT, result, focus_widget=image_panel.get("image_name"))
            return None

        # バリデーション後、アクションを発行（成功すればプレビューを開く）
        def post_dispatch_check():
            if not dock_widget.state_store.state.has_input_error:
                open_preview_canvas()
                
        dock_widget.dispatcher.dispatch(ConfirmImageAction(layer_name=layer_name, image_path=img_path))
        post_dispatch_check()
        return None

    def handle_delete_layer():
        layer_name = image_panel.get_value("edit_layer")
        if not layer_name: return None
            
        reply = QMessageBox.question(
            dock_widget, UIMessages.MSG_CONFIRM_DELETE_LAYER_TITLE,
            UIMessages.MSG_CONFIRM_DELETE_LAYER.format(name=layer_name),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes: return None
            
        has_points = False
        pt_layer = dock_widget.point_layer
        if pt_layer and pt_layer.isValid() and "drawing_name" in pt_layer.fields().names():
            for f in pt_layer.getFeatures():
                if safe_get_str(f, "drawing_name") == layer_name:
                    has_points = True
                    break
        if has_points:
            pts_reply = QMessageBox.question(
                dock_widget, UIMessages.MSG_CONFIRM_POINTS_EXIST_TITLE, UIMessages.MSG_CONFIRM_POINTS_EXIST,
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if pts_reply != QMessageBox.Yes: return None

        dock_widget.dispatcher.dispatch(DeleteLayerAction(layer_name=layer_name))
        
        QMessageBox.information(dock_widget, UIMessages.MSG_DELETE_LAYER_SUCCESS_TITLE, UIMessages.MSG_DELETE_LAYER_SUCCESS.format(name=layer_name))
        
        combo = refresh_edit_layer_combo()
        if combo.count() > 0:
            dock_widget.dispatcher.dispatch(SetGeorefStateAction(layer_name=combo.currentText()))
            open_preview_canvas()
        if dock_widget.state_store.state.focus_active:
            dock_widget.update_symbology_opacity()
        return None

    def handle_rename_layer():
        old_name = image_panel.get_value("edit_layer")
        new_name = image_panel.get_value("image_name").strip()
        if not old_name or not new_name: return None

        dock_widget.dispatcher.dispatch(RenameLayerAction(old_name=old_name, new_name=new_name))
        if not dock_widget.state_store.state.has_input_error:
            refresh_edit_layer_combo()
            dock_widget._ensure_drawing_selected(new_name)
            QMessageBox.information(dock_widget, UIMessages.MSG_RENAME_LAYER_SUCCESS_TITLE, UIMessages.MSG_RENAME_LAYER_SUCCESS.format(old=old_name, new=new_name))
            if dock_widget.state_store.state.focus_active:
                dock_widget.update_symbology_opacity()
        return None

    def handle_export_layer():
        layer_name = dock_widget.state_store.state.confirmed_layer_name or image_panel.get_value("image_name").strip()
        dock_widget.dispatcher.dispatch(ExportLayerAction(layer_name=layer_name))
        if not dock_widget.state_store.state.has_input_error:
            dock_widget._update_drawing_combo()
            dock_widget._ensure_drawing_selected(layer_name)
            dock_widget._ensure_drawing_visible(layer_name)
            if dock_widget.image_dialog:
                dock_widget.image_dialog.close()
        return None

    def handle_edit_layer_changed():
        layer_name = image_panel.get_value("edit_layer")
        if not layer_name:
            return SetGeorefStateAction(image_path="", layer_name="", clear_ref_points=True, affine_params=None, residual_summary="")
        
        meta = dock_widget.layer_manager.load_image_metadata().get(layer_name, {})
        image_path = meta.get("file_path", "")
        # 動的フォールバック
        if not image_path or not os.path.isfile(image_path):
            project = QgsProject.instance()
            for tree_layer in project.layerTreeRoot().findLayers():
                l = tree_layer.layer()
                if l and l.isValid() and l.name() == layer_name and hasattr(l, 'source'):
                    src = l.source()
                    if os.path.isfile(src):
                        image_path = src
                        break
                        
        affine = meta.get("affine_params")
        ref_points = [{"name": r.get("name", ""), "pixel_x": r.get("pixel_x", 0.0), "pixel_y": r.get("pixel_y", 0.0), "real_x": r.get("real_x", 0.0), "real_y": r.get("real_y", 0.0)} for r in meta.get("ref_points", [])]
        
        dock_widget.dispatcher.dispatch(SetGeorefStateAction(image_path=image_path, layer_name=layer_name, ref_points=ref_points, affine_params=tuple(affine) if affine else None, residual_summary=""))
        open_preview_canvas()
        return None

    def handle_ref_table_cell_changed(row: int, column: int):
        ref_points = dock_widget.state_store.state.ref_points_data
        if row >= len(ref_points) or column not in (2, 3): return None

        table = image_panel.get("ref_points_table")
        item_x, item_y = table.item(row, 2), table.item(row, 3)
        sx_str, sy_str = item_x.text().strip() if item_x else "", item_y.text().strip() if item_y else ""

        new_refs = [dict(r) for r in ref_points]
        try:
            if sx_str and sy_str:
                math_x, math_y = from_survey_coords(float(sx_str), float(sy_str))
                new_refs[row]["real_x"], new_refs[row]["real_y"] = math_x, math_y
            else:
                new_refs[row]["real_x"], new_refs[row]["real_y"] = None, None
        except ValueError:
            new_refs[row]["real_x"], new_refs[row]["real_y"] = None, None

        return SetGeorefStateAction(ref_points=new_refs, affine_params=None)

    # --- プレビュー操作・キャンバス連携 ---
    def open_preview_canvas():
        state = dock_widget.state_store.state
        if not state.current_copied_image_path or not os.path.isfile(state.current_copied_image_path):
            return
            
        dialog = dock_widget.image_dialog
        if dialog and dialog.raster_layer is not None:
            current_src = dialog.raster_layer.source()
            if os.path.normcase(os.path.normpath(current_src)) != os.path.normcase(os.path.normpath(state.current_copied_image_path)):
                _create_preview_layer(state.current_copied_image_path)
            else:
                dialog.set_ref_points_data(state.ref_points_data)
                dialog.show()
                dialog.raise_()
                dialog.activateWindow()
        else:
            _create_preview_layer(state.current_copied_image_path)

    def _create_preview_layer(image_path: str):
        success, msg, r_layer = dock_widget.layer_manager.load_preview_raster(image_path)
        if not success or r_layer is None:
            QMessageBox.critical(dock_widget, UIMessages.ERR_TITLE_LOAD, UIMessages.ERR_PREVIEW_FAILED.format(msg=msg))
            return
        if dock_widget.image_dialog:
            dock_widget.image_dialog.setup_raster(r_layer, handle_preview_click, dock_widget.state_store.state.ref_points_data)
            dock_widget.image_dialog.show()
            dock_widget.image_dialog.raise_()
            dock_widget.image_dialog.activateWindow()

    def handle_preview_click(pixel_x: float, pixel_y: float):
        ref_points = dock_widget.state_store.state.ref_points_data
        dialog = dock_widget.image_dialog
        snapped_index = None

        if dialog and dialog.raster_layer and dialog.georef_tool:
            tool, rlayer = dialog.georef_tool, dialog.raster_layer
            extent, w, h = rlayer.extent(), float(rlayer.width()), float(rlayer.height())
            if w > 0 and h > 0:
                click_map_x = extent.xMinimum() + (pixel_x / w) * extent.width()
                click_map_y = extent.yMaximum() - (pixel_y / h) * extent.height()
                click_screen = tool.toCanvasCoordinates(QgsPointXY(click_map_x, click_map_y))

                min_dist = float("inf")
                for idx, rdata in enumerate(ref_points):
                    rx, ry = float(rdata["pixel_x"]), float(rdata["pixel_y"])
                    r_map_x = extent.xMinimum() + (rx / w) * extent.width()
                    r_map_y = extent.yMaximum() - (ry / h) * extent.height()
                    r_screen = tool.toCanvasCoordinates(QgsPointXY(r_map_x, r_map_y))
                    dist = math.hypot(click_screen.x() - r_screen.x(), click_screen.y() - r_screen.y())
                    if dist <= 15.0 and dist < min_dist:
                        min_dist, snapped_index = dist, idx

        if snapped_index is not None:
            existing = dict(ref_points[snapped_index])
            others = [r["name"] for i, r in enumerate(ref_points) if i != snapped_index]
            dlg = GridInputDialog(dock_widget.layer_manager, existing_point=existing, existing_names=others, parent=dialog or dock_widget)
            if dlg.exec_() == QDialog.Accepted:
                new_refs = list(ref_points)
                if dlg.dialog_action == "delete":
                    del new_refs[snapped_index]
                elif dlg.dialog_action == "confirm":
                    new_refs[snapped_index] = existing
                    new_refs[snapped_index]["name"] = dlg.result_grid_name
                    new_refs[snapped_index]["real_x"] = dlg.result_real_x
                    new_refs[snapped_index]["real_y"] = dlg.result_real_y
                dock_widget.dispatcher.dispatch(SetGeorefStateAction(ref_points=new_refs, affine_params=None))
            return

        if len(ref_points) >= 4:
            QMessageBox.information(dock_widget, UIMessages.MSG_TITLE_LIMIT, UIMessages.MSG_LIMIT_REFS)
            return

        others = [r["name"] for r in ref_points]
        dlg = GridInputDialog(dock_widget.layer_manager, existing_point=None, existing_names=others, parent=dialog or dock_widget)
        if dlg.exec_() == QDialog.Accepted and dlg.dialog_action == "confirm":
            new_refs = list(ref_points)
            new_refs.append({"name": dlg.result_grid_name, "pixel_x": pixel_x, "pixel_y": pixel_y, "real_x": dlg.result_real_x, "real_y": dlg.result_real_y})
            dock_widget.dispatcher.dispatch(SetGeorefStateAction(ref_points=new_refs, affine_params=None))

    # =========================================================================
    # イベントマッピング (auto_bind)
    # =========================================================================
    action_mapping = {
        "mode_changed": lambda idx: ChangeTab1ModeAction(mode="new" if idx == 0 else "edit"),
        "browse_image": handle_browse_image,
        "edit_layer_changed": handle_edit_layer_changed,
        "rename_layer": handle_rename_layer,
        "delete_layer": handle_delete_layer,
        "confirm_image": handle_confirm_image,
        "ref_table_cell_changed": handle_ref_table_cell_changed,
        "transform_clicked": lambda: TransformAction(),
        "export_layer_clicked": handle_export_layer,
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
        # 1. モードの切り替え
        is_new = (state.tab1_mode == "new")
        if "tab1_mode" in diff:
            image_panel.get_row("image_path").setVisible(is_new)
            image_panel.get_row("edit_layer").setVisible(not is_new)
            image_panel.get_row("rename_delete").setVisible(not is_new)
            image_panel.get("confirm_image").setText("基準点設置" if is_new else "プレビュー再表示")

            if not is_new:
                combo = refresh_edit_layer_combo()
                if combo.count() > 0:
                    handle_edit_layer_changed()
                else:
                    dock_widget.dispatcher.dispatch(SetGeorefStateAction(image_path="", layer_name="", clear_ref_points=True, affine_params=None, residual_summary=""))
            
            has_images = bool(dock_widget.layer_manager.load_image_metadata())
            image_panel.get("rename_layer").setEnabled(has_images if not is_new else False)
            image_panel.get("delete_layer").setEnabled(has_images if not is_new else False)

        # 2. パス・レイヤ名の同期
        if "current_copied_image_path" in diff or "confirmed_layer_name" in diff:
            w_path = image_panel.get("image_path")
            w_path.blockSignals(True)
            w_path.setText(state.current_copied_image_path or "")
            w_path.blockSignals(False)

            w_name = image_panel.get("image_name")
            w_name.blockSignals(True)
            w_name.setText(state.confirmed_layer_name or "")
            w_name.blockSignals(False)

        # 3. 基準点テーブルと情報の同期
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