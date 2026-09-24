"""
/***************************************************************************
 PointerGeocoding Plugin - Coordinate Transformation & CSV Export Module
 ***************************************************************************/
"""

import csv
import math
from typing import Tuple, Dict, List

import numpy as np
from scipy.optimize import least_squares

from qgis.core import QgsVectorLayer

from .core import to_survey_coords


# 座標変換パラメータの算出失敗を呼び出し側へ通知する例外(メッセージはユーザー向け日本語文)。
class TransformError(Exception):
    """Raised when coordinate transformation parameters cannot be computed."""


class CoordinateTransformer:
    """Performs 2-point Helmert or N-point non-shear Affine transformation in standard mathematical coordinates
    (math_x=East, math_y=North).
    """

    @staticmethod
    # 2点対応から標準数学座標系での2点ヘルマート(相似)変換パラメータa/b/Tx/Tyを算出。
    def compute_helmert_2p(
        p1: Tuple[float, float],
        p2: Tuple[float, float],
        P1: Tuple[float, float],
        P2: Tuple[float, float],
    ) -> Dict[str, float]:
        """Compute 2-point Helmert (similarity) transformation parameters in standard mathematical coordinates.

        Canvas X = a * x - b * y + Tx  (East-West)
        Canvas Y = b * x + a * y + Ty  (North-South)

        :param p1: Local canvas/pixel coordinate (x1, y1) of reference point 1.
        :param p2: Local canvas/pixel coordinate (x2, y2) of reference point 2.
        :param P1: Target mathematical coordinate (math_x1, math_y1) of reference point 1.
        :param P2: Target mathematical coordinate (math_x2, math_y2) of reference point 2.
        :return: Parameter dictionary {'a': a, 'b': b, 'Tx': Tx, 'Ty': Ty}.
        :rtype: Dict[str, float]
        :raises TransformError: If the points are degenerate (same drawing point or same real coordinate).
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
            raise TransformError(
                "図面上の基準点1と基準点2が同一点であるため、ヘルマート変換パラメータを計算できません。\n異なる基準点を指定してください。"
            )

        # Check real coordinates distance
        real_L2 = dX * dX + dY * dY
        if real_L2 < 1e-9:
            raise TransformError(
                "入力された基準点1と基準点2の実座標が同一位置です。\n有効な基準点実座標を入力してください。"
            )

        a = (dx * dX + dy * dY) / L2
        b = (dx * dY - dy * dX) / L2
        Tx = X1 - (a * x1 - b * y1)
        Ty = Y1 - (b * x1 + a * y1)

        return {"a": a, "b": b, "Tx": Tx, "Ty": Ty}

    @staticmethod
    # ヘルマート変換パラメータを局所座標(x, y)に適用し、標準数学座標系の座標へ変換。
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
    # アフィン変換パラメータ(A〜F)を局所座標(x, y)に適用し、標準数学座標系の座標へ変換。
    def apply_affine(
        x: float, y: float, params: Tuple[float, float, float, float, float, float]
    ) -> Tuple[float, float]:
        """Apply Affine transformation formula to a local coordinate in standard mathematical system."""
        A, B, C, D, E, F = params
        X = A * x + B * y + C
        Y = D * x + E * y + F
        return X, Y

    @classmethod
    # 2点以上の対応点から、2点ならヘルマート、3点以上なら最小二乗法で非せん断アフィン変換パラメータを算出。
    def compute_affine_points(
        cls,
        local_points: List[Tuple[float, float]],
        real_points: List[Tuple[float, float]],
    ) -> Tuple[float, float, float, float, float, float]:
        """Compute Affine / Helmert transformation parameters (A, B, C, D, E, F)
        from 2, 3, or 4+ point correspondences in standard mathematical coordinates.

        Canvas X = A * x + B * y + C  (East-West)
        Canvas Y = D * x + E * y + F  (North-South)

        :param local_points: List of (x, y) pixel/local coordinates.
        :param real_points: List of target mathematical coordinates (math_x, math_y) = (East, North).
        :return: (A, B, C, D, E, F).
        :raises TransformError: If the parameters cannot be computed.
        """
        n = len(local_points)
        if n < 2 or len(real_points) < n:
            raise TransformError("座標変換には最低2点以上の基準点が必要です。")

        # N=2: 2点等比相似変換（ヘルマート変換）
        if n == 2:
            p1, p2 = local_points[0], local_points[1]
            P1, P2 = real_points[0], real_points[1]
            h_params = cls.compute_helmert_2p(p1, p2, P1, P2)
            a = h_params["a"]
            b = h_params["b"]
            Tx = h_params["Tx"]
            Ty = h_params["Ty"]
            # World file affine parameters with pixel Y reflection:
            # Equivalent affine matrix: A=a, B=b, C=Tx, D=b, E=-a, F=Ty
            return (a, b, Tx, b, -a, Ty)

        # N>=3: 5パラメータ非せん断アフィン変換 (最小二乗法で手ブレ誤差を平滑化)
        try:
            # 1. まず通常の6パラメータアフィンを初期値推定のために計算
            M_aff = []
            b_aff = []
            for (x, y), (X, Y) in zip(local_points, real_points):
                M_aff.append([x, y, 1, 0, 0, 0])
                b_aff.append(X)
                M_aff.append([0, 0, 0, x, y, 1])
                b_aff.append(Y)
            M_aff = np.array(M_aff)
            b_aff = np.array(b_aff)

            aff_res, _, _, _ = np.linalg.lstsq(M_aff, b_aff, rcond=None)
            A0, B0, C0, D0, E0, F0 = aff_res
            
            # 2. 初期パラメータの推定
            # 展開式: A = Sx*cosθ, B = Sx*sinθ, D = -Sy*sinθ, E = Sy*cosθ
            Sx0 = math.hypot(A0, B0)
            if Sx0 > 1e-9:
                cos_t0 = A0 / Sx0
                sin_t0 = B0 / Sx0
            else:
                cos_t0, sin_t0 = 1.0, 0.0

            # 鏡映（Y軸反転等）を許容するため Sy0 は負になり得る
            Sy0 = -D0 * sin_t0 + E0 * cos_t0
            theta0 = math.atan2(sin_t0, cos_t0)
            p0 = [Sx0, Sy0, theta0, C0, F0]

            # 3. 5パラメータ非せん断アフィン最適化用 目的関数
            def residuals(p):
                Sx, Sy, theta, Tx, Ty = p
                cos_t = math.cos(theta)
                sin_t = math.sin(theta)
                
                A_p = Sx * cos_t
                B_p = Sx * sin_t
                C_p = Tx
                D_p = -Sy * sin_t
                E_p = Sy * cos_t
                F_p = Ty
                
                err = []
                for (px, py), (rx, ry) in zip(local_points, real_points):
                    err.append(A_p * px + B_p * py + C_p - rx)
                    err.append(D_p * px + E_p * py + F_p - ry)
                return err

            # 4. 最適化の実行
            opt_res = least_squares(residuals, p0, method='lm')
            Sx_opt, Sy_opt, theta_opt, Tx_opt, Ty_opt = opt_res.x

            # 5. アフィン6要素に再展開して返却
            cos_t = math.cos(theta_opt)
            sin_t = math.sin(theta_opt)
            A = Sx_opt * cos_t
            B = Sx_opt * sin_t
            C = Tx_opt
            D = -Sy_opt * sin_t
            E = Sy_opt * cos_t
            F = Ty_opt

            return (float(A), float(B), float(C), float(D), float(E), float(F))

        except Exception as e:
            import traceback
            from qgis.core import QgsMessageLog, Qgis
            
            # デバッグ用の詳細情報を構築
            debug_msg = (
                f"=== 3点/4点変換エラー詳細 ===\n"
                f"local_points: {local_points}\n"
                f"real_points: {real_points}\n"
                f"Exception: {str(e)}\n"
                f"Traceback:\n{traceback.format_exc()}\n"
                f"============================="
            )
            
            # QGISのメッセージログとPythonコンソールの両方に出力
            QgsMessageLog.logMessage(debug_msg, "PointerGeocoding", Qgis.Critical)
            print(debug_msg)
            
            # 最適化に失敗した場合のフォールバック（通常の最小二乗アフィン）
            if 'aff_res' in locals():
                return (float(A0), float(B0), float(C0), float(D0), float(E0), float(F0))
            else:
                raise TransformError(f"座標変換パラメータの算出に失敗しました。\n詳細: {str(e)}") from e


# 打刻点レイヤの全フィーチャを測地座標系に変換し、CSVファイルへ出力。
def export_points_to_csv(
    point_layer: QgsVectorLayer,
    filepath: str,
    encoding: str = "utf-8-sig",
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
    :return: Tuple of (success, message).
    :rtype: Tuple[bool, str]
    """
    if not point_layer or not point_layer.isValid():
        return False, "打刻点レイヤが無効です。"

    features_data = list(point_layer.getFeatures())
    total_count = len(features_data)

    if total_count == 0:
        return False, "出力対象の打刻点が存在しません。"

    # Check for uncalculated (NULL) real_x / real_y
    uncalculated_count = 0
    for feat in features_data:
        mx = feat["real_x"] if feat["real_x"] is not None else feat["canvas_x"]
        my = feat["real_y"] if feat["real_y"] is not None else feat["canvas_y"]
        if mx is None or my is None:
            uncalculated_count += 1

    if uncalculated_count > 0:
        return False, f"実座標が未取得の打刻点が {uncalculated_count} 件存在します。"

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
        return False, f"CSVファイルの書き込み中にエラーが発生しました:\n{e}"