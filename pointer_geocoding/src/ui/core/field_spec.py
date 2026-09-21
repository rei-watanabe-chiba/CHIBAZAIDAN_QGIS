"""
/***************************************************************************
 PointerGeocoding Plugin - CoreUI field_spec (declaration-only data types)
 ***************************************************************************/

T-0045: pure dataclasses describing "what a panel looks like" (widget kind /
label / choices / visibility / event-hook name). No PyQt widget is ever
constructed in this module -- that is CoreUIBuilder's job (builder.py). This
mirrors the "宣言のみ" design described in .claude/state/v2-coreui-plan.md.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple


class WidgetType(Enum):
    """Kinds of rows/fields CoreUIBuilder knows how to construct.

    Only the kinds actually needed by a real screen's schema are implemented
    here (originally tab1_image.py's TAB1_* specs; RADIO_ROW was added for
    start_dialog.py's T-0046 adoption); new kinds should be added only once
    a real screen needs them (avoids speculative/unused surface area, per
    the CoreUI plan's "逃げ道" principle for screen-specific exceptions).
    """
    LINEEDIT_ROW = "lineedit_row"
    COMBOBOX_ROW = "combobox_row"
    BUTTON = "button"
    BUTTON_ROW = "button_row"
    TABLE = "table"
    SEGMENTED_TOGGLE = "segmented_toggle"
    INFO_PANEL = "info_panel"
    RADIO_ROW = "radio_row"
    SPINBOX_ROW = "spinbox_row"
    SECTION_HEADER = "section_header"
    DOUBLE_SPINBOX_ROW = "double_spinbox_row"
    COLOR_BUTTON_ROW = "color_button_row"
    ROW_GROUP = "row_group"
    SPACER = "spacer"
    
    # --- 新規追加 (アプローチB) ---
    #: 複数のチェックボックスを横に並べる。複数選択が可能。
    #: FieldSpec.options でラベルを指定し、FieldSpec.default_indices で初期選択を指定する。
    CHECKBOX_ROW = "checkbox_row"
    
    #: 縦スクロール可能なリストウィジェット。
    #: FieldSpec.checkable が True の場合はアイテムにチェックボックスが付与される。
    LIST_WIDGET = "list_widget"


@dataclass
class ButtonDef:
    """One button, either standalone within a BUTTON_ROW field or as the
    trailing button of a LINEEDIT_ROW field (e.g. Tab1's "参照..." button).
    """
    field_id: str
    text: str
    on_click: Optional[str] = None
    style_variant: Optional[str] = None
    enabled: bool = True
    stretch: int = 1


@dataclass
class InfoLine:
    """One line within an INFO_PANEL field (T-0045: models Tab1's status
    panel, which stacks a bold header / separator / plain status line / a
    word-wrapped multi-line residual summary).
    """
    kind: str
    field_id: Optional[str] = None
    text: str = ""
    min_height: Optional[int] = None


@dataclass
class FieldSpec:
    """One declared row/field within a PanelSpec.
    """
    field_id: str
    widget_type: WidgetType
    label: Optional[str] = None
    placeholder: Optional[str] = None
    on_change: Optional[str] = None
    on_click: Optional[str] = None
    style_variant: Optional[str] = None
    enabled: bool = True
    trailing_button: Optional[ButtonDef] = None
    buttons: List[ButtonDef] = field(default_factory=list)
    options: List[str] = field(default_factory=list)
    default_index: int = 0
    table_headers: List[str] = field(default_factory=list)
    table_min_height: Optional[int] = None
    table_col_resize_modes: List[str] = field(default_factory=list)
    info_lines: List[InfoLine] = field(default_factory=list)
    main_ratio: Optional[Tuple[int, int]] = None
    row_height: Optional[int] = None
    visible: bool = True
    spin_min: int = 0
    spin_max: int = 999999
    spin_default: int = 0
    centered: bool = False
    dspin_min: float = 0.0
    dspin_max: float = 999.0
    dspin_step: float = 1.0
    dspin_default: float = 0.0
    color_default: str = "#FFFFFF"
    sub_fields: List["FieldSpec"] = field(default_factory=list)
    stretch: int = 1
    label_width: Optional[int] = None

    # --- 新規追加 (アプローチB) ---
    #: CHECKBOX_ROW または checkable な LIST_WIDGET 用。初期状態でチェックを入れるインデックスのリスト。
    default_indices: List[int] = field(default_factory=list)
    #: LIST_WIDGET 用。Trueにするとアイテムにチェックボックスが付く。
    checkable: bool = False
    #: LIST_WIDGET 用。リストの最小高さ（px）。
    list_min_height: Optional[int] = None


@dataclass
class PanelSpec:
    """A named collection of FieldSpecs built together into one container
    widget (a vertical stack, one row per field, in declared order).
    """
    panel_id: str
    fields: List[FieldSpec]
    rules: List = field(default_factory=list)
    margins: Tuple[int, int, int, int] = (0, 0, 0, 0)
    spacing: int = 6