"""
/***************************************************************************
 PointerGeocoding Plugin - Georeferencing Logic (Controller)
 ***************************************************************************/

Tab 1 (画像管理・事前配置) のイベントに対するドメインロジックを実行するController層です。
GUI（QMessageBox等）の操作は完全にViewへ移譲され、EventDispatcherを介した
安全な処理（例外キャッチ・ビジーガード）を提供します。
"""
# 【変更不可侵の絶対的ルール】 測量座標系（X軸=南北, Y軸=東西）を採用。QGISキャンバス上のX座標(東西)はSurvey Y、Y座標(南北)はSurvey Xに対応する。

import os
from dataclasses import dataclass
from typing import Optional, List, Tuple, Dict, Any

from qgis.core import QgsProject, QgsRasterLayer
from qgis.PyQt.QtCore import QObject

from ..logic.transform import CoordinateTransformer, TransformError
from ..logic.core import (
    to_survey_coords,
    from_survey_coords,
    update_point_layer_geometry,
    evaluate_residuals,
    safe_get_str,
)
from ..ui.core.state import UIAction, SetGeorefStateAction, SetValidationAction


@dataclass
class DeleteLayerAction(UIAction):
    layer_name: str
    has_points: bool

@dataclass
class RenameLayerAction(UIAction):
    old_name: str
    new_name: str

@dataclass
class ExecuteTransformAction(UIAction):
    pass

@dataclass
class ExportLayerAction(UIAction):
    layer_name: str
    image_path: str


class GeorefLogic(QObject):
    """
    画像管理・幾何補正（ジオリファレンス）の純粋なビジネスロジックを担うクラス。
    """
    INVALID_CHARS_PATTERN = r'[\\/:*?"<>|]'
    WORLD_FILE_EXTENSIONS = (".tfw", ".jgw", ".pgw", ".bpw", ".wld")

    # GeorefLogicの初期化、DI依存の保持、DeleteLayerAction等のハンドラ登録とViewコールバックの初期値設定。
    def __init__(self, state_store, layer_manager, layers_dict, iface, dispatcher, parent=None):
        super().__init__(parent)
        self.state_store = state_store
        self.layer_manager = layer_manager
        self.layers_dict = layers_dict
        self.iface = iface
        self.dispatcher = dispatcher
        self.point_layer = layers_dict.get("point_layer")
        self.parent_widget = parent

        self._is_modifying_layer = False

        # ハンドラの登録
        self.dispatcher.register_handler(DeleteLayerAction, self.handle_delete_layer)
        self.dispatcher.register_handler(RenameLayerAction, self.handle_rename_layer)
        self.dispatcher.register_handler(ExecuteTransformAction, self.handle_execute_transform)
        self.dispatcher.register_handler(ExportLayerAction, self.handle_export_layer)

        # View からのコールバック (DI)
        self.is_focus_mode_active_cb = lambda: False
        self.update_symbology_opacity_cb = lambda: None
        self.ensure_drawing_selected_cb = lambda name: None
        self.ensure_drawing_visible_cb = lambda name: None
        self.update_drawing_combo_cb = lambda: None

    # View層で解決されるべき操作（画像ダイアログ取得・フォーカスモード判定等）のコールバックを注入する。
    def bind_view_callbacks(self, callbacks: Dict[str, Any]) -> None:
        """View層で解決されるべき操作を注入する"""
        self.is_focus_mode_active_cb = callbacks.get("is_focus_mode_active", self.is_focus_mode_active_cb)
        self.update_symbology_opacity_cb = callbacks.get("update_symbology_opacity", self.update_symbology_opacity_cb)
        self.ensure_drawing_selected_cb = callbacks.get("ensure_drawing_selected", self.ensure_drawing_selected_cb)
        self.ensure_drawing_visible_cb = callbacks.get("ensure_drawing_visible", self.ensure_drawing_visible_cb)
        self.update_drawing_combo_cb = callbacks.get("update_drawing_combo", self.update_drawing_combo_cb)

    # =========================================================================
    # View向けヘルパーメソッド（純粋計算・状態取得）
    # =========================================================================

    # レイヤ編集中フラグ（_is_modifying_layer）を設定する。
    def set_modifying_layer(self, is_modifying: bool) -> None:
        self._is_modifying_layer = is_modifying

    # レイヤ編集中フラグ（_is_modifying_layer）の現在値を返す。
    def is_modifying_layer(self) -> bool:
        return self._is_modifying_layer

    # 測量座標から数学座標への変換アダプタ呼び出し (ルール [RULE-GEO-01])
    def convert_to_math_coords(self, sx: float, sy: float) -> Tuple[float, float]:
        """測量座標から数学座標への変換アダプタ呼び出し (ルール [RULE-GEO-01])"""
        return from_survey_coords(sx, sy)

    # 数学座標から測量座標への変換アダプタ呼び出し (ルール [RULE-GEO-01])
    def convert_to_survey_coords(self, math_x: float, math_y: float) -> Tuple[float, float]:
        """数学座標から測量座標への変換アダプタ呼び出し (ルール [RULE-GEO-01])"""
        return to_survey_coords(math_x, math_y)

    # 基準点群とアフィン変換パラメータから残差サマリ（最大値・RMS等）を算出する。
    def get_residuals_summary(self, ref_points: List[Dict[str, Any]], affine_params: Tuple) -> Tuple[float, float]:
        return evaluate_residuals(ref_points, affine_params)

    # 指定レイヤに属する打刻点が存在するかどうかを判定する。
    def check_layer_has_points(self, layer_name: str) -> bool:
        """指定レイヤに属する打刻点が存在するかどうかを返す"""
        if self.point_layer and self.point_layer.isValid() and "drawing_name" in self.point_layer.fields().names():
            for f in self.point_layer.getFeatures():
                if safe_get_str(f, "drawing_name") == layer_name:
                    return True
        return False

    # 編集対象レイヤのメタデータをロードし、画像パス探索・基準点整形を行って整合性を担保して返す。
    def load_edit_layer_metadata(self, layer_name: str) -> Optional[Dict[str, Any]]:
        """編集対象レイヤのメタデータをロードし、整合性を担保して返す"""
        meta = self.layer_manager.load_image_metadata()
        layer_meta = meta.get(layer_name, {})
        image_path = layer_meta.get("file_path", "")
        
        # パスが見つからない場合はプロジェクトから探索
        if not image_path or not os.path.isfile(image_path):
            project = QgsProject.instance()
            for tree_layer in project.layerTreeRoot().findLayers():
                l = tree_layer.layer()
                if l and l.isValid() and l.name() == layer_name and hasattr(l, 'source'):
                    src = l.source()
                    if os.path.isfile(src):
                        image_path = src
                        break
        
        if not image_path:
            return None
            
        saved_params = layer_meta.get("affine_params")
        if saved_params is not None:
            saved_params = tuple(saved_params)

        ref_points = [{
            "name": r.get("name", ""),
            "pixel_x": r.get("pixel_x", 0.0),
            "pixel_y": r.get("pixel_y", 0.0),
            "real_x": r.get("real_x"),
            "real_y": r.get("real_y"),
        } for r in layer_meta.get("ref_points", [])]

        result = {
            "image_path": image_path,
            "layer_name": layer_name,
            "ref_points": ref_points,
        }
        affine_params = self._resolve_loaded_affine(ref_points, saved_params)
        if affine_params is not None:
            result["affine_params"] = affine_params
        else:
            result["clear_affine"] = True
        return result

    # 読込んだ基準点から再計算した変換と保存値を突き合わせ、採用すべき変換パラメータ（無ければNone）を返す。
    def _resolve_loaded_affine(self, ref_points: List[Dict[str, Any]], saved_params: Optional[Tuple]) -> Optional[Tuple]:
        def _is_num(v) -> bool:
            return isinstance(v, (int, float)) and not isinstance(v, bool)

        if len(ref_points) < 2 or not all(_is_num(r.get("real_x")) and _is_num(r.get("real_y")) for r in ref_points):
            return None

        try:
            local_pts = [(float(r["pixel_x"]), float(r["pixel_y"])) for r in ref_points]
            real_pts = [(float(r["real_x"]), float(r["real_y"])) for r in ref_points]
            recomputed = CoordinateTransformer.compute_affine_points(local_pts, real_pts)
        except Exception:
            return None
        if recomputed is None:
            return None

        if saved_params is None:
            return tuple(recomputed)

        try:
            sa, sb, sc, sd, se, sf = (float(v) for v in saved_params)
            ra, rb, rc, rd, re_, rf = (float(v) for v in recomputed)
        except Exception:
            return None

        max_diff = 0.0
        for px, py in local_pts:
            dx = (sa * px + sb * py + sc) - (ra * px + rb * py + rc)
            dy = (sd * px + se * py + sf) - (rd * px + re_ * py + rf)
            max_diff = max(max_diff, abs(dx), abs(dy))
        if max_diff <= 1e-3:
            return tuple(saved_params)
        return None

    # プレビュー用ラスタレイヤをロードして返す(失敗時はエラーをstateへ通知しNone)。
    def prepare_preview_raster(self, image_path: str) -> Optional[QgsRasterLayer]:
        success, msg, raster_layer = self.layer_manager.load_preview_raster(image_path)
        if not success or raster_layer is None:
            self.state_store.dispatch(SetValidationAction(True, msg))
            return None
        return raster_layer

    # 画像レイヤ名の一覧(メタデータのキー)を返す。
    def get_image_layer_names(self) -> List[str]:
        return list(self.layer_manager.load_image_metadata().keys())

    # 指定名の画像レイヤがメタデータに存在するかを返す。
    def image_layer_exists(self, layer_name: str) -> bool:
        return layer_name in self.layer_manager.load_image_metadata()

    # =========================================================================
    # EventDispatcher Action Handlers (Heavy Logic & Persistence)
    # =========================================================================

    # DeleteLayerActionを処理し、レイヤ削除・打刻点のdrawing_nameクリア・画像/ワールドファイル削除・メタデータ削除を行う。
    def handle_delete_layer(self, action: DeleteLayerAction) -> Optional[List[UIAction]]:
        layer_name = action.layer_name

        if action.has_points:
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

        if self.is_focus_mode_active_cb():
            self.update_symbology_opacity_cb()
            
        return []

    # RenameLayerActionを処理し、重複チェック後にレイヤ名変更・メタデータ更新・drawing_name変更を行う。
    def handle_rename_layer(self, action: RenameLayerAction) -> Optional[List[UIAction]]:
        old_name = action.old_name
        new_name = action.new_name

        meta = self.layer_manager.load_image_metadata()
        if new_name in meta:
            return [SetValidationAction(True, f"同名のレイヤが既に存在します: {new_name}")]

        project = QgsProject.instance()
        for tree_layer in project.layerTreeRoot().findLayers():
            layer = tree_layer.layer()
            if layer and layer.name() == old_name:
                layer.setName(new_name)
                break

        meta[new_name] = meta.pop(old_name)
        self.layer_manager.save_image_metadata(meta)
        self.layer_manager.rename_drawing_name(old_name, new_name)

        image_path = meta[new_name].get("file_path", self.state_store.state.current_copied_image_path)
        if self.is_focus_mode_active_cb():
            self.update_symbology_opacity_cb()
        self.ensure_drawing_selected_cb(new_name)

        return [SetGeorefStateAction(layer_name=new_name, image_path=image_path)]

    # ExecuteTransformActionを処理し、基準点群からアフィン変換パラメータを計算してUIStateへ反映する。
    def handle_execute_transform(self, action: ExecuteTransformAction) -> Optional[List[UIAction]]:
        state = self.state_store.state
        local_pts = [(float(r["pixel_x"]), float(r["pixel_y"])) for r in state.ref_points_data]
        real_pts = [(float(r["real_x"]), float(r["real_y"])) for r in state.ref_points_data]

        try:
            affine_params = CoordinateTransformer.compute_affine_points(local_pts, real_pts)
        except TransformError as e:
            return [SetValidationAction(True, str(e))]

        return [SetGeorefStateAction(affine_params=affine_params)]

    # ExportLayerActionを処理し、画像のセッションディレクトリへのコピー・ワールドファイル書き込み・メタデータ更新・ジオリファレンス済みラスタのキャンバス配置を行う。
    def handle_export_layer(self, action: ExportLayerAction) -> Optional[List[UIAction]]:
        state = self.state_store.state
        if state.calculated_affine_params is None:
            return [SetValidationAction(True, "変換計算が未実行のため、レイヤ出力できません。")]
        layer_name = action.layer_name
        src_path = action.image_path

        session_img_dir = self.layer_manager.session_image_dir
        current_dir = os.path.normcase(os.path.normpath(os.path.dirname(src_path)))
        already_in_session = bool(session_img_dir) and current_dir == os.path.normcase(os.path.normpath(session_img_dir))

        dest_path = src_path
        if not already_in_session:
            success, msg, copy_path = self.layer_manager.copy_image_to_session(src_path)
            if not success:
                return [SetValidationAction(True, msg)]
            dest_path = copy_path

        success, msg, _ = self.layer_manager.write_world_file(dest_path, state.calculated_affine_params)
        if not success:
            return [SetValidationAction(True, f"ワールドファイルの書き込みに失敗: {msg}")]

        self.layer_manager.update_image_metadata(
            layer_name, dest_path, state.ref_points_data, state.calculated_affine_params
        )

        if self.point_layer and self.point_layer.isValid():
            update_point_layer_geometry(self.point_layer, state.calculated_affine_params, drawing_name=layer_name)

        success, msg, raster_layer = self.layer_manager.load_georeferenced_raster(
            dest_path, custom_layer_name=layer_name
        )
        if not success or raster_layer is None:
            return [SetValidationAction(True, f"キャンバス配置に失敗: {msg}")]

        self.iface.mapCanvas().setExtent(raster_layer.extent())
        self.iface.mapCanvas().refresh()

        self.update_drawing_combo_cb()
        self.ensure_drawing_selected_cb(layer_name)
        self.ensure_drawing_visible_cb(layer_name)

        return []