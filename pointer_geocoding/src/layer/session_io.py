"""
/***************************************************************************
 PointerGeocoding Plugin - Session I/O Mixin
 ***************************************************************************/

Stage C split (mechanical, logic-preserving): extracted from
layer_manager.py. Provides SessionIOMixin, mixed into LayerManager,
containing new/existing session setup, image copying, world file
generation, raster/reference-point loading, and project save.
"""
# 【変更不可侵の絶対的ルール】 測量座標系（X軸=南北, Y軸=東西）を採用。QGISキャンバス上のX座標(東西)はSurvey Y、Y座標(南北)はSurvey Xに対応する。

import os
import shutil
from typing import Optional, Tuple, Dict, Any, List

from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
)

from .models import get_local_crs, suppress_crs_prompt


class SessionIOMixin:
    """Mixin providing session setup/loading, image/raster handling, and
    reference-point/project persistence for LayerManager."""

    def setup_new_session(
        self,
        parent_dir: str,
        session_name: str,
        image_file_path: Optional[str] = None,
        grid_config: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Build the automated session folder structure, GeoPackage, and QGIS project.

        Initializes empty 'image' and 'point' folders, creates vector layers,
        generates or copies PointGeo_grid.csv, and leaves raster loading to the pre-georeferencing step.
        """
        try:
            # 1. Create directory hierarchy (image folder starts empty)
            session_dir = os.path.join(parent_dir, session_name)
            image_dir = os.path.join(session_dir, "image")
            point_dir = os.path.join(session_dir, "point")

            os.makedirs(image_dir, exist_ok=True)
            os.makedirs(point_dir, exist_ok=True)

            # 1.0 Create json/ directory and initialize settings.json with defaults
            self.session_dir = session_dir  # Set early so ensure_json_dir can resolve path
            self.ensure_json_dir()

            # 1.1 Generate or copy PointGeo_grid.csv into session_dir
            grid_ok, grid_msg = self.setup_or_copy_grid_csv(session_dir, grid_config)
            if not grid_ok:
                return False, f"グリッドCSVの配置に失敗しました: {grid_msg}", None

            # 2. Create GeoPackage with points and ref_points tables
            gpkg_path = os.path.join(point_dir, "session_layers.gpkg")
            success, msg = self.create_initial_gpkg(gpkg_path)
            if not success:
                return False, f"GeoPackageの初期化に失敗しました: {gpkg_path}\n詳細: {msg}", None

            # 3. Initialize QGIS Project with custom local orthogonal CRS
            # 【変更不可侵の絶対的ルール】 測量座標系（X軸=南北, Y軸=東西）を採用。QGISキャンバス上のX座標(東西)はSurvey Y、Y座標(南北)はSurvey Xに対応する。
            project = QgsProject.instance()
            project.clear()
            project.writeEntry("Paths", "/Absolute", False)

            qgz_path = os.path.join(session_dir, f"{session_name}.qgz")
            project.setFileName(qgz_path)

            local_crs = get_local_crs()
            project.setCrs(local_crs)

            # 4. Load vector layers with CRS prompt suppression
            with suppress_crs_prompt():
                # 4.1 Load points layer
                points_uri = f"{gpkg_path}|layername=points"
                point_layer = QgsVectorLayer(points_uri, "打刻点", "ogr")
                if not point_layer.isValid():
                    return False, "打刻点レイヤ (points) の読み込みに失敗しました。", None
                point_layer.setCrs(local_crs)
                self.apply_point_labeling(point_layer)
                project.addMapLayer(point_layer)

                # 4.2 ref_points is loaded from CSV in load_grid_csv_to_memory() below.
                #     No GPKG-based ref_points layer is created or loaded here.

            # 4.3 Ensure the '画像ファイル' raster group exists in the layer tree from
            # session creation, even before any image has been added (T-0015). It was
            # previously only created lazily, the first time load_georeferenced_raster()
            # ran, which meant an unused new session showed no such group at all.
            if project.layerTreeRoot().findGroup("画像ファイル") is None:
                project.layerTreeRoot().addGroup("画像ファイル")

            # 5. Save initial project state
            project.write(qgz_path)

            # Update instance states (no raster layer loaded initially)
            self.session_dir = session_dir
            self.gpkg_path = gpkg_path
            self.qgz_path = qgz_path
            self.point_layer = point_layer
            self.ref_point_layer = None  # Will be set by load_grid_csv_to_memory
            self.raster_layer = None
            self.grid_csv_path = os.path.join(session_dir, "PointGeo_grid.csv")

            # Load grid CSV into memory cache and build ref_points CSV layer
            self.load_grid_csv_to_memory(self.grid_csv_path)

            # Build initial spatial index and caches with Observer pattern
            self.init_spatial_index_and_cache()

            layers_dict = {
                "session_dir": session_dir,
                "gpkg_path": gpkg_path,
                "qgz_path": qgz_path,
                "point_layer": point_layer,
                "ref_point_layer": self.ref_point_layer,
                "raster_layer": None,
                "grid_csv_path": self.grid_csv_path,
                "grid_data": self.grid_data,
                "max_gx": self.max_gx,
                "unique_gy": self.unique_gy,
                "spatial_index": self.spatial_index,
                "attr_cache": self.attr_cache,
            }
            return True, "新規セッションが正常に作成されました。", layers_dict

        except Exception as e:
            return False, f"セッション構築中に例外が発生しました: {str(e)}", None

    def copy_image_to_session(
        self, src_image_path: str, custom_name: Optional[str] = None
    ) -> Tuple[bool, str, str]:
        """Copy a user-selected drawing image to the session's image/ directory.

        :param src_image_path: Absolute path to the source image file.
        :param custom_name: Optional user-specified filename (without or with extension).
        :return: (success, message, dest_file_path).
        """
        if not self.session_dir:
            return False, "セッションが初期化されていません。", ""

        if not os.path.isfile(src_image_path):
            return False, f"指定された画像ファイルが存在しません: {src_image_path}", ""

        image_dir = os.path.join(self.session_dir, "image")
        os.makedirs(image_dir, exist_ok=True)

        _, src_ext = os.path.splitext(src_image_path)
        if custom_name and (c_name := custom_name.strip()):
            c_base, c_ext = os.path.splitext(c_name)
            final_ext = c_ext or src_ext
            target_filename = f"{c_base}{final_ext}"
        else:
            target_filename = os.path.basename(src_image_path)

        dest_path = os.path.join(image_dir, target_filename)

        # Duplicate check in destination
        if os.path.exists(dest_path):
            return False, f"同名の画像ファイルが既にimageフォルダに存在します:\n{target_filename}", dest_path

        try:
            shutil.copy2(src_image_path, dest_path)
            return True, "画像ファイルをセッションフォルダにコピーしました。", dest_path
        except Exception as e:
            return False, f"画像のコピーに失敗しました: {str(e)}", ""

    @staticmethod
    def write_world_file(
        raster_path: str, affine_params: Tuple[float, float, float, float, float, float]
    ) -> Tuple[bool, str, str]:
        """Generate an ESRI 6-line world file (tfw/pgw/jgw/wld) based on affine parameters.
        # 【変更不可侵の絶対的ルール】 測量座標系（X軸=南北, Y軸=東西）を採用。QGISキャンバス上のX座標(東西)はSurvey Y、Y座標(南北)はSurvey Xに対応する。

        Standard ESRI / GDAL World File format (6 lines):
        Line 1: A (pixel size in Canvas X / Survey Y direction)
        Line 2: D (rotation about Y axis)
        Line 3: B (rotation about X axis)
        Line 4: E (pixel size in Canvas Y / Survey X direction)
        Line 5: C (Canvas X / Survey Y coordinate of the center of upper-left pixel)
        Line 6: F (Canvas Y / Survey X coordinate of the center of upper-left pixel)

        :param raster_path: Path to the image in session_dir/image/.
        :param affine_params: Tuple of (A, B, C, D, E, F) from coordinate transformation.
        :return: (success, message, world_file_path).
        """
        A, B, C, D, E, F = affine_params
        base, ext = os.path.splitext(raster_path)
        ext_lower = ext.lower().lstrip(".")

        if ext_lower in ("tif", "tiff"):
            wld_ext = ".tfw"
        elif ext_lower in ("jpg", "jpeg"):
            wld_ext = ".jgw"
        elif ext_lower == "png":
            wld_ext = ".pgw"
        elif ext_lower == "bmp":
            wld_ext = ".bpw"
        else:
            wld_ext = ".wld"

        world_file_path = f"{base}{wld_ext}"
        content = (
            f"{A:.10f}\n"
            f"{D:.10f}\n"
            f"{B:.10f}\n"
            f"{E:.10f}\n"
            f"{C:.10f}\n"
            f"{F:.10f}\n"
        )

        try:
            # Write specific world file
            with open(world_file_path, "w", encoding="ascii") as f:
                f.write(content)

            # Also write generic .wld file for maximum compatibility
            generic_wld_path = f"{base}.wld"
            if generic_wld_path != world_file_path:
                with open(generic_wld_path, "w", encoding="ascii") as f:
                    f.write(content)

            return True, "ワールドファイルを正常に生成しました。", world_file_path
        except Exception as e:
            return False, f"ワールドファイルの書き込みに失敗しました: {str(e)}", ""

    @staticmethod
    def load_preview_raster(image_path: str) -> Tuple[bool, str, Optional[QgsRasterLayer]]:
        """Load a standalone raster layer for display in a preview map canvas.
        # 【変更不可侵の絶対的ルール】 測量座標系（X軸=南北, Y軸=東西）を採用。QGISキャンバス上のX座標(東西)はSurvey Y、Y座標(南北)はSurvey Xに対応する。

        Does not add the layer to QgsProject.instance().
        """
        if not os.path.isfile(image_path):
            return False, f"画像ファイルが存在しません: {image_path}", None

        layer_name = os.path.splitext(os.path.basename(image_path))[0]
        layer = QgsRasterLayer(image_path, f"プレビュー_{layer_name}")
        if not layer.isValid():
            return False, f"プレビュー用画像の読み込みに失敗しました: {image_path}", None

        layer.setCrs(get_local_crs())
        return True, "", layer

    def load_georeferenced_raster(
        self, image_path: str, custom_layer_name: Optional[str] = None
    ) -> Tuple[bool, str, Optional[QgsRasterLayer]]:
        """Load the georeferenced raster image into QgsProject under '画像ファイル' group.
        # 【変更不可侵の絶対的ルール】 測量座標系（X軸=南北, Y軸=東西）を採用。QGISキャンバス上のX座標(東西)はSurvey Y、Y座標(南北)はSurvey Xに対応する。

        Retains all previously loaded images in the project so multiple drawings can coexist.
        """
        project = QgsProject.instance()
        local_crs = get_local_crs()

        if custom_layer_name and (custom_trimmed := custom_layer_name.strip()):
            layer_name = custom_trimmed
        else:
            layer_name = os.path.splitext(os.path.basename(image_path))[0]

        with suppress_crs_prompt():
            raster_layer = QgsRasterLayer(image_path, layer_name)
            if not raster_layer.isValid():
                return False, f"ジオリファレンス画像の読み込みに失敗しました: {image_path}", None

            raster_layer.setCrs(local_crs)

            # Ensure '画像ファイル' group exists in QGIS layer tree
            root = project.layerTreeRoot()
            group_name = "画像ファイル"
            if (image_group := root.findGroup(group_name)) is None:
                image_group = root.addGroup(group_name)

            # If a layer with the exact same custom name already exists in image_group, remove only that specific duplicate
            for tree_layer in image_group.findLayers():
                if (l := tree_layer.layer()) and l.name() == layer_name:
                    project.removeMapLayer(l.id())
                    break

            # Add to project and place inside '画像ファイル' group without deleting other images
            project.addMapLayer(raster_layer, addToLegend=False)
            image_group.addLayer(raster_layer)

        self.raster_layer = raster_layer
        project.write()
        return True, "画像をマップに配置しました。", raster_layer

    def save_ref_points(self, ref_points_data: List[Dict[str, Any]]) -> bool:
        """Persist reference point definitions into the GeoPackage ref_points layer.
        # 【変更不可侵の絶対的ルール】 測量座標系（X軸=南北, Y軸=東西）を採用。QGISキャンバス上のX座標(東西)はSurvey Y、Y座標(南北)はSurvey Xに対応する。
        """
        if not self.ref_point_layer or not self.ref_point_layer.isValid():
            return False

        self.ref_point_layer.startEditing()
        # Clear existing reference points
        existing_fids = [f.id() for f in self.ref_point_layer.getFeatures()]
        if existing_fids:
            self.ref_point_layer.deleteFeatures(existing_fids)

        for i, rdata in enumerate(ref_points_data):
            feat = QgsFeature(self.ref_point_layer.fields())
            feat.setAttribute("ref_id", i + 1)
            feat.setAttribute("ref_name", rdata.get("name", f"Ref-{i+1}"))
            feat.setAttribute("canvas_x", rdata.get("pixel_x", 0.0))
            feat.setAttribute("canvas_y", rdata.get("pixel_y", 0.0))
            feat.setAttribute("target_x", rdata.get("real_x", 0.0))
            feat.setAttribute("target_y", rdata.get("real_y", 0.0))
            feat.setGeometry(
                QgsGeometry.fromPointXY(
                    QgsPointXY(float(rdata.get("real_x", 0.0)), float(rdata.get("real_y", 0.0)))
                )
            )
            self.ref_point_layer.addFeature(feat)

        self.ref_point_layer.commitChanges()
        self.ref_point_layer.triggerRepaint()
        QgsProject.instance().write()
        return True

    def load_existing_session(
        self, session_dir: str, grid_config: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Load an existing QGIS session project and locate its vector and raster layers.

        :param session_dir: Absolute path to the existing session directory.
        :type session_dir: str
        :param grid_config: Optional grid configuration dictionary.
        :type grid_config: Optional[Dict[str, Any]]
        :return: Tuple of (success, message, layers_dict).
        :rtype: Tuple[bool, str, Optional[Dict[str, Any]]]
        """
        try:
            if not os.path.exists(session_dir):
                return False, f"指定されたセッションディレクトリが存在しません: {session_dir}", None

            # Ensure PointGeo_grid.csv is configured or maintained
            grid_csv_file = os.path.join(session_dir, "PointGeo_grid.csv")
            if grid_config is not None or not os.path.isfile(grid_csv_file):
                grid_ok, grid_msg = self.setup_or_copy_grid_csv(session_dir, grid_config)
                if not grid_ok:
                    return False, f"グリッドCSVの配置に失敗しました: {grid_msg}", None

            # Find .qgz project in session directory
            qgz_files = [f for f in os.listdir(session_dir) if f.endswith(".qgz")]
            if not qgz_files:
                return False, f"セッションディレクトリ内に .qgz プロジェクトファイルが見つかりません: {session_dir}", None

            qgz_path = os.path.join(session_dir, qgz_files[0])
            gpkg_path = os.path.join(session_dir, "point", "session_layers.gpkg")

            project = QgsProject.instance()
            project.clear()

            # Load project with CRS prompt suppression
            with suppress_crs_prompt():
                loaded = project.read(qgz_path)
                if not loaded:
                    return False, f"QGISプロジェクトの読み込みに失敗しました: {qgz_path}", None

            # Re-enforce relative path storage
            project.writeEntry("Paths", "/Absolute", False)

            # Apply custom local orthogonal CRS to project
            # 【変更不可侵の絶対的ルール】 測量座標系（X軸=南北, Y軸=東西）を採用。QGISキャンバス上のX座標(東西)はSurvey Y、Y座標(南北)はSurvey Xに対応する。
            local_crs = get_local_crs()
            project.setCrs(local_crs)

            # Ensure the '画像ファイル' raster group exists in the layer tree, even for
            # sessions that were saved before any image was ever added (T-0015). Persist
            # it back to the project file so it is not re-created on every reload.
            if project.layerTreeRoot().findGroup("画像ファイル") is None:
                project.layerTreeRoot().addGroup("画像ファイル")
                project.write(qgz_path)

            # Locate required layers from project mapLayers
            point_layer: Optional[QgsVectorLayer] = None
            raster_layer: Optional[QgsRasterLayer] = None

            for layer in project.mapLayers().values():
                if isinstance(layer, QgsVectorLayer):
                    src = layer.source().lower()
                    if "layername=points" in src or layer.name() in ("打刻点", "points"):
                        point_layer = layer
                    # ref_points CSV layer will be rebuilt below; remove stale ones from the project
                    elif layer.dataProvider().name() == "delimitedtext" and layer.name() == "ref_points":
                        project.removeMapLayer(layer.id())
                elif isinstance(layer, QgsRasterLayer):
                    raster_layer = layer

            # Fallback auto-recovery: If points layer is missing, recover from GeoPackage
            with suppress_crs_prompt():
                if point_layer is None and os.path.exists(gpkg_path):
                    points_uri = f"{gpkg_path}|layername=points"
                    point_layer = QgsVectorLayer(points_uri, "打刻点", "ogr")
                    if point_layer.isValid():
                        point_layer.setCrs(local_crs)
                        project.addMapLayer(point_layer)

            if point_layer is None or not point_layer.isValid():
                return False, "打刻点レイヤ (points) を検出できませんでした。", None

            # Ensure CRS is set to local orthogonal CRS
            point_layer.setCrs(local_crs)
            if raster_layer and raster_layer.isValid():
                raster_layer.setCrs(local_crs)

            self.apply_point_labeling(point_layer)

            self.session_dir = session_dir
            self.gpkg_path = gpkg_path
            self.qgz_path = qgz_path
            self.point_layer = point_layer
            self.ref_point_layer = None  # Will be set by load_grid_csv_to_memory
            self.raster_layer = raster_layer
            self.grid_csv_path = grid_csv_file

            # Load grid CSV into memory cache and rebuild ref_points CSV layer
            self.load_grid_csv_to_memory(self.grid_csv_path)

            # Build initial spatial index and caches with Observer pattern (including drawing_name migration)
            self.init_spatial_index_and_cache()

            layers_dict = {
                "session_dir": session_dir,
                "gpkg_path": gpkg_path,
                "qgz_path": qgz_path,
                "point_layer": point_layer,
                "ref_point_layer": self.ref_point_layer,
                "raster_layer": raster_layer,
                "grid_csv_path": self.grid_csv_path,
                "grid_data": self.grid_data,
                "max_gx": self.max_gx,
                "unique_gy": self.unique_gy,
                "spatial_index": self.spatial_index,
                "attr_cache": self.attr_cache,
            }
            return True, "既存セッションが正常に読み込まれました。", layers_dict

        except Exception as e:
            return False, f"既存セッション読み込み中に例外が発生しました: {str(e)}", None

    def save_project(self) -> bool:
        """Write current project changes to disk.

        :return: True if save succeeded, False otherwise.
        :rtype: bool
        """
        project = QgsProject.instance()
        return project.write()
