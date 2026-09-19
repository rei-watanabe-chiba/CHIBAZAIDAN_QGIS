"""
/***************************************************************************
 PointerGeocoding Plugin - Grid CSV Mixin
 ***************************************************************************/

Stage C split (mechanical, logic-preserving): extracted from
layer_manager.py. Provides GridCsvMixin, mixed into LayerManager,
containing PointGeo_grid.csv generation/deployment and in-memory loading
(including building the ref_points Delimited Text layer).
"""
# 【変更不可侵の絶対的ルール】 測量座標系（X軸=南北, Y軸=東西）を採用。QGISキャンバス上のX座標(東西)はSurvey Y、Y座標(南北)はSurvey Xに対応する。

import os
import csv
import shutil
from typing import Optional, Dict, Any, Tuple

from qgis.core import (
    QgsProject,
    QgsVectorLayer,
)

from ..logic.core import from_survey_coords, to_excel_column
from .models import get_local_crs


class GridCsvMixin:
    """Mixin providing grid CSV generation/deployment and in-memory loading for LayerManager."""

    @classmethod
    def generate_grid_csv(
        cls,
        output_path: str,
        origin_x: int,
        origin_y: int,
        range_x_min: int,
        range_x_max: int,
        range_y_min: int,
        range_y_max: int,
    ) -> Tuple[bool, str]:
        """Generate PointGeo_grid.csv containing coordinates for all small grids in the specified range.
        # 【変更不可侵の絶対的ルール】 測量座標系（X軸=南北, Y軸=東西）を採用。QGISキャンバス上のX座標(東西)はSurvey Y、Y座標(南北)はSurvey Xに対応する。

        Survey coordinate system:
        - X axis = North-South (Survey X)
        - Y axis = East-West (Survey Y)
        - Large grid: 40m x 40m, named as [X Number][Y Letter] (e.g., 1A, 10J)
        - Small grid: 4m x 4m (10x10 inside large grid), named as 00..99
        - Output coordinates: Upper-left vertex of each small grid in real-world space.
        - Encoding: UTF-8 with BOM (utf-8-sig).
        - The origin (origin_x, origin_y) always represents the theoretical 1A-00 point;
          range_x_min/range_y_min need not be 1, in which case grids are generated starting
          from the specified minimum while the offset formula still measures from 1A-00.

        :param output_path: Destination path of PointGeo_grid.csv.
        :type output_path: str
        :param origin_x: Origin X coordinate (1A-00).
        :type origin_x: int
        :param origin_y: Origin Y coordinate (1A-00).
        :type origin_y: int
        :param range_x_min: Minimum (inclusive) large grid number along the X axis (>=1).
        :type range_x_min: int
        :param range_x_max: Maximum (inclusive) large grid number along the X axis (<=300).
        :type range_x_max: int
        :param range_y_min: Minimum (inclusive) large grid letter index along the Y axis (>=1, 'A').
        :type range_y_min: int
        :param range_y_max: Maximum (inclusive) large grid letter index along the Y axis (<=702, 'ZZ').
        :type range_y_max: int
        :return: Tuple of (success, message).
        :rtype: Tuple[bool, str]
        """
        try:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, mode="w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["大グリッドＸ", "大グリッドＹ", "小グリッド", "Ｘ座標", "Ｙ座標"])
                for gx in range(range_x_min, range_x_max + 1):
                    gx_offset = origin_x - (gx - 1) * 40
                    for gy in range(range_y_min, range_y_max + 1):
                        grid_y_str = to_excel_column(gy)
                        gy_offset = origin_y + (gy - 1) * 40
                        for sx in range(10):
                            coord_x = gx_offset - sx * 4
                            for sy in range(10):
                                coord_y = gy_offset + sy * 4
                                sub_grid = f"{sx}{sy}"
                                writer.writerow([gx, grid_y_str, sub_grid, coord_x, coord_y])
            return True, f"グリッドCSVを正常に生成しました: {output_path}"
        except Exception as e:
            return False, f"グリッドCSVの生成に失敗しました: {str(e)}"

    @classmethod
    def setup_or_copy_grid_csv(
        cls, session_dir: str, grid_config: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, str]:
        """Deploy PointGeo_grid.csv into the session directory by copy or automatic generation.

        :param session_dir: Target session root directory.
        :type session_dir: str
        :param grid_config: Optional grid configuration dictionary.
        :type grid_config: Optional[Dict[str, Any]]
        :return: Tuple of (success, message).
        :rtype: Tuple[bool, str]
        """
        dest_path = os.path.join(session_dir, "PointGeo_grid.csv")

        # If no config provided, check if file already exists in session_dir
        if not grid_config:
            if os.path.isfile(dest_path):
                return True, "既存のグリッドCSVを維持します。"
            # Default fallback parameters
            grid_config = {
                "use_existing_csv": False,
                "origin_x": 0,
                "origin_y": 0,
                "range_x_min": 1,
                "range_x_max": 10,
                "range_y_min": 1,
                "range_y_max": 10,
            }

        use_existing = grid_config.get("use_existing_csv", False)
        src_path = grid_config.get("csv_path", "")

        if use_existing and src_path:
            if not os.path.isfile(src_path):
                return False, f"指定されたグリッドCSVファイルが存在しません:\n{src_path}"
            # Avoid copying onto itself
            if os.path.abspath(src_path) != os.path.abspath(dest_path):
                try:
                    shutil.copy2(src_path, dest_path)
                except Exception as e:
                    return False, f"グリッドCSVファイルのコピーに失敗しました: {str(e)}"
            return True, f"グリッドCSVを配置しました: {dest_path}"
        else:
            origin_x = int(grid_config.get("origin_x", 0))
            origin_y = int(grid_config.get("origin_y", 0))
            range_x_min = int(grid_config.get("range_x_min", 1))
            range_x_max = int(grid_config.get("range_x_max", 10))
            range_y_min = int(grid_config.get("range_y_min", 1))
            range_y_max = int(grid_config.get("range_y_max", 10))
            return cls.generate_grid_csv(
                dest_path, origin_x, origin_y, range_x_min, range_x_max, range_y_min, range_y_max
            )

    def load_grid_csv_to_memory(self, csv_path: Optional[str] = None) -> bool:
        """Load PointGeo_grid.csv into memory cache.

        Extracts:
        - grid_data: (Xグリッド:int, Yグリッド:str, 小グリッド:str) -> (X実座標:float, Y実座標:float)
        - max_gx: maximum large grid X (int)
        - unique_gy: set of unique large grid Y strings (set[str])

        :param csv_path: Path to the grid CSV. If None, uses self.grid_csv_path.
        :type csv_path: Optional[str]
        :return: True if loaded successfully, False otherwise.
        :rtype: bool
        """
        target_path = csv_path or self.grid_csv_path
        if not target_path or not os.path.isfile(target_path):
            return False

        grid_data: Dict[Tuple[int, str, str], Tuple[float, float]] = {}
        max_gx: int = 0
        unique_gy: set = set()

        encodings = ["utf-8-sig", "utf-8", "cp932"]
        success = False

        for enc in encodings:
            try:
                with open(target_path, mode="r", newline="", encoding=enc) as f:
                    reader = csv.reader(f)
                    for row in reader:
                        if not row or len(row) < 5:
                            continue
                        try:
                            gx = int(row[0].strip())
                        except ValueError:
                            continue

                        gy = str(row[1]).strip().upper()
                        sub_grid = str(row[2]).strip().zfill(2)
                        try:
                            survey_x = float(row[3].strip())
                            survey_y = float(row[4].strip())
                        except ValueError:
                            continue

                        math_x, math_y = from_survey_coords(survey_x, survey_y)
                        grid_data[(gx, gy, sub_grid)] = (math_x, math_y)
                        if gx > max_gx:
                            max_gx = gx
                        unique_gy.add(gy)

                success = True
                break
            except Exception:
                continue

        if success:
            self.grid_data = grid_data
            self.max_gx = max_gx
            self.unique_gy = unique_gy
            self.grid_csv_path = target_path

            # Build ref_points layer directly from the CSV using Delimited Text Provider.
            # 【変更不可侵の絶対的ルール】 QGIS X = Survey Y (Ｙ座標列), QGIS Y = Survey X (Ｘ座標列)
            # xField / yField are intentionally swapped to convert survey coordinates to QGIS canvas.
            local_crs = get_local_crs()
            crs_authid = local_crs.authid() if local_crs.isValid() else "EPSG:4326"
            # URL-encode the file path for the URI (spaces → %20, backslash → forward slash)
            import urllib.parse
            encoded_path = urllib.parse.quote(target_path.replace("\\", "/"), safe=":/")
            uri = (
                f"file:///{encoded_path}"
                f"?type=csv&delimiter=,&useHeader=yes"
                f"&xField=%EF%BC%B9%E5%BA%A7%E6%A8%99"   # Ｙ座標 (UTF-8 percent-encoded)
                f"&yField=%EF%BC%B8%E5%BA%A7%E6%A8%99"   # Ｘ座標 (UTF-8 percent-encoded)
                f"&crs={crs_authid}"
                f"&trimFields=yes"
            )
            csv_layer = QgsVectorLayer(uri, "ref_points", "delimitedtext")

            if csv_layer.isValid():
                # Remove any previously loaded ref_points CSV layer from the project
                existing = QgsProject.instance().mapLayersByName("ref_points")
                for old_layer in existing:
                    # Only remove CSV-type layers (not GPKG-based ones)
                    if old_layer.dataProvider().name() == "delimitedtext":
                        QgsProject.instance().removeMapLayer(old_layer.id())

                # Load current settings to apply to symbology
                current_settings = self.load_settings()
                self.apply_ref_point_symbology(csv_layer, current_settings)
                self.ref_point_layer = csv_layer

                # Insert into "基準点データ" group if it exists, otherwise root
                root = QgsProject.instance().layerTreeRoot()
                ref_group = root.findGroup("基準点データ")
                if ref_group:
                    QgsProject.instance().addMapLayer(csv_layer, False)
                    ref_group.insertLayer(0, csv_layer)
                else:
                    QgsProject.instance().addMapLayer(csv_layer)

            return True
        return False
