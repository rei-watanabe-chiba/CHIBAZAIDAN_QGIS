"""
/***************************************************************************
 PointerGeocoding Plugin - Dialogs Logic (Controller)
 ***************************************************************************/

スタンドアロンの各種ダイアログ（GridInputDialog, FeatureManageDialog, PointNameEntryDialog, PointEditDialog）
のUIイベントを受容し、ビジネスロジック（グリッド座標検証、点名重複チェック等）を処理するController層です。
"""
import re
from typing import Dict, Any, Optional, Tuple, Callable

from qgis.PyQt.QtCore import QObject

from ..logic.core import check_point_duplicate, build_point_ident, to_survey_coords
from ..ui.constants import UILabels, UIMessages
from ..ui.core.validators import RequiredValidator, DuplicateValidator


class GridInputLogic(QObject):
    def __init__(self, layer_manager, existing_names, parent=None):
        super().__init__(parent)
        self.layer_manager = layer_manager
        self.existing_names = existing_names

    def validate_and_lookup(self, gx: int, gy: str, sub_grid: int) -> Tuple[bool, str, str, Optional[float], Optional[float]]:
        """グリッド座標をLayerManagerのキャッシュに照会して検証・実座標変換する"""
        sub_grid_str = f"{sub_grid:02d}"
        grid_name = f"{gx}-{gy}-{sub_grid_str}"

        if not gy:
            return False, "大グリッドＹを入力してください (英字)。", "info", None, None

        if grid_name in self.existing_names:
            return False, UILabels.ERR_GRID_DUPLICATE.format(grid=grid_name), "error", None, None

        unique_gy = getattr(self.layer_manager, "unique_gy", set())
        if unique_gy and gy not in unique_gy:
            return False, UILabels.ERR_GY_NOT_FOUND.format(gy=gy), "error", None, None

        grid_data = getattr(self.layer_manager, "grid_data", {})
        key = (gx, gy, sub_grid_str)

        if key in grid_data:
            math_x, math_y = grid_data[key]
            survey_x, survey_y = to_survey_coords(math_x, math_y)
            msg = UILabels.STATUS_GRID_FOUND.format(grid=grid_name, rx=survey_x, ry=survey_y)
            return True, msg, "success", float(math_x), float(math_y)
        else:
            return False, UILabels.ERR_GRID_NOT_FOUND.format(grid=grid_name), "error", None, None


class PointNameEntryLogic(QObject):
    def __init__(self, point_layer, excavation_type, feature_name, drawing_name, is_sp_attribute, parent=None):
        super().__init__(parent)
        self.point_layer = point_layer
        self.excavation_type = excavation_type
        self.feature_name = feature_name
        self.drawing_name = drawing_name
        self.is_sp_attribute = is_sp_attribute

    def validate_inputs(self, point_name: str, branch_no: str) -> Tuple[bool, str]:
        """SP属性の必須チェックと、全属性に対する重複チェックを行う"""
        if self.is_sp_attribute:
            req_result = RequiredValidator(UIMessages.ERR_POINT_NAME_REQUIRED).validate(point_name)
            if not req_result.is_valid:
                return False, req_result.message

        ident = build_point_ident(self.excavation_type, self.feature_name, point_name, branch_no, self.drawing_name)
        dup_result = DuplicateValidator(
            lambda v: check_point_duplicate(
                self.point_layer, self.excavation_type, self.feature_name, v, branch_no, self.drawing_name
            ),
            message=UIMessages.ERR_POINT_NAME_DUPLICATE.format(ident=ident),
        ).validate(point_name)

        if not dup_result.is_valid:
            return False, dup_result.message

        return True, ""


class FeatureManageLogic(QObject):
    def __init__(self, feature_colors, parent=None):
        super().__init__(parent)
        self.feature_colors = feature_colors

    def validate_feature_name(self, text: str, mode: str, current_feature: str) -> Tuple[bool, str, str]:
        """遺構名の入力検証と重複チェックを行う"""
        if not text:
            return False, UIMessages.ERR_NEW_FEATURE_REQUIRED, "error"

        if text in (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成")):
            return False, f"エラー: '{text}' は遺構名として使用できません。", "error"

        if mode == "new":
            if text in self.feature_colors:
                return False, f"エラー: 遺構名 '{text}' は既に登録されています。", "error"
            return True, UILabels.STATUS_MSG_NEW_FEATURE.format(feature=text), "info"
        else:
            if text in self.feature_colors and text != current_feature:
                return False, f"エラー: 遺構名 '{text}' は既に登録されています。", "error"
            return True, UILabels.STATUS_MSG_EDIT_FEATURE.format(feature=text), "success"