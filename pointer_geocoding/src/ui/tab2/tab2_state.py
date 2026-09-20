"""
/***************************************************************************
 PointerGeocoding Plugin - Tab 2 State Model
 ***************************************************************************/
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from qgis.PyQt.QtGui import QColor

@dataclass
class Tab2State:
    """Tab 2 (遺物点作成) の状態を保持するデータクラス"""
    
    # 1. UIモード管理
    current_mode: str = "new"  # "new" or "edit"
    autonum_mode: str = "auto" # "auto" or "release"
    
    # 2. 選択・編集状態
    selected_edit_point_id: Optional[int] = None
    selected_point_data: Optional[Dict[str, Any]] = None
    has_digitized_with_branch: bool = False
    
    # 3. 制御フラグ
    suppress_realtime_commit: bool = False
    point_info_has_error: bool = False
    is_out_of_bounds: bool = False
    
    # 4. キャッシュ・表示データ
    current_display_filters: Dict[str, Any] = field(default_factory=dict)
    point_info_summary: Dict[str, str] = field(
        default_factory=lambda: {"group": "-", "pointname": "-", "coords": "-"}
    )
    
    # 5. 遺構カラー・リストキャッシュ
    current_feature_color: QColor = field(default_factory=lambda: QColor("#FF5722"))
    feature_name_list: List[str] = field(default_factory=list)

    def reset_selection(self) -> None:
        """既存点の選択状態と関連するエラー・キャッシュをリセットする"""
        self.selected_edit_point_id = None
        self.selected_point_data = None
        self.is_out_of_bounds = False
        self.point_info_has_error = False
        self.has_digitized_with_branch = False