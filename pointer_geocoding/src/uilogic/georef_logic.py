"""
/***************************************************************************
 PointerGeocoding Plugin - Georeferencing Logic (Controller)
 ***************************************************************************/

Tab 1 (画像管理・事前配置) のUIイベントを受容し、ビジネスロジック（画像操作、基準点設定、
座標変換、レイヤ出力）を処理するController層です。
View層からは BuiltPanel やコールバックを注入（DI）されることで直接イベントをバインドし、
循環参照を防ぎます。
"""
# 【変更不可侵の絶対的ルール】 測量座標系（X軸=南北, Y軸=東西）を採用。QGISキャンバス上のX座標(東西)はSurvey Y、Y座標(南北)はSurvey Xに対応する。

import os
import re
import math
from contextlib import nullcontext
from typing import Optional, List, Tuple, Dict, Any

from qgis.core import QgsProject, QgsPointXY, Qgis
from qgis.PyQt.QtCore import Qt, pyqtSlot, QObject
from qgis.PyQt.QtWidgets import QMessageBox, QFileDialog, QTableWidgetItem, QDialog

from ..logic.transform import CoordinateTransformer
from ..ui.style import UIStyleHelper
from ..logic.core import (
    to_survey_coords,
    from_survey_coords,
    update_point_layer_geometry,
    evaluate_residuals,
    safe_get_str,
)
from ..ui.constants import UILabels, UIDialogTitles, UIMessages
from ..ui.dialogs import GridInputDialog
from ..ui.core.state import ChangeTab1ModeAction, SetGeorefStateAction
from ..ui.core.validators import (
    RequiredValidator,
    RegexValidator,
    DuplicateValidator,
    show_validation_error,
)
from ..ui.core.builder import BuiltPanel


class GeorefLogic(QObject):
    """
    画像管理・幾何補正（ジオリファレンス）制御を担うControllerクラス。
    """
    INVALID_CHARS_PATTERN = r'[\\/:*?"<>|]'
    WORLD_FILE_EXTENSIONS = (".tfw", ".jgw", ".pgw", ".bpw", ".wld")

    def __init__(self, state_store, layer_manager, layers_dict, iface, parent=None):
        super().__init__(parent)
        self.state_store = state_store
        self.layer_manager = layer_manager
        self.layers_dict = layers_dict
        self.iface = iface
        self.point_layer = layers_dict.get("point_layer")
        self.parent_widget = parent

        self._is_modifying_layer = False  # リネーム・削除時の連鎖ポップアップ抑止フラグ

        # コールバック群 (DI)
        self.get_image_dialog_cb = lambda: None
        self.is_focus_mode_active_cb = lambda: False
        self.update_symbology_opacity_cb = lambda: None
        self.ensure_drawing_selected_cb = lambda name: None
        self.ensure_drawing_visible_cb = lambda name: None
        self.update_drawing_combo_cb = lambda: None
        self.busy_interaction_guard_cb = lambda: nullcontext()

        # UI パネル (DI)
        self.info_panel: Optional[BuiltPanel] = None
        self.mode_panel: Optional[BuiltPanel] = None
        self.image_panel: Optional[BuiltPanel] = None
        self.transform_panel: Optional[BuiltPanel] = None

    def bind_view_callbacks(self, callbacks: Dict[str, Any]) -> None:
        self.get_image_dialog_cb = callbacks.get("get_image_dialog", self.get_image_dialog_cb)
        self.is_focus_mode_active_cb = callbacks.get("is_focus_mode_active", self.is_focus_mode_active_cb)
        self.update_symbology_opacity_cb = callbacks.get("update_symbology_opacity", self.update_symbology_opacity_cb)
        self.ensure_drawing_selected_cb = callbacks.get("ensure_drawing_selected", self.ensure_drawing_selected_cb)
        self.ensure_drawing_visible_cb = callbacks.get("ensure_drawing_visible", self.ensure_drawing_visible_cb)
        self.update_drawing_combo_cb = callbacks.get("update_drawing_combo", self.update_drawing_combo_cb)
        self.busy_interaction_guard_cb = callbacks.get("busy_interaction_guard", self.busy_interaction_guard_cb)

    def bind_ui_panels(self, info_panel: BuiltPanel, mode_panel: BuiltPanel, image_panel: BuiltPanel, transform_panel: BuiltPanel) -> None:
        self.info_panel = info_panel
        self.mode_panel = mode_panel
        self.image_panel = image_panel
        self.transform_panel = transform_panel

        self.mode_panel.bind("mode_changed", self._on_tab1_mode_changed)
        self.image_panel.bind("browse_image", self._browse_image_file)
        self.image_panel.bind("edit_layer_changed", self._on_edit_layer_changed)
        self.image_panel.bind("rename_layer", self._on_rename_layer_clicked)
        self.image_panel.bind("delete_layer", self._on_delete_layer_clicked)
        self.image_panel.bind("confirm_image", self._on_confirm_image_clicked)
        self.image_panel.bind("ref_table_cell_changed", self._on_ref_table_cell_changed)
        self.transform_panel.bind("transform_clicked", self._on_transform_clicked)
        self.transform_panel.bind("export_layer_clicked", self._on_export_layer_clicked)

    # =========================================================================
    # 状態の同期 (一方向データフローの受け口)
    # =========================================================================

    def on_state_changed(self, new_state: Any, diff: Dict[str, Any]) -> None:
        """UIStateStoreの変更を検知し、Tab1のUIを安全に同期する"""
        if not self.image_panel:
            return

        # 1. モード変更時のUI表示・非表示切り替え
        if "tab1_mode" in diff:
            is_new = (new_state.tab1_mode == "new")
            self.image_panel.get_row("image_path").setVisible(is_new)
            self.image_panel.get_row("edit_layer").setVisible(not is_new)
            self.image_panel.get_row("rename_delete").setVisible(not is_new)
            
            btn_confirm = self.image_panel.get("confirm_image")
            if is_new:
                btn_confirm.setText("基準点設置")
            else:
                btn_confirm.setText("プレビュー再表示")
            
            if not is_new:
                # 編集削除モード: コンボボックスを再構築し、最初のアイテムを選択
                self._is_modifying_layer = True
                try:
                    self._refresh_edit_layer_combo()
                    combo = self.image_panel.get("edit_layer")
                    if combo.count() > 0:
                        # 強制的に先頭を選択させ、Stateを更新する
                        if combo.currentIndex() != 0:
                            combo.setCurrentIndex(0)
                        else:
                            self._on_edit_layer_changed()
                    else:
                        self.state_store.dispatch(SetGeorefStateAction(
                            image_path="", layer_name="", clear_ref_points=True, affine_params=None
                        ))
                finally:
                    self._is_modifying_layer = False

                # 編集削除モードに切り替えた直後、図面が存在すれば自動プレビューを表示
                latest_state = self.state_store.state
                if latest_state.current_copied_image_path:
                    self._show_preview_if_needed()
            else:
                # 新規モード: 状態をクリア
                self.state_store.dispatch(SetGeorefStateAction(
                    image_path="", layer_name="", clear_ref_points=True, affine_params=None
                ))

            self._update_edit_mode_button_states(new_state)

        # 2. パスとレイヤ名の同期 (blockSignalsによるループ防止)
        if "current_copied_image_path" in diff or "confirmed_layer_name" in diff:
            path = new_state.current_copied_image_path or ""
            name = new_state.confirmed_layer_name or ""
            
            w_path = self.image_panel.get("image_path")
            w_path.blockSignals(True)
            w_path.setText(path)
            w_path.blockSignals(False)

            w_name = self.image_panel.get("image_name")
            w_name.blockSignals(True)
            w_name.setText(name)
            w_name.blockSignals(False)

        # 3. 基準点テーブルやボタンの同期
        keys_to_check = ("ref_points_data", "calculated_affine_params", "current_copied_image_path", "confirmed_layer_name")
        if any(k in diff for k in keys_to_check):
            self._refresh_ref_points_table_and_markers(new_state)
            self._update_ref_points_status(new_state)

    def _update_edit_mode_button_states(self, state) -> None:
        if state.tab1_mode == "edit":
            has_images = bool(self.layer_manager.load_image_metadata())
            self.image_panel.get("rename_layer").setEnabled(has_images)
            self.image_panel.get("delete_layer").setEnabled(has_images)
            self.image_panel.get("confirm_image").setEnabled(has_images)
        else:
            self.image_panel.get("confirm_image").setEnabled(True)

    def _refresh_edit_layer_combo(self) -> None:
        meta = self.layer_manager.load_image_metadata()
        combo = self.image_panel.get("edit_layer")
        UIStyleHelper.repopulate_combo_box(
            combo, list(meta.keys()), preserve_current=False
        )
        if self.state_store.state.confirmed_layer_name in meta:
            idx = combo.findText(self.state_store.state.confirmed_layer_name)
            if idx >= 0:
                combo.blockSignals(True)
                combo.setCurrentIndex(idx)
                combo.blockSignals(False)

    # =========================================================================
    # モード切り替え & 状態管理 (Action Dispatch)
    # =========================================================================

    def _on_tab1_mode_changed(self, mode_index: int) -> None:
        mode = "new" if mode_index == 0 else "edit"
        if self.state_store.state.tab1_mode != mode:
            self.state_store.dispatch(ChangeTab1ModeAction(mode))

    def _on_edit_layer_changed(self, *args) -> None:
        layer_name = self.image_panel.get_value("edit_layer")
        if not layer_name:
            self.state_store.dispatch(SetGeorefStateAction(
                image_path="", layer_name="", clear_ref_points=True, affine_params=None
            ))
            return

        meta = self.layer_manager.load_image_metadata()
        layer_meta = meta.get(layer_name, {})
        image_path = layer_meta.get("file_path", "")
        affine_params = layer_meta.get("affine_params")
        if affine_params is not None:
            affine_params = tuple(affine_params)
        
        ref_points = []
        for r in layer_meta.get("ref_points", []):
            ref_points.append({
                "name": r.get("name", ""),
                "pixel_x": r.get("pixel_x", 0.0),
                "pixel_y": r.get("pixel_y", 0.0),
                "real_x": r.get("real_x", 0.0),
                "real_y": r.get("real_y", 0.0),
            })
            
        self.state_store.dispatch(SetGeorefStateAction(
            image_path=image_path,
            layer_name=layer_name,
            ref_points=ref_points,
            affine_params=affine_params
        ))
        
        # ユーザーによる手動操作（リネーム・削除等のプログラム処理中ではない）の場合、プレビューを自動表示
        if not self._is_modifying_layer and image_path:
            self._show_preview_if_needed()

    def _show_preview_if_needed(self) -> None:
        """安全にプレビューダイアログを起動またはアクティブにする"""
        state = self.state_store.state
        if not state.current_copied_image_path or not os.path.isfile(state.current_copied_image_path):
            return

        image_dialog = self.get_image_dialog_cb()
        if image_dialog and image_dialog.raster_layer is not None:
            image_dialog.set_ref_points_data(state.ref_points_data)
            image_dialog.show()
            image_dialog.raise_()
            image_dialog.activateWindow()
        else:
            self._create_preview_canvas(state.current_copied_image_path)

    # =========================================================================
    # レイヤの削除 & リネーム
    # =========================================================================

    def _on_delete_layer_clicked(self) -> None:
        layer_name = self.image_panel.get_value("edit_layer")
        if not layer_name:
            return
            
        reply = QMessageBox.question(
            self.parent_widget,
            UIMessages.MSG_CONFIRM_DELETE_LAYER_TITLE,
            UIMessages.MSG_CONFIRM_DELETE_LAYER.format(name=layer_name),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
            
        has_points = False
        if self.point_layer and self.point_layer.isValid() and "drawing_name" in self.point_layer.fields().names():
            for f in self.point_layer.getFeatures():
                if safe_get_str(f, "drawing_name") == layer_name:
                    has_points = True
                    break
            if has_points:
                pts_reply = QMessageBox.question(
                    self.parent_widget,
                    UIMessages.MSG_CONFIRM_POINTS_EXIST_TITLE,
                    UIMessages.MSG_CONFIRM_POINTS_EXIST,
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                )
                if pts_reply != QMessageBox.Yes:
                    return

        with self.busy_interaction_guard_cb():
            if has_points:
                self.layer_manager.clear_drawing_name_for_layer(layer_name)

            project = QgsProject.instance()
            for tree_layer in project.layerTreeRoot().findLayers():
                l = tree_layer.layer()
                if l and l.name() == layer_name:
                    project.removeMapLayer(l.id())
                    break

            meta = self.layer_manager.load_image_metadata()
            if layer_name in meta:
                file_path = meta[layer_name].get("file_path", "")
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except Exception:
                        pass

                base, _ = os.path.splitext(file_path)
                for ext in self.WORLD_FILE_EXTENSIONS:
                    if os.path.exists(base + ext):
                        try:
                            os.remove(base + ext)
                        except Exception:
                            pass

                self.layer_manager.delete_image_metadata(layer_name)

            self._destroy_preview_canvas()

            if self.is_focus_mode_active_cb():
                self.update_symbology_opacity_cb()

        QMessageBox.information(
            self.parent_widget,
            UIMessages.MSG_DELETE_LAYER_SUCCESS_TITLE,
            UIMessages.MSG_DELETE_LAYER_SUCCESS.format(name=layer_name),
        )

        # 削除後の自動選択で意図しないプレビューがポップアップするのを防ぐ
        self._is_modifying_layer = True
        try:
            self._refresh_edit_layer_combo()
            combo = self.image_panel.get("edit_layer")
            if combo.count() > 0:
                if combo.currentIndex() != 0:
                    combo.setCurrentIndex(0)
                else:
                    self._on_edit_layer_changed()
            else:
                self.state_store.dispatch(SetGeorefStateAction(
                    image_path="", layer_name="", clear_ref_points=True, affine_params=None
                ))
        finally:
            self._is_modifying_layer = False

        self._update_edit_mode_button_states(self.state_store.state)

    def _on_rename_layer_clicked(self) -> None:
        old_name = self.image_panel.get_value("edit_layer")
        if not old_name:
            return

        new_name = self.image_panel.get_value("image_name").strip()

        if not new_name:
            QMessageBox.warning(self.parent_widget, UIMessages.ERR_TITLE_INPUT, UIMessages.ERR_REQUIRED_IMAGE_NAME)
            self.image_panel.get("image_name").setFocus()
            return

        if re.search(self.INVALID_CHARS_PATTERN, new_name):
            QMessageBox.warning(self.parent_widget, UIMessages.ERR_TITLE_INPUT, UIMessages.ERR_INVALID_IMAGE_NAME)
            self.image_panel.get("image_name").setFocus()
            return

        if new_name == old_name:
            return

        meta = self.layer_manager.load_image_metadata()
        if old_name not in meta:
            QMessageBox.warning(self.parent_widget, UIMessages.ERR_TITLE_GENERIC, UIMessages.ERR_LAYER_META_NOT_FOUND.format(name=old_name))
            return

        if new_name in meta:
            QMessageBox.warning(self.parent_widget, UIMessages.ERR_TITLE_DUPLICATE, UIMessages.ERR_DUPLICATE_LAYER_NAME.format(name=new_name))
            self.image_panel.get("image_name").setFocus()
            return

        with self.busy_interaction_guard_cb():
            project = QgsProject.instance()
            for tree_layer in project.layerTreeRoot().findLayers():
                layer = tree_layer.layer()
                if layer and layer.name() == old_name:
                    layer.setName(new_name)
                    break

            meta[new_name] = meta.pop(old_name)
            self.layer_manager.save_image_metadata(meta)
            
            image_path = meta[new_name].get("file_path", self.state_store.state.current_copied_image_path)
            self.state_store.dispatch(SetGeorefStateAction(layer_name=new_name, image_path=image_path))

            self.layer_manager.rename_drawing_name(old_name, new_name)

            # リネーム後のコンボボックス再構築時に意図しないプレビューポップアップを防ぐ
            self._is_modifying_layer = True
            try:
                self._refresh_edit_layer_combo()
                combo = self.image_panel.get("edit_layer")
                idx = combo.findText(new_name)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
                else:
                    self._on_edit_layer_changed()
            finally:
                self._is_modifying_layer = False

            if self.is_focus_mode_active_cb():
                self.update_symbology_opacity_cb()

        self.ensure_drawing_selected_cb(new_name)

        QMessageBox.information(
            self.parent_widget,
            UIMessages.MSG_RENAME_LAYER_SUCCESS_TITLE,
            UIMessages.MSG_RENAME_LAYER_SUCCESS.format(old=old_name, new=new_name),
        )

    # =========================================================================
    # 画像ファイル選択 & プレビュー表示
    # =========================================================================

    def _browse_image_file(self) -> None:
        start_dir = self.layers_dict.get("session_dir", os.path.expanduser("~"))
        filepath, _ = QFileDialog.getOpenFileName(
            self.parent_widget,
            UIDialogTitles.BROWSE_IMAGE,
            start_dir,
            UIDialogTitles.IMAGE_FILTER,
        )
        if filepath:
            norm_path = os.path.normpath(filepath)
            base_name, _ = os.path.splitext(os.path.basename(norm_path))
            self.state_store.dispatch(SetGeorefStateAction(
                image_path=norm_path,
                layer_name=base_name,
                clear_ref_points=True,
                affine_params=None
            ))

    def _on_confirm_image_clicked(self) -> None:
        state = self.state_store.state
        if state.tab1_mode == "edit":
            self._on_setup_ref_points_clicked()
            return

        layer_name = self.image_panel.get_value("image_name").strip()

        result = RequiredValidator(UIMessages.ERR_REQUIRED_IMAGE_NAME).validate(layer_name)
        if not result.is_valid:
            show_validation_error(self.parent_widget, UIMessages.ERR_TITLE_INPUT, result, focus_widget=self.image_panel.get("image_name"))
            return

        result = RegexValidator(self.INVALID_CHARS_PATTERN, message=UIMessages.ERR_INVALID_IMAGE_NAME).validate(layer_name)
        if not result.is_valid:
            show_validation_error(self.parent_widget, UIMessages.ERR_TITLE_INPUT, result, focus_widget=self.image_panel.get("image_name"))
            return

        meta = self.layer_manager.load_image_metadata()
        result = DuplicateValidator(
            lambda name: name in meta,
            message=UIMessages.ERR_DUPLICATE_LAYER_NAME.format(name=layer_name),
        ).validate(layer_name)
        if not result.is_valid:
            show_validation_error(self.parent_widget, UIMessages.ERR_TITLE_DUPLICATE, result, focus_widget=self.image_panel.get("image_name"))
            return

        src_path = self.image_panel.get_value("image_path").strip()
        if not src_path or not os.path.isfile(src_path):
            QMessageBox.warning(self.parent_widget, UIMessages.ERR_TITLE_INPUT, UIMessages.ERR_INVALID_IMAGE)
            self.image_panel.get("image_path").setFocus()
            return

        src_base, _ = os.path.splitext(src_path)
        if any(os.path.isfile(src_base + ext) for ext in self.WORLD_FILE_EXTENSIONS):
            QMessageBox.warning(self.parent_widget, UIMessages.ERR_TITLE_FILE, UIMessages.ERR_SOURCE_HAS_WORLDFILE)
            self.image_panel.get("image_path").setFocus()
            return

        self.state_store.dispatch(SetGeorefStateAction(
            layer_name=layer_name,
            image_path=src_path,
            clear_ref_points=True,
            affine_params=None
        ))
        
        # State更新直後の状態を取得してダイアログを構築
        current_state = self.state_store.state
        image_dialog = self.get_image_dialog_cb()
        if image_dialog and image_dialog.raster_layer is not None:
            image_dialog.set_ref_points_data(current_state.ref_points_data)
            image_dialog.show()
            image_dialog.raise_()
            image_dialog.activateWindow()
        else:
            self._create_preview_canvas(src_path)

    def _create_preview_canvas(self, image_path: str) -> bool:
        success, msg, raster_layer = self.layer_manager.load_preview_raster(image_path)
        if not success or raster_layer is None:
            QMessageBox.critical(self.parent_widget, UIMessages.ERR_TITLE_LOAD, UIMessages.ERR_PREVIEW_FAILED.format(msg=msg))
            return False

        image_dialog = self.get_image_dialog_cb()
        if image_dialog:
            image_dialog.setup_raster(
                raster_layer,
                self._on_preview_canvas_point_clicked,
                self.state_store.state.ref_points_data,
            )
            image_dialog.show()
            image_dialog.raise_()
            image_dialog.activateWindow()

        return True

    def _destroy_preview_canvas(self) -> None:
        image_dialog = self.get_image_dialog_cb()
        if image_dialog is not None:
            image_dialog.clean_up()

    def _on_setup_ref_points_clicked(self) -> None:
        state = self.state_store.state
        if not state.current_copied_image_path or not os.path.isfile(state.current_copied_image_path):
            QMessageBox.information(self.parent_widget, UIMessages.MSG_TITLE_INFO, UIMessages.MSG_CONFIRM_IMAGE_FIRST)
            return

        image_dialog = self.get_image_dialog_cb()
        if image_dialog and image_dialog.raster_layer is not None:
            image_dialog.set_ref_points_data(state.ref_points_data)
            image_dialog.show()
            image_dialog.raise_()
            image_dialog.activateWindow()
        else:
            self._create_preview_canvas(state.current_copied_image_path)

    @pyqtSlot(float, float)
    def _on_preview_canvas_point_clicked(self, pixel_x: float, pixel_y: float) -> None:
        snapped_index: Optional[int] = None
        image_dialog = self.get_image_dialog_cb()
        ref_points = self.state_store.state.ref_points_data

        if image_dialog and image_dialog.raster_layer and image_dialog.georef_tool:
            tool = image_dialog.georef_tool
            rlayer = image_dialog.raster_layer
            extent = rlayer.extent()
            w = float(rlayer.width())
            h = float(rlayer.height())

            if w > 0 and h > 0 and extent.width() > 0 and extent.height() > 0:
                click_map_x = extent.xMinimum() + (pixel_x / w) * extent.width()
                click_map_y = extent.yMaximum() - (pixel_y / h) * extent.height()
                click_screen = tool.toCanvasCoordinates(QgsPointXY(click_map_x, click_map_y))

                min_dist = float("inf")
                for idx, rdata in enumerate(ref_points):
                    rx = float(rdata["pixel_x"])
                    ry = float(rdata["pixel_y"])
                    r_map_x = extent.xMinimum() + (rx / w) * extent.width()
                    r_map_y = extent.yMaximum() - (ry / h) * extent.height()
                    r_screen = tool.toCanvasCoordinates(QgsPointXY(r_map_x, r_map_y))
                    dist = math.hypot(click_screen.x() - r_screen.x(), click_screen.y() - r_screen.y())
                    if dist <= 15.0 and dist < min_dist:
                        min_dist = dist
                        snapped_index = idx

        if snapped_index is not None:
            existing_point = dict(ref_points[snapped_index])
            other_names = [r["name"] for i, r in enumerate(ref_points) if i != snapped_index]
            dlg = GridInputDialog(
                self.layer_manager,
                existing_point=existing_point,
                existing_names=other_names,
                parent=image_dialog or self.parent_widget,
            )
            if dlg.exec_() == QDialog.Accepted:
                if dlg.dialog_action == "delete":
                    new_refs = list(ref_points)
                    del new_refs[snapped_index]
                    self.state_store.dispatch(SetGeorefStateAction(ref_points=new_refs, affine_params=None))
                elif dlg.dialog_action == "confirm":
                    new_refs = list(ref_points)
                    new_refs[snapped_index] = dict(existing_point)
                    new_refs[snapped_index]["name"] = dlg.result_grid_name
                    new_refs[snapped_index]["real_x"] = dlg.result_real_x
                    new_refs[snapped_index]["real_y"] = dlg.result_real_y
                    self.state_store.dispatch(SetGeorefStateAction(ref_points=new_refs, affine_params=None))
            return

        if len(ref_points) >= 4:
            QMessageBox.information(self.parent_widget, UIMessages.MSG_TITLE_LIMIT, UIMessages.MSG_LIMIT_REFS)
            return

        other_names = [r["name"] for r in ref_points]
        dlg = GridInputDialog(
            self.layer_manager,
            existing_point=None,
            existing_names=other_names,
            parent=image_dialog or self.parent_widget,
        )
        if dlg.exec_() == QDialog.Accepted and dlg.dialog_action == "confirm":
            pt_entry = {
                "name": dlg.result_grid_name,
                "pixel_x": pixel_x,
                "pixel_y": pixel_y,
                "real_x": dlg.result_real_x,
                "real_y": dlg.result_real_y,
            }
            new_refs = list(ref_points)
            new_refs.append(pt_entry)
            self.state_store.dispatch(SetGeorefStateAction(ref_points=new_refs, affine_params=None))

    # =========================================================================
    # 基準点テーブル & 状態管理
    # =========================================================================

    def _on_ref_table_cell_changed(self, row: int, column: int) -> None:
        ref_points = self.state_store.state.ref_points_data
        if row >= len(ref_points):
            return

        table_ref_points = self.image_panel.get("ref_points_table")
        item_x = table_ref_points.item(row, 2)
        item_y = table_ref_points.item(row, 3)
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

            new_refs = [dict(r) for r in ref_points]
            if sx is not None and sy is not None:
                math_x, math_y = from_survey_coords(sx, sy)
                new_refs[row]["real_x"] = math_x
                new_refs[row]["real_y"] = math_y
            else:
                new_refs[row]["real_x"] = None
                new_refs[row]["real_y"] = None

            self.state_store.dispatch(SetGeorefStateAction(ref_points=new_refs, affine_params=None))

    def _update_ref_points_status(self, state) -> None:
        count = len(state.ref_points_data)
        fname = (
            state.confirmed_layer_name if state.confirmed_layer_name
            else (os.path.basename(state.current_copied_image_path) if state.current_copied_image_path else UILabels.UNLOADED)
        )
        self.info_panel.get("tab1_info.line1").setText(UILabels.TAB1_INFO_IMAGE_REF.format(name=fname, count=count))
        self.info_panel.get("tab1_info.line3_6").setText("")

        all_coords_valid = False
        if count >= 2:
            all_coords_valid = all(r["real_x"] is not None and r["real_y"] is not None for r in state.ref_points_data)

        if count < 2:
            self.transform_panel.get("transform").setEnabled(False)
            self.transform_panel.get("export_layer").setEnabled(False)
            UIStyleHelper.update_status_panel(
                self.info_panel.get("tab1_info"), self.info_panel.get("tab1_info.line2"),
                UILabels.STATUS_NEED_MORE_REFS.format(count=count), status_type="warning"
            )
        elif not all_coords_valid:
            self.transform_panel.get("transform").setEnabled(False)
            self.transform_panel.get("export_layer").setEnabled(False)
            UIStyleHelper.update_status_panel(
                self.info_panel.get("tab1_info"), self.info_panel.get("tab1_info.line2"),
                UILabels.STATUS_INPUT_COORDS.format(count=count), status_type="info"
            )
        else:
            self.transform_panel.get("transform").setEnabled(True)
            mode_str = UILabels.TRANSFORM_HELMERT if count == 2 else UILabels.TRANSFORM_AFFINE.format(count=count)
            
            if state.calculated_affine_params is None:
                self.transform_panel.get("export_layer").setEnabled(False)
                UIStyleHelper.update_status_panel(
                    self.info_panel.get("tab1_info"), self.info_panel.get("tab1_info.line2"),
                    UILabels.STATUS_READY_TRANSFORM.format(count=count, mode=mode_str), status_type="info"
                )
            else:
                self.transform_panel.get("export_layer").setEnabled(True)

    def _on_delete_selected_ref_point(self) -> None:
        table_ref_points = self.image_panel.get("ref_points_table")
        current_row = table_ref_points.currentRow()
        ref_points = self.state_store.state.ref_points_data
        
        if current_row < 0 or current_row >= len(ref_points):
            QMessageBox.information(self.parent_widget, UIMessages.MSG_TITLE_INFO, UIMessages.MSG_SELECT_REF_ROW)
            return

        new_refs = list(ref_points)
        del new_refs[current_row]
        self.state_store.dispatch(SetGeorefStateAction(ref_points=new_refs, affine_params=None))

    def _on_clear_all_refs(self) -> None:
        self.state_store.dispatch(SetGeorefStateAction(clear_ref_points=True, affine_params=None))

    def _refresh_ref_points_table_and_markers(self, state) -> None:
        ref_points = state.ref_points_data
        image_dialog = self.get_image_dialog_cb()
        if image_dialog:
            image_dialog.clear_markers()
            image_dialog.set_ref_points_data(ref_points)

        def _build_row(i: int):
            rdata = ref_points[i]
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

            if image_dialog:
                image_dialog.add_marker(rdata["pixel_x"], rdata["pixel_y"], rdata["name"])

            return (name_item, pix_item, QTableWidgetItem(rx_str), QTableWidgetItem(ry_str))

        table_ref_points = self.image_panel.get("ref_points_table")
        UIStyleHelper.rebuild_table_rows(table_ref_points, len(ref_points), _build_row)

    # =========================================================================
    # 座標変換 & レイヤ出力
    # =========================================================================

    def _on_transform_clicked(self) -> None:
        state = self.state_store.state
        if len(state.ref_points_data) < 2:
            QMessageBox.warning(self.parent_widget, UIMessages.ERR_TITLE_GENERIC, UIMessages.ERR_MIN_2_REFS)
            return

        local_pts: List[Tuple[float, float]] = []
        real_pts: List[Tuple[float, float]] = []

        for rdata in state.ref_points_data:
            if rdata["real_x"] is None or rdata["real_y"] is None:
                QMessageBox.warning(self.parent_widget, UIMessages.ERR_TITLE_INPUT, UIMessages.ERR_INPUT_REAL_COORDS.format(name=rdata["name"]))
                return
            local_pts.append((float(rdata["pixel_x"]), float(rdata["pixel_y"])))
            real_pts.append((float(rdata["real_x"]), float(rdata["real_y"])))

        affine_params = CoordinateTransformer.compute_affine_points(local_pts, real_pts, parent=self.parent_widget)
        if affine_params is None:
            return

        self.state_store.dispatch(SetGeorefStateAction(affine_params=affine_params))
        
        rotation_deg, aspect_ratio_pct = evaluate_residuals(state.ref_points_data, affine_params)
        mode_str = UILabels.TRANSFORM_HELMERT if len(local_pts) == 2 else UILabels.TRANSFORM_AFFINE.format(count=len(local_pts))

        res_summary = (
            f"【{mode_str} 計算完了】\n"
            f"画像の回転角度: {rotation_deg:.2f} 度\n"
            f"アスペクト比(縦/横): {aspect_ratio_pct:.2f} %"
        )
        self.info_panel.get("tab1_info.line3_6").setText(res_summary)
        
        UIStyleHelper.update_status_panel(
            self.info_panel.get("tab1_info"), self.info_panel.get("tab1_info.line2"),
            UILabels.TAB1_INFO_TRANSFORM_DONE, status_type="success"
        )

        self.iface.messageBar().pushMessage(
            UIMessages.MSG_TITLE_INFO, UILabels.MSG_TRANSFORM_SUCCESS,
            level=Qgis.MessageLevel.Success, duration=4,
        )

    def _on_export_layer_clicked(self) -> None:
        state = self.state_store.state
        if state.calculated_affine_params is None:
            QMessageBox.warning(self.parent_widget, UIMessages.ERR_TITLE_GENERIC, UILabels.ERR_TRANSFORM_NOT_CALCULATED)
            return

        layer_name = state.confirmed_layer_name or self.image_panel.get_value("image_name").strip()

        if not state.current_copied_image_path or not os.path.isfile(state.current_copied_image_path):
            QMessageBox.critical(self.parent_widget, UIMessages.ERR_TITLE_FILE, UIMessages.ERR_IMAGE_FILE_NOT_FOUND)
            return

        session_img_dir = self.layer_manager.session_image_dir
        current_dir = os.path.normcase(os.path.normpath(os.path.dirname(state.current_copied_image_path)))
        already_in_session = bool(session_img_dir) and current_dir == os.path.normcase(os.path.normpath(session_img_dir))

        dest_path = state.current_copied_image_path
        if not already_in_session:
            success, msg, copy_path = self.layer_manager.copy_image_to_session(state.current_copied_image_path)
            if not success:
                QMessageBox.critical(self.parent_widget, UIMessages.ERR_TITLE_FILE, msg)
                return
            dest_path = copy_path

        with self.busy_interaction_guard_cb():
            success, msg, _ = self.layer_manager.write_world_file(dest_path, state.calculated_affine_params)
            if not success:
                QMessageBox.critical(self.parent_widget, UIMessages.ERR_TITLE_GENERIC, UIMessages.ERR_WORLDFILE_FAILED.format(msg=msg))
                return

            self.layer_manager.update_image_metadata(
                layer_name, dest_path, state.ref_points_data, state.calculated_affine_params
            )

            if self.point_layer and self.point_layer.isValid():
                update_point_layer_geometry(self.point_layer, state.calculated_affine_params, drawing_name=layer_name)

            success, msg, raster_layer = self.layer_manager.load_georeferenced_raster(
                dest_path, custom_layer_name=layer_name
            )
            if not success or raster_layer is None:
                QMessageBox.critical(self.parent_widget, UIMessages.ERR_TITLE_GENERIC, UIMessages.ERR_CANVAS_PLACEMENT_FAILED.format(msg=msg))
                return

            self.iface.mapCanvas().setExtent(raster_layer.extent())
            self.iface.mapCanvas().refresh()

            self._destroy_preview_canvas()

            self.update_drawing_combo_cb()
            self.ensure_drawing_selected_cb(layer_name)
            self.ensure_drawing_visible_cb(layer_name)

        self.iface.messageBar().pushMessage(
            UIMessages.MSG_GEOREF_COMPLETE_TITLE, UIMessages.MSG_GEOREF_COMPLETE,
            level=Qgis.MessageLevel.Success, duration=6,
        )

        if state.tab1_mode == "new":
            self.state_store.dispatch(SetGeorefStateAction(
                image_path="", layer_name="", clear_ref_points=True, affine_params=None
            ))

        image_dialog = self.get_image_dialog_cb()
        if image_dialog:
            image_dialog.close()