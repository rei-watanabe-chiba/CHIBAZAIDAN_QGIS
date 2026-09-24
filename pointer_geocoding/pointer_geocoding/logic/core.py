"""
/***************************************************************************
 PointerGeocoding Plugin - Core Business Logic & Coordinate Adapter Module
 ***************************************************************************/
"""

import math
import re
from enum import Enum
from typing import Optional, Tuple, Dict, Any, List

from qgis.core import (
    QgsVectorLayer,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    NULL,
)
from qgis.PyQt.QtCore import QVariant


# =============================================================================
# 0. Excavation Type / Attribute Type Enums
# =============================================================================
#
# 出土形態・属性記号の文字列比較を型安全なEnumに統一する。
# GeoPackage属性・CSV出力・QGIS式エンジン(CASE WHEN等)は引き続き文字列を要求する
# ため、`str`を継承したEnum(いわゆる StrEnum 相当)として定義する。これにより
# `ExcavationType.GRID == "グリッド"` は Trueとなり、既存の文字列ベースの
# データ形式・比較コードとの互換性を壊さない。実際の値の読み書きには明示的に
# `.value` を用いる（feat.setAttribute等、QGIS側APIへ渡す箇所での曖昧さを避けるため）。


class ExcavationType(str, Enum):
    """出土形態: 'グリッド' または '遺構'。main_dock_constants.UILabels.EXCAVATION_OPTIONS と同じ値集合。"""

    GRID = "グリッド"
    FEATURE = "遺構"


class AttributeType(str, Enum):
    """属性記号: 'S' / 'P' / 'C' / 'SP'。main_dock_constants.UILabels.ATTRIBUTE_OPTIONS と同じ値集合。"""

    S = "S"
    P = "P"
    C = "C"
    SP = "SP"


# =============================================================================
# 1. Coordinate System Adapters
# =============================================================================

# 数学/キャンバス座標(X:東西, Y:南北)を、測量座標(X:南北, Y:東西)に変換する。
def to_survey_coords(math_x: float, math_y: float) -> Tuple[float, float]:
    """Convert standard mathematical/canvas coordinates to survey coordinates.

    Mathematical/QGIS Canvas System:
        math_x: East-West axis (positive East)
        math_y: North-South axis (positive North)

    Survey System (Public Survey Coordinate System in Japan):
        survey_x: North-South axis (positive North)
        survey_y: East-West axis (positive East)

    :param math_x: Coordinate along East-West axis (Canvas X).
    :type math_x: float
    :param math_y: Coordinate along North-South axis (Canvas Y).
    :type math_y: float
    :return: Tuple of (survey_x, survey_y).
    :rtype: Tuple[float, float]
    """
    survey_x = float(math_y)
    survey_y = float(math_x)
    return survey_x, survey_y


# 測量座標(X:南北, Y:東西)を、数学/キャンバス座標(X:東西, Y:南北)に変換する。
def from_survey_coords(survey_x: float, survey_y: float) -> Tuple[float, float]:
    """Convert survey coordinates to standard mathematical/canvas coordinates.

    Survey System (Public Survey Coordinate System in Japan):
        survey_x: North-South axis (positive North)
        survey_y: East-West axis (positive East)

    Mathematical/QGIS Canvas System:
        math_x: East-West axis (positive East, Canvas X)
        math_y: North-South axis (positive North, Canvas Y)

    :param survey_x: Coordinate along North-South axis (Survey X).
    :type survey_x: float
    :param survey_y: Coordinate along East-West axis (Survey Y).
    :type survey_y: float
    :return: Tuple of (math_x, math_y).
    :rtype: Tuple[float, float]
    """
    math_x = float(survey_y)
    math_y = float(survey_x)
    return math_x, math_y


# =============================================================================
# 2. Point Layer Geometry & Attribute Synchronization Logic
# =============================================================================

# 更新リストを受け取り、編集セッション開始からフィールド名解決・属性/ジオメトリ変更・コミットまでを一括実行する。
def batch_update_attributes(
    layer: QgsVectorLayer,
    updates: List[Tuple[int, Dict[str, Any]]],
    geometries: Optional[Dict[int, QgsGeometry]] = None,
) -> int:
    """Encapsulate the startEditing -> field index resolution -> changeAttributeValue
    (optionally also changeGeometry) -> commitChanges boilerplate shared by callers
    that batch-update layer attributes (and, optionally, geometries) in a single
    edit session.

    Field name -> index resolution is cached per field name (equivalent to callers
    that previously resolved indices once before the loop). If a field name does
    not exist on the layer (indexFromName returns -1), that particular attribute
    write is silently skipped, matching prior per-site behavior of guarding each
    changeAttributeValue call with an `if idx != -1` check.

    :param layer: Target vector layer to edit.
    :type layer: QgsVectorLayer
    :param updates: List of (feature_id, {field_name: value}) pairs to apply.
    :type updates: List[Tuple[int, Dict[str, Any]]]
    :param geometries: Optional mapping of feature_id -> new QgsGeometry to apply
        within the same edit session, for callers that also update geometry.
    :type geometries: Optional[Dict[int, QgsGeometry]]
    :return: Number of (feature_id, updates) entries processed.
    :rtype: int
    """
    if not layer or not layer.isValid():
        return 0

    layer.startEditing()
    field_idx_cache: Dict[str, int] = {}
    processed_count = 0

    for fid, attr_values in updates:
        for field_name, value in attr_values.items():
            if field_name not in field_idx_cache:
                field_idx_cache[field_name] = layer.fields().indexFromName(field_name)
            idx = field_idx_cache[field_name]
            if idx != -1:
                layer.changeAttributeValue(fid, idx, value)
        if geometries and fid in geometries:
            layer.changeGeometry(fid, geometries[fid])
        processed_count += 1

    layer.commitChanges()
    return processed_count


# アフィン変換パラメータを用い、対象図面名に一致する点群の実座標・キャンバス座標・ジオメトリを一括更新する。
def update_point_layer_geometry(
    point_layer: QgsVectorLayer,
    affine_params: Tuple[float, float, float, float, float, float],
    drawing_name: str = "",
) -> int:
    """Batch update real/canvas coordinates and geometries for points matching drawing_name
    using calculated Affine transformation parameters in standard mathematical coordinates.

    Formula:
        calc_math_x = A * px + B * py + C  (East-West)
        calc_math_y = D * px + E * py + F  (North-South)

    :param point_layer: Target vector layer containing digitized points.
    :type point_layer: QgsVectorLayer
    :param affine_params: Affine parameters tuple (A, B, C, D, E, F).
    :type affine_params: Tuple[float, float, float, float, float, float]
    :param drawing_name: Target drawing name to filter which points to transform. If empty, transforms all.
    :type drawing_name: str
    :return: Number of updated features.
    :rtype: int
    """
    if not point_layer or not point_layer.isValid():
        return 0

    A, B, C, D, E, F = affine_params
    has_drawing_col = "drawing_name" in point_layer.fields().names()

    updates: List[Tuple[int, Dict[str, Any]]] = []
    geometries: Dict[int, QgsGeometry] = {}

    for feat in point_layer.getFeatures():
        if drawing_name and has_drawing_col:
            feat_drawing = safe_get_str(feat, "drawing_name")
            if feat_drawing != drawing_name:
                continue

        # Prefer pixel coordinates, fallback to existing canvas coordinates
        px = feat["pixel_x"] if "pixel_x" in feat.fields().names() and feat["pixel_x"] is not None else feat["canvas_x"]
        py = feat["pixel_y"] if "pixel_y" in feat.fields().names() and feat["pixel_y"] is not None else feat["canvas_y"]

        if px is None or py is None:
            continue

        try:
            px_val = float(px)
            py_val = float(py)
        except (ValueError, TypeError):
            continue

        calc_math_x = A * px_val + B * py_val + C
        calc_math_y = D * px_val + E * py_val + F

        # In standard mathematical coordinates, real_x=math_x (East), real_y=math_y (North)
        updates.append((
            feat.id(),
            {
                "canvas_x": calc_math_x,
                "canvas_y": calc_math_y,
                "real_x": calc_math_x,
                "real_y": calc_math_y,
            },
        ))
        geometries[feat.id()] = QgsGeometry.fromPointXY(QgsPointXY(calc_math_x, calc_math_y))

    updated_count = batch_update_attributes(point_layer, updates, geometries=geometries)
    return updated_count


# =============================================================================
# 3. Residual Evaluation Logic
# =============================================================================

# アフィンパラメータ(または基準点データ)から、画像の回転角(度)と縦横比変化(%)を算出する。
def evaluate_residuals(
    ref_points_data_or_params: Any,
    affine_params: Optional[Tuple[float, float, float, float, float, float]] = None,
) -> Tuple[float, float]:
    """Calculate overall transformation indicators: image rotation angle (degrees) and aspect ratio change (%).

    :param ref_points_data_or_params: List of reference point dicts, or affine parameters tuple directly.
    :type ref_points_data_or_params: Any
    :param affine_params: Affine parameters tuple (A, B, C, D, E, F) if first argument is ref_points_data.
    :type affine_params: Optional[Tuple[float, float, float, float, float, float]]
    :return: Tuple of (rotation_deg, aspect_ratio_pct).
             rotation_deg: Image rotation angle in degrees computed via math.atan2(D, A).
             aspect_ratio_pct: Aspect ratio change percentage (Sy / Sx) * 100.
    :rtype: Tuple[float, float]
    """
    if affine_params is not None:
        params = affine_params
    elif isinstance(ref_points_data_or_params, (tuple, list)) and len(ref_points_data_or_params) == 6:
        params = tuple(ref_points_data_or_params)
    else:
        raise ValueError("Valid affine parameters (A, B, C, D, E, F) must be provided.")

    A, B, C, D, E, F = params

    # rotation_deg: image rotation angle in degrees (QGIS world file specification: X-axis rotation)
    rotation_deg = math.degrees(math.atan2(D, A))

    # aspect_ratio_pct: aspect ratio change percentage (Sy / Sx) * 100
    # Sx: scale in X direction, Sy: scale in Y direction
    sx = math.hypot(A, D)
    sy = math.hypot(B, E)
    aspect_ratio_pct = (sy / sx * 100.0) if sx > 1e-9 else 100.0

    return rotation_deg, aspect_ratio_pct


# =============================================================================
# 4. Point Number & Duplicate Verification Logic
# =============================================================================

# 出土形態・遺構名・点名・枝番の組み合わせが同一の点が既に存在するかを図面横断で判定する。
def check_point_duplicate(
    point_layer: QgsVectorLayer,
    excavation_type: str,
    feature_name: str,
    point_name: str,
    branch_no: str,
    drawing_name: str = "",
    exclude_feature_id: Optional[int] = None,
) -> bool:
    """Check whether a point with the same identification attributes already exists.

    Duplicate detection is global across drawings: a point is considered a
    duplicate whenever its 出土形態(+遺構名)・点名・枝番 combination matches,
    regardless of which 対象図面 it belongs to. ``drawing_name`` is retained
    as a parameter only for call-signature compatibility with
    build_point_ident()/check_duplicate_and_build_message() and is not used
    to filter candidates here.

    :param point_layer: Vector layer containing digitized points.
    :type point_layer: QgsVectorLayer
    :param excavation_type: ExcavationType.GRID.value ('グリッド') or ExcavationType.FEATURE.value ('遺構').
    :type excavation_type: str
    :param feature_name: Feature name string.
    :type feature_name: str
    :param point_name: Point number string.
    :type point_name: str
    :param branch_no: Branch number string.
    :type branch_no: str
    :param drawing_name: Unused for filtering; kept for signature compatibility.
    :type drawing_name: str
    :param exclude_feature_id: When set, the feature with this id is skipped
        during the scan (used by existing-point number correction, so a point being
        renumbered is not treated as a duplicate of itself).
    :type exclude_feature_id: Optional[int]
    :return: True if duplicate found, False otherwise.
    :rtype: bool
    """
    if not point_layer or not point_layer.isValid():
        return False

    for feat in point_layer.getFeatures():
        if exclude_feature_id is not None and feat.id() == exclude_feature_id:
            continue

        f_type = safe_get_str(feat, "excavation_type")
        f_feat = safe_get_str(feat, "feature_name")
        f_pname = safe_get_str(feat, "point_name")
        f_branch = safe_get_str(feat, "branch_no")

        if excavation_type == ExcavationType.GRID.value:
            if f_type == ExcavationType.GRID.value and f_pname == point_name and f_branch == branch_no:
                return True
        else:
            if (
                f_type == ExcavationType.FEATURE.value
                and f_feat == feature_name
                and f_pname == point_name
                and f_branch == branch_no
            ):
                return True
    return False


# 重複判定用のキー(出土形態[+遺構名]・点名・枝番)を返す。check_point_duplicate と同一の判定規則。
def point_duplicate_key(
    excavation_type: str,
    feature_name: str,
    point_name: str,
    branch_no: str,
) -> Optional[Tuple[str, str, str, str]]:
    """Return the duplicate-detection key used by check_point_duplicate().

    Grid points ignore feature_name (key uses ""); feature points include it.
    Returns None when excavation_type is neither GRID nor FEATURE (such a
    point never matches any duplicate query in check_point_duplicate()).
    """
    if excavation_type == ExcavationType.GRID.value:
        return (ExcavationType.GRID.value, "", point_name, branch_no)
    if excavation_type == ExcavationType.FEATURE.value:
        return (ExcavationType.FEATURE.value, feature_name, point_name, branch_no)
    return None


# 出土形態・遺構名・点名・枝番(・図面名)から、重複エラー等で表示する識別文字列を組み立てる。
def build_point_ident(
    excavation_type: str,
    feature_name: str,
    point_name: str,
    branch_no: str,
    drawing_name: str = "",
) -> str:
    """Build a human-readable identifier string for a digitized point.

    Shared by both the new-point digitizing flow and existing-point editing
    as the single source of truth for the identifier shown in duplicate
    errors.

    The identifier's optional drawing-name suffix is shown as a trailing
    "図面:..." line (not a leading "[drawing_name]" prefix) since callers
    display this identifier inline in the 点情報パネル status band (as a
    tooltip) rather than in a QMessageBox. Overlong drawing names (>15
    characters) are truncated with a trailing "..." to keep the message
    compact within the panel's ~300px width.

    :param excavation_type: ExcavationType.GRID.value or ExcavationType.FEATURE.value.
    :type excavation_type: str
    :param feature_name: Feature name string (used only when excavation_type is FEATURE).
    :type feature_name: str
    :param point_name: Point number string.
    :type point_name: str
    :param branch_no: Branch number string.
    :type branch_no: str
    :param drawing_name: Optional target drawing name string.
    :type drawing_name: str
    :return: Formatted identifier, e.g. "SK01-5 (a)\\n図面:plan_01".
    :rtype: str
    """
    ident = (
        f"{feature_name}-{point_name}"
        if excavation_type == ExcavationType.FEATURE.value
        else f"{ExcavationType.GRID.value}-{point_name}"
    )
    if branch_no:
        ident += f" ({branch_no})"
    if drawing_name:
        display_drawing = drawing_name if len(drawing_name) <= 15 else f"{drawing_name[:15]}..."
        ident = f"{ident}\n図面:{display_drawing}"
    return ident


# 重複チェックを行い、重複していればbuild_point_identで整形した識別文字列を返す(check_point_duplicate+build_point_identの合成)。
def check_duplicate_and_build_message(
    point_layer: QgsVectorLayer,
    excavation_type: str,
    feature_name: str,
    point_name: str,
    branch_no: str,
    drawing_name: str = "",
    exclude_feature_id: Optional[int] = None,
) -> Optional[str]:
    """Check for a duplicate point and, if found, return its formatted identifier.

    Thin combination of check_point_duplicate() + build_point_ident().
    Real-time duplicate checks call check_point_duplicate()/
    build_point_ident() directly rather than through this wrapper, but it is
    kept as a convenience API for any caller needing the combined
    check+message behavior in one call.

    :return: Formatted identifier string if a duplicate exists, otherwise None.
    :rtype: Optional[str]
    """
    if check_point_duplicate(
        point_layer,
        excavation_type,
        feature_name,
        point_name,
        branch_no,
        drawing_name,
        exclude_feature_id=exclude_feature_id,
    ):
        return build_point_ident(excavation_type, feature_name, point_name, branch_no, drawing_name)
    return None


# 同一グループ内で最も新しく打刻された点(point_id最大)のpoint_nameから採番用の数値部を取り出し、次の点番号を決定する。
def get_next_point_number(
    point_layer: QgsVectorLayer,
    excavation_type: str,
    feature_name: str,
) -> int:
    """Determine the next point number by following the most recently digitized point.

    Among the features matching the active excavation_type/feature_name
    group, finds the feature with the maximum point_id (auto-incrementing
    primary key, i.e. the most recently digitized point in that group),
    extracts the leading numeric "body" portion of its point_name (e.g. '5'
    from a branch-suffixed '5-a'), and returns that body number + 1. This
    follows the most recently digitized point (rather than the max of all
    numeric point_name values) so that manual edits to older points do not
    disturb the auto-numbering sequence.

    SP属性(AttributeType.SP)の点は自由入力(手入力)の対象であり、
    数値の自動採番シーケンスには含めない。SP属性の点が直前の打刻であっても、
    その point_name の数値プレフィックスを "body_num" として引き継がないよう、
    S/P/C用の探索対象からSP属性のフィーチャを除外する。

    :param point_layer: Vector layer containing digitized points.
    :type point_layer: QgsVectorLayer
    :param excavation_type: ExcavationType.GRID.value ('グリッド') or ExcavationType.FEATURE.value ('遺構').
    :type excavation_type: str
    :param feature_name: Feature name string (used when excavation_type == ExcavationType.FEATURE.value).
    :type feature_name: str
    :return: Next point number (starts at 1 when no matching feature exists, or when the
        latest matching feature's point_name has no leading numeric body).
    :rtype: int
    """
    if not point_layer or not point_layer.isValid():
        return 1

    max_point_id = None
    latest_point_name = None
    for feat in point_layer.getFeatures():
        ex_type = safe_get_str(feat, "excavation_type")
        if excavation_type == ExcavationType.GRID.value:
            if ex_type != ExcavationType.GRID.value:
                continue
        else:
            f_name = safe_get_str(feat, "feature_name")
            if ex_type != ExcavationType.FEATURE.value or f_name != feature_name:
                continue

        # SP属性の点は自動採番(S/P/C)の対象外なので除外する。
        if safe_get_str(feat, "attribute_type") == AttributeType.SP.value:
            continue

        pid = feat["point_id"]
        if pid is None or not isinstance(pid, int):
            continue
        if max_point_id is None or pid > max_point_id:
            max_point_id = pid
            latest_point_name = feat["point_name"]

    if max_point_id is None:
        return 1

    pname = "" if latest_point_name is None else str(latest_point_name)
    match = re.match(r"^(\d+)", pname)
    body_num = int(match.group(1)) if match else 0
    return body_num + 1


# クリックで得た座標・属性値・ピクセル座標から、レイヤーに追加可能な打刻済みフィーチャを構築する。
def build_digitized_feature(
    point_layer: QgsVectorLayer,
    next_id: int,
    map_point: QgsPointXY,
    attributes: Dict[str, Any],
    pixel_coords: Optional[Tuple[float, float]] = None,
) -> QgsFeature:
    """Construct a complete QgsFeature ready for insertion into the points layer.

    Internal coordinates are set in standard mathematical coordinates:
        canvas_x = map_point.x()
        canvas_y = map_point.y()
        real_x   = map_point.x()
        real_y   = map_point.y()

    :param point_layer: Target vector layer.
    :type point_layer: QgsVectorLayer
    :param next_id: Primary key point_id integer.
    :type next_id: int
    :param map_point: Canvas coordinate point (standard mathematical coordinates).
    :type map_point: QgsPointXY
    :param attributes: Attribute dictionary (drawing_name, excavation_type, feature_name, color_code, attribute_type, point_name, branch_no).
    :type attributes: Dict[str, Any]
    :param pixel_coords: Optional (pixel_x, pixel_y) local drawing coordinates.
    :type pixel_coords: Optional[Tuple[float, float]]
    :return: Constructed QgsFeature.
    :rtype: QgsFeature
    """
    feat = QgsFeature(point_layer.fields())
    feat.setGeometry(QgsGeometry.fromPointXY(map_point))
    feat.setAttribute("point_id", next_id)

    field_names = point_layer.fields().names()
    if "drawing_name" in field_names:
        feat.setAttribute("drawing_name", attributes.get("drawing_name", ""))

    feat.setAttribute("excavation_type", attributes.get("excavation_type", ExcavationType.GRID.value))
    feat.setAttribute("feature_name", attributes.get("feature_name", ""))
    feat.setAttribute("color_code", attributes.get("color_code", ""))
    feat.setAttribute("attribute_type", attributes.get("attribute_type", AttributeType.S.value))
    feat.setAttribute("point_name", str(attributes.get("point_name", "1")))
    feat.setAttribute("branch_no", str(attributes.get("branch_no", "")))

    # Mathematical coordinates
    feat.setAttribute("canvas_x", map_point.x())
    feat.setAttribute("canvas_y", map_point.y())
    feat.setAttribute("real_x", map_point.x())
    feat.setAttribute("real_y", map_point.y())

    if pixel_coords and "pixel_x" in field_names and "pixel_y" in field_names:
        feat.setAttribute("pixel_x", pixel_coords[0])
        feat.setAttribute("pixel_y", pixel_coords[1])

    return feat


# レイヤー全体をスキャンし、既存point_idの最大値+1を次の主キー候補として返す。
def get_next_point_id(point_layer: QgsVectorLayer) -> int:
    """Determine the next available integer point_id (primary key) across the whole layer.

    Scans all features in the layer and returns one greater than the maximum
    existing point_id. Features whose point_id is None or not an int are
    ignored (same behaviour as the original inline logic in
    Tab2DigitizingMixin._on_canvas_clicked).

    :param point_layer: Vector layer containing digitized points.
    :type point_layer: QgsVectorLayer
    :return: Next point_id (starts at 1 if the layer has no valid point_id values).
    :rtype: int
    """
    max_id = 0
    for f in point_layer.getFeatures():
        pid = f["point_id"]
        if pid is not None and isinstance(pid, int):
            max_id = max(max_id, pid)
    return max_id + 1


# 編集セッションを開始し、指定フィーチャを1件追加・コミットする(再描画はコミット時のネイティブなシグナルに委ねる)。
def insert_feature_to_layer(point_layer: QgsVectorLayer, feature: QgsFeature) -> bool:
    """Insert a single feature into a vector layer via an edit session.

    Call sequence: startEditing -> addFeatures -> commitChanges (repaint is left
    to the native signals emitted on commit). No additional success/failure
    handling is introduced beyond what existed before.

    :param point_layer: Target vector layer.
    :type point_layer: QgsVectorLayer
    :param feature: Feature to insert.
    :type feature: QgsFeature
    :return: True (the original inline code did not check/return a success value;
        this return is provided for API completeness and is not currently
        relied upon by callers).
    :rtype: bool
    """
    point_layer.startEditing()
    point_layer.addFeatures([feature])
    point_layer.commitChanges()
    return True


# =============================================================================
# 5. Excel-style Column Letter Conversion Utilities
# =============================================================================

# 1始まりの数値インデックスを、Excel形式の列アルファベット文字列に変換する。
def to_excel_column(n: int) -> str:
    """Convert a 1-based index into an Excel-style column letter (1 -> 'A', 26 -> 'Z', 27 -> 'AA', 79 -> 'CA').

    :param n: 1-based column index.
    :type n: int
    :return: Alphabetical column representation.
    :rtype: str
    """
    if n <= 0:
        return ""
    result = []
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        result.append(chr(65 + remainder))
    return "".join(reversed(result))


# Excel形式の列アルファベット文字列を、1始まりの数値インデックスに変換する。
def from_excel_column(col_str: str) -> int:
    """Convert Excel-style column alphabet to 1-based index (e.g. 'A'->1, 'Z'->26, 'AA'->27).

    :param col_str: Column letter string.
    :type col_str: str
    :return: 1-based index, or 0 if invalid.
    :rtype: int
    """
    clean_str = col_str.strip().upper()
    if not clean_str or not clean_str.isalpha():
        return 0
    num = 0
    for ch in clean_str:
        num = num * 26 + (ord(ch) - ord("A") + 1)
    return num


# =============================================================================
# 6. Affine Inverse Adapter (map coordinates -> source drawing pixel coordinates)
# =============================================================================

# アフィン変換の逆変換を用い、マップ座標(数学座標)から元図面上のピクセル座標を逆算する。
def pixel_from_affine(
    affine_params: Optional[Tuple[float, float, float, float, float, float]],
    map_point: QgsPointXY,
) -> Tuple[float, float]:
    """Invert the forward affine transform to recover local drawing pixel coordinates.

    Given the forward transform (pixel -> math coordinates):
        math_x = A * px + B * py + C
        math_y = D * px + E * py + F

    this returns (px, py) for a given (math_x, math_y) = map_point. Used when
    digitizing a new point on an already-georeferenced image, so the point can
    be traced back to its position on the original source drawing.

    :param affine_params: Affine parameters tuple (A, B, C, D, E, F), or None if
        the target drawing has no recorded transform yet.
    :type affine_params: Optional[Tuple[float, float, float, float, float, float]]
    :param map_point: Point in standard mathematical/canvas coordinates.
    :type map_point: QgsPointXY
    :return: Tuple of (pixel_x, pixel_y). (0.0, 0.0) if affine_params is None or singular.
    :rtype: Tuple[float, float]
    """
    if not affine_params:
        return 0.0, 0.0

    A, B, C, D, E, F = affine_params
    det = A * E - B * D
    if abs(det) <= 1e-10:
        return 0.0, 0.0

    pixel_x = (E * (map_point.x() - C) - B * (map_point.y() - F)) / det
    pixel_y = (-D * (map_point.x() - C) + A * (map_point.y() - F)) / det
    return pixel_x, pixel_y


# (source, mtime) -> (width, height) のキャッシュ。クリックごとのファイルオープンを避ける。
_SOURCE_SIZE_CACHE: Dict[Tuple[str, Optional[float]], Tuple[int, int]] = {}


# ラスタレイヤの元画像のピクセル寸法(幅,高さ)を返す。回転ワールドファイルではQGISのレイヤ寸法が回転後になるため使わない。
def get_source_image_size(raster_layer: Any) -> Optional[Tuple[int, int]]:
    """Return the pixel size (width, height) of the original source image.

    Priority: GDAL RasterXSize/YSize -> QImageReader size -> layer width()/height().
    Results are cached by (source path, file mtime).

    :return: (width, height), or None if no size could be determined.
    """
    try:
        source = raster_layer.source()
    except Exception:
        source = ""
    path = source.split("|", 1)[0] if source else ""

    mtime: Optional[float] = None
    if path:
        try:
            import os
            mtime = os.path.getmtime(path)
        except Exception:
            mtime = None

    key = (source, mtime)
    if source and key in _SOURCE_SIZE_CACHE:
        return _SOURCE_SIZE_CACHE[key]

    size: Optional[Tuple[int, int]] = None

    if path:
        try:
            import warnings
            from osgeo import gdal
            with warnings.catch_warnings():
                # UseExceptions未指定のFutureWarningを抑止(グローバル設定は変更しない)
                warnings.simplefilter("ignore")
                ds = gdal.Open(path)
            if ds is not None:
                try:
                    w, h = int(ds.RasterXSize), int(ds.RasterYSize)
                finally:
                    ds = None
                if w > 0 and h > 0:
                    size = (w, h)
        except Exception:
            size = None

    if size is None and path:
        try:
            from qgis.PyQt.QtGui import QImageReader
            qsize = QImageReader(path).size()
            if qsize.isValid() and qsize.width() > 0 and qsize.height() > 0:
                size = (qsize.width(), qsize.height())
        except Exception:
            size = None

    if size is not None:
        if source:
            _SOURCE_SIZE_CACHE[key] = size
        return size

    try:
        return int(raster_layer.width()), int(raster_layer.height())
    except Exception:
        return None


# =============================================================================
# 7. QgsFeature Attribute Access Helpers (NULL-safe type conversion)
# =============================================================================

# QgsFeatureの属性値をNULL・フィールド欠如に配慮しつつ、トリム済み文字列として安全に取得する。
def safe_get_str(feat: QgsFeature, field_name: str, default: str = "") -> str:
    """Safely read a QgsFeature attribute as a trimmed string, guarding NULL/missing values.

    Consolidates the previously duplicated `str(feat[field_name] or "").strip()` pattern
    found across this module, tab1_georef_mixin.py and tab2_digitizing_mixin.py. A missing
    field (KeyError -- e.g. an optional column such as "drawing_name" that does not exist
    on a given layer schema) falls back to `default`, matching prior call-site behaviour of
    guarding such lookups with a `field_name in layer.fields().names()` check before ever
    reading the attribute.

    :param feat: Source feature.
    :type feat: QgsFeature
    :param field_name: Attribute field name to read.
    :type field_name: str
    :param default: Fallback value used when the attribute is NULL/None or the field does
        not exist on the feature.
    :type default: str
    :return: Trimmed string value.
    :rtype: str
    """
    try:
        value = feat[field_name]
    except KeyError:
        return default
    if value is None or value == NULL:
        return default
    return str(value).strip()


# QgsFeatureの属性値をNULL・フィールド欠如・変換失敗に配慮しつつ、float型として安全に取得する。
def safe_get_float(feat: QgsFeature, field_name: str, default: float = 0.0) -> float:
    """Safely read a QgsFeature attribute as a float, guarding NULL/missing/invalid values.

    :param feat: Source feature.
    :type feat: QgsFeature
    :param field_name: Attribute field name to read.
    :type field_name: str
    :param default: Fallback value used when the attribute is NULL/None, the field does not
        exist on the feature, or the value cannot be converted to float.
    :type default: float
    :return: Converted float value.
    :rtype: float
    """
    try:
        value = feat[field_name]
    except KeyError:
        return default
    if value is None or value == NULL:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


# QgsFeatureの属性値をNULL・フィールド欠如・変換失敗に配慮しつつ、int型として安全に取得する。
def safe_get_int(feat: QgsFeature, field_name: str, default: int = 0) -> int:
    """Safely read a QgsFeature attribute as an int, guarding NULL/missing/invalid values.

    :param feat: Source feature.
    :type feat: QgsFeature
    :param field_name: Attribute field name to read.
    :type field_name: str
    :param default: Fallback value used when the attribute is NULL/None, the field does not
        exist on the feature, or the value cannot be converted to int.
    :type default: int
    :return: Converted int value.
    :rtype: int
    """
    try:
        value = feat[field_name]
    except KeyError:
        return default
    if value is None or value == NULL:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default
