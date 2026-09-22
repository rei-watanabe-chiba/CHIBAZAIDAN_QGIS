"""
/***************************************************************************
 PointerGeocoding Plugin - Main Image (View)
 ***************************************************************************/

Tab 1 (画像管理・事前配置) のUI構築とイベントルーティングを担うViewモジュールです。
QMessageBoxやQFileDialogなどのGUI操作はすべてこのView内で完結させ、
確定した意思決定のみをUIActionとしてEventDispatcherへ発行します。
"""
import os
import re
from contextlib import nullcontext
from typing import Any, Dict

from qgis.core import Qgis
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QScrollArea, QFrame, 
    QMessageBox, QFileDialog, QTableWidgetItem, QDialog
)

from .constants import UIConfig, UILabels, UIPlaceholders, UIDialogTitles, UIMessages
from .core.builder import CoreUIBuilder
from .core.field_spec import ButtonDef, FieldSpec, InfoLine, PanelSpec, WidgetType
from .core.state import ChangeTab1ModeAction, SetGeorefStateAction
from .core.validators import ValidationResult, RequiredValidator, RegexValidator, DuplicateValidator, show_validation_error
from .style import UIStyleHelper
from .dialogs import GridInputDialog
from ..uilogic.georef_logic import (
    GeorefLogic, DeleteLayerAction, RenameLayerAction, 
    ExecuteTransformAction, ExportLayerAction
)

# =========================================================================
# CoreUI Schemas for Tab 1
# =========================================================================

TAB1_INFO_PANEL_SPEC = PanelSpec(
    panel_id="tab1_info_panel",
    fields=[
        FieldSpec(
            field_id="tab1_info",
            widget_type=WidgetType.INFO_PANEL,
            info_lines=[
                InfoLine(kind="bold", field_id="line1", text=UILabels.TAB1_INFO_IMAGE_REF.format(name=UILabels.UNLOADED, count=0)),
                InfoLine(kind="separator"),
                InfoLine(kind="plain", field_id="line2", text=UILabels.TRANSFORM_INIT_STATUS),
                InfoLine(kind="wrap", field_id="line3_6", text=UILabels.TAB1_INFO_RESIDUAL_INIT, min_height=14 * 4),
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
            trailing_button=ButtonDef(field_id="browse_image", text=UILabels.BTN_BROWSE, on_click="browse_image"),
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
                ButtonDef(field_id="transform", text=UILabels.BTN_TRANSFORM, style_variant="primary", on_click="transform_clicked", enabled=False),
                ButtonDef(field_id="export_layer", text=UILabels.BTN_EXPORT_LAYER, style_variant="accent", on_click="export_layer_clicked", enabled=False),
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
        UIConfig.COMMON_MARGIN_LR, UIConfig.DIALOG_MARGIN
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

    dispatcher = getattr(dock_widget, "dispatcher", dock_widget.state_store)

    logic = GeorefLogic(
        state_store=dock_widget.state_store,
        layer_manager=dock_widget.layer_manager,
        layers_dict=dock_widget.layers_dict,
        iface=dock_widget.iface,
        dispatcher=dispatcher,
        parent=dock_widget
    )

    callbacks = {
        "get_image_dialog": lambda: getattr(dock_widget, "image_dialog", None),
        "is_focus_mode_active": lambda: dock_widget.state_store.state.focus_active if hasattr(dock_widget, "state_store") else False,
        "update_symbology_opacity": lambda: dock_widget.update_symbology_opacity() if hasattr(dock_widget, "update_symbology_opacity") else None,
        "ensure_drawing_selected": lambda name: dock_widget._ensure_drawing_selected(name) if hasattr(dock_widget, "_ensure_drawing_selected") else None,
        "ensure_drawing_visible": lambda name: dock_widget._ensure_drawing_visible(name) if hasattr(dock_widget, "_ensure_drawing_visible") else None,
        "update_drawing_combo": lambda: dock_widget._update_drawing_combo() if hasattr(dock_widget, "_update_drawing_combo") else None,
    }
    logic.bind_view_callbacks(callbacks)
    dock_widget.georef_logic = logic

    # =========================================================================
    # View-side GUI event handlers
    # =========================================================================

    def _refresh_edit_layer_combo():
        meta = dock_widget.layer_manager.load_image_metadata()
        combo = image_panel.get("edit_layer")
        UIStyleHelper.repopulate_combo_box(combo, list(meta.keys()), preserve_current=False)
        if dock_widget.state_store.state.confirmed_layer_name in meta:
            idx = combo.findText(dock_widget.state_store.state.confirmed_layer_name)
            if idx >= 0:
                combo.blockSignals(True)
                combo.setCurrentIndex(idx)
                combo.blockSignals(False)

    def _on_mode_changed(idx: int):
        mode = "new" if idx == 0 else "edit"
        dock_widget.state_store.dispatch(ChangeTab1ModeAction(mode))

    def _on_browse_image_file():
        start_dir = dock_widget.layers_dict.get("session_dir", os.path.expanduser("~"))
        filepath, _ = QFileDialog.getOpenFileName(dock_widget, UIDialogTitles.BROWSE_IMAGE, start_dir, UIDialogTitles.IMAGE_FILTER)
        if filepath:
            norm_path = os.path.normpath(filepath)
            base_name, _ = os.path.splitext(os.path.basename(norm_path))
            dock_widget.state_store.dispatch(SetGeorefStateAction(
                image_path=norm_path, layer_name=base_name, clear_ref_points=True, affine_params=None
            ))

    def _on_edit_layer_changed(*args):
        layer_name = image_panel.get_value("edit_layer")
        if not layer_name:
            dock_widget.state_store.dispatch(SetGeorefStateAction(image_path="", layer_name="", clear_ref_points=True, affine_params=None))
            return
        
        meta_data = logic.load_edit_layer_metadata(layer_name)
        if meta_data:
            dock_widget.state_store.dispatch(SetGeorefStateAction(**meta_data))
            if not logic.is_modifying_layer() and meta_data["image_path"]:
                logic.show_preview_if_needed(_on_preview_canvas_point_clicked)
        else:
            dock_widget.state_store.dispatch(SetGeorefStateAction(image_path="", layer_name="", clear_ref_points=True, affine_params=None))

    def _on_rename_layer_clicked():
        old_name = image_panel.get_value("edit_layer")
        new_name = image_panel.get_value("image_name").strip()
        
        if not new_name:
            show_validation_error(dock_widget, UIMessages.ERR_TITLE_INPUT, ValidationResult(False, UIMessages.ERR_REQUIRED_IMAGE_NAME), image_panel.get("image_name"))
            return
            
        result = RegexValidator(logic.INVALID_CHARS_PATTERN, message=UIMessages.ERR_INVALID_IMAGE_NAME).validate(new_name)
        if not result.is_valid:
            show_validation_error(dock_widget, UIMessages.ERR_TITLE_INPUT, result, image_panel.get("image_name"))
            return
            
        dispatcher.dispatch(RenameLayerAction(old_name=old_name, new_name=new_name))
        
        if not dock_widget.state_store.state.has_input_error:
            QMessageBox.information(dock_widget, UIMessages.MSG_RENAME_LAYER_SUCCESS_TITLE, UIMessages.MSG_RENAME_LAYER_SUCCESS.format(old=old_name, new=new_name))
            logic.set_modifying_layer(True)
            try:
                _refresh_edit_layer_combo()
                combo = image_panel.get("edit_layer")
                idx = combo.findText(new_name)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            finally:
                logic.set_modifying_layer(False)

    def _on_delete_layer_clicked():
        layer_name = image_panel.get_value("edit_layer")
        if not layer_name: return
        
        if QMessageBox.question(dock_widget, UIMessages.MSG_CONFIRM_DELETE_LAYER_TITLE, UIMessages.MSG_CONFIRM_DELETE_LAYER.format(name=layer_name), QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
            
        has_points = logic.check_layer_has_points(layer_name)
        if has_points:
            if QMessageBox.question(dock_widget, UIMessages.MSG_CONFIRM_POINTS_EXIST_TITLE, UIMessages.MSG_CONFIRM_POINTS_EXIST, QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
                
        dispatcher.dispatch(DeleteLayerAction(layer_name=layer_name, has_points=has_points))
        
        if not dock_widget.state_store.state.has_input_error:
            QMessageBox.information(dock_widget, UIMessages.MSG_DELETE_LAYER_SUCCESS_TITLE, UIMessages.MSG_DELETE_LAYER_SUCCESS.format(name=layer_name))
            logic.set_modifying_layer(True)
            try:
                _refresh_edit_layer_combo()
                combo = image_panel.get("edit_layer")
                if combo.count() > 0:
                    if combo.currentIndex() != 0:
                        combo.setCurrentIndex(0)
                    else:
                        _on_edit_layer_changed()
                else:
                    dock_widget.state_store.dispatch(SetGeorefStateAction(image_path="", layer_name="", clear_ref_points=True, affine_params=None))
            finally:
                logic.set_modifying_layer(False)

    def _on_confirm_image_clicked():
        state = dock_widget.state_store.state
        if state.tab1_mode == "edit":
            if not state.current_copied_image_path or not os.path.isfile(state.current_copied_image_path):
                QMessageBox.information(dock_widget, UIMessages.MSG_TITLE_INFO, UIMessages.MSG_CONFIRM_IMAGE_FIRST)
                return
            logic.show_preview_if_needed(_on_preview_canvas_point_clicked)
            return

        layer_name = image_panel.get_value("image_name").strip()
        result = RequiredValidator(UIMessages.ERR_REQUIRED_IMAGE_NAME).validate(layer_name)
        if not result.is_valid:
            show_validation_error(dock_widget, UIMessages.ERR_TITLE_INPUT, result, image_panel.get("image_name"))
            return

        result = RegexValidator(logic.INVALID_CHARS_PATTERN, message=UIMessages.ERR_INVALID_IMAGE_NAME).validate(layer_name)
        if not result.is_valid:
            show_validation_error(dock_widget, UIMessages.ERR_TITLE_INPUT, result, image_panel.get("image_name"))
            return

        meta = dock_widget.layer_manager.load_image_metadata()
        result = DuplicateValidator(lambda name: name in meta, message=UIMessages.ERR_DUPLICATE_LAYER_NAME.format(name=layer_name)).validate(layer_name)
        if not result.is_valid:
            show_validation_error(dock_widget, UIMessages.ERR_TITLE_DUPLICATE, result, image_panel.get("image_name"))
            return

        src_path = image_panel.get_value("image_path").strip()
        if not src_path or not os.path.isfile(src_path):
            QMessageBox.warning(dock_widget, UIMessages.ERR_TITLE_INPUT, UIMessages.ERR_INVALID_IMAGE)
            return

        src_base, _ = os.path.splitext(src_path)
        if any(os.path.isfile(src_base + ext) for ext in logic.WORLD_FILE_EXTENSIONS):
            QMessageBox.warning(dock_widget, UIMessages.ERR_TITLE_FILE, UIMessages.ERR_SOURCE_HAS_WORLDFILE)
            return

        dock_widget.state_store.dispatch(SetGeorefStateAction(layer_name=layer_name, image_path=src_path, clear_ref_points=True, affine_params=None))
        logic.show_preview_if_needed(_on_preview_canvas_point_clicked)

    def _on_preview_canvas_point_clicked(pixel_x: float, pixel_y: float) -> None:
        snapped_index = logic.find_snapped_ref_point(pixel_x, pixel_y)
        ref_points = dock_widget.state_store.state.ref_points_data
        image_dialog = getattr(dock_widget, "image_dialog", None)
        parent_dlg = image_dialog or dock_widget

        if snapped_index is not None:
            existing_point = dict(ref_points[snapped_index])
            other_names = [r["name"] for i, r in enumerate(ref_points) if i != snapped_index]
            dlg = GridInputDialog(dock_widget.layer_manager, existing_point=existing_point, existing_names=other_names, parent=parent_dlg)
            if dlg.exec_() == QDialog.Accepted:
                new_refs = list(ref_points)
                if dlg.dialog_action == "delete":
                    del new_refs[snapped_index]
                elif dlg.dialog_action == "confirm":
                    new_refs[snapped_index] = dict(existing_point)
                    new_refs[snapped_index]["name"] = dlg.result_grid_name
                    new_refs[snapped_index]["real_x"] = dlg.result_real_x
                    new_refs[snapped_index]["real_y"] = dlg.result_real_y
                dock_widget.state_store.dispatch(SetGeorefStateAction(ref_points=new_refs, affine_params=None))
            return

        if len(ref_points) >= 4:
            QMessageBox.information(parent_dlg, UIMessages.MSG_TITLE_LIMIT, UIMessages.MSG_LIMIT_REFS)
            return

        other_names = [r["name"] for r in ref_points]
        dlg = GridInputDialog(dock_widget.layer_manager, existing_point=None, existing_names=other_names, parent=parent_dlg)
        if dlg.exec_() == QDialog.Accepted and dlg.dialog_action == "confirm":
            pt_entry = {
                "name": dlg.result_grid_name, "pixel_x": pixel_x, "pixel_y": pixel_y,
                "real_x": dlg.result_real_x, "real_y": dlg.result_real_y,
            }
            new_refs = list(ref_points)
            new_refs.append(pt_entry)
            dock_widget.state_store.dispatch(SetGeorefStateAction(ref_points=new_refs, affine_params=None))

    def _on_ref_table_cell_changed(row: int, column: int):
        ref_points = dock_widget.state_store.state.ref_points_data
        if row >= len(ref_points): return

        table_ref_points = image_panel.get("ref_points_table")
        item_x = table_ref_points.item(row, 2)
        item_y = table_ref_points.item(row, 3)
        text_x = item_x.text().strip() if item_x else ""
        text_y = item_y.text().strip() if item_y else ""

        if column in (2, 3):
            sx = sy = None
            if text_x:
                try: sx = float(text_x)
                except ValueError: pass
            if text_y:
                try: sy = float(text_y)
                except ValueError: pass

            new_refs = [dict(r) for r in ref_points]
            if sx is not None and sy is not None:
                math_x, math_y = logic.convert_to_math_coords(sx, sy)
                new_refs[row]["real_x"] = math_x
                new_refs[row]["real_y"] = math_y
            else:
                new_refs[row]["real_x"] = new_refs[row]["real_y"] = None

            dock_widget.state_store.dispatch(SetGeorefStateAction(ref_points=new_refs, affine_params=None))

    def _on_transform_clicked():
        state = dock_widget.state_store.state
        if len(state.ref_points_data) < 2:
            QMessageBox.warning(dock_widget, UIMessages.ERR_TITLE_GENERIC, UIMessages.ERR_MIN_2_REFS)
            return
            
        for rdata in state.ref_points_data:
            if rdata["real_x"] is None or rdata["real_y"] is None:
                QMessageBox.warning(dock_widget, UIMessages.ERR_TITLE_INPUT, UIMessages.ERR_INPUT_REAL_COORDS.format(name=rdata["name"]))
                return
                
        dispatcher.dispatch(ExecuteTransformAction())
        
        if not dock_widget.state_store.state.has_input_error:
            dock_widget.iface.messageBar().pushMessage(
                UIMessages.MSG_TITLE_INFO, UILabels.MSG_TRANSFORM_SUCCESS,
                level=Qgis.MessageLevel.Success, duration=4
            )

    def _on_export_layer_clicked():
        state = dock_widget.state_store.state
        if state.calculated_affine_params is None:
            QMessageBox.warning(dock_widget, UIMessages.ERR_TITLE_GENERIC, UILabels.ERR_TRANSFORM_NOT_CALCULATED)
            return
            
        layer_name = state.confirmed_layer_name or image_panel.get_value("image_name").strip()
        
        if not state.current_copied_image_path or not os.path.isfile(state.current_copied_image_path):
            QMessageBox.critical(dock_widget, UIMessages.ERR_TITLE_FILE, UIMessages.ERR_IMAGE_FILE_NOT_FOUND)
            return
            
        dispatcher.dispatch(ExportLayerAction(layer_name=layer_name, image_path=state.current_copied_image_path))
        
        if not dock_widget.state_store.state.has_input_error:
            dock_widget.iface.messageBar().pushMessage(
                UIMessages.MSG_GEOREF_COMPLETE_TITLE, UIMessages.MSG_GEOREF_COMPLETE,
                level=Qgis.MessageLevel.Success, duration=6
            )
            if state.tab1_mode == "new":
                dock_widget.state_store.dispatch(SetGeorefStateAction(image_path="", layer_name="", clear_ref_points=True, affine_params=None))
            
            image_dialog = getattr(dock_widget, "image_dialog", None)
            if image_dialog: image_dialog.close()

    # Bindings
    mode_panel.bind("mode_changed", _on_mode_changed)
    image_panel.bind("browse_image", _on_browse_image_file)
    image_panel.bind("edit_layer_changed", _on_edit_layer_changed)
    image_panel.bind("rename_layer", _on_rename_layer_clicked)
    image_panel.bind("delete_layer", _on_delete_layer_clicked)
    image_panel.bind("confirm_image", _on_confirm_image_clicked)
    image_panel.bind("ref_table_cell_changed", _on_ref_table_cell_changed)
    transform_panel.bind("transform_clicked", _on_transform_clicked)
    transform_panel.bind("export_layer_clicked", _on_export_layer_clicked)

    # =========================================================================
    # State Synchronization (View Update)
    # =========================================================================

    def _refresh_ref_points_table_and_markers(state):
        ref_points = state.ref_points_data
        image_dialog = getattr(dock_widget, "image_dialog", None)
        if image_dialog:
            image_dialog.clear_markers()
            image_dialog.set_ref_points_data(ref_points)

        def _build_row(i: int):
            rdata = ref_points[i]
            name_item = QTableWidgetItem(rdata["name"])
            name_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            pix_item = QTableWidgetItem(f"({rdata['pixel_x']:.1f}, {rdata['pixel_y']:.1f})")
            pix_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)

            rx_str = ry_str = ""
            if rdata["real_x"] is not None and rdata["real_y"] is not None:
                sx, sy = logic.convert_to_survey_coords(rdata["real_x"], rdata["real_y"])
                rx_str, ry_str = f"{sx:.3f}", f"{sy:.3f}"

            if image_dialog:
                image_dialog.add_marker(rdata["pixel_x"], rdata["pixel_y"], rdata["name"])

            return (name_item, pix_item, QTableWidgetItem(rx_str), QTableWidgetItem(ry_str))

        table_ref_points = image_panel.get("ref_points_table")
        UIStyleHelper.rebuild_table_rows(table_ref_points, len(ref_points), _build_row)

    def _update_ref_points_status(state):
        count = len(state.ref_points_data)
        fname = (state.confirmed_layer_name if state.confirmed_layer_name else (os.path.basename(state.current_copied_image_path) if state.current_copied_image_path else UILabels.UNLOADED))
        info_panel.get("tab1_info.line1").setText(UILabels.TAB1_INFO_IMAGE_REF.format(name=fname, count=count))
        info_panel.get("tab1_info.line3_6").setText("")

        all_coords_valid = False
        if count >= 2:
            all_coords_valid = all(r["real_x"] is not None and r["real_y"] is not None for r in state.ref_points_data)

        if count < 2:
            transform_panel.get("transform").setEnabled(False)
            transform_panel.get("export_layer").setEnabled(False)
            UIStyleHelper.update_status_panel(info_panel.get("tab1_info"), info_panel.get("tab1_info.line2"), UILabels.STATUS_NEED_MORE_REFS.format(count=count), status_type="warning")
        elif not all_coords_valid:
            transform_panel.get("transform").setEnabled(False)
            transform_panel.get("export_layer").setEnabled(False)
            UIStyleHelper.update_status_panel(info_panel.get("tab1_info"), info_panel.get("tab1_info.line2"), UILabels.STATUS_INPUT_COORDS.format(count=count), status_type="info")
        else:
            transform_panel.get("transform").setEnabled(True)
            mode_str = UILabels.TRANSFORM_HELMERT if count == 2 else UILabels.TRANSFORM_AFFINE.format(count=count)
            
            if state.calculated_affine_params is None:
                transform_panel.get("export_layer").setEnabled(False)
                UIStyleHelper.update_status_panel(info_panel.get("tab1_info"), info_panel.get("tab1_info.line2"), UILabels.STATUS_READY_TRANSFORM.format(count=count, mode=mode_str), status_type="info")
            else:
                transform_panel.get("export_layer").setEnabled(True)
                rotation_deg, aspect_ratio_pct = logic.get_residuals_summary(state.ref_points_data, state.calculated_affine_params)
                res_summary = f"【{mode_str} 計算完了】\n画像の回転角度: {rotation_deg:.2f} 度\nアスペクト比(縦/横): {aspect_ratio_pct:.2f} %"
                info_panel.get("tab1_info.line3_6").setText(res_summary)
                UIStyleHelper.update_status_panel(info_panel.get("tab1_info"), info_panel.get("tab1_info.line2"), UILabels.TAB1_INFO_TRANSFORM_DONE, status_type="success")

    def _on_state_changed(state: Any, diff: Dict[str, Any]):
        if "tab1_mode" in diff:
            is_new = (state.tab1_mode == "new")
            image_panel.get_row("image_path").setVisible(is_new)
            image_panel.get_row("edit_layer").setVisible(not is_new)
            image_panel.get_row("rename_delete").setVisible(not is_new)
            image_panel.get("confirm_image").setText("基準点設置" if is_new else "プレビュー再表示")
            
            if not is_new:
                logic.set_modifying_layer(True)
                try:
                    _refresh_edit_layer_combo()
                    combo = image_panel.get("edit_layer")
                    if combo.count() > 0:
                        if combo.currentIndex() != 0:
                            combo.blockSignals(True)
                            combo.setCurrentIndex(0)
                            combo.blockSignals(False)
                        _on_edit_layer_changed()
                    else:
                        dock_widget.state_store.dispatch(SetGeorefStateAction(image_path="", layer_name="", clear_ref_points=True, affine_params=None))
                finally:
                    logic.set_modifying_layer(False)

                if state.current_copied_image_path:
                    logic.show_preview_if_needed(_on_preview_canvas_point_clicked)
            else:
                dock_widget.state_store.dispatch(SetGeorefStateAction(image_path="", layer_name="", clear_ref_points=True, affine_params=None))

            has_images = bool(dock_widget.layer_manager.load_image_metadata())
            if state.tab1_mode == "edit":
                image_panel.get("rename_layer").setEnabled(has_images)
                image_panel.get("delete_layer").setEnabled(has_images)
                image_panel.get("confirm_image").setEnabled(has_images)
            else:
                image_panel.get("confirm_image").setEnabled(True)

        if "current_copied_image_path" in diff or "confirmed_layer_name" in diff:
            w_path = image_panel.get("image_path")
            w_path.blockSignals(True)
            w_path.setText(state.current_copied_image_path or "")
            w_path.blockSignals(False)

            w_name = image_panel.get("image_name")
            w_name.blockSignals(True)
            w_name.setText(state.confirmed_layer_name or "")
            w_name.blockSignals(False)

        keys_to_check = ("ref_points_data", "calculated_affine_params", "current_copied_image_path", "confirmed_layer_name")
        if any(k in diff for k in keys_to_check):
            _refresh_ref_points_table_and_markers(state)
            _update_ref_points_status(state)

    dock_widget.state_store.state_changed.connect(_on_state_changed)

    return scroll