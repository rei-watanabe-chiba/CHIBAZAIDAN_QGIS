"""
/***************************************************************************
 PointerGeocoding Plugin - Coordinate Transformation & CSV Export Module
 ***************************************************************************/
"""

import csv
import math
from typing import Optional, Tuple, Dict, Any, List, Callable

from qgis.core import (
    QgsVectorLayer,
    QgsFeature,
    QgsProject,
    QgsGeometry,
    QgsPointXY,
    Qgis,
)
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtWidgets import QWidget

from .core import (
    to_survey_coords,
    from_survey_coords,
    update_point_layer_geometry,
    evaluate_residuals,
    batch_update_attributes,
)
from ..ui.style import UIStyleHelper


class CoordinateTransformer:
    """Performs 2-point Helmert or 3-point Affine transformation in standard mathematical coordinates
    (math_x=East, math_y=North), computes residuals in survey coordinates,
    and updates digitized point features.
    """

    def __init__(self, point_layer: QgsVectorLayer, ref_point_layer: QgsVectorLayer) -> None:
        """Initialize CoordinateTransformer.

        :param point_layer: Vector layer for digitized points (points table).
        :type point_layer: QgsVectorLayer
        :param ref_point_layer: Vector layer for reference points (ref_points table).
        :type ref_point_layer: QgsVectorLayer
        """
        self.point_layer = point_layer
        self.ref_point_layer = ref_point_layer

    @staticmethod
    def compute_helmert_2p(
        p1: Tuple[float, float],
        p2: Tuple[float, float],
        P1: Tuple[float, float],
        P2: Tuple[float, float],
        parent: Optional[QWidget] = None,
    ) -> Optional[Dict[str, float]]:
        """Compute 2-point Helmert (similarity) transformation parameters in standard mathematical coordinates.

        Canvas X = a * x - b * y + Tx  (East-West)
        Canvas Y = b * x + a * y + Ty  (North-South)

        :param p1: Local canvas/pixel coordinate (x1, y1) of reference point 1.
        :param p2: Local canvas/pixel coordinate (x2, y2) of reference point 2.
        :param P1: Target mathematical coordinate (math_x1, math_y1) of reference point 1.
        :param P2: Target mathematical coordinate (math_x2, math_y2) of reference point 2.
        :param parent: Optional parent QWidget for error message dialogs.
        :return: Parameter dictionary {'a': a, 'b': b, 'Tx': Tx, 'Ty': Ty} or None on error.
        :rtype: Optional[Dict[str, float]]
        """
        x1, y1 = p1[0], -p1[1]
        x2, y2 = p2[0], -p2[1]
        X1, Y1 = P1
        X2, Y2 = P2

        dx = x2 - x1
        dy = y2 - y1
        dX = X2 - X1
        dY = Y2 - Y1

        L2 = dx * dx + dy * dy
        if L2 < 1e-9:
            if parent:
                UIStyleHelper.show_error_dialog(
                    parent,
                    "計算エラー",
                    "図面上の基準点1と基準点2が同一点であるため、ヘルマート変換パラメータを計算できません。\n異なる基準点を指定してください。",
                )
            return None

        # Check real coordinates distance
        real_L2 = dX * dX + dY * dY
        if real_L2 < 1e-9:
            if parent:
                UIStyleHelper.show_error_dialog(
                    parent,
                    "計算エラー",
                    "入力された基準点1と基準点2の実座標が同一位置です。\n有効な基準点実座標を入力してください。",
                )
            return None

        a = (dx * dX + dy * dY) / L2
        b = (dx * dY - dy * dX) / L2
        Tx = X1 - (a * x1 - b * y1)
        Ty = Y1 - (b * x1 + a * y1)

        return {"a": a, "b": b, "Tx": Tx, "Ty": Ty}

    @staticmethod
    def compute_affine_3p(
        p1: Tuple[float, float],
        p2: Tuple[float, float],
        p3: Tuple[float, float],
        P1: Tuple[float, float],
        P2: Tuple[float, float],
        P3: Tuple[float, float],
        parent: Optional[QWidget] = None,
    ) -> Optional[Tuple[float, float, float, float, float, float]]:
        """Compute 3-point Affine transformation parameters in standard mathematical coordinates.

        Canvas X = A * x + B * y + C  (East-West)
        Canvas Y = D * x + E * y + F  (North-South)

        :param p1: Local pixel coordinate (x1, y1) of ref 1.
        :param p2: Local pixel coordinate (x2, y2) of ref 2.
        :param p3: Local pixel coordinate (x3, y3) of ref 3.
        :param P1: Target mathematical coordinate (math_x1, math_y1) of ref 1.
        :param P2: Target mathematical coordinate (math_x2, math_y2) of ref 2.
        :param P3: Target mathematical coordinate (math_x3, math_y3) of ref 3.
        :param parent: Optional parent QWidget for error message dialogs.
        :return: Tuple of (A, B, C, D, E, F) or None on error.
        :rtype: Optional[Tuple[float, float, float, float, float, float]]
        """
        x1, y1 = p1
        x2, y2 = p2
        x3, y3 = p3
        X1, Y1 = P1
        X2, Y2 = P2
        X3, Y3 = P3

        # Determinant of the 3 points on the local drawing
        det = x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2)
        if abs(det) < 1e-9:
            if parent:
                UIStyleHelper.show_error_dialog(
                    parent,
                    "計算エラー",
                    "選択された3つの基準点が同一直線上に存在するため、アフィン変換行列を定義できません。\n同一直線上にない有効な3基準点を指定してください。",
                )
            return None

        # Determinant of real coordinates
        det_real = X1 * (Y2 - Y3) + X2 * (Y3 - Y1) + X3 * (Y1 - Y2)
        if abs(det_real) < 1e-9:
            if parent:
                UIStyleHelper.show_error_dialog(
                    parent,
                    "計算エラー",
                    "入力された基準点の実座標3点が同一直線上に存在します。\n三角形を形成する有効な実座標を入力してください。",
                )
            return None

        A = (X1 * (y2 - y3) + X2 * (y3 - y1) + X3 * (y1 - y2)) / det
        B = (X1 * (x3 - x2) + X2 * (x1 - x3) + X3 * (x2 - x1)) / det
        C = (X1 * (x2 * y3 - x3 * y2) + X2 * (x3 * y1 - x1 * y3) + X3 * (x1 * y2 - x2 * y1)) / det

        D = (Y1 * (y2 - y3) + Y2 * (y3 - y1) + Y3 * (y1 - y2)) / det
        E = (Y1 * (x3 - x2) + Y2 * (x1 - x3) + Y3 * (x2 - x1)) / det
        F = (Y1 * (x2 * y3 - x3 * y2) + Y2 * (x3 * y1 - x1 * y3) + Y3 * (x1 * y2 - x2 * y1)) / det

        return (A, B, C, D, E, F)

    @staticmethod
    def apply_helmert(x: float, y: float, params: Dict[str, float]) -> Tuple[float, float]:
        """Apply Helmert transformation formula to a local coordinate in standard mathematical system."""
        a = params["a"]
        b = params["b"]
        Tx = params["Tx"]
        Ty = params["Ty"]
        X = a * x - b * y + Tx
        Y = b * x + a * y + Ty
        return X, Y

    @staticmethod
    def apply_affine(
        x: float, y: float, params: Tuple[float, float, float, float, float, float]
    ) -> Tuple[float, float]:
        """Apply Affine transformation formula to a local coordinate in standard mathematical system."""
        A, B, C, D, E, F = params
        X = A * x + B * y + C
        Y = D * x + E * y + F
        return X, Y

    @classmethod
    def compute_affine_points(
        cls,
        local_points: List[Tuple[float, float]],
        real_points: List[Tuple[float, float]],
        parent: Optional[QWidget] = None,
    ) -> Optional[Tuple[float, float, float, float, float, float]]:
        """Compute Affine / Helmert transformation parameters (A, B, C, D, E, F)
        from 2, 3, or 4+ point correspondences in standard mathematical coordinates.

        Canvas X = A * x + B * y + C  (East-West)
        Canvas Y = D * x + E * y + F  (North-South)

        :param local_points: List of (x, y) pixel/local coordinates.
        :param real_points: List of target mathematical coordinates (math_x, math_y) = (East, North).
        :param parent: Optional parent QWidget for dialogs.
        :return: (A, B, C, D, E, F) or None on failure.
        """
        n = len(local_points)
        if n < 2 or len(real_points) < n:
            if parent:
                UIStyleHelper.show_error_dialog(parent, "計算エラー", "座標変換には最低2点以上の基準点が必要です。")
            return None

        if n == 2:
            p1, p2 = local_points[0], local_points[1]
            P1, P2 = real_points[0], real_points[1]
            h_params = cls.compute_helmert_2p(p1, p2, P1, P2, parent)
            if h_params is None:
                return None
            a = h_params["a"]
            b = h_params["b"]
            Tx = h_params["Tx"]
            Ty = h_params["Ty"]
            # World file affine parameters with pixel Y reflection:
            # X = a*x + b*y + Tx, Y = b*x - a*y + Ty
            # Equivalent affine matrix: A=a, B=b, C=Tx, D=b, E=-a, F=Ty
            return (a, b, Tx, b, -a, Ty)

        # For N >= 3, use least-squares / exact normal equations
        s_xx = sum(p[0] * p[0] for p in local_points)
        s_yy = sum(p[1] * p[1] for p in local_points)
        s_xy = sum(p[0] * p[1] for p in local_points)
        s_x = sum(p[0] for p in local_points)
        s_y = sum(p[1] for p in local_points)
        N = float(n)

        det = (
            s_xx * (s_yy * N - s_y * s_y)
            - s_xy * (s_xy * N - s_y * s_x)
            + s_x * (s_xy * s_y - s_yy * s_x)
        )
        if abs(det) < 1e-9:
            if parent:
                UIStyleHelper.show_error_dialog(
                    parent,
                    "計算エラー",
                    "基準点が同一直線上に存在するため、アフィン変換行列を定義できません。\n有効な基準点を指定してください。",
                )
            return None

        inv00 = (s_yy * N - s_y * s_y) / det
        inv01 = (s_y * s_x - s_xy * N) / det
        inv02 = (s_xy * s_y - s_yy * s_x) / det

        inv10 = inv01
        inv11 = (s_xx * N - s_x * s_x) / det
        inv12 = (s_xy * s_x - s_xx * s_y) / det

        inv20 = inv02
        inv21 = inv12
        inv22 = (s_xx * s_yy - s_xy * s_xy) / det

        s_xX = sum(local_points[i][0] * real_points[i][0] for i in range(n))
        s_yX = sum(local_points[i][1] * real_points[i][0] for i in range(n))
        s_X = sum(real_points[i][0] for i in range(n))

        A = inv00 * s_xX + inv01 * s_yX + inv02 * s_X
        B = inv10 * s_xX + inv11 * s_yX + inv12 * s_X
        C = inv20 * s_xX + inv21 * s_yX + inv22 * s_X

        s_xY = sum(local_points[i][0] * real_points[i][1] for i in range(n))
        s_yY = sum(local_points[i][1] * real_points[i][1] for i in range(n))
        s_Y = sum(real_points[i][1] for i in range(n))

        D = inv00 * s_xY + inv01 * s_yY + inv02 * s_Y
        E = inv10 * s_xY + inv11 * s_yY + inv12 * s_Y
        F = inv20 * s_xY + inv21 * s_yY + inv22 * s_Y

        return (A, B, C, D, E, F)

    def execute_transformation(
        self,
        ref_points_data: List[Dict[str, Any]],
        parent: Optional[QWidget] = None,
        drawing_name: str = "",
        layer_manager: Optional[Any] = None,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Perform coordinate transformation in standard mathematical system and update point features.

        :param ref_points_data: List of dicts containing ref point configurations:
                                [{'ref_name': str, 'pixel_x': float, 'pixel_y': float,
                                  'real_x': float, 'real_y': float, ...}, ...]
        :param parent: Optional parent QWidget.
        :param drawing_name: Target drawing name to filter which points to transform.
        :param layer_manager: Instance of LayerManager to update metadata.
        :return: Tuple of (success, message, result_dict).
        :rtype: Tuple[bool, str, Dict[str, Any]]
        """
        if not self.point_layer or not self.point_layer.isValid():
            return False, "打刻点レイヤが無効です。", {}

        num_refs = len(ref_points_data)
        if num_refs < 2:
            if parent:
                UIStyleHelper.show_error_dialog(
                    parent, "エラー", "座標変換には最低2点以上の基準点が必要です。"
                )
            return False, "基準点数が不足しています。", {}

        # 1. Update target_x and target_y in ref_points layer if layer exists
        if self.ref_point_layer and self.ref_point_layer.isValid():
            ref_updates: List[Tuple[int, Dict[str, Any]]] = []
            for rdata in ref_points_data:
                fid = rdata.get("feature_id")
                if fid is not None:
                    target_x = rdata.get("real_x", rdata.get("target_x", 0.0))
                    target_y = rdata.get("real_y", rdata.get("target_y", 0.0))
                    ref_updates.append((fid, {"target_x": target_x, "target_y": target_y}))
            batch_update_attributes(self.ref_point_layer, ref_updates)

        # 2. Prepare correspondence points in mathematical coordinates
        local_pts: List[Tuple[float, float]] = []
        real_pts: List[Tuple[float, float]] = []

        for r in ref_points_data:
            px = float(r.get("pixel_x", r.get("canvas_x", 0.0)))
            py = float(r.get("pixel_y", r.get("canvas_y", 0.0)))
            rx = float(r.get("real_x", r.get("target_x", 0.0)))
            ry = float(r.get("real_y", r.get("target_y", 0.0)))
            local_pts.append((px, py))
            real_pts.append((rx, ry))

        final_affine = self.compute_affine_points(local_pts, real_pts, parent=parent)
        if final_affine is None:
            return False, "座標変換パラメータの算出に失敗しました。", {}

        mode_str = "HELMERT_2P" if num_refs == 2 else f"AFFINE_{num_refs}P"

        # 3. Compute transformation indicators (rotation and aspect ratio) using core_logic
        rotation_deg, aspect_ratio_pct = evaluate_residuals(ref_points_data, final_affine)

        # 4. Batch update digitized points coordinates and geometries
        updated_count = update_point_layer_geometry(
            self.point_layer, final_affine, drawing_name=drawing_name
        )

        result_data: Dict[str, Any] = {
            "mode": mode_str,
            "rotation_deg": rotation_deg,
            "aspect_ratio_pct": aspect_ratio_pct,
            "updated_count": updated_count,
            "affine_params": final_affine,
        }

        # Update metadata if layer_manager and drawing_name are provided
        if layer_manager and drawing_name:
            file_path = ""
            meta = layer_manager.load_image_metadata()
            if drawing_name in meta:
                file_path = meta[drawing_name].get("file_path", "")

            meta_ref_points = [
                {
                    "name": r.get("name", r.get("ref_name", "")),
                    "pixel_x": float(r.get("pixel_x", r.get("canvas_x", 0.0))),
                    "pixel_y": float(r.get("pixel_y", r.get("canvas_y", 0.0))),
                    "real_x": float(r.get("real_x", r.get("target_x", 0.0))),
                    "real_y": float(r.get("real_y", r.get("target_y", 0.0))),
                }
                for r in ref_points_data
            ]
            layer_manager.update_image_metadata(drawing_name, file_path, meta_ref_points, final_affine)

        # Save project to persist attribute updates
        QgsProject.instance().write()

        return True, f"座標変換が完了しました ({updated_count}件更新)", result_data

    def reset_real_coordinates(self) -> None:
        """Reset real_x and real_y fields in points layer to NULL when reference point configuration changes."""
        if not self.point_layer or not self.point_layer.isValid():
            return

        self.point_layer.startEditing()
        rx_idx = self.point_layer.fields().indexFromName("real_x")
        ry_idx = self.point_layer.fields().indexFromName("real_y")

        for feat in self.point_layer.getFeatures():
            if rx_idx != -1:
                self.point_layer.changeAttributeValue(feat.id(), rx_idx, QVariant())
            if ry_idx != -1:
                self.point_layer.changeAttributeValue(feat.id(), ry_idx, QVariant())

        self.point_layer.commitChanges()
        self.point_layer.triggerRepaint()


def export_points_to_csv(
    point_layer: QgsVectorLayer,
    filepath: str,
    encoding: str = "utf-8-sig",
    parent: Optional[QWidget] = None,
) -> Tuple[bool, str]:
    """Export digitized points to a CSV file with full headers.

    Uses to_survey_coords adapter at the I/O boundary to convert internal mathematical coordinates
    (math_x=East, math_y=North) to survey coordinates (survey_x=North, survey_y=East).

    :param point_layer: Layer containing digitized points.
    :type point_layer: QgsVectorLayer
    :param filepath: Target CSV destination file path.
    :type filepath: str
    :param encoding: File encoding ('utf-8-sig' or 'cp932').
    :type encoding: str
    :param parent: Optional parent QWidget.
    :return: Tuple of (success, message).
    :rtype: Tuple[bool, str]
    """
    if not point_layer or not point_layer.isValid():
        return False, "打刻点レイヤが無効です。"

    features_data = list(point_layer.getFeatures())
    total_count = len(features_data)

    if total_count == 0:
        if parent:
            UIStyleHelper.show_warning_dialog(parent, "警告", "出力対象の打刻点が存在しません。")
        return False, "打刻データが存在しません。"

    # Check for uncalculated (NULL) real_x / real_y
    uncalculated_count = 0
    for feat in features_data:
        mx = feat["real_x"] if feat["real_x"] is not None else feat["canvas_x"]
        my = feat["real_y"] if feat["real_y"] is not None else feat["canvas_y"]
        if mx is None or my is None:
            uncalculated_count += 1

    if uncalculated_count > 0:
        if parent:
            UIStyleHelper.show_warning_dialog(
                parent,
                "座標未取得エラー",
                f"実座標が未取得の打刻点が {uncalculated_count} 件存在します。",
            )
        return False, "未計算の打刻点が存在します。"

    # Output CSV file
    try:
        with open(filepath, mode="w", newline="", encoding=encoding) as f:
            writer = csv.writer(f)
            # Survey Coordinate System Header
            # Ｘ座標: North-South, Ｙ座標: East-West
            writer.writerow([
                "出土形態",
                "遺構名",
                "属性",
                "点名",
                "枝番",
                "Ｘ座標(南北)",
                "Ｙ座標(東西)",
            ])

            for feat in features_data:
                math_x = feat["real_x"] if feat["real_x"] is not None else feat["canvas_x"]
                math_y = feat["real_y"] if feat["real_y"] is not None else feat["canvas_y"]

                # Apply to_survey_coords adapter at CSV boundary
                survey_x, survey_y = to_survey_coords(float(math_x), float(math_y))

                writer.writerow([
                    str(feat["excavation_type"] or ""),
                    str(feat["feature_name"] or ""),
                    str(feat["attribute_type"] or ""),
                    str(feat["point_name"] or ""),
                    str(feat["branch_no"] or ""),
                    f"{survey_x:.3f}",
                    f"{survey_y:.3f}",
                ])

        return True, f"CSVファイルが正常に出力されました: {filepath} ({total_count}件)"

    except Exception as e:
        if parent:
            UIStyleHelper.show_error_dialog(
                parent, "ファイル出力エラー", f"CSVファイルの書き込み中にエラーが発生しました:\n{str(e)}"
            )
        return False, str(e)
