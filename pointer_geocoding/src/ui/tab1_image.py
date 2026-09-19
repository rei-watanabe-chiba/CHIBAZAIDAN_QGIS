"""
/***************************************************************************
 PointerGeocoding Plugin - Tab 1 (Georeferencing) Mixin
 ***************************************************************************/

Stage B split (mechanical, logic-preserving): extracted from main_dock.py.
Provides Tab1GeorefMixin, mixed into MainDockWidget, containing all UI
construction and event handlers for Tab 1 (image addition, preview
canvas, reference point management, coordinate transformation & layer
export).
"""
# 【変更不可侵の絶対的ルール】 測量座標系（X軸=南北, Y軸=東西）を採用。QGISキャンバス上のX座標(東西)はSurvey Y、Y座標(南北)はSurvey Xに対応する。

import os
import re
import math
from contextlib import nullcontext
from typing import Optional, List, Tuple

from qgis.core import (
    QgsProject,
    QgsPointXY,
    Qgis,
)
from qgis.PyQt.QtCore import Qt, pyqtSlot
from qgis.PyQt.QtWidgets import (
    QWidget,
    QDialog,
    QVBoxLayout,
    QScrollArea,
    QFileDialog,
    QMessageBox,
    QFrame,
    QTableWidgetItem,
)

from ..logic.transform import CoordinateTransformer
from .style import UIStyleHelper
from ..logic.core import (
    to_survey_coords,
    from_survey_coords,
    update_point_layer_geometry,
    evaluate_residuals,
    safe_get_str,
)
from .constants import (
    UIConfig,
    UILabels,
    UIDialogTitles,
    UIMessages,
)
from .dialogs import GridInputDialog
from .core import CoreUIBuilder
from .core.validators import (
    RequiredValidator,
    RegexValidator,
    DuplicateValidator,
    show_validation_error,
)
from .schemas import (
    TAB1_IMAGE_SECTION_SPEC,
    TAB1_INFO_PANEL_SPEC,
    TAB1_MODE_TOGGLE_SPEC,
    TAB1_TRANSFORM_SECTION_SPEC,
)

# T-0018: world file extensions recognized by this plugin's own georeferencing
# output (see LayerManager.write_world_file()). Shared by the "既存ワールド
# ファイル拒否" check in _on_confirm_image_clicked() and the cleanup logic in
# _on_delete_layer_clicked().
WORLD_FILE_EXTENSIONS = (".tfw", ".jgw", ".pgw", ".bpw", ".wld")


class Tab1GeorefMixin:
    """Mixin providing Tab 1 (Image Addition & Pre-Georeferencing) behavior for MainDockWidget."""

    def _create_tab1_ui(self) -> QWidget:
        """Construct Tab 1: Image Addition & Pre-Georeferencing.

        T-0045: widget construction is delegated to CoreUIBuilder against
        the declarative panels in schemas.py (TAB1_* specs); this method wires
        the built widgets/rows to the instance attributes used throughout
        this mixin and binds each panel's event hooks to the actual
        business-logic handlers below.
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

        # Information Panel (T-0020: constructed here, but placed at the
        # bottom of the side panel below; see layout.addWidget(...) near the
        # end of this method instead of here).
        info_panel = CoreUIBuilder.build(TAB1_INFO_PANEL_SPEC, parent=container)
        self.panel_tab1_info = info_panel.get("tab1_info")
        self.lbl_tab1_info_1 = info_panel.get("tab1_info.line1")
        self.lbl_tab1_info_2 = info_panel.get("tab1_info.line2")
        self.lbl_tab1_info_3_6 = info_panel.get("tab1_info.line3_6")

        # 2. Mode Toggle
        mode_panel = CoreUIBuilder.build(TAB1_MODE_TOGGLE_SPEC, parent=container)
        self.tab1_mode_container = mode_panel.get("tab1_mode")
        self.tab1_mode_buttons = mode_panel.get_buttons("tab1_mode")
        mode_panel.bind("mode_changed", self._on_tab1_mode_changed)
        layout.addWidget(mode_panel.widget)

        # 3. Mode-specific inputs + 4. Reference Points Table
        image_panel = CoreUIBuilder.build(TAB1_IMAGE_SECTION_SPEC, parent=container)
        self._tab1_image_panel = image_panel
        self.sec_image = image_panel.widget
        self.row_image_path = image_panel.get_row("image_path")
        self.edit_image_path = image_panel.get("image_path")
        self.btn_browse_image = image_panel.get("browse_image")
        self.row_edit_layer = image_panel.get_row("edit_layer")
        self.combo_edit_layer = image_panel.get("edit_layer")
        self.edit_image_name = image_panel.get("image_name")
        self.row_rename_delete = image_panel.get_row("rename_delete")
        self.btn_rename_layer = image_panel.get("rename_layer")
        self.btn_delete_layer = image_panel.get("delete_layer")
        self.btn_confirm_image = image_panel.get("confirm_image")
        self.table_ref_points = image_panel.get("ref_points_table")

        image_panel.bind("browse_image", self._browse_image_file)
        image_panel.bind("edit_layer_changed", self._on_edit_layer_changed)
        image_panel.bind("rename_layer", self._on_rename_layer_clicked)
        image_panel.bind("delete_layer", self._on_delete_layer_clicked)
        image_panel.bind("confirm_image", self._on_confirm_image_clicked)
        image_panel.bind("ref_table_cell_changed", self._on_ref_table_cell_changed)
        layout.addWidget(self.sec_image)

        # 5. Coordinate Transformation & Placement
        transform_panel = CoreUIBuilder.build(TAB1_TRANSFORM_SECTION_SPEC, parent=container)
        self.sec_transform = transform_panel.widget
        self.btn_transform = transform_panel.get("transform")
        self.btn_export_layer = transform_panel.get("export_layer")
        transform_panel.bind("transform_clicked", self._on_transform_clicked)
        transform_panel.bind("export_layer_clicked", self._on_export_layer_clicked)
        layout.addWidget(self.sec_transform)

        # T-0020: Information Panel is placed at the bottom of the 図面管理
        # side panel (moved from the top of this tab in the pre-T-0020
        # QTabWidget layout).
        layout.addWidget(self.panel_tab1_info)

        layout.addStretch()

        scroll.setWidget(container)
        return scroll

    def _on_tab1_mode_changed(self, mode_index: int) -> None:
        """Handle Tab 1 mode switch between New Add (0) and Edit/Delete (1)."""
        if mode_index == 0:
            self.row_image_path.show()
            self.row_edit_layer.hide()
            self.row_rename_delete.hide()
            self.edit_image_path.clear()
            self.edit_image_name.clear()
            self.confirmed_layer_name = None
            self.ref_points_data.clear()
            self._refresh_ref_points_table_and_markers()
        else:
            self.row_image_path.hide()
            self.row_edit_layer.show()
            self.row_rename_delete.show()
            self._refresh_edit_layer_combo()
            self._on_edit_layer_changed()

        # T-0018: keep rename/delete/setup-ref-points button enablement in
        # sync with whether any images exist, both when switching modes and
        # (via _on_delete_layer_clicked()) after a deletion.
        self._update_edit_mode_button_states()

    def _update_edit_mode_button_states(self) -> None:
        """Enable/disable per-image action buttons based on image count.

        In Edit/Delete mode, "レイヤ名変更"/"削除"/"基準点設置" all operate on
        an existing image, so they are disabled once no images remain (e.g.
        after deleting the last one). In New-Add mode, "基準点設置" must stay
        enabled even with zero images, since it is how the very first image
        gets added ("レイヤ名変更"/"削除" are not shown in this mode at all).
        """
        if self.tab1_mode_buttons[1].isChecked():
            has_images = bool(self.layer_manager.load_image_metadata())
            self.btn_rename_layer.setEnabled(has_images)
            self.btn_delete_layer.setEnabled(has_images)
            self.btn_confirm_image.setEnabled(has_images)
        else:
            self.btn_confirm_image.setEnabled(True)

    def _refresh_edit_layer_combo(self) -> None:
        meta = self.layer_manager.load_image_metadata()
        UIStyleHelper.repopulate_combo_box(
            self.combo_edit_layer, list(meta.keys()), preserve_current=False
        )

    def _on_edit_layer_changed(self) -> None:
        layer_name = self._tab1_image_panel.get_value("edit_layer")
        if not layer_name:
            self.edit_image_name.clear()
            self.ref_points_data.clear()
            # T-0018: without this, a stale path from a just-deleted (or
            # previously selected) layer would remain valid enough for
            # _on_setup_ref_points_clicked()'s os.path.isfile() guard to pass,
            # allowing a "ghost" preview to be opened once the combo is empty.
            self.current_copied_image_path = None
            self._refresh_ref_points_table_and_markers()
            return

        self.edit_image_name.setText(layer_name)
        self.confirmed_layer_name = layer_name
        
        meta = self.layer_manager.load_image_metadata()
        layer_meta = meta.get(layer_name, {})
        self.current_copied_image_path = layer_meta.get("file_path", "")
        
        self.ref_points_data = []
        for r in layer_meta.get("ref_points", []):
            self.ref_points_data.append({
                "name": r.get("name", ""),
                "pixel_x": r.get("pixel_x", 0.0),
                "pixel_y": r.get("pixel_y", 0.0),
                "real_x": r.get("real_x", 0.0),
                "real_y": r.get("real_y", 0.0),
            })
        self._refresh_ref_points_table_and_markers()

    def _on_delete_layer_clicked(self) -> None:
        layer_name = self._tab1_image_panel.get_value("edit_layer")
        if not layer_name:
            return
            
        reply = QMessageBox.question(
            self,
            UIMessages.MSG_CONFIRM_DELETE_LAYER_TITLE,
            UIMessages.MSG_CONFIRM_DELETE_LAYER.format(name=layer_name),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
            
        # Warning if points exist for this drawing
        if self.point_layer and self.point_layer.isValid() and "drawing_name" in self.point_layer.fields().names():
            has_points = False
            for f in self.point_layer.getFeatures():
                if safe_get_str(f, "drawing_name") == layer_name:
                    has_points = True
                    break
            if has_points:
                pts_reply = QMessageBox.question(
                    self,
                    UIMessages.MSG_CONFIRM_POINTS_EXIST_TITLE,
                    UIMessages.MSG_CONFIRM_POINTS_EXIST,
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                )
                if pts_reply != QMessageBox.Yes:
                    return

        with (self.busy_interaction_guard() if hasattr(self, "busy_interaction_guard") else nullcontext()):
            if has_points:
                self.layer_manager.clear_drawing_name_for_layer(layer_name)

            # Remove from QGIS Project first to release file locks
            project = QgsProject.instance()
            for tree_layer in project.layerTreeRoot().findLayers():
                l = tree_layer.layer()
                if l and l.name() == layer_name:
                    project.removeMapLayer(l.id())
                    break

            # T-0018: force an immediate canvas redraw so the removed layer's
            # image does not linger on screen as a "ghost" until the user pans
            # or zooms (removeMapLayer() alone does not repaint the canvas).

            # Delete metadata and file
            meta = self.layer_manager.load_image_metadata()
            if layer_name in meta:
                file_path = meta[layer_name].get("file_path", "")
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except Exception:
                        pass

                # Also remove world files if exist
                base, _ = os.path.splitext(file_path)
                for ext in WORLD_FILE_EXTENSIONS:
                    if os.path.exists(base + ext):
                        try:
                            os.remove(base + ext)
                        except Exception:
                            pass

                self.layer_manager.delete_image_metadata(layer_name)

            # T-0018: unconditionally tear down the preview dialog after any
            # deletion. If other images remain, the user simply re-opens "基準点
            # 設置" for the desired one and a fresh preview is built; this avoids
            # leaving a stale/ghost raster_layer reference around that could be
            # (mis)reused by _on_setup_ref_points_clicked()/_on_confirm_image_clicked().
            self._destroy_preview_canvas()

            # Phase 1: Event-driven opacity update after delete
            if hasattr(self, "is_focus_mode_active") and self.is_focus_mode_active():
                if hasattr(self, "update_symbology_opacity"):
                    self.update_symbology_opacity()

        QMessageBox.information(
            self,
            UIMessages.MSG_DELETE_LAYER_SUCCESS_TITLE,
            UIMessages.MSG_DELETE_LAYER_SUCCESS.format(name=layer_name),
        )
        self._refresh_edit_layer_combo()
        self._on_edit_layer_changed()
        self._update_edit_mode_button_states()

    def _on_rename_layer_clicked(self) -> None:
        """Rename the currently selected layer (T-0015: metadata-only rename).

        This only reassigns the metadata dictionary key and calls
        ``QgsRasterLayer.setName()`` on the matching project-tree layer; the
        underlying image file on disk is never touched (no copy, no delete, no
        ``os.rename()``), so this operation cannot raise a Windows
        ``[WinError 32]``-style file-locking error by construction.
        """
        old_name = self._tab1_image_panel.get_value("edit_layer")
        if not old_name:
            return

        new_name = self._tab1_image_panel.get_value("image_name").strip()

        if not new_name:
            QMessageBox.warning(
                self, UIMessages.ERR_TITLE_INPUT, UIMessages.ERR_REQUIRED_IMAGE_NAME,
            )
            self.edit_image_name.setFocus()
            return

        if re.search(self.INVALID_CHARS_PATTERN, new_name):
            QMessageBox.warning(
                self, UIMessages.ERR_TITLE_INPUT, UIMessages.ERR_INVALID_IMAGE_NAME,
            )
            self.edit_image_name.setFocus()
            return

        if new_name == old_name:
            return

        meta = self.layer_manager.load_image_metadata()
        if old_name not in meta:
            QMessageBox.warning(
                self,
                UIMessages.ERR_TITLE_GENERIC,
                UIMessages.ERR_LAYER_META_NOT_FOUND.format(name=old_name),
            )
            return

        if new_name in meta:
            QMessageBox.warning(
                self,
                UIMessages.ERR_TITLE_DUPLICATE,
                UIMessages.ERR_DUPLICATE_LAYER_NAME.format(name=new_name),
            )
            self.edit_image_name.setFocus()
            return

        with (self.busy_interaction_guard() if hasattr(self, "busy_interaction_guard") else nullcontext()):
            # 1. Rename the matching raster layer in the QGIS project tree, if loaded.
            # NOTE (T-0012, carried over): matched by display name, which has been
            # reported as reliably identifying the layer for this session's raster group.
            project = QgsProject.instance()
            for tree_layer in project.layerTreeRoot().findLayers():
                layer = tree_layer.layer()
                if layer and layer.name() == old_name:
                    layer.setName(new_name)
                    break

            # 2. Reassign the metadata dictionary key (file_path/ref_points/affine_params
            # are carried over unchanged; the physical file itself is never touched).
            meta[new_name] = meta.pop(old_name)
            self.layer_manager.save_image_metadata(meta)
            self.confirmed_layer_name = new_name
            self.current_copied_image_path = meta[new_name].get(
                "file_path", self.current_copied_image_path
            )

            # 3. Update drawing_name attribute on digitized points referencing the old name.
            self.layer_manager.rename_drawing_name(old_name, new_name)

            # 4. Refresh the edit-layer combo and reselect the renamed layer.
            self._refresh_edit_layer_combo()
            index = self.combo_edit_layer.findText(new_name)
            if index >= 0:
                self.combo_edit_layer.setCurrentIndex(index)
            self._on_edit_layer_changed()

            self.lbl_tab1_info_1.setText(
                UILabels.TAB1_INFO_IMAGE_REF.format(name=new_name, count=len(self.ref_points_data))
            )

            # Phase 1: Event-driven opacity update after rename
            if hasattr(self, "is_focus_mode_active") and self.is_focus_mode_active():
                if hasattr(self, "update_symbology_opacity"):
                    self.update_symbology_opacity()

        if hasattr(self, "_ensure_drawing_selected"):
            self._ensure_drawing_selected(new_name)

        QMessageBox.information(
            self,
            UIMessages.MSG_RENAME_LAYER_SUCCESS_TITLE,
            UIMessages.MSG_RENAME_LAYER_SUCCESS.format(old=old_name, new=new_name),
        )

    # =========================================================================
    # Tab 1: Image Addition, Preview Canvas & Georeferencing Handlers
    # =========================================================================

    def _browse_image_file(self) -> None:
        """Open file dialog to select an analog drawing image."""
        start_dir = self.layers_dict.get("session_dir", os.path.expanduser("~"))
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            UIDialogTitles.BROWSE_IMAGE,
            start_dir,
            UIDialogTitles.IMAGE_FILTER,
        )
        if filepath:
            norm_path = os.path.normpath(filepath)
            self.edit_image_path.setText(norm_path)
            base_name, ext = os.path.splitext(os.path.basename(norm_path))
            self.edit_image_name.setText(base_name)
            self.confirmed_layer_name = None

    def _on_confirm_image_clicked(self) -> None:
        """Handle the "基準点設置" button.

        New-add mode: validate the source image (layer name, duplicate check,
        rejects images with an existing world file) and open the preview
        canvas directly against the original source file for reference-point
        setup. T-0018: the file is NOT copied into the session here anymore
        (see ``_on_export_layer_clicked``, which performs the copy just
        before writing the world file); this avoids leaving an orphaned copy
        under image/ if setup is cancelled before "レイヤ出力" completes.
        Edit/delete mode: renaming is handled separately by
        ``_on_rename_layer_clicked`` (metadata-only, no file I/O), so here we
        simply (re)open the preview canvas for the currently selected layer.
        """
        is_edit_mode = self.tab1_mode_buttons[1].isChecked()

        if is_edit_mode:
            self._on_setup_ref_points_clicked()
            return

        layer_name = self._tab1_image_panel.get_value("image_name").strip()

        # T-0045-b (③) + extension: required/forbidden-pattern/duplicate
        # checks are judged via the generic ui/core/validators.py Validator
        # classes, and their failure display (QMessageBox.warning() + focus)
        # is collapsed via show_validation_error(); messages/focus targets
        # are unchanged from before.
        result = RequiredValidator(UIMessages.ERR_REQUIRED_IMAGE_NAME).validate(layer_name)
        if not result.is_valid:
            show_validation_error(self, UIMessages.ERR_TITLE_INPUT, result, focus_widget=self.edit_image_name)
            return

        result = RegexValidator(
            self.INVALID_CHARS_PATTERN, message=UIMessages.ERR_INVALID_IMAGE_NAME
        ).validate(layer_name)
        if not result.is_valid:
            show_validation_error(self, UIMessages.ERR_TITLE_INPUT, result, focus_widget=self.edit_image_name)
            return

        # T-0015: the on-disk image file name no longer doubles as the layer
        # name, so layer-name uniqueness must be checked against the metadata
        # keys directly (previously this was checked indirectly via the
        # destination file-existence check inside copy_image_to_session()).
        meta = self.layer_manager.load_image_metadata()
        result = DuplicateValidator(
            lambda name: name in meta,
            message=UIMessages.ERR_DUPLICATE_LAYER_NAME.format(name=layer_name),
        ).validate(layer_name)
        if not result.is_valid:
            show_validation_error(self, UIMessages.ERR_TITLE_DUPLICATE, result, focus_widget=self.edit_image_name)
            return

        src_path = self._tab1_image_panel.get_value("image_path").strip()
        if not src_path or not os.path.isfile(src_path):
            QMessageBox.warning(
                self,
                UIMessages.ERR_TITLE_INPUT,
                UIMessages.ERR_INVALID_IMAGE,
            )
            self.edit_image_path.setFocus()
            return

        # T-0018: reject source images that already carry a world file. This
        # plugin always derives its own world file from the computed affine/
        # Helmert transform at "レイヤ出力" time, so an existing world file
        # would create ambiguity about which georeferencing is authoritative.
        src_base, _ = os.path.splitext(src_path)
        if any(os.path.isfile(src_base + ext) for ext in WORLD_FILE_EXTENSIONS):
            QMessageBox.warning(
                self,
                UIMessages.ERR_TITLE_FILE,
                UIMessages.ERR_SOURCE_HAS_WORLDFILE,
            )
            self.edit_image_path.setFocus()
            return

        # T-0018: do NOT copy the image into the session yet here. Copying at
        # "基準点設置" time (as before) meant a setup that was interrupted or
        # cancelled before "レイヤ出力" left an orphaned copy under image/,
        # which then made copy_image_to_session()'s destination-exists check
        # reject a later retry with the same source file. The physical copy
        # is now deferred until _on_export_layer_clicked(), immediately
        # before the world file is written; until then, current_copied_image_path
        # simply points at the original (uncopied) source file, which the
        # preview dialog can load directly (load_preview_raster() only needs
        # a readable file path, independent of where it lives).
        self.confirmed_layer_name = layer_name
        self.current_copied_image_path = src_path

        # Clear old reference points for newly added image
        self.ref_points_data.clear()
        self.calculated_affine_params = None
        self._refresh_ref_points_table_and_markers()
        if self.image_dialog:
            self.image_dialog.clear_markers()
            self.image_dialog.set_ref_points_data([])

        self.lbl_tab1_info_1.setText(
            UILabels.TAB1_INFO_IMAGE_REF.format(
                name=layer_name, count=len(self.ref_points_data)
            )
        )

        # Automatically show the 画像 dialog with its embedded preview canvas
        if self.image_dialog and self.image_dialog.raster_layer is not None:
            self.image_dialog.set_ref_points_data(self.ref_points_data)
            self.image_dialog.show()
            self.image_dialog.raise_()
            self.image_dialog.activateWindow()
        else:
            self._create_preview_canvas(self.current_copied_image_path)

    def _create_preview_canvas(self, image_path: str) -> bool:
        """Load a raster into the 画像 dialog's embedded preview canvas (T-0024).

        self.image_dialog (main_dock_dialogs.ImageDialog) is constructed once
        at dock init time (it also hosts the 画像管理 form), so this only
        needs to (re)populate its raster/georef tool via setup_raster() and
        show/raise/activate the dialog window itself.
        """
        success, msg, raster_layer = self.layer_manager.load_preview_raster(image_path)
        if not success or raster_layer is None:
            QMessageBox.critical(
                self,
                UIMessages.ERR_TITLE_LOAD,
                UIMessages.ERR_PREVIEW_FAILED.format(msg=msg),
            )
            return False

        self.image_dialog.setup_raster(
            raster_layer,
            self._on_preview_canvas_point_clicked,
            self.ref_points_data,
        )
        self.image_dialog.show()
        self.image_dialog.raise_()
        self.image_dialog.activateWindow()

        return True

    def _destroy_preview_canvas(self) -> None:
        """Safely clean up the 画像 dialog's embedded preview canvas resources.

        Only clears the raster/georef tool state (image_dialog.clean_up());
        it does not close the dialog itself, since it also hosts the
        画像管理 form (which should stay open/usable, e.g. after deleting a
        single layer in Edit/Delete mode). See _on_export_layer_clicked()
        for the explicit self.image_dialog.close() once a full georeference
        workflow completes.
        """
        if self.image_dialog is not None:
            self.image_dialog.clean_up()

    def _on_setup_ref_points_clicked(self) -> None:
        """Open or raise the modeless preview dialog for setting reference points."""
        if not self.current_copied_image_path or not os.path.isfile(self.current_copied_image_path):
            QMessageBox.information(
                self,
                UIMessages.MSG_TITLE_INFO,
                UIMessages.MSG_CONFIRM_IMAGE_FIRST,
            )
            return

        if self.image_dialog and self.image_dialog.raster_layer is not None:
            self.image_dialog.set_ref_points_data(self.ref_points_data)
            self.image_dialog.show()
            self.image_dialog.raise_()
            self.image_dialog.activateWindow()
        else:
            self._create_preview_canvas(self.current_copied_image_path)

    @pyqtSlot(float, float)
    def _on_preview_canvas_point_clicked(self, pixel_x: float, pixel_y: float) -> None:
        """Handle reference point click on preview canvas with 15px snap detection and GridInputDialog."""
        snapped_index: Optional[int] = None

        # 1. Snap test against existing reference points within 15 screen pixels
        if (
            self.image_dialog
            and self.image_dialog.raster_layer
            and self.image_dialog.georef_tool
        ):
            tool = self.image_dialog.georef_tool
            rlayer = self.image_dialog.raster_layer
            extent = rlayer.extent()
            w = float(rlayer.width())
            h = float(rlayer.height())

            if w > 0 and h > 0 and extent.width() > 0 and extent.height() > 0:
                click_map_x = extent.xMinimum() + (pixel_x / w) * extent.width()
                click_map_y = extent.yMaximum() - (pixel_y / h) * extent.height()
                click_screen = tool.toCanvasCoordinates(QgsPointXY(click_map_x, click_map_y))

                min_dist = float("inf")
                for idx, rdata in enumerate(self.ref_points_data):
                    rx = float(rdata["pixel_x"])
                    ry = float(rdata["pixel_y"])
                    r_map_x = extent.xMinimum() + (rx / w) * extent.width()
                    r_map_y = extent.yMaximum() - (ry / h) * extent.height()
                    r_screen = tool.toCanvasCoordinates(QgsPointXY(r_map_x, r_map_y))
                    dist = math.hypot(
                        click_screen.x() - r_screen.x(), click_screen.y() - r_screen.y()
                    )
                    if dist <= 15.0 and dist < min_dist:
                        min_dist = dist
                        snapped_index = idx

        # 2. Case: Snapped to existing point -> Edit / Delete modal
        if snapped_index is not None:
            existing_point = self.ref_points_data[snapped_index]
            other_names = [
                r["name"] for i, r in enumerate(self.ref_points_data) if i != snapped_index
            ]
            dlg = GridInputDialog(
                self.layer_manager,
                existing_point=existing_point,
                existing_names=other_names,
                parent=self.image_dialog or self,
            )
            if dlg.exec_() == QDialog.Accepted:
                if dlg.dialog_action == "delete":
                    del self.ref_points_data[snapped_index]
                    self.calculated_affine_params = None
                    self._refresh_ref_points_table_and_markers()
                elif dlg.dialog_action == "confirm":
                    existing_point["name"] = dlg.result_grid_name
                    existing_point["real_x"] = dlg.result_real_x
                    existing_point["real_y"] = dlg.result_real_y
                    self.calculated_affine_params = None
                    self._refresh_ref_points_table_and_markers()
            return

        # 3. Case: New point clicked -> Add new modal
        if len(self.ref_points_data) >= 4:
            QMessageBox.information(
                self,
                UIMessages.MSG_TITLE_LIMIT,
                UIMessages.MSG_LIMIT_REFS,
            )
            return

        other_names = [r["name"] for r in self.ref_points_data]
        dlg = GridInputDialog(
            self.layer_manager,
            existing_point=None,
            existing_names=other_names,
            parent=self.image_dialog or self,
        )
        if dlg.exec_() == QDialog.Accepted and dlg.dialog_action == "confirm":
            pt_entry = {
                "name": dlg.result_grid_name,
                "pixel_x": pixel_x,
                "pixel_y": pixel_y,
                "real_x": dlg.result_real_x,
                "real_y": dlg.result_real_y,
            }
            self.ref_points_data.append(pt_entry)
            self.calculated_affine_params = None
            self._refresh_ref_points_table_and_markers()

    def _on_ref_table_cell_changed(self, row: int, column: int) -> None:
        """Handle coordinate manual entry in reference points table."""
        if row >= len(self.ref_points_data):
            return

        item_x = self.table_ref_points.item(row, 2)
        item_y = self.table_ref_points.item(row, 3)
        text_x = item_x.text().strip() if item_x else ""
        text_y = item_y.text().strip() if item_y else ""

        if column in (2, 3):
            sx: Optional[float] = None
            sy: Optional[float] = None
            if text_x:
                try:
                    sx = float(text_x)
                except ValueError:
                    sx = None
            if text_y:
                try:
                    sy = float(text_y)
                except ValueError:
                    sy = None

            if sx is not None and sy is not None:
                # User entered survey coordinates (column 2=X(North), column 3=Y(East))
                # Convert to internal mathematical coordinates
                math_x, math_y = from_survey_coords(sx, sy)
                self.ref_points_data[row]["real_x"] = math_x
                self.ref_points_data[row]["real_y"] = math_y
            else:
                self.ref_points_data[row]["real_x"] = None
                self.ref_points_data[row]["real_y"] = None

            self.calculated_affine_params = None
            self._update_ref_points_status()

    def _update_ref_points_status(self) -> None:
        """Refresh reference point UI state and validate button enabling."""
        count = len(self.ref_points_data)
        fname = (
            self.confirmed_layer_name
            if self.confirmed_layer_name
            else (
                os.path.basename(self.current_copied_image_path)
                if self.current_copied_image_path
                else UILabels.UNLOADED
            )
        )
        self.lbl_tab1_info_1.setText(
            UILabels.TAB1_INFO_IMAGE_REF.format(name=fname, count=count)
        )
        self.lbl_tab1_info_3_6.setText("")

        # Check if at least 2 points exist and all have valid coordinates
        all_coords_valid = False
        if count >= 2:
            all_coords_valid = all(
                r["real_x"] is not None and r["real_y"] is not None
                for r in self.ref_points_data
            )

        if count < 2:
            self.btn_transform.setEnabled(False)
            self.btn_export_layer.setEnabled(False)
            self.calculated_affine_params = None
            UIStyleHelper.update_status_panel(
                self.panel_tab1_info,
                self.lbl_tab1_info_2,
                UILabels.STATUS_NEED_MORE_REFS.format(count=count),
                status_type="warning",
            )
        elif not all_coords_valid:
            self.btn_transform.setEnabled(False)
            self.btn_export_layer.setEnabled(False)
            self.calculated_affine_params = None
            UIStyleHelper.update_status_panel(
                self.panel_tab1_info,
                self.lbl_tab1_info_2,
                UILabels.STATUS_INPUT_COORDS.format(count=count),
                status_type="info",
            )
        else:
            self.btn_transform.setEnabled(True)
            mode_str = (
                UILabels.TRANSFORM_HELMERT
                if count == 2
                else UILabels.TRANSFORM_AFFINE.format(count=count)
            )
            if self.calculated_affine_params is None:
                self.btn_export_layer.setEnabled(False)
                UIStyleHelper.update_status_panel(
                    self.panel_tab1_info,
                    self.lbl_tab1_info_2,
                    UILabels.STATUS_READY_TRANSFORM.format(
                        count=count, mode=mode_str
                    ),
                    status_type="info",
                )
            else:
                self.btn_export_layer.setEnabled(True)

    def _on_delete_selected_ref_point(self) -> None:
        """Delete selected reference point from list and table."""
        current_row = self.table_ref_points.currentRow()
        if current_row < 0 or current_row >= len(self.ref_points_data):
            QMessageBox.information(
                self,
                UIMessages.MSG_TITLE_INFO,
                UIMessages.MSG_SELECT_REF_ROW,
            )
            return

        del self.ref_points_data[current_row]
        self.calculated_affine_params = None
        self._refresh_ref_points_table_and_markers()

    def _on_clear_all_refs(self) -> None:
        """Clear all reference points."""
        self.ref_points_data.clear()
        self.calculated_affine_params = None
        self._refresh_ref_points_table_and_markers()

    def _refresh_ref_points_table_and_markers(self) -> None:
        """Re-render table and vertex markers based on current ref_points_data."""
        if self.image_dialog:
            self.image_dialog.clear_markers()
            self.image_dialog.set_ref_points_data(self.ref_points_data)

        def _build_row(i: int):
            rdata = self.ref_points_data[i]

            name_item = QTableWidgetItem(rdata["name"])
            name_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)

            pix_item = QTableWidgetItem(f"({rdata['pixel_x']:.1f}, {rdata['pixel_y']:.1f})")
            pix_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)

            if rdata["real_x"] is not None and rdata["real_y"] is not None:
                sx, sy = to_survey_coords(float(rdata["real_x"]), float(rdata["real_y"]))
                rx_str = f"{sx:.3f}"
                ry_str = f"{sy:.3f}"
            else:
                rx_str = ""
                ry_str = ""

            if self.image_dialog:
                self.image_dialog.add_marker(rdata["pixel_x"], rdata["pixel_y"], rdata["name"])

            return (name_item, pix_item, QTableWidgetItem(rx_str), QTableWidgetItem(ry_str))

        UIStyleHelper.rebuild_table_rows(
            self.table_ref_points, len(self.ref_points_data), _build_row
        )
        self._update_ref_points_status()

    def _on_transform_clicked(self) -> None:
        """Compute transformation parameters and evaluate residuals without writing files or placing layers.
        # 【変更不可侵の絶対的ルール】 測量座標系（X軸=南北, Y軸=東西）を採用。QGISキャンバス上のX座標(東西)はSurvey Y、Y座標(南北)はSurvey Xに対応する。
        """
        if len(self.ref_points_data) < 2:
            QMessageBox.warning(
                self,
                UIMessages.ERR_TITLE_GENERIC,
                UIMessages.ERR_MIN_2_REFS,
            )
            return

        local_pts: List[Tuple[float, float]] = []
        real_pts: List[Tuple[float, float]] = []

        for rdata in self.ref_points_data:
            if rdata["real_x"] is None or rdata["real_y"] is None:
                QMessageBox.warning(
                    self,
                    UIMessages.ERR_TITLE_INPUT,
                    UIMessages.ERR_INPUT_REAL_COORDS.format(name=rdata["name"]),
                )
                return
            local_pts.append((float(rdata["pixel_x"]), float(rdata["pixel_y"])))
            # Standard mathematical coordinates: (math_x=East, math_y=North)
            real_pts.append((float(rdata["real_x"]), float(rdata["real_y"])))

        affine_params = CoordinateTransformer.compute_affine_points(
            local_pts, real_pts, parent=self
        )
        if affine_params is None:
            return

        self.calculated_affine_params = affine_params

        # Evaluate transformation indicators using core_logic
        rotation_deg, aspect_ratio_pct = evaluate_residuals(self.ref_points_data, affine_params)
        mode_str = (
            UILabels.TRANSFORM_HELMERT
            if len(local_pts) == 2
            else UILabels.TRANSFORM_AFFINE.format(count=len(local_pts))
        )

        res_summary = (
            f"【{mode_str} 計算完了】\n"
            f"画像の回転角度: {rotation_deg:.2f} 度\n"
            f"アスペクト比(縦/横): {aspect_ratio_pct:.2f} %"
        )
        self.lbl_tab1_info_3_6.setText(res_summary)
        
        UIStyleHelper.update_status_panel(
            self.panel_tab1_info,
            self.lbl_tab1_info_2,
            UILabels.TAB1_INFO_TRANSFORM_DONE,
            status_type="success",
        )

        self.btn_export_layer.setEnabled(True)
        self.iface.messageBar().pushMessage(
            UIMessages.MSG_TITLE_INFO,
            UILabels.MSG_TRANSFORM_SUCCESS,
            level=Qgis.MessageLevel.Success,
            duration=4,
        )
        # T-0045-b (②): the post-transform QMessageBox.information() dialog
        # (rotation angle / aspect ratio) formerly shown here has been
        # removed; the same content is already displayed above in the
        # information panel (lbl_tab1_info_3_6, res_summary), so no
        # information is lost. The messageBar() success toast and status
        # panel update remain as the completion notification.

    def _on_export_layer_clicked(self) -> None:
        """Write world file, update metadata, update points, and load to canvas."""
        if self.calculated_affine_params is None:
            QMessageBox.warning(
                self,
                UIMessages.ERR_TITLE_GENERIC,
                UILabels.ERR_TRANSFORM_NOT_CALCULATED,
            )
            return

        layer_name = self.confirmed_layer_name or self._tab1_image_panel.get_value("image_name").strip()

        # T-0018: previously this block had a fallback that searched
        # session_image_dir for a file whose basename matched layer_name when
        # current_copied_image_path looked invalid. That search predates
        # T-0015's decoupling of the on-disk file name from the layer name,
        # so a filename == layer_name match is no longer reliable, and it is
        # unreachable in practice anyway: by the time this button is
        # reachable (enabled only after a successful "座標変換"), a valid
        # preview session must already have set current_copied_image_path,
        # either to the original source file (new-add mode, not yet copied)
        # or to the existing session file (edit mode). The fallback has been
        # removed; an invalid path here now indicates a genuine error.
        if not self.current_copied_image_path or not os.path.isfile(self.current_copied_image_path):
            QMessageBox.critical(
                self,
                UIMessages.ERR_TITLE_FILE,
                UIMessages.ERR_IMAGE_FILE_NOT_FOUND,
            )
            return

        # T-0018: new-add mode defers the physical copy into the session's
        # image/ directory until export time (see _on_confirm_image_clicked()).
        # Detect the not-yet-copied case by checking whether the current path
        # already lives inside the session's image/ directory; if not, copy
        # it now, before writing the world file. Edit/delete mode's path
        # already lives in image/ (set from metadata by
        # _on_edit_layer_changed()), so this is a no-op for that mode.
        # T-0019: normcase() is combined with normpath() to absorb Windows
        # drive-letter case differences, matching the pattern established in
        # T-0012 for other file path comparisons in this module.
        session_img_dir = self.layer_manager.session_image_dir
        current_dir = os.path.normcase(os.path.normpath(os.path.dirname(self.current_copied_image_path)))
        already_in_session = bool(session_img_dir) and current_dir == os.path.normcase(
            os.path.normpath(session_img_dir)
        )

        if not already_in_session:
            success, msg, dest_path = self.layer_manager.copy_image_to_session(
                self.current_copied_image_path
            )
            if not success:
                QMessageBox.critical(self, UIMessages.ERR_TITLE_FILE, msg)
                return
            self.current_copied_image_path = dest_path

        with (self.busy_interaction_guard() if hasattr(self, "busy_interaction_guard") else nullcontext()):
            # 1. Write world file
            success, msg, _ = self.layer_manager.write_world_file(
                self.current_copied_image_path, self.calculated_affine_params
            )
            if not success:
                QMessageBox.critical(
                    self,
                    UIMessages.ERR_TITLE_GENERIC,
                    UIMessages.ERR_WORLDFILE_FAILED.format(msg=msg),
                )
                return

            # 2. Persist reference points and affine params into JSON metadata
            self.layer_manager.update_image_metadata(
                layer_name,
                self.current_copied_image_path,
                self.ref_points_data,
                self.calculated_affine_params
            )

            # 3. Batch update coordinates and geometry for matching points
            if self.point_layer and self.point_layer.isValid():
                update_point_layer_geometry(
                    self.point_layer,
                    self.calculated_affine_params,
                    drawing_name=layer_name,
                )

            # 4. Load georeferenced raster to main canvas with specified layer name
            success, msg, raster_layer = self.layer_manager.load_georeferenced_raster(
                self.current_copied_image_path, custom_layer_name=layer_name
            )
            if not success or raster_layer is None:
                QMessageBox.critical(
                    self,
                    UIMessages.ERR_TITLE_GENERIC,
                    UIMessages.ERR_CANVAS_PLACEMENT_FAILED.format(msg=msg),
                )
                return

            self.canvas.setExtent(raster_layer.extent())
            self.canvas.refresh()

            # 5. Clean up dynamic preview canvas
            self._destroy_preview_canvas()

            # 6. Dynamically refresh target drawing table in Tab 2 and select new layer
            self._update_drawing_combo()
            if hasattr(self, "_ensure_drawing_selected"):
                self._ensure_drawing_selected(layer_name)
            self._ensure_drawing_visible(layer_name)

        self.iface.messageBar().pushMessage(
            UIMessages.MSG_GEOREF_COMPLETE_TITLE,
            UIMessages.MSG_GEOREF_COMPLETE,
            level=Qgis.MessageLevel.Success,
            duration=6,
        )

        # Clear UI state if in new add mode
        if self.tab1_mode_buttons[0].isChecked():
            self.edit_image_path.clear()
            self.edit_image_name.clear()
            self.ref_points_data.clear()
            self.calculated_affine_params = None
            self.confirmed_layer_name = None
            self._refresh_ref_points_table_and_markers()

        # 7. Automatically close the 画像 dialog, returning to the main
        # digitizing area (T-0024; formerly "switch to Tab 2" / close the
        # 図面管理 side panel). ImageDialog.closeEvent hides it and invokes
        # its on_close callback (_update_main_map_tool_state), which
        # restores the main digitizing tool once no other dialog is open.
        self.image_dialog.close()

