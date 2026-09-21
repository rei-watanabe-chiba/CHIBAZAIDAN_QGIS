"""
/***************************************************************************
 PointerGeocoding Plugin - Georeferencing Logic (Controller)
 ***************************************************************************/

Tab 1 (画像管理・事前配置) のビジネスロジックを処理するController層です。
EventDispatcher からルーティングされた Action を受け取り、アフィン変換、ファイル操作、
レイヤの配置を実行します。UI（View）の知識は一切持ちません。
"""
import os
import math
from typing import Optional, List, Tuple

from qgis.core import QgsProject, Qgis
from qgis.PyQt.QtCore import QObject

from ..logic.transform import CoordinateTransformer
from ..logic.core import evaluate_residuals
from ..ui.constants import UILabels, UIMessages
from ..ui.core.state import (
    UIStateStore, SetGeorefStateAction, UIAction, SetValidationAction,
    ConfirmImageAction, DeleteLayerAction, RenameLayerAction, TransformAction, ExportLayerAction
)

class GeorefLogic(QObject):
    WORLD_FILE_EXTENSIONS = (".tfw", ".jgw", ".pgw", ".bpw", ".wld")

    def __init__(self, state_store: UIStateStore, layer_manager, layers_dict, dispatcher, iface, parent=None):
        super().__init__(parent)
        self.state_store = state_store
        self.layer_manager = layer_manager
        self.point_layer = layers_dict.get("point_layer")
        self.iface = iface

        # ディスパッチャーへハンドラとバリデータ登録
        dispatcher.register_validator(ConfirmImageAction, self.validate_confirm_image)
        dispatcher.register_handler(ConfirmImageAction, self.handle_confirm_image)
        
        dispatcher.register_handler(DeleteLayerAction, self.handle_delete_layer)
        
        dispatcher.register_validator(RenameLayerAction, self.validate_rename_layer)
        dispatcher.register_handler(RenameLayerAction, self.handle_rename_layer)
        
        dispatcher.register_validator(TransformAction, self.validate_transform)
        dispatcher.register_handler(TransformAction, self.handle_transform)
        
        dispatcher.register_validator(ExportLayerAction, self.validate_export_layer)
        dispatcher.register_handler(ExportLayerAction, self.handle_export_layer)

    # =========================================================================
    # 画像選択・確認 (Confirm)
    # =========================================================================
    def validate_confirm_image(self, action: ConfirmImageAction) -> Optional[str]:
        if not action.image_path or not os.path.isfile(action.image_path):
            return UIMessages.ERR_INVALID_IMAGE
        src_base, _ = os.path.splitext(action.image_path)
        if any(os.path.isfile(src_base + ext) for ext in self.WORLD_FILE_EXTENSIONS):
            return UIMessages.ERR_SOURCE_HAS_WORLDFILE
        meta = self.layer_manager.load_image_metadata()
        if action.layer_name in meta:
            return UIMessages.ERR_DUPLICATE_LAYER_NAME.format(name=action.layer_name)
        return None

    def handle_confirm_image(self, action: ConfirmImageAction) -> Optional[UIAction]:
        return SetGeorefStateAction(
            layer_name=action.layer_name,
            image_path=action.image_path,
            clear_ref_points=True,
            affine_params=None,
            residual_summary=""
        )

    # =========================================================================
    # レイヤ操作 (Delete / Rename)
    # =========================================================================
    def handle_delete_layer(self, action: DeleteLayerAction) -> Optional[UIAction]:
        layer_name = action.layer_name
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
                try: os.remove(file_path)
                except Exception: pass

            base, _ = os.path.splitext(file_path)
            for ext in self.WORLD_FILE_EXTENSIONS:
                if os.path.exists(base + ext):
                    try: os.remove(base + ext)
                    except Exception: pass

            self.layer_manager.delete_image_metadata(layer_name)

        return SetGeorefStateAction(image_path="", layer_name="", clear_ref_points=True, affine_params=None, residual_summary="")

    def validate_rename_layer(self, action: RenameLayerAction) -> Optional[str]:
        if action.old_name == action.new_name:
            return "変更がありません。"
        meta = self.layer_manager.load_image_metadata()
        if action.old_name not in meta:
            return UIMessages.ERR_LAYER_META_NOT_FOUND.format(name=action.old_name)
        if action.new_name in meta:
            return UIMessages.ERR_DUPLICATE_LAYER_NAME.format(name=action.new_name)
        return None

    def handle_rename_layer(self, action: RenameLayerAction) -> Optional[UIAction]:
        old_name, new_name = action.old_name, action.new_name
        project = QgsProject.instance()
        for tree_layer in project.layerTreeRoot().findLayers():
            layer = tree_layer.layer()
            if layer and layer.name() == old_name:
                layer.setName(new_name)
                break

        meta = self.layer_manager.load_image_metadata()
        meta[new_name] = meta.pop(old_name)
        self.layer_manager.save_image_metadata(meta)
        
        image_path = meta[new_name].get("file_path", self.state_store.state.current_copied_image_path)
        self.layer_manager.rename_drawing_name(old_name, new_name)

        return SetGeorefStateAction(layer_name=new_name, image_path=image_path)

    # =========================================================================
    # 座標変換・配置 (Transform / Export)
    # =========================================================================
    def validate_transform(self, action: TransformAction) -> Optional[str]:
        state = self.state_store.state
        if len(state.ref_points_data) < 2:
            return UIMessages.ERR_MIN_2_REFS
        for rdata in state.ref_points_data:
            if rdata["real_x"] is None or rdata["real_y"] is None:
                return UIMessages.ERR_INPUT_REAL_COORDS.format(name=rdata["name"])
        return None

    def handle_transform(self, action: TransformAction) -> Optional[UIAction]:
        state = self.state_store.state
        local_pts, real_pts = [], []
        for rdata in state.ref_points_data:
            local_pts.append((float(rdata["pixel_x"]), float(rdata["pixel_y"])))
            real_pts.append((float(rdata["real_x"]), float(rdata["real_y"])))

        affine_params = CoordinateTransformer.compute_affine_points(local_pts, real_pts, parent=None)
        if affine_params is None:
            return SetValidationAction(has_error=True, message="座標変換パラメータの算出に失敗しました。")

        rotation_deg, aspect_ratio_pct = evaluate_residuals(state.ref_points_data, affine_params)
        mode_str = UILabels.TRANSFORM_HELMERT if len(local_pts) == 2 else UILabels.TRANSFORM_AFFINE.format(count=len(local_pts))
        res_summary = (
            f"【{mode_str} 計算完了】\n"
            f"画像の回転角度: {rotation_deg:.2f} 度\n"
            f"アスペクト比(縦/横): {aspect_ratio_pct:.2f} %"
        )
        
        if self.iface:
            self.iface.messageBar().pushMessage(
                UIMessages.MSG_TITLE_INFO, UILabels.MSG_TRANSFORM_SUCCESS,
                level=Qgis.MessageLevel.Success, duration=4,
            )
            
        return SetGeorefStateAction(affine_params=affine_params, residual_summary=res_summary)

    def validate_export_layer(self, action: ExportLayerAction) -> Optional[str]:
        state = self.state_store.state
        if state.calculated_affine_params is None:
            return UILabels.ERR_TRANSFORM_NOT_CALCULATED
        if not state.current_copied_image_path or not os.path.isfile(state.current_copied_image_path):
            return UIMessages.ERR_IMAGE_FILE_NOT_FOUND
        return None

    def handle_export_layer(self, action: ExportLayerAction) -> Optional[UIAction]:
        from ..logic.transform import update_point_layer_geometry
        state = self.state_store.state
        dest_path = state.current_copied_image_path
        
        session_img_dir = self.layer_manager.session_image_dir
        current_dir = os.path.normcase(os.path.normpath(os.path.dirname(dest_path)))
        already_in_session = bool(session_img_dir) and current_dir == os.path.normcase(os.path.normpath(session_img_dir))
        
        if not already_in_session:
            success, msg, copy_path = self.layer_manager.copy_image_to_session(dest_path)
            if not success:
                return SetValidationAction(has_error=True, message=msg)
            dest_path = copy_path

        success, msg, _ = self.layer_manager.write_world_file(dest_path, state.calculated_affine_params)
        if not success:
            return SetValidationAction(has_error=True, message=UIMessages.ERR_WORLDFILE_FAILED.format(msg=msg))

        self.layer_manager.update_image_metadata(
            action.layer_name, dest_path, state.ref_points_data, state.calculated_affine_params
        )

        if self.point_layer and self.point_layer.isValid():
            update_point_layer_geometry(self.point_layer, state.calculated_affine_params, drawing_name=action.layer_name)

        success, msg, raster_layer = self.layer_manager.load_georeferenced_raster(
            dest_path, custom_layer_name=action.layer_name
        )
        if not success or raster_layer is None:
            return SetValidationAction(has_error=True, message=UIMessages.ERR_CANVAS_PLACEMENT_FAILED.format(msg=msg))

        if self.iface:
            self.iface.mapCanvas().setExtent(raster_layer.extent())
            self.iface.mapCanvas().refresh()
            self.iface.messageBar().pushMessage(
                UIMessages.MSG_GEOREF_COMPLETE_TITLE, UIMessages.MSG_GEOREF_COMPLETE,
                level=Qgis.MessageLevel.Success, duration=6,
            )

        if state.tab1_mode == "new":
            return SetGeorefStateAction(image_path="", layer_name="", clear_ref_points=True, affine_params=None, residual_summary="")
        return None