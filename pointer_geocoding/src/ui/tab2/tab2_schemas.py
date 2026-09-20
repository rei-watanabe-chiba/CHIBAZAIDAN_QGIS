"""
/***************************************************************************
 PointerGeocoding Plugin - Tab 2 (Digitizing) Schemas
 ***************************************************************************/
"""
from ...ui.constants import UIConfig, UILabels, UIPlaceholders
from ...ui.core.field_spec import ButtonDef, FieldSpec, PanelSpec, WidgetType

# -------------------------------------------------------------------------
# Tab 2: モード切替パネル (tab2_mode_toggle)
# -------------------------------------------------------------------------
TAB2_MODE_TOGGLE_SPEC = PanelSpec(
    panel_id="tab2_mode_toggle",
    fields=[
        FieldSpec(
            field_id="tab2_mode",
            widget_type=WidgetType.SEGMENTED_TOGGLE,
            options=[UILabels.TAB2_MODE_NEW, UILabels.TAB2_MODE_EDIT],
            default_index=0,
            main_ratio=(0, 10),
            on_change="mode_changed",
        ),
    ],
)

# -------------------------------------------------------------------------
# Tab 2: 点情報パネル (group_point_info)
# -------------------------------------------------------------------------
TAB2_POINT_INFO_SPEC = PanelSpec(
    panel_id="tab2_point_info",
    spacing=UIConfig.PANEL_MARGIN,
    fields=[
        # ① 状態文言 + サマリー表示用のステータスパネル
        FieldSpec(
            field_id="point_info_summary",
            widget_type=WidgetType.INFO_PANEL,
            info_lines=[], # 初期表示は空。動的に update_status_panel で上書きされる
        ),
        # ② 点名 (非SP属性用のQSpinBox)
        FieldSpec(
            field_id="point_name",
            widget_type=WidgetType.SPINBOX_ROW,
            label=UILabels.POINT_NAME,
            spin_min=1,
            spin_max=999999,
            spin_default=1,
            on_change="point_identity_changed",
        ),
        # ③ 点名 (SP属性用のフリーテキストQLineEdit, 初期非表示)
        FieldSpec(
            field_id="point_name_sp",
            widget_type=WidgetType.LINEEDIT_ROW,
            label=UILabels.POINT_NAME,
            placeholder=UIPlaceholders.POINT_NAME_SP,
            on_change="point_identity_changed",
            visible=False,
        ),
        # ④ 枝番 (QLineEdit)
        FieldSpec(
            field_id="branch_no",
            widget_type=WidgetType.LINEEDIT_ROW,
            label=UILabels.BRANCH_NO,
            placeholder=UIPlaceholders.BRANCH_NO,
            on_change="branch_text_changed",
        ),
        # ⑤ 新規モード用：自動連番/解除 トグル
        FieldSpec(
            field_id="autonum_mode",
            widget_type=WidgetType.SEGMENTED_TOGGLE,
            options=[UILabels.AUTONUM_MODE_AUTO, UILabels.AUTONUM_MODE_RELEASE],
            default_index=0,
            on_change="autonum_mode_changed",
        ),
        # ⑥ 編集モード用：削除ボタン (初期非表示)
        FieldSpec(
            field_id="edit_mode_actions",
            widget_type=WidgetType.BUTTON_ROW,
            centered=False,
            visible=False,
            buttons=[
                ButtonDef(
                    field_id="delete_point",
                    text=UILabels.BTN_DELETE_POINT,
                    on_click="delete_point_clicked"
                ),
            ],
        ),
    ],
)

# -------------------------------------------------------------------------
# Tab 2: 属性パネル (group_attribute_panel)
# -------------------------------------------------------------------------
TAB2_ATTRIBUTE_SPEC = PanelSpec(
    panel_id="tab2_attribute",
    spacing=UIConfig.PANEL_MARGIN,
    fields=[
        # ① 属性 (S/P/C/SP)
        FieldSpec(
            field_id="attribute_code",
            widget_type=WidgetType.COMBOBOX_ROW,
            label=UILabels.ATTRIBUTE_CODE,
            on_change="category_changed",
        ),
        # ② 出土形態 (グリッド/遺構)
        FieldSpec(
            field_id="excavation_type",
            widget_type=WidgetType.COMBOBOX_ROW,
            label=UILabels.EXCAVATION_TYPE,
            on_change="excavation_type_changed",
        ),
        # ③ 遺構名 (初期非表示)
        FieldSpec(
            field_id="feature_name",
            widget_type=WidgetType.COMBOBOX_ROW,
            label=UILabels.FEATURE_SELECTOR,
            on_change="feature_combo_changed",
            visible=False,
        ),
        # ④ 遺構管理アクション (初期非表示)
        FieldSpec(
            field_id="feature_actions",
            widget_type=WidgetType.BUTTON_ROW,
            centered=False,
            visible=False,
            buttons=[
                ButtonDef(
                    field_id="manage_feature",
                    text=UILabels.FEATURE_MANAGE,
                    on_click="manage_feature_clicked",
                    stretch=1,
                ),
            ],
        ),
    ],
)

# -------------------------------------------------------------------------
# Tab 2: 表示設定パネル (group_display)
# -------------------------------------------------------------------------
TAB2_DISPLAY_FILTER_SPEC = PanelSpec(
    panel_id="tab2_display",
    spacing=UIConfig.PANEL_MARGIN,
    fields=[
        # ① フォーカスモード トグル＆設定ボタン
        FieldSpec(
            field_id="filter_actions",
            widget_type=WidgetType.BUTTON_ROW,
            centered=False,
            buttons=[
                ButtonDef(
                    field_id="filter_toggle",
                    text=UILabels.BTN_FILTER_OFF,
                    on_click="filter_toggled", # QCheckBoxのように扱えるようTab2内でカスタムバインド
                    stretch=3,
                ),
                ButtonDef(
                    field_id="filter_settings",
                    text=UILabels.BTN_FILTER_SETTINGS,
                    on_click="filter_settings_clicked",
                    stretch=1,
                ),
            ],
        ),
        # ② 基準点表示ラジオボタン
        FieldSpec(
            field_id="ref_point_visibility",
            widget_type=WidgetType.RADIO_ROW,
            label=UILabels.LBL_REF_POINT_VISIBILITY,
            options=[UILabels.RADIO_VISIBLE, UILabels.RADIO_HIDDEN],
            default_index=0,
            on_change="ref_point_visibility_changed",
        ),
        # ③ 図面選択テーブル
        FieldSpec(
            field_id="drawing_list_table",
            widget_type=WidgetType.TABLE,
            table_headers=["表示", "レイヤ名"],
            table_col_resize_modes=["contents", "stretch"],
            table_min_height=UIConfig.DRAWING_LIST_HEIGHT,
            on_change="drawing_table_cell_changed",
        ),
    ],
)