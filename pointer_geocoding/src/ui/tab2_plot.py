"""
/***************************************************************************
 PointerGeocoding Plugin - Tab 2 (Digitizing) Mixin
 ***************************************************************************/

Stage B split (mechanical, logic-preserving): extracted from main_dock.py.
Provides Tab2DigitizingMixin, mixed into MainDockWidget, containing all UI
construction and event handlers for Tab 2 (Master Focus Mode, continuous
artifact point digitizing, existing point editing/deletion, and CSV
export).

T-0032 (large follow-up to T-0027): redesigns the 点情報パネル/属性パネル and
substantially expands existing-point editing:
- Existing-point editing unlocks nearly all category widgets (only
  combo_drawing_name stays locked, see _CATEGORY_LOCK_WIDGET_NAMES); the
  former PointRenameDialog is removed in favor of directly editing
  edit_point_name/edit_point_name_sp/edit_branch_no in-panel and committing
  via btn_rename_point, plus a new btn_update_attribute for committing
  出土形態/遺構名/属性記号 changes.

T-0033 (UI follow-up to T-0032, after in-QGIS review): 点情報パネル/属性パネル/
フォーカスモードパネルのQGroupBoxタイトルを廃止しHLine区切りに変更
(UIStyleHelper.build_separator); 点情報パネルは状態文言+出土形態+点名/枝番+
XY座標を1つの複数行QLabelにまとめ、start_dialog.pyのpanel_preview_statusと同じ
左ボーダー色分けフレーム(UIStyleHelper.create_status_panel/update_status_panel)
で表示する(新規点作成=info/既設点編集=warning/エラー=error)。点名/枝番の入力欄と
削除ボタンはこのフレームの外(下)に配置。カラーボタンは無効時グレー表示
(_update_color_picker_button)。遺構名未指定/点名重複エラー時はそれぞれ
combo_feature_name/点名入力欄に赤枠を表示(_update_error_borders)。T-0032の
透明度「更新」ボタン(btn_update_opacity)は削除し、スライダーのリアルタイム反映
のみに戻した。

T-0038 (3段階UX改善の3/3、最終段): 編集モードで既設点を選択している間
(self.selected_edit_point_id is not None)、点名/枝番/出土形態/遺構名/属性の各
ウィジェットの値確定シグナル(QSpinBox/QLineEditはeditingFinished、QComboBoxは
currentIndexChanged/currentTextChanged)で直接フィーチャへコミットするように
変更し、旧「点名変更」(btn_rename_point/_on_rename_point_clicked)・
「属性変更」(btn_update_attribute/_on_update_attribute_clicked)の確定ボタンは
廃止した。実コミット処理は共通ヘルパー _commit_fields_to_feature に集約し、
_commit_point_identity_if_editing/_commit_attribute_fields_if_editing から
呼び出す。新規モード中や、_on_existing_point_selected によるフォームへの
既設値ロード中(self._suppress_realtime_commit)は一切コミットしない。
"""

import os
from contextlib import nullcontext
from typing import Dict, Any, List, Tuple, Optional

from qgis.core import (
    QgsProject,
    QgsPointXY,
    Qgis,
)
from qgis.gui import (
    QgsFilterLineEdit,
)
from qgis.PyQt.QtCore import Qt, pyqtSlot
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QRadioButton,
    QButtonGroup,
    QLabel,
    QPushButton,
    QComboBox,
    QGroupBox,
    QDialog,
    QScrollArea,
    QFileDialog,
    QMessageBox,
    QColorDialog,
    QFrame,
    QSlider,
    QListWidget,
    QListWidgetItem,
    QTableWidget,
    QTableWidgetItem,
    QLineEdit,
)

# T-0022: SP属性専用の点名QLineEditで使用する入力バリデータ。
# PyQt5/PyQt6両対応パターンは start_dialog.py (L31-38付近) を踏襲する。
try:
    from qgis.PyQt.QtGui import QRegularExpressionValidator
    from qgis.PyQt.QtCore import QRegularExpression
    HAS_QT_REGEX = True
except ImportError:
    from qgis.PyQt.QtGui import QRegExpValidator
    from qgis.PyQt.QtCore import QRegExp
    HAS_QT_REGEX = False

from ..logic.transform import export_points_to_csv
from .style import UIStyleHelper
from ..logic.core import (
    check_point_duplicate,
    build_point_ident,
    get_next_point_number,
    get_next_point_id,
    build_digitized_feature,
    insert_feature_to_layer,
    pixel_from_affine,
    safe_get_str,
    to_survey_coords,
    ExcavationType,
    AttributeType,
)
from .constants import (
    UIConfig,
    UILabels,
    UIPlaceholders,
    UIDialogTitles,
    UIMessages,
    MAIN_RATIO,
)
from .dialogs import (
    FeatureManageDialog,
    FeatureCreateDialog,
    PointNameEntryDialog,
    DisplayFilterDialog,
)


class Tab2DigitizingMixin:
    """Mixin providing Tab 2 (Master Focus Mode, Digitizing & CSV Export) behavior for MainDockWidget."""

    def _create_tab2_ui(self) -> QWidget:
        """Construct Tab 2: 3 always-expanded panels.

        ① 点情報パネル (group_point_info) — title-less, HLine区切り; 左ボーダー
           色分けフレーム内に状態文言(新規点作成/既設点編集/エラー)+出土形態・
           点名/枝番・XY座標をまとめた複数行テキストを表示。フレームの外(下)に
           editable 点名/枝番 inputs + 既設点のみの削除/点名変更(コミット)ボタン;
        ② 属性パネル (group_attribute_panel) — title-less、HLine区切り;
           属性→出土形態→遺構名→(作成・カラーの行)→対象図面、既設点編集時のみの
           属性変更ボタン;
        ③ 表示設定パネル (group_display) — title-less、HLine区切り;
           フォーカスモード(ON/OFFトグルとスライダー)、基準点表示設定、
           図面選択リスト (table_drawing_list) を統合。
        """
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(
            UIConfig.PANEL_CONTAINER_MARGIN_LEFT,
            0,
            UIConfig.PANEL_CONTAINER_MARGIN_RIGHT,
            UIConfig.PANEL_MARGIN,
        )
        layout.setSpacing(0)

        # =============================================================
        # T-0036: tab2先頭の新規/編集モード切替トグル。tab1_georef_mixin.py の
        # self.tab1_mode_container/tab1_mode_buttons と同じ
        # UIStyleHelper.build_segmented_toggle() パターンを踏襲する。
        # 今回はUI表示の切替(点情報パネルのボタンエリア)のみを担当し、
        # 既存のselected_edit_point_id/キャンバスクリック処理には接続しない
        # (実際のクリック挙動連動はT-0037で別途実装)。
        # =============================================================
        self.tab2_current_mode = "new"
        # T-0038: guards against real-time field-commit handlers firing while
        # _on_existing_point_selected() is programmatically populating the
        # form widgets from a freshly loaded feature (see that method).
        self._suppress_realtime_commit = False
        self.tab2_mode_container, self.tab2_mode_buttons = UIStyleHelper.build_segmented_toggle(
            [UILabels.TAB2_MODE_NEW, UILabels.TAB2_MODE_EDIT], default_index=0, parent=container
        )
        tab2_mode_row = UIStyleHelper.build_flex_row(
            main_label=None,
            child_configs=[(self.tab2_mode_container, 1)],
            main_ratio=(0, 10),
            row_height=UIConfig.ROW_HEIGHT,
        )
        layout.addWidget(tab2_mode_row)
        layout.addSpacing(UIConfig.PANEL_MARGIN)

        self.tab2_mode_buttons[0].toggled.connect(lambda checked: self._on_tab2_mode_changed(0) if checked else None)
        self.tab2_mode_buttons[1].toggled.connect(lambda checked: self._on_tab2_mode_changed(1) if checked else None)

        # =============================================================
        # Panel 1: 点情報パネル (T-0033: title removed; the status band +
        # 出土形態/点名+枝番/XY座標 summary is now a single flat multi-line
        # QLabel inside a left-border color-coded QFrame, matching
        # start_dialog.py's panel_preview_status style. The editable
        # point-name/branch inputs and existing-point-only action buttons
        # live below this frame, outside of it. T-0034: the leading HLine
        # separator that used to precede this panel was removed because
        # main_dock.py now places its own separator directly above
        # tab2_container, avoiding two adjacent separators.)
        # =============================================================
        self.group_point_info = QGroupBox(container)
        info_layout = QVBoxLayout(self.group_point_info)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(UIConfig.PANEL_MARGIN)

        # T-0033: flat multi-line summary (status + 出土形態 + 点名+枝番 +
        # XY座標) inside a create_status_panel()-style left-border frame;
        # color-coded via _update_point_info_status() (新規点作成=info/blue,
        # 既設点編集=warning/orange, エラー=error/red -- reusing the same
        # QFrame[statusType=...] styles as start_dialog.py's
        # panel_preview_status, no dedicated "editing" style needed).
        self.panel_point_info, self.lbl_point_info_status = UIStyleHelper.create_status_panel(
            UILabels.STATUS_NEW_POINT, status_type="info", parent=self.group_point_info
        )
        info_layout.addWidget(self.panel_point_info)

        # 番号・枝番 (editable inputs, directly under the summary panel
        # above). T-0032: no longer force-disabled while an existing point
        # is selected (see _CATEGORY_LOCK_WIDGET_NAMES). T-0038: editing
        # these while an existing point is selected now commits directly to
        # the selected feature in real time (on editingFinished, see
        # _commit_point_identity_if_editing), replacing the former
        # PointRenameDialog / btn_rename_point confirm-button flow.
        # [EXCEPTION PROTECTION: QSpinBox preserved for S/P/C attributes per
        # OSネイティブUI保護原則]. T-0022: SP属性選択時のみ、専用の自由入力
        # QLineEdit(半角英数字・ハイフン・アンダースコアのみ)をこれと並置し、
        # 表示/非表示を切り替える(QSpinBoxは変更しない)。
        self.lbl_point_name = QLabel(UILabels.POINT_NAME, self.group_point_info)
        self.edit_point_name = UIStyleHelper.create_spinbox(1, 999999, 1, self.group_point_info)
        self.edit_point_name.valueChanged.connect(self._on_point_identity_changed)
        self.edit_point_name_sp = QLineEdit(self.group_point_info)
        self.edit_point_name_sp.setPlaceholderText(UIPlaceholders.POINT_NAME_SP)
        if HAS_QT_REGEX:
            self.edit_point_name_sp.setValidator(
                QRegularExpressionValidator(
                    QRegularExpression(r"^[A-Za-z0-9_-]+$"), self.edit_point_name_sp
                )
            )
        else:
            self.edit_point_name_sp.setValidator(
                QRegExpValidator(QRegExp(r"^[A-Za-z0-9_-]+$"), self.edit_point_name_sp)
            )
        self.edit_point_name_sp.hide()
        self.edit_point_name_sp.textChanged.connect(self._on_point_identity_changed)
        row_point_name = UIStyleHelper.build_flex_row(
            self.lbl_point_name,
            [(self.edit_point_name, 1), (self.edit_point_name_sp, 1)],
            main_ratio=MAIN_RATIO,
            row_height=UIConfig.ROW_HEIGHT,
        )
        info_layout.addWidget(row_point_name)

        self.lbl_branch_no = QLabel(UILabels.BRANCH_NO, self.group_point_info)
        self.edit_branch_no = QgsFilterLineEdit(self.group_point_info)
        self.edit_branch_no.setShowClearButton(True)
        self.edit_branch_no.setPlaceholderText(UIPlaceholders.BRANCH_NO)
        self.edit_branch_no.textChanged.connect(self._on_branch_text_changed)
        row_branch_no = UIStyleHelper.build_flex_row(
            self.lbl_branch_no,
            [(self.edit_branch_no, 1)],
            main_ratio=MAIN_RATIO,
            row_height=UIConfig.ROW_HEIGHT,
        )
        info_layout.addWidget(row_branch_no)

        # T-0038: the former "既設点のみ" 点名変更 confirm-button row
        # (row_existing_actions/btn_rename_point) is retired now that
        # editing point-name/branch while an existing point is selected
        # commits in real time (see edit_point_name(_sp)/edit_branch_no
        # editingFinished wiring above and _commit_point_identity_if_editing).
        # Only the mode-linked button area below (widget_edit_mode_actions,
        # holding btn_delete_point) remains for existing-point-only actions.

        # =============================================================
        # T-0036: モード連動ボタンエリア。新規モード=自動連番/解除トグル
        # (自動連番=既存の直前打刻追従型採番を適用/解除=点名フィールドへの
        # 自動上書きをスキップしユーザーの手入力を許す。SP属性選択時は
        # 元々自動採番の対象外なので、トグルは自動的に「解除」側へ固定し
        # 無効化する。see _update_autonum_toggle_for_sp)、
        # 編集モード=削除のみ(btn_delete_point。既存の削除ロジックは変更しない)。
        # この2つの領域はtab2_current_mode(①のトグル)に連動して表示/非表示を
        # 切り替えるのみで、selected_edit_point_id/キャンバスクリック処理とは
        # 独立している(T-0037で別途統合予定)。
        # =============================================================
        self.tab2_autonum_mode = "auto"
        self.tab2_autonum_container, self.tab2_autonum_buttons = UIStyleHelper.build_segmented_toggle(
            [UILabels.AUTONUM_MODE_AUTO, UILabels.AUTONUM_MODE_RELEASE],
            default_index=0,
            parent=self.group_point_info,
        )
        self.tab2_autonum_buttons[0].toggled.connect(
            lambda checked: self._on_tab2_autonum_mode_changed(0) if checked else None
        )
        self.tab2_autonum_buttons[1].toggled.connect(
            lambda checked: self._on_tab2_autonum_mode_changed(1) if checked else None
        )

        self.widget_new_mode_actions = QWidget(self.group_point_info)
        new_mode_actions_layout = QHBoxLayout(self.widget_new_mode_actions)
        new_mode_actions_layout.setContentsMargins(0, 0, 0, 0)
        new_mode_actions_layout.setSpacing(8)
        new_mode_actions_layout.addWidget(self.tab2_autonum_container)
        info_layout.addWidget(self.widget_new_mode_actions)

        self.widget_edit_mode_actions = QWidget(self.group_point_info)
        edit_mode_actions_layout = QHBoxLayout(self.widget_edit_mode_actions)
        edit_mode_actions_layout.setContentsMargins(0, 0, 0, 0)
        edit_mode_actions_layout.setSpacing(8)

        self.btn_delete_point = QPushButton(UILabels.BTN_DELETE_POINT, self.widget_edit_mode_actions)
        self.btn_delete_point.clicked.connect(self._on_delete_selected_point)
        edit_mode_actions_layout.addWidget(self.btn_delete_point)

        info_layout.addWidget(self.widget_edit_mode_actions)
        self.widget_edit_mode_actions.hide()

        layout.addWidget(self.group_point_info)
        layout.addWidget(UIStyleHelper.build_separator(container))

        # =============================================================
        # Panel 2: 属性パネル (T-0032 order: 属性→出土形態→遺構名→
        # (作成・カラーの行)→対象図面→(既設点編集時のみ)属性変更ボタン)
        # =============================================================
        self.group_attribute_panel = QGroupBox(container)
        attr_layout = QVBoxLayout(self.group_attribute_panel)
        attr_layout.setContentsMargins(0, 0, 0, 0)
        attr_layout.setSpacing(UIConfig.PANEL_MARGIN)

        # 属性 (T-0032: display-only labels "S:石器"/"P:土器"/"C:炭化物"/"SP";
        # the raw AttributeType value is stored as itemData and must be read
        # via _get_attribute_value()/set via _set_attribute_value()).
        self.lbl_attribute = QLabel(UILabels.ATTRIBUTE_CODE, self.group_attribute_panel)
        self.combo_attribute = QComboBox(self.group_attribute_panel)
        for value in UILabels.ATTRIBUTE_OPTIONS:
            self.combo_attribute.addItem(UILabels.ATTRIBUTE_DISPLAY_MAP.get(value, value), value)
        self.combo_attribute.currentIndexChanged.connect(self._on_category_changed)
        row_attribute = UIStyleHelper.build_flex_row(
            self.lbl_attribute,
            [(self.combo_attribute, 1)],
            main_ratio=MAIN_RATIO,
            row_height=UIConfig.ROW_HEIGHT,
        )
        attr_layout.addWidget(row_attribute)

        # 出土形態
        self.lbl_excavation_type = QLabel(UILabels.EXCAVATION_TYPE, self.group_attribute_panel)
        self.combo_excavation_type = QComboBox(self.group_attribute_panel)
        self.combo_excavation_type.addItems(UILabels.EXCAVATION_OPTIONS)
        self.combo_excavation_type.currentIndexChanged.connect(self._on_excavation_type_changed)
        row_excavation = UIStyleHelper.build_flex_row(
            self.lbl_excavation_type,
            [(self.combo_excavation_type, 1)],
            main_ratio=MAIN_RATIO,
            row_height=UIConfig.ROW_HEIGHT,
        )
        attr_layout.addWidget(row_excavation)

        # 遺構名 (selector only; 遺構管理ボタンは別行に配置, see row_feature_actions).
        self.lbl_feature_selector = QLabel(UILabels.FEATURE_SELECTOR, self.group_attribute_panel)
        self.combo_feature_name = QComboBox(self.group_attribute_panel)
        self.combo_feature_name.addItem(UILabels.UNREGISTERED)
        self.combo_feature_name.currentTextChanged.connect(self._on_feature_combo_changed)

        self.row_feature_selector = UIStyleHelper.build_flex_row(
            self.lbl_feature_selector,
            [(self.combo_feature_name, 1)],
            main_ratio=MAIN_RATIO,
            row_height=UIConfig.ROW_HEIGHT,
        )
        attr_layout.addWidget(self.row_feature_selector)

        # 遺構管理ボタン (FEAT-01: color picker moved to dialog, create button renamed to manage)
        self.row_feature_actions = QWidget(self.group_attribute_panel)
        feature_actions_layout = QHBoxLayout(self.row_feature_actions)
        feature_actions_layout.setContentsMargins(0, 0, 0, 0)
        feature_actions_layout.setSpacing(8)

        self.btn_manage_feature = QPushButton(UILabels.FEATURE_MANAGE, self.row_feature_actions)
        self.btn_manage_feature.clicked.connect(self._on_manage_feature_clicked)
        feature_actions_layout.addWidget(self.btn_manage_feature, 1)
        self.btn_create_feature = self.btn_manage_feature

        attr_layout.addWidget(self.row_feature_actions)


        # Initial visibility for feature-specific controls (default is グリッド)
        self.row_feature_selector.hide()

        # T-0038: the former 属性変更 confirm button (btn_update_attribute)
        # is retired now that 出土形態/遺構名/属性記号 changes commit in real
        # time while an existing point is selected (see combo_attribute's
        # extra currentIndexChanged connection above, and
        # _on_excavation_type_changed/_on_feature_combo_changed below, all of
        # which call _commit_attribute_fields_if_editing).

        layout.addWidget(self.group_attribute_panel)
        layout.addWidget(UIStyleHelper.build_separator(container))

        # =============================================================
        # Panel 3: 表示設定パネル (フォーカスモード + 基準点表示 + 図面選択リスト)
        # =============================================================
        self.group_display = QGroupBox(container)
        self.group_focus = self.group_display
        self.group_drawing_list = self.group_display
        display_layout = QVBoxLayout(self.group_display)
        display_layout.setContentsMargins(0, 0, 0, 0)
        display_layout.setSpacing(UIConfig.PANEL_MARGIN)

        # Filter toggle button and settings button row
        filter_btn_row = QWidget(self.group_display)
        filter_btn_layout = QHBoxLayout(filter_btn_row)
        filter_btn_layout.setContentsMargins(0, 0, 0, 0)
        filter_btn_layout.setSpacing(6)

        self.btn_filter = QPushButton(UILabels.BTN_FILTER_OFF, filter_btn_row)
        self.btn_filter.setCheckable(True)
        self.btn_filter.toggled.connect(self._on_focus_mode_toggled)
        self.btn_focus_mode = self.btn_filter  # Compatibility alias

        self.btn_filter_settings = QPushButton(UILabels.BTN_FILTER_SETTINGS, filter_btn_row)
        self.btn_filter_settings.clicked.connect(self._on_filter_settings_clicked)

        filter_btn_layout.addWidget(self.btn_filter, 3)
        filter_btn_layout.addWidget(self.btn_filter_settings, 1)
        display_layout.addWidget(filter_btn_row)

        self._current_display_filters: Dict[str, Any] = {
            "attributes": [
                AttributeType.S.value,
                AttributeType.P.value,
                AttributeType.C.value,
                AttributeType.SP.value,
            ],
            "excavation_types": [
                ExcavationType.FEATURE.value,
                ExcavationType.GRID.value,
            ],
            "feature_names": [],
            "target_drawing": UILabels.FILTER_DRAWING_SELECTED,
        }

        # 基準点レイヤ(プロジェクト共通・図面ごとではない)の表示/非表示を
        # 切り替えるラジオボタン行。
        self.lbl_ref_point_visibility = QLabel(UILabels.LBL_REF_POINT_VISIBILITY, self.group_display)
        self.radio_ref_point_visible = QRadioButton(UILabels.RADIO_VISIBLE, self.group_display)
        self.radio_ref_point_hidden = QRadioButton(UILabels.RADIO_HIDDEN, self.group_display)
        self.ref_point_visibility_group = QButtonGroup(self.group_display)
        self.ref_point_visibility_group.addButton(self.radio_ref_point_visible)
        self.ref_point_visibility_group.addButton(self.radio_ref_point_hidden)
        self._sync_ref_point_visibility_radios()
        self.radio_ref_point_visible.toggled.connect(self._on_ref_point_visibility_radio_toggled)
        row_ref_point_visibility = UIStyleHelper.build_flex_row(
            self.lbl_ref_point_visibility,
            [(self.radio_ref_point_visible, 1), (self.radio_ref_point_hidden, 1), (None, 1)],
            main_ratio=MAIN_RATIO,
            row_height=UIConfig.ROW_HEIGHT,
        )
        display_layout.addWidget(row_ref_point_visibility)

        self.table_drawing_list = QTableWidget(self.group_display)
        self.table_drawing_list.setColumnCount(2)
        self.table_drawing_list.setHorizontalHeaderLabels(["表示", "レイヤ名"])
        self.table_drawing_list.setFixedHeight(UIConfig.DRAWING_LIST_HEIGHT)
        self.table_drawing_list.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_drawing_list.setSelectionMode(QTableWidget.SingleSelection)
        self.table_drawing_list.setFocusPolicy(Qt.NoFocus)
        self.table_drawing_list.setShowGrid(False)
        self.table_drawing_list.setStyleSheet(
            "QTableView::indicator { subcontrol-position: center; }"
            "QTableView { border: none; }"
            "QTableView::item:focus { border: none; outline: none; }"
        )
        self.table_drawing_list.verticalHeader().setVisible(False)
        self.table_drawing_list.verticalHeader().setMinimumSectionSize(20)
        self.table_drawing_list.verticalHeader().setDefaultSectionSize(20)
        header = self.table_drawing_list.horizontalHeader()
        header.setStretchLastSection(True)
        header.resizeSection(0, 40)
        self.table_drawing_list.setColumnWidth(0, 40)
        self.table_drawing_list.itemChanged.connect(self._on_table_cell_changed)
        self.table_drawing_list.itemSelectionChanged.connect(self._on_table_selection_changed)
        header.sectionClicked.connect(self._on_header_clicked)
        display_layout.addWidget(self.table_drawing_list)

        layout.addWidget(self.group_display)
        layout.addStretch()

        scroll.setWidget(container)

        # T-0032: initialize 点情報パネル error-tracking flag; the summary
        # panel itself already defaults to status_type="info" (新規点作成)
        # via create_status_panel() above.
        self._point_info_has_error = False

        # T-0033: sync 作成/カラー button enabled state (and the color
        # picker's gray-when-disabled styling) with the default 出土形態
        # selection (グリッド), since neither combo emits its
        # currentIndexChanged signal for the initial index-(-1)->0 transition
        # performed by addItems() above.
        self._update_feature_related_visibility()

        return scroll

    def _create_tab4_ui(self) -> QWidget:
        """Construct the 出力 (CSV export) dialog content (T-0024).

        Formerly Section 4 of Tab 2 (embedded at the bottom of the main
        digitizing area); split out into its own modeless dialog so the
        main digitizing area stays focused on continuous point entry. The
        widgets/handlers themselves (_browse_csv_path / _on_export_csv_clicked)
        are unchanged.

        T-0034: renamed from _create_output_ui() to _create_tab4_ui() to
        align with the tab1/tab2/tab3 naming pattern used by main_dock.py's
        self.tab1_container / self.tab2_container / self.tab3_container /
        self.tab4_container.
        """
        csv_group = QGroupBox()
        csv_layout = QVBoxLayout(csv_group)
        csv_layout.setContentsMargins(
            UIConfig.COMMON_MARGIN_LR,
            UIConfig.DIALOG_MARGIN,
            UIConfig.COMMON_MARGIN_LR,
            UIConfig.DIALOG_MARGIN,
        )
        csv_layout.setSpacing(UIConfig.DIALOG_MARGIN)
        csv_layout.addWidget(
            UIStyleHelper.build_separator(csv_group, title_text=UILabels.GROUP_CSV)
        )

        self.lbl_encoding = QLabel(UILabels.ENCODING, csv_group)
        self.radio_utf8 = QRadioButton(UILabels.RADIO_UTF8, csv_group)
        self.radio_utf8.setChecked(True)
        self.radio_sjis = QRadioButton(UILabels.RADIO_SJIS, csv_group)
        row_encoding = UIStyleHelper.build_flex_row(
            self.lbl_encoding,
            [(self.radio_utf8, 1), (self.radio_sjis, 1), (None, 1)],
            main_ratio=MAIN_RATIO,
            row_height=UIConfig.ROW_HEIGHT,
        )
        csv_layout.addWidget(row_encoding)

        self.lbl_csv_path = QLabel(UILabels.CSV_DESTINATION, csv_group)
        self.edit_csv_path = QgsFilterLineEdit(csv_group)
        self.edit_csv_path.setShowClearButton(True)
        self.edit_csv_path.setPlaceholderText(UIPlaceholders.CSV_PATH)
        self.btn_browse_csv = QPushButton(UILabels.BTN_BROWSE, csv_group)
        self.btn_browse_csv.clicked.connect(self._browse_csv_path)
        row_csv = UIStyleHelper.build_flex_row(
            self.lbl_csv_path,
            [(self.edit_csv_path, 1), (self.btn_browse_csv, 0)],
            main_ratio=MAIN_RATIO,
            row_height=UIConfig.ROW_HEIGHT,
        )
        csv_layout.addWidget(row_csv)

        self.btn_export_csv = QPushButton(UILabels.BTN_EXPORT_CSV, csv_group)
        UIStyleHelper.set_accent_button(self.btn_export_csv)
        self.btn_export_csv.clicked.connect(self._on_export_csv_clicked)
        csv_layout.addWidget(self.btn_export_csv)

        return csv_group

    # =========================================================================
    # Tab 2: Focus Mode, Artifact Digitizing & CSV Export Handlers
    # =========================================================================

    def _get_drawing_layers(self) -> List[Tuple[str, str, bool]]:
        """Extract valid raster layer information from the '画像ファイル' group in QGIS layer tree.

        :return: List of tuples (layer_name, layer_id, is_visible).
        :rtype: List[Tuple[str, str, bool]]
        """
        root = QgsProject.instance().layerTreeRoot()
        if not root:
            return []
        image_group = root.findGroup("画像ファイル")
        if not image_group:
            return []

        result: List[Tuple[str, str, bool]] = []
        for tree_layer in image_group.findLayers():
            layer = tree_layer.layer()
            if layer and layer.isValid():
                result.append((layer.name(), layer.id(), tree_layer.itemVisibilityChecked()))
        return result

    def _get_drawing_layer_names(self) -> List[str]:
        """Extract valid raster layer names from the '画像ファイル' group in QGIS layer tree.

        :return: List of raster layer names.
        :rtype: List[str]
        """
        return [info[0] for info in self._get_drawing_layers()]

    def _update_drawing_combo(self, *args: Any) -> None:
        """Dynamically refresh the target drawing table."""
        if not hasattr(self, "table_drawing_list") or self.table_drawing_list is None:
            return

        current_selection = self._get_target_drawing_name()
        self.table_drawing_list.blockSignals(True)
        self.table_drawing_list.setRowCount(0)

        # Row 0: DRAWING_UNSPECIFIED
        self.table_drawing_list.insertRow(0)
        item_col0 = QTableWidgetItem()
        item_col0.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        item_col0.setCheckState(Qt.Unchecked)
        self.table_drawing_list.setItem(0, 0, item_col0)

        item_col1 = QTableWidgetItem(UILabels.DRAWING_UNSPECIFIED)
        item_col1.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        self.table_drawing_list.setItem(0, 1, item_col1)

        layers_info = self._get_drawing_layers()
        for r_idx, (name, layer_id, is_vis) in enumerate(layers_info, start=1):
            self.table_drawing_list.insertRow(r_idx)

            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            chk_item.setCheckState(Qt.Checked if is_vis else Qt.Unchecked)
            chk_item.setData(Qt.UserRole, layer_id)
            self.table_drawing_list.setItem(r_idx, 0, chk_item)

            name_item = QTableWidgetItem(name)
            name_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            self.table_drawing_list.setItem(r_idx, 1, name_item)

        self.table_drawing_list.blockSignals(False)
        self._ensure_drawing_selected(current_selection)

        # Refresh 基準点 visibility radios (the ref point layer may not have
        # existed yet when _create_tab2_ui() first ran; this signal handler is
        # also invoked on every project layersAdded/layersRemoved, see dock.py).
        if hasattr(self, "radio_ref_point_visible") and self.radio_ref_point_visible is not None:
            self._sync_ref_point_visibility_radios()

    def _on_table_cell_changed(self, item: QTableWidgetItem) -> None:
        """Toggle canvas visibility when checkbox column state changes.

        :param item: Changed QTableWidgetItem.
        :type item: QTableWidgetItem
        """
        if item is None or item.column() != 0:
            return
        layer_id = item.data(Qt.UserRole)
        if not layer_id:
            return
        is_checked = item.checkState() == Qt.Checked
        root = QgsProject.instance().layerTreeRoot()
        if root and layer_id:
            image_group = root.findGroup("画像ファイル")
            if image_group:
                tree_layer = image_group.findLayer(layer_id)
                if tree_layer:
                    tree_layer.setItemVisibilityChecked(is_checked)
                    self.canvas.refresh()

    def _on_table_selection_changed(self) -> None:
        """Handle selection changes in table_drawing_list."""
        self._on_category_changed()
        self._commit_attribute_fields_if_editing()

    def _on_header_clicked(self, logical_index: int) -> None:
        """Handle clicking the horizontal header (column 0 toggle all).

        :param logical_index: Index of the clicked header section.
        :type logical_index: int
        """
        if logical_index != 0:
            return
        row_count = self.table_drawing_list.rowCount()
        if row_count <= 1:
            return

        all_checked = True
        for row in range(1, row_count):
            item = self.table_drawing_list.item(row, 0)
            if item and item.checkState() != Qt.Checked:
                all_checked = False
                break

        new_state = Qt.Unchecked if all_checked else Qt.Checked
        for row in range(1, row_count):
            item = self.table_drawing_list.item(row, 0)
            if item:
                item.setCheckState(new_state)

    def _get_target_drawing_name(self) -> str:
        """Return the text of col 1 for the currently selected row in table_drawing_list.

        :return: Layer name in column 1, or DRAWING_UNSPECIFIED if row 0 or none selected.
        :rtype: str
        """
        if not hasattr(self, "table_drawing_list") or self.table_drawing_list is None:
            return UILabels.DRAWING_UNSPECIFIED
        row = -1
        sel_model = self.table_drawing_list.selectionModel()
        if sel_model:
            selected_rows = sel_model.selectedRows()
            if selected_rows:
                row = selected_rows[0].row()
        if row < 0:
            row = self.table_drawing_list.currentRow()

        if row <= 0:
            return UILabels.DRAWING_UNSPECIFIED
        item = self.table_drawing_list.item(row, 1)
        if not item:
            return UILabels.DRAWING_UNSPECIFIED
        return item.text().strip()

    def _ensure_drawing_selected(self, layer_name: str) -> None:
        """Select and scroll to the row corresponding to layer_name in table_drawing_list.

        :param layer_name: Layer name to select.
        :type layer_name: str
        """
        if not hasattr(self, "table_drawing_list") or self.table_drawing_list is None:
            return
        row_count = self.table_drawing_list.rowCount()
        if row_count == 0:
            return

        target_row = 0
        if layer_name and layer_name != UILabels.DRAWING_UNSPECIFIED:
            for r in range(1, row_count):
                item = self.table_drawing_list.item(r, 1)
                if item and item.text() == layer_name:
                    target_row = r
                    break

        self.table_drawing_list.selectRow(target_row)
        scroll_item = self.table_drawing_list.item(target_row, 1)
        if scroll_item:
            self.table_drawing_list.scrollToItem(scroll_item)

    def _find_ref_point_tree_layer(self) -> Optional[Any]:
        """Locate the QgsLayerTreeLayer node for the shared 基準点レイヤ (ref_point_layer).

        The ref point layer is project-wide (not per-drawing); it lives inside
        the "基準点データ" group if present (see layer/grid_csv.py), otherwise
        directly under the root, mirroring _get_drawing_layers()'s lookup
        pattern for the "画像ファイル" group.

        :return: The matching QgsLayerTreeLayer, or None if unavailable.
        :rtype: Optional[Any]
        """
        ref_layer = getattr(self.layer_manager, "ref_point_layer", None) if self.layer_manager else None
        if ref_layer is None:
            return None
        root = QgsProject.instance().layerTreeRoot()
        if not root:
            return None
        ref_group = root.findGroup("基準点データ")
        search_root = ref_group if ref_group else root
        return search_root.findLayer(ref_layer.id())

    def _sync_ref_point_visibility_radios(self) -> None:
        """Initialize/refresh 基準点 visibility radio buttons from the actual layer tree state.

        If the ref point layer is not yet loaded (self.layer_manager.ref_point_layer
        is None, e.g. before a session/grid CSV has been set up), both radios are
        disabled and 表示 is kept selected by default so the UI is ready to reflect
        the layer's true state as soon as it becomes available (see callers:
        _create_tab2_ui() at construction time, and _update_drawing_combo() on
        every project layersAdded/layersRemoved signal).
        """
        tree_layer = self._find_ref_point_tree_layer()
        enabled = tree_layer is not None
        self.radio_ref_point_visible.setEnabled(enabled)
        self.radio_ref_point_hidden.setEnabled(enabled)

        is_visible = tree_layer.itemVisibilityChecked() if tree_layer else True
        # Avoid re-entrant canvas refresh/tree writes while programmatically
        # syncing the radio state from the actual layer tree.
        self.radio_ref_point_visible.blockSignals(True)
        self.radio_ref_point_hidden.blockSignals(True)
        self.radio_ref_point_visible.setChecked(is_visible)
        self.radio_ref_point_hidden.setChecked(not is_visible)
        self.radio_ref_point_visible.blockSignals(False)
        self.radio_ref_point_hidden.blockSignals(False)

    def _on_ref_point_visibility_radio_toggled(self, checked: bool) -> None:
        """Toggle canvas visibility for the shared 基準点レイヤ.

        Connected only to radio_ref_point_visible.toggled; since the two
        radios share a QButtonGroup (mutually exclusive), checked==True means
        表示 was just selected and checked==False means 非表示 was selected.

        :param checked: Whether radio_ref_point_visible is now checked.
        :type checked: bool
        """
        tree_layer = self._find_ref_point_tree_layer()
        if tree_layer:
            tree_layer.setItemVisibilityChecked(checked)
            self.canvas.refresh()

    def _ensure_drawing_visible(self, drawing_name: str) -> None:
        """Ensure the specified drawing is checked ON in table_drawing_list and visible on canvas.

        :param drawing_name: Layer name to make visible.
        :type drawing_name: str
        """
        if not hasattr(self, "table_drawing_list") or self.table_drawing_list is None:
            return
        if not drawing_name or drawing_name == UILabels.DRAWING_UNSPECIFIED:
            return

        root = QgsProject.instance().layerTreeRoot()
        image_group = root.findGroup("画像ファイル") if root else None

        for r in range(1, self.table_drawing_list.rowCount()):
            name_item = self.table_drawing_list.item(r, 1)
            if name_item and name_item.text() == drawing_name:
                chk_item = self.table_drawing_list.item(r, 0)
                if chk_item and chk_item.checkState() != Qt.Checked:
                    self.table_drawing_list.blockSignals(True)
                    chk_item.setCheckState(Qt.Checked)
                    self.table_drawing_list.blockSignals(False)

                    layer_id = chk_item.data(Qt.UserRole)
                    if image_group and layer_id:
                        tree_layer = image_group.findLayer(layer_id)
                        if tree_layer:
                            tree_layer.setItemVisibilityChecked(True)
                    self.canvas.refresh()
                break

    def is_focus_mode_active(self) -> bool:
        """Return whether Focus / Filter Mode is currently active.

        :return: True if filter mode button is checked.
        :rtype: bool
        """
        btn = getattr(self, "btn_filter", None) or getattr(self, "btn_focus_mode", None)
        return bool(btn is not None and btn.isChecked())

    def _get_attribute_value(self) -> str:
        """Return the raw AttributeType value (S/P/C/SP) currently selected.

        T-0032: combo_attribute now shows display-only labels (e.g. "S:石器")
        while storing the raw value as itemData; callers needing the actual
        stored/compared value must use this instead of currentText().

        :return: Currently selected AttributeType value string.
        :rtype: str
        """
        if not hasattr(self, "combo_attribute"):
            return ""
        return self.combo_attribute.currentData() or self.combo_attribute.currentText()

    def _set_attribute_value(self, value: str) -> None:
        """Select the combo_attribute item whose itemData matches ``value``.

        :param value: Raw AttributeType value (S/P/C/SP) to select.
        :type value: str
        """
        idx = self.combo_attribute.findData(value)
        if idx >= 0:
            self.combo_attribute.setCurrentIndex(idx)
        else:
            self.combo_attribute.setCurrentText(value)

    def get_focus_category_filter(self) -> Dict[str, Any]:
        """Return dictionary of filter criteria for display filtering.

        - Attributes, excavation types, and feature names are static lists from DisplayFilterDialog.
        - Target drawing is dynamically evaluated: if 'selected' drawing mode is chosen,
          the currently selected drawing name is returned; otherwise drawing_name is empty (all drawings).

        :return: Dict with filter criteria ('attributes', 'excavation_types', 'feature_names', 'drawing_name', 'target_drawing').
        :rtype: Dict[str, Any]
        """
        filters = getattr(self, "_current_display_filters", None)
        if not filters:
            feature_names = []
            if hasattr(self, "feature_colors") and self.feature_colors:
                feature_names = sorted(list(self.feature_colors.keys()))
            filters = {
                "attributes": [
                    AttributeType.S.value,
                    AttributeType.P.value,
                    AttributeType.C.value,
                    AttributeType.SP.value,
                ],
                "excavation_types": [
                    ExcavationType.FEATURE.value,
                    ExcavationType.GRID.value,
                ],
                "feature_names": feature_names,
                "target_drawing": UILabels.FILTER_DRAWING_SELECTED,
            }
            self._current_display_filters = filters

        target_drawing_setting = filters.get("target_drawing", UILabels.FILTER_DRAWING_SELECTED)

        drawing_name = ""
        if target_drawing_setting == UILabels.FILTER_DRAWING_SELECTED:
            d_name = (
                self._get_target_drawing_name()
                if hasattr(self, "_get_target_drawing_name")
                else ""
            )
            if d_name != UILabels.DRAWING_UNSPECIFIED:
                drawing_name = d_name

        return {
            "attributes": list(filters.get("attributes", [])),
            "excavation_types": list(filters.get("excavation_types", [])),
            "feature_names": list(filters.get("feature_names", [])),
            "drawing_name": drawing_name,
            "target_drawing": target_drawing_setting,
        }

    def _push_focus_state_to_tool(self) -> None:
        """Push current Focus Mode state to CanvasDigitizingTool (Step3: one-way push).

        Called whenever Focus Mode is toggled or any filter setting changes,
        so the map tool never needs to call back into this dock widget to read UI state
        (see CanvasDigitizingTool.update_focus_state).
        """
        if getattr(self, "map_tool", None) is not None:
            self.map_tool.update_focus_state(
                self.is_focus_mode_active(), self.get_focus_category_filter()
            )

    def _on_focus_mode_toggled(self, checked: bool) -> None:
        """Handle Filter Mode toggle button click.

        :param checked: True if toggled ON, False if OFF.
        :type checked: bool
        """
        btn = getattr(self, "btn_filter", None) or getattr(self, "btn_focus_mode", None)
        if btn is not None:
            if checked:
                btn.setText(UILabels.BTN_FILTER_ON)
                btn.setStyleSheet(
                    "background-color: #1976D2; color: #FFFFFF; font-weight: bold; border-radius: 4px; padding: 4px;"
                )
            else:
                btn.setText(UILabels.BTN_FILTER_OFF)
                btn.setStyleSheet("")

        self._push_focus_state_to_tool()
        self.update_symbology_opacity()

    def _on_filter_settings_clicked(self) -> None:
        """Open DisplayFilterDialog to configure display filter parameters."""
        feature_names: List[str] = []
        if hasattr(self, "feature_colors") and self.feature_colors:
            feature_names = sorted(list(self.feature_colors.keys()))
        elif hasattr(self, "layer_manager") and getattr(self.layer_manager, "feature_colors", None):
            feature_names = sorted(list(self.layer_manager.feature_colors.keys()))

        current = dict(getattr(self, "_current_display_filters", {}))
        # If feature_names in filters is empty but we have registered features, default to all features
        if not current.get("feature_names") and feature_names:
            current["feature_names"] = list(feature_names)

        dlg = DisplayFilterDialog(
            parent=self,
            feature_names=feature_names,
            initial_filters=current,
        )
        if dlg.exec_() == QDialog.Accepted:
            self._current_display_filters = dlg.get_filters()
            self._push_focus_state_to_tool()
            if self.is_focus_mode_active():
                self.update_symbology_opacity()

    def _on_category_changed(self, *args: Any) -> None:
        """Synchronize symbology opacity, drawing visibility, point number, and
        点情報パネル status when category changes.

        Triggered whenever attribute type (S/P/C/SP), excavation type,
        feature name, or target drawing changes (see
        _on_excavation_type_changed / _on_feature_combo_changed below, both
        of which delegate here).

        T-0032: while an existing point is selected (self.selected_edit_point_id
        is not None), auto-numbering (_apply_next_point_number) is skipped so
        that changing 出土形態/遺構名/属性 while editing an existing point does
        not clobber its point_name/branch_no; only the SP<->QSpinBox widget
        visibility is refreshed (per T-0022/T-0023 value retention rules).
        """
        current_drawing = (
            self._get_target_drawing_name()
            if hasattr(self, "_get_target_drawing_name")
            else ""
        )
        if current_drawing and current_drawing != UILabels.DRAWING_UNSPECIFIED:
            self._ensure_drawing_visible(current_drawing)

        self._is_out_of_bounds = False

        if getattr(self, "selected_edit_point_id", None) is not None:
            self._update_point_name_widget_visibility()
        else:
            self._apply_next_point_number()

        self._push_focus_state_to_tool()
        if self.is_focus_mode_active():
            self.update_symbology_opacity()

        self._refresh_point_info_labels()
        self._update_point_info_status()

    def _update_feature_related_visibility(self) -> None:
        """Sync 遺構名セレクタ/作成ボタン/カラーピッカー visibility with the
        current excavation type + feature selection (T-0027, updated T-0032).
        """
        is_feature = self.combo_excavation_type.currentText() == ExcavationType.FEATURE.value
        self.row_feature_selector.setVisible(is_feature)
        self.row_feature_actions.setVisible(is_feature)
        if hasattr(self, "btn_manage_feature"):
            self.btn_manage_feature.setEnabled(is_feature)
        if hasattr(self, "btn_create_feature"):
            self.btn_create_feature.setEnabled(is_feature)
        if hasattr(self, "btn_color_picker") and self.btn_color_picker is not None:
            is_placeholder = self.combo_feature_name.currentText() in (
                UILabels.UNREGISTERED,
                getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成"),
                "",
            )
            self.btn_color_picker.setEnabled(is_feature and not is_placeholder)
            self._update_color_picker_button()

    def _on_excavation_type_changed(self, index: int) -> None:
        """Toggle feature name selector/create button/color picker based on excavation type.

        T-0038: also commits 出土形態/遺構名/属性記号 to the selected existing
        feature in real time (no-op in 新規モード or while loading, see
        _commit_attribute_fields_if_editing).
        """
        self._update_feature_related_visibility()
        self._on_category_changed()
        self._commit_attribute_fields_if_editing()

    def _on_feature_combo_changed(self, text: str) -> None:
        """Toggle create button/color picker when the feature selection changes.

        T-0038: also commits 出土形態/遺構名/属性記号 to the selected existing
        feature in real time (no-op in 新規モード or while loading, see
        _commit_attribute_fields_if_editing).
        """
        self._update_feature_related_visibility()
        self._on_category_changed()
        self._commit_attribute_fields_if_editing()

    def _restore_feature_names(self) -> None:
        """Extract existing unique feature names from points layer and populate combo box."""
        if not self.point_layer or not self.point_layer.isValid():
            return

        UIStyleHelper.populate_combo_from_layer_field(
            self.combo_feature_name,
            self.point_layer,
            "feature_name",
            leading_item=UILabels.UNREGISTERED,
            target_list=self.feature_name_list,
        )

    def register_new_feature_name(self, new_name: str) -> str:
        """Register a newly entered feature name into the combo box and select it."""
        clean_name = new_name.strip()
        idx = self.combo_feature_name.findText(clean_name)
        if idx >= 0:
            self.combo_feature_name.setCurrentIndex(idx)
        else:
            self.combo_feature_name.addItem(clean_name)
            self.feature_name_list.append(clean_name)
            self.combo_feature_name.setCurrentText(clean_name)
        return clean_name

    def _rename_and_recolor_feature(
        self, old_name: str, new_name: str, new_color: str
    ) -> None:
        """Update feature_name and color_code for all features matching old_name.

        FEAT-01: Renames and recolors features in point_layer, then refreshes
        combo_feature_name and internal state while suppressing real-time
        commit signals to prevent re-entrant attribute updates.
        """
        if not self.point_layer or not self.point_layer.isValid():
            return

        fields = self.point_layer.fields()
        feat_idx = fields.indexFromName("feature_name")
        color_idx = fields.indexFromName("color_code")

        if feat_idx == -1 or color_idx == -1:
            return

        updated_count = 0
        self.point_layer.startEditing()
        for feat in self.point_layer.getFeatures():
            curr_feat_name = safe_get_str(feat, "feature_name")
            if curr_feat_name == old_name:
                self.point_layer.changeAttributeValue(feat.id(), feat_idx, new_name)
                self.point_layer.changeAttributeValue(feat.id(), color_idx, new_color)
                updated_count += 1
        self.point_layer.commitChanges()

        # Defensively suppress real-time commit signals during UI updates
        prev_suppress = getattr(self, "_suppress_realtime_commit", False)
        self._suppress_realtime_commit = True
        self.combo_feature_name.blockSignals(True)
        try:
            # Update feature_name_list
            if hasattr(self, "feature_name_list"):
                if old_name in self.feature_name_list:
                    idx = self.feature_name_list.index(old_name)
                    self.feature_name_list[idx] = new_name
                elif new_name not in self.feature_name_list:
                    self.feature_name_list.append(new_name)

            # Update combo box items
            cur_text = self.combo_feature_name.currentText()
            found_idx = self.combo_feature_name.findText(old_name)
            if found_idx >= 0:
                self.combo_feature_name.setItemText(found_idx, new_name)
                if cur_text == old_name:
                    self.combo_feature_name.setCurrentIndex(found_idx)
            else:
                new_idx = self.combo_feature_name.findText(new_name)
                if new_idx < 0:
                    self.combo_feature_name.addItem(new_name)
                    new_idx = self.combo_feature_name.findText(new_name)
                if cur_text == old_name:
                    self.combo_feature_name.setCurrentIndex(new_idx)

            if self.combo_feature_name.currentText() == new_name:
                self.current_feature_color = QColor(new_color)
        finally:
            self.combo_feature_name.blockSignals(False)
            self._suppress_realtime_commit = prev_suppress

        self._update_point_info_status()

    def _on_manage_feature_clicked(self) -> None:
        """Open FeatureManageDialog to manage feature names and colors.

        Extracts existing unique (feature_name, color_code) pairs from point_layer,
        binds _rename_and_recolor_feature as callback, and on accept registers
        the newly created feature name.
        """
        feature_colors: Dict[str, str] = {}
        for name in getattr(self, "feature_name_list", []):
            if name and name not in (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成")):
                feature_colors[name] = "#FF5722"

        if self.point_layer and self.point_layer.isValid():
            for feat in self.point_layer.getFeatures():
                fname = safe_get_str(feat, "feature_name").strip()
                if fname and fname not in (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成")):
                    c_code = safe_get_str(feat, "color_code").strip()
                    if c_code:
                        feature_colors[fname] = c_code
                    elif fname not in feature_colors:
                        feature_colors[fname] = "#FF5722"

        cur_text = self.combo_feature_name.currentText().strip()
        initial_feature = cur_text if cur_text in feature_colors else None

        dlg = FeatureManageDialog(
            parent=self,
            feature_colors=feature_colors,
            on_update_callback=self._rename_and_recolor_feature,
            initial_feature=initial_feature,
        )
        UIStyleHelper.apply_theme(dlg)
        if dlg.exec_() == QDialog.Accepted:
            new_name = dlg.result_text.strip()
            if new_name:
                if hasattr(dlg, "result_color") and dlg.result_color:
                    self.current_feature_color = QColor(dlg.result_color)
                self.register_new_feature_name(new_name)

    _on_create_feature_clicked = _on_manage_feature_clicked

    def _update_color_picker_button(self) -> None:
        """Reflect current feature color on the picker button."""
        if hasattr(self, "btn_color_picker") and self.btn_color_picker is not None:
            if self.btn_color_picker.isEnabled():
                color_hex = self.current_feature_color.name()
            else:
                color_hex = "#9E9E9E"
            self.btn_color_picker.setStyleSheet(
                f"background-color: {color_hex}; color: #FFFFFF; font-weight: bold; border-radius: 4px; padding: 4px;"
            )

    def _pick_color(self) -> None:
        """Open QColorDialog to select a feature group color.

        T-0027: applying the color to all points of the selected feature now
        happens immediately once the dialog is accepted (QColorDialog.getColor()
        only returns a valid color on OK), replacing the former separate
        "グループ一括適用" (btn_apply_color) confirmation step.
        """
        color = QColorDialog.getColor(
            self.current_feature_color, self, UIDialogTitles.COLOR_PICKER
        )
        if color.isValid():
            self.current_feature_color = color
            self._update_color_picker_button()
            self._apply_feature_color_group()

    def _apply_feature_color_group(self) -> None:
        """Apply the selected color to all existing points belonging to the selected feature."""
        if not self.point_layer or not self.point_layer.isValid():
            return

        selected_feat = self.combo_feature_name.currentText()
        if selected_feat in (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成")):
            QMessageBox.information(
                self,
                UIMessages.MSG_TITLE_INFO,
                UIMessages.MSG_SELECT_FEATURE_NAME,
            )
            return

        color_hex = self.current_feature_color.name()
        field_idx = self.point_layer.fields().indexFromName("color_code")

        updated_count = 0
        self.point_layer.startEditing()
        for feat in self.point_layer.getFeatures():
            if safe_get_str(feat, "feature_name") == selected_feat:
                self.point_layer.changeAttributeValue(feat.id(), field_idx, color_hex)
                updated_count += 1
        self.point_layer.commitChanges()

        self.iface.messageBar().pushMessage(
            UIMessages.MSG_COLOR_APPLIED_TITLE,
            UIMessages.MSG_COLOR_APPLIED.format(
                feature=selected_feat, count=updated_count, color=color_hex
            ),
            level=Qgis.MessageLevel.Info,
            duration=4,
        )

    def get_digitizing_input_state(self) -> Dict[str, Any]:
        """Collect current input parameters for digitizing validation.

        T-0027: feature creation is now performed explicitly beforehand via
        the 作成 button/FeatureCreateDialog (see _on_create_feature_clicked),
        not implicitly at click-time. If excavation_type is 遺構 and the
        "新規作成" placeholder is still selected (no concrete feature chosen
        yet), digitizing is blocked (see _is_feature_name_missing/
        _update_point_info_status, T-0032).
        """
        d_name = (
            self._get_target_drawing_name()
            if hasattr(self, "_get_target_drawing_name")
            else ""
        )
        if d_name == UILabels.DRAWING_UNSPECIFIED:
            d_name = ""
        ex_type = self.combo_excavation_type.currentText()
        feat_name = self.combo_feature_name.currentText().strip()
        is_placeholder_feat = (not feat_name) or feat_name in (
            UILabels.UNREGISTERED,
            getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成"),
        )

        attr_type = self._get_attribute_value()
        pname, branch = self._get_current_point_name_and_branch()

        if not pname:
            return {
                "can_click": False,
                "error_message": UIMessages.ERR_POINT_NAME_REQUIRED,
            }

        if ex_type == ExcavationType.FEATURE.value and is_placeholder_feat:
            return {
                "can_click": False,
                "error_message": UIMessages.ERR_NEW_FEATURE_REQUIRED,
            }

        return {
            "can_click": True,
            "drawing_name": d_name,
            "excavation_type": ex_type,
            "feature_name": feat_name,
            "color_code": self.current_feature_color.name(),
            "attribute_type": attr_type,
            "point_name": pname,
            "branch_no": branch,
        }

    def _is_sp_attribute(self) -> bool:
        """Return True when the currently selected attribute code is 'SP'.

        :return: True if combo_attribute is currently set to AttributeType.SP.value.
        :rtype: bool
        """
        return hasattr(self, "combo_attribute") and self._get_attribute_value() == AttributeType.SP.value

    def _update_point_name_widget_visibility(self) -> None:
        """Show the widget matching the current attribute type, hide the other.

        S/P/C attributes use the QSpinBox (edit_point_name); SP uses the
        free-text QLineEdit (edit_point_name_sp). See T-0022.

        T-0036: also keeps the 自動連番/解除 toggle (tab2_autonum_container)
        in sync with the SP selection, since SP already has its own
        always-manual numbering behavior (see _update_autonum_toggle_for_sp).
        """
        is_sp = self._is_sp_attribute()
        self.edit_point_name.setVisible(not is_sp)
        self.edit_point_name_sp.setVisible(is_sp)
        self._update_autonum_toggle_for_sp(is_sp)

    def _update_autonum_toggle_for_sp(self, is_sp: bool) -> None:
        """Force the 自動連番/解除 toggle to 解除+disabled while SP is selected.

        SP attributes never use the QSpinBox auto-numbering widget (they use
        edit_point_name_sp, a free-text field awaiting manual entry per
        T-0022/_apply_next_point_number), so the 自動連番/解除 toggle would be
        meaningless while SP is active. T-0036: automatically select 解除
        (index 1) and disable both buttons in that case; re-enable them once
        a non-SP attribute is selected again.

        T-0047 fix: when the attribute switches away from SP back to a
        non-SP attribute (S/P/C), the 自動連番/解除 toggle -- which SP had
        forced to 解除+disabled -- is automatically restored to 自動連番
        (index 0), re-triggering _on_tab2_autonum_mode_changed(0) so a point
        number is (re-)numbered immediately. This only applies to the
        SP->非SP transition (detected via was_forced_by_sp, i.e. the toggle
        was still disabled just before this call); switching between two
        non-SP attributes (e.g. S -> P) never forces the toggle here, so a
        deliberate 解除 selection made while already on a non-SP attribute is
        left untouched. The restore is further skipped while an existing
        point is selected for editing (selected_edit_point_id is not None)
        so it never clobbers that point's already-entered point_name.

        :param is_sp: Whether the currently selected attribute is SP.
        :type is_sp: bool
        """
        if not hasattr(self, "tab2_autonum_buttons"):
            return
        was_forced_by_sp = not self.tab2_autonum_buttons[0].isEnabled()
        if is_sp:
            if not self.tab2_autonum_buttons[1].isChecked():
                self.tab2_autonum_buttons[1].setChecked(True)
            self.tab2_autonum_buttons[0].setEnabled(False)
            self.tab2_autonum_buttons[1].setEnabled(False)
        else:
            self.tab2_autonum_buttons[0].setEnabled(True)
            self.tab2_autonum_buttons[1].setEnabled(True)
            is_editing_existing = getattr(self, "selected_edit_point_id", None) is not None
            if (
                was_forced_by_sp
                and not is_editing_existing
                and not self.tab2_autonum_buttons[0].isChecked()
            ):
                self.tab2_autonum_buttons[0].setChecked(True)

    def _on_tab2_autonum_mode_changed(self, index: int) -> None:
        """Handle 自動連番(0)/解除(1) toggle changes in the 新規モード button area.

        自動連番 re-applies the existing "直前打刻追従型" auto-numbering
        (core_logic.get_next_point_number, unchanged) to edit_point_name
        immediately. 解除 leaves the current edit_point_name value untouched
        so the user can type a point name manually; see _apply_next_point_number
        for where this flag is consulted to skip the auto-overwrite.

        :param index: 0 for 自動連番, 1 for 解除.
        :type index: int
        """
        self.tab2_autonum_mode = "auto" if index == 0 else "release"
        if self.tab2_autonum_mode == "auto" and not self._is_sp_attribute():
            self.edit_point_name.setValue(self._get_next_point_number())
            self._refresh_point_info_labels()

    def _on_tab2_mode_changed(self, index: int) -> None:
        """Handle tab2先頭の新規(0)/編集(1)モードトグルの切り替え (T-0036).

        This toggles which button area is visible inside 点情報パネル
        (新規モード=自動連番/解除トグル、編集モード=削除ボタンのみ). The actual
        canvas click routing (which of _on_canvas_clicked /
        _on_existing_point_selected fires) is driven by
        CanvasDigitizingTool._handle_digitize_click reading
        self.tab2_current_mode directly (T-0037); this method itself only
        updates the mode flag and the panel's visible button area.

        :param index: 0 for 新規, 1 for 編集.
        :type index: int
        """
        self.tab2_current_mode = "new" if index == 0 else "edit"
        self._is_out_of_bounds = False
        is_new = (self.tab2_current_mode == "new")
        if hasattr(self, "widget_new_mode_actions"):
            self.widget_new_mode_actions.setVisible(is_new)
        if hasattr(self, "widget_edit_mode_actions"):
            self.widget_edit_mode_actions.setVisible(not is_new)
            
        # Disable widgets in edit mode to prevent accidental input
        if hasattr(self, "edit_point_name"): self.edit_point_name.setEnabled(is_new)
        if hasattr(self, "edit_point_name_sp"): self.edit_point_name_sp.setEnabled(is_new)
        if hasattr(self, "edit_branch_no"): self.edit_branch_no.setEnabled(is_new)
        if hasattr(self, "group_attribute_panel"): self.group_attribute_panel.setEnabled(is_new)
        # T-0042: switching back to 新規モード while an edit-mode selection is
        # still held (selected_edit_point_id) leaves the duplicate-check
        # exclusion and edit_point_name value stale, letting a duplicate
        # point-name slip through on the next digitize click. Clear the
        # selection state via the existing _reset_point_selection() (same
        # helper _on_blank_click_in_edit_mode() uses) so the point-name is
        # recalculated and the exclusion is dropped.
        if self.tab2_current_mode == "new" and getattr(self, "selected_edit_point_id", None) is not None:
            self._reset_point_selection()

    def _get_next_point_number(self) -> int:
        """Calculate next point number based on current excavation type and feature name.

        Queries the point layer on-demand for the group matching the current
        excavation_type/feature_name selection (see core_logic.get_next_point_number
        for the "直前打刻追従型" (max point_id) numbering strategy).
        """
        ex_type = self.combo_excavation_type.currentText()
        feat_name = ""
        if ex_type == ExcavationType.FEATURE.value:
            feat_name = self.combo_feature_name.currentText().strip()
            if feat_name in (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成")):
                feat_name = ""

        return get_next_point_number(
            self.point_layer,
            ex_type,
            feat_name,
        )

    def _get_current_point_name_and_branch(self) -> Tuple[str, str]:
        """Read the current point-name (SP text or S/P/C spinbox) and branch number.

        :return: Tuple of (point_name, branch_no) trimmed strings.
        :rtype: Tuple[str, str]
        """
        pname = (
            self.edit_point_name_sp.text().strip()
            if self._is_sp_attribute()
            else str(self.edit_point_name.value())
        )
        branch = self.edit_branch_no.text().strip() if hasattr(self, "edit_branch_no") else ""
        return pname, branch

    def _is_feature_name_missing(self) -> bool:
        """Return True when excavation_type is 遺構 but no concrete feature is selected yet.

        :return: True if 遺構名未指定 (エラー優先順位1位, T-0032).
        :rtype: bool
        """
        if not hasattr(self, "combo_excavation_type"):
            return False
        if self.combo_excavation_type.currentText() != ExcavationType.FEATURE.value:
            return False
        feat_text = self.combo_feature_name.currentText().strip()
        return (not feat_text) or feat_text in (
            UILabels.UNREGISTERED,
            getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成"),
        )

    def _check_realtime_duplicate(self) -> Optional[str]:
        """Real-time duplicate check against the currently entered category/point-name state.

        Excludes the currently selected existing point (if any) from the scan,
        so editing a point in-place is never flagged as a duplicate of itself.

        :return: Formatted identifier (core_logic.build_point_ident) if a
            duplicate exists, otherwise None.
        :rtype: Optional[str]
        """
        if not self.point_layer or not self.point_layer.isValid():
            return None

        pname, branch = self._get_current_point_name_and_branch()
        if not pname:
            return None

        ex_type = self.combo_excavation_type.currentText()
        feat_name = self.combo_feature_name.currentText().strip()
        if feat_name in (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成")):
            feat_name = ""
        drawing_name = (
            self._get_target_drawing_name()
            if hasattr(self, "_get_target_drawing_name")
            else ""
        )
        if drawing_name == UILabels.DRAWING_UNSPECIFIED:
            drawing_name = ""

        is_dup = check_point_duplicate(
            self.point_layer,
            ex_type,
            feat_name,
            pname,
            branch,
            drawing_name,
            exclude_feature_id=getattr(self, "selected_edit_point_id", None),
        )
        if not is_dup:
            return None
        return build_point_ident(ex_type, feat_name, pname, branch, drawing_name)

    def _validate_drawing_bounds(
        self, drawing_name: str, map_point: QgsPointXY
    ) -> Tuple[bool, Optional[Tuple[float, float]]]:
        """Validate whether map_point falls within the pixel bounds of drawing_name.

        :param drawing_name: Target drawing name, or empty / DRAWING_UNSPECIFIED.
        :type drawing_name: str
        :param map_point: Canvas/map coordinate point.
        :type map_point: QgsPointXY
        :return: (True, (px, py)) if within bounds; (True, (0.0, 0.0)) if drawing
            is unspecified/empty; (False, None) if out of bounds or missing affine params.
        :rtype: Tuple[bool, Optional[Tuple[float, float]]]
        """
        if not drawing_name or drawing_name == UILabels.DRAWING_UNSPECIFIED:
            return True, (0.0, 0.0)

        if not self.layer_manager:
            return False, None

        meta = self.layer_manager.load_image_metadata()
        layer_meta = meta.get(drawing_name) if meta else None
        if not layer_meta:
            return False, None

        affine_params = layer_meta.get("affine_params")
        if not affine_params:
            return False, None

        px, py = pixel_from_affine(affine_params, map_point)

        # Find raster layer to get width and height
        raster_layer = None
        root = QgsProject.instance().layerTreeRoot()
        if root:
            image_group = root.findGroup("画像ファイル")
            if image_group:
                for tree_layer in image_group.findLayers():
                    l = tree_layer.layer()
                    if l and l.isValid() and l.name() == drawing_name:
                        raster_layer = l
                        break
        if raster_layer is None:
            layers = QgsProject.instance().mapLayersByName(drawing_name)
            if layers and layers[0].isValid():
                raster_layer = layers[0]

        if raster_layer is None or not hasattr(raster_layer, "width") or not hasattr(raster_layer, "height"):
            return False, None

        width = raster_layer.width()
        height = raster_layer.height()
        if 0 <= px <= width and 0 <= py <= height:
            return True, (px, py)
        return False, None

    def _check_realtime_out_of_bounds(self) -> bool:
        """Check whether the currently selected existing point falls outside
        the bounds of the currently selected drawing.

        :return: True if out of bounds (or missing affine params), False otherwise.
        :rtype: bool
        """
        if getattr(self, "selected_edit_point_id", None) is None:
            return False
        if not self.point_layer or not self.point_layer.isValid():
            return False

        drawing_name = (
            self._get_target_drawing_name()
            if hasattr(self, "_get_target_drawing_name")
            else ""
        )
        if not drawing_name or drawing_name == UILabels.DRAWING_UNSPECIFIED:
            return False

        feat = self.point_layer.getFeature(self.selected_edit_point_id)
        if not feat.isValid() or not feat.hasGeometry():
            return False

        map_point = feat.geometry().asPoint()
        is_valid, _ = self._validate_drawing_bounds(drawing_name, map_point)
        return not is_valid

    def _build_point_info_text(self, status_text: str) -> str:
        """Compose the flat multi-line 点情報パネル summary text (T-0033).

        Combines the status line (新規点作成/既設点編集/エラー, no longer given
        a dedicated banner style) with the 出土形態/点名+枝番/XY座標 summary
        lines computed by _refresh_point_info_labels (stored on
        self._point_info_summary), in the same order used since T-0032.

        :param status_text: Current status line text.
        :type status_text: str
        :return: Newline-joined 4-line summary text.
        :rtype: str
        """
        summary = getattr(self, "_point_info_summary", None) or {}
        return "\n".join(
            [
                status_text,
                f"{UILabels.LBL_INFO_GROUP_OR_FEATURE} {summary.get('group', '-')}",
                f"{UILabels.LBL_INFO_POINT_BRANCH} {summary.get('pointname', '-')}",
                f"{UILabels.LBL_INFO_COORDS} {summary.get('coords', '-')}",
            ]
        )

    def _update_error_borders(self) -> None:
        """Apply/remove red error-highlight borders on the fields directly
        implicated by the current 点情報パネル error state (T-0033):
        combo_feature_name for 遺構名未指定, combo_drawing_name for
        図面範囲外, and whichever point-name input is currently active
        (edit_point_name or edit_point_name_sp) for 点名重複.
        """
        if hasattr(self, "combo_feature_name"):
            UIStyleHelper.set_error_border(self.combo_feature_name, self._is_feature_name_missing())

        if hasattr(self, "combo_drawing_name"):
            is_editing = getattr(self, "selected_edit_point_id", None) is not None
            is_oob = (
                self._check_realtime_out_of_bounds()
                if is_editing
                else getattr(self, "_is_out_of_bounds", False)
            )
            UIStyleHelper.set_error_border(self.combo_drawing_name, is_oob)

        if hasattr(self, "edit_point_name") and hasattr(self, "edit_point_name_sp"):
            is_dup = bool(self._check_realtime_duplicate())
            is_sp = self._is_sp_attribute()
            UIStyleHelper.set_error_border(self.edit_point_name, is_dup and not is_sp)
            UIStyleHelper.set_error_border(self.edit_point_name_sp, is_dup and is_sp)

    def _update_point_info_status(self) -> None:
        """Refresh the 点情報パネル summary text/border color (T-0033: flat
        multi-line QLabel inside a create_status_panel()-style left-border
        QFrame, replacing T-0032's separate banner + whole-panel tint).

        Priority order per the design: 遺構名未指定 > 図面範囲外 > 点名重複エラー > normal
        (新規点作成=info/blue / 既設点編集=warning/orange -- reusing
        QFrame[statusType="warning"] since no dedicated "editing" style is
        defined). Refreshes the per-field red error borders (see
        _update_error_borders, T-0033) and sets self._point_info_has_error,
        which _commit_point_identity_if_editing/_commit_attribute_fields_if_editing
        (T-0038) consult to skip committing to the selected feature while an
        error is active (replacing the former btn_rename_point/
        btn_update_attribute setEnabled() guard).
        """
        if not hasattr(self, "lbl_point_info_status"):
            return

        is_editing = getattr(self, "selected_edit_point_id", None) is not None
        tooltip = ""

        if self._is_feature_name_missing():
            status_type = "error"
            text = UILabels.STATUS_ERR_FEATURE_REQUIRED
            self._point_info_has_error = True
        elif is_editing and self._check_realtime_out_of_bounds():
            status_type = "error"
            text = UILabels.STATUS_ERR_OUT_OF_BOUNDS
            self._point_info_has_error = True
        elif not is_editing and getattr(self, "_is_out_of_bounds", False):
            status_type = "error"
            text = UILabels.STATUS_ERR_OUT_OF_BOUNDS
            self._point_info_has_error = True
        else:
            dup_ident = self._check_realtime_duplicate()
            if dup_ident:
                status_type = "error"
                text = UILabels.STATUS_ERR_DUPLICATE
                tooltip = dup_ident
                self._point_info_has_error = True
            else:
                self._point_info_has_error = False
                if is_editing:
                    status_type, text = "warning", UILabels.STATUS_EDIT_POINT
                else:
                    status_type, text = "info", UILabels.STATUS_NEW_POINT

        full_text = self._build_point_info_text(text)
        UIStyleHelper.update_status_panel(
            self.panel_point_info, self.lbl_point_info_status, full_text, status_type
        )
        self.lbl_point_info_status.setToolTip(tooltip)

        self._update_error_borders()

    def _commit_fields_to_feature(self, updates: Dict[str, Any]) -> bool:
        """Write ``updates`` (point_layer field name -> new value) to the
        currently selected existing feature and refresh dependent state
        (T-0038: shared commit core extracted from the former
        btn_rename_point/_on_rename_point_clicked and
        btn_update_attribute/_on_update_attribute_clicked click handlers).

        Callers are responsible for validating the values beforehand (see
        _commit_point_identity_if_editing/_commit_attribute_fields_if_editing,
        which both consult self._point_info_has_error before calling this);
        this method performs no validation itself and always attempts the
        write once called.

        :param updates: Mapping of point_layer field name to new value.
        :type updates: Dict[str, Any]
        :return: True if the write was attempted (an existing feature was
            selected and point_layer is available), False otherwise.
        :rtype: bool
        """
        if self.selected_edit_point_id is None or not self.point_layer:
            return False

        with (self.busy_interaction_guard() if hasattr(self, "busy_interaction_guard") else nullcontext()):
            field_names = self.point_layer.fields().names()
            self.point_layer.startEditing()
            for field_name, value in updates.items():
                if field_name in field_names:
                    idx = field_names.index(field_name)
                    self.point_layer.changeAttributeValue(self.selected_edit_point_id, idx, value)
            self.point_layer.commitChanges()

            if self._selected_point_data is not None:
                self._selected_point_data.update(updates)

            if self.is_focus_mode_active():
                self.update_symbology_opacity()

        return True

    def _commit_point_identity_if_editing(self, *args: Any) -> None:
        pass

    def _commit_attribute_fields_if_editing(self, *args: Any) -> None:
        """Real-time commit of 出土形態/遺構名/カラー/属性記号 to the selected
        existing feature (T-0038).

        Connected to combo_attribute's currentIndexChanged and invoked from
        _on_excavation_type_changed/_on_feature_combo_changed (which wrap
        combo_excavation_type/combo_feature_name). No-op under the same
        conditions as _commit_point_identity_if_editing (new-mode, still
        loading, or a live validation error).

        点名/枝番はここでは扱わない(_commit_point_identity_if_editing側の責務)。

        :param args: Unused signal payload (int for currentIndexChanged,
            str for currentTextChanged).
        :type args: Any
        """
        if getattr(self, "_suppress_realtime_commit", False):
            return
        if self.selected_edit_point_id is None or not self.point_layer:
            return
        if getattr(self, "_point_info_has_error", False):
            return

        raw_drawing = (
            self._get_target_drawing_name()
            if hasattr(self, "_get_target_drawing_name")
            else ""
        )
        drawing_name = "" if raw_drawing == UILabels.DRAWING_UNSPECIFIED else raw_drawing

        ex_type = self.combo_excavation_type.currentText()
        feat_name = self.combo_feature_name.currentText().strip()
        if feat_name in (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成")):
            feat_name = ""
        is_feature = ex_type == ExcavationType.FEATURE.value
        attr_value = self._get_attribute_value()

        updates: Dict[str, Any] = {
            "drawing_name": drawing_name,
            "excavation_type": ex_type,
            "feature_name": feat_name if is_feature else "",
            "color_code": self.current_feature_color.name() if is_feature else "",
            "attribute_type": attr_value,
        }

        # 新旧で図面が変化した場合のみ、_validate_drawing_bounds でピクセル座標を再計算し updates["pixel_x"] と pixel_y を更新する
        old_drawing_name = ""
        if self._selected_point_data is not None:
            old_drawing_name = str(self._selected_point_data.get("drawing_name") or "").strip()

        if drawing_name != old_drawing_name:
            feat = self.point_layer.getFeature(self.selected_edit_point_id)
            if feat.isValid() and feat.hasGeometry():
                map_point = feat.geometry().asPoint()
                is_valid, px_coords = self._validate_drawing_bounds(drawing_name, map_point)
                if not is_valid:
                    self._update_point_info_status()
                    return
                if px_coords is not None:
                    updates["pixel_x"] = px_coords[0]
                    updates["pixel_y"] = px_coords[1]

        if self._commit_fields_to_feature(updates):
            self._refresh_point_info_labels(override=self._selected_point_data)
            self._update_point_info_status()

    def _on_point_identity_changed(self, *args: Any) -> None:
        """Handle edit_point_name(_sp) value changes: refresh summary + status.

        :param args: Unused signal payload (valueChanged(int)/textChanged(str)).
        :type args: Any
        """
        self._refresh_point_info_labels()
        self._update_point_info_status()

    def _refresh_point_info_labels(self, override: Optional[Dict[str, Any]] = None) -> None:
        """Recompute the 出土形態/点名+枝番/XY座標 summary lines for 点情報パネル
        (T-0027/T-0032; T-0033: stored on self._point_info_summary and
        rendered into the flat multi-line panel text by
        _update_point_info_status/_build_point_info_text rather than being
        set directly on now-removed per-line QLabels).

        :param override: When set (an existing point is selected), the
            loaded feature data dict (as emitted by
            CanvasDigitizingTool.existing_point_selected) is displayed
            instead of the live category-widget selections.
        :type override: Optional[Dict[str, Any]]
        """
        if not hasattr(self, "lbl_point_info_status"):
            return

        if override is not None:
            ex_type = str(override.get("excavation_type") or ExcavationType.GRID.value)
            if ex_type == ExcavationType.FEATURE.value:
                group_label = str(override.get("feature_name") or "") or UILabels.UNREGISTERED
            else:
                group_label = ExcavationType.GRID.value
            pname = str(override.get("point_name") or "")
            branch = str(override.get("branch_no") or "")
            cx = override.get("canvas_x")
            cy = override.get("canvas_y")
            if cx is not None and cy is not None:
                survey_x, survey_y = to_survey_coords(float(cx), float(cy))
                coords_text = f"X: {survey_x:.3f}  Y: {survey_y:.3f}"
            else:
                coords_text = "-"
        else:
            ex_type = (
                self.combo_excavation_type.currentText()
                if hasattr(self, "combo_excavation_type")
                else ExcavationType.GRID.value
            )
            if ex_type == ExcavationType.FEATURE.value:
                group_label = (
                    self.combo_feature_name.currentText()
                    if hasattr(self, "combo_feature_name")
                    else UILabels.UNREGISTERED
                )
            else:
                group_label = ExcavationType.GRID.value
            pname, branch = self._get_current_point_name_and_branch()
            coords_text = "-"

        pn_display = f"{pname} {branch}".strip() if pname else ""
        self._point_info_summary = {
            "group": group_label or "-",
            "pointname": pn_display or "-",
            "coords": coords_text,
        }

    def _apply_next_point_number(self) -> None:
        """Refresh the point-name entry widget(s) for the current attribute/category selection.

        For S/P/C attributes, auto-increments the QSpinBox using the
        "直前打刻追従型" numbering logic. For SP, auto-numbering is skipped
        entirely and the free-text QLineEdit is cleared, awaiting manual entry.
        T-0027: also refreshes the 点情報パネル preview labels.

        T-0036: for S/P/C attributes, the QSpinBox auto-increment is further
        gated by the 自動連番/解除 toggle (tab2_autonum_mode) -- while 解除 is
        selected, the current edit_point_name value is left untouched instead
        of being overwritten, so the user can type a point name manually
        (mirrors, but does not replace, the SP-only manual-entry path above).
        """
        self._update_point_name_widget_visibility()
        if self._is_sp_attribute():
            self.edit_point_name_sp.clear()
        elif getattr(self, "tab2_autonum_mode", "auto") == "auto":
            next_num = self._get_next_point_number()
            self.edit_point_name.setValue(next_num)
        self._refresh_point_info_labels()

    @pyqtSlot(str)
    def _on_branch_text_changed(self, text: str) -> None:
        """Handle branch number cleared to increment point number if previously digitized with branch."""
        if not text.strip() and self._has_digitized_with_branch:
            self._apply_next_point_number()
            self._has_digitized_with_branch = False
        self._on_point_identity_changed()

    def _on_canvas_clicked(self, map_point: QgsPointXY) -> None:
        """Handle a plain (non-hit) click on the main canvas from CanvasDigitizingTool.

        Validates the current digitizing input state, resolves duplicate
        checks, builds the feature via core_logic.build_digitized_feature(),
        and writes it to point_layer. This consolidates logic that
        previously lived in CanvasDigitizingTool._handle_digitize_click
        (Step3: event-driven decoupling — map_tool.py now only reports
        "canvas was clicked here").

        T-0032: the former QMessageBox-based duplicate-error prompt is
        removed; digitizing is silently blocked (no dialog) whenever the
        live 点情報パネル status would show an error (遺構名未指定 or 点名重複),
        since that state is already visible to the user via the panel's
        color/status band before they click.

        T-0037: this handler is now only reached in 新規(new) mode
        (CanvasDigitizingTool._handle_digitize_click routes clicks to
        canvas_clicked without any existing-feature snap check while in
        new mode, and does not call this handler at all while in 編集(edit)
        mode). The former "blank click while a point is selected deselects
        it" behavior (T-0027) has been removed accordingly; selection
        clearing is now only triggered explicitly (e.g. the dock's reset
        button), never by a plain canvas click.

        T-0040: when the 自動連番/解除 toggle is set to 解除 (including while
        it is forced to 解除 by an SP attribute selection, see
        _update_autonum_toggle_for_sp), the click is instead routed to
        _handle_release_mode_click, which pops up PointNameEntryDialog at
        the click location to collect 点名/枝番 instead of relying on the
        panel's (possibly stale/empty) edit_point_name(_sp) value.

        :param map_point: Click location in standard mathematical/canvas coordinates.
        :type map_point: QgsPointXY
        """
        if not self.point_layer or not self.point_layer.isValid():
            return

        if getattr(self, "tab2_autonum_mode", "auto") == "release":
            self._handle_release_mode_click(map_point)
            return

        # 1. Retrieve and validate current digitizing input state
        state = self.get_digitizing_input_state()
        if not state.get("can_click", False):
            return

        # 2. Real-time error checks (遺構名未指定 / 点名重複); replaces the
        # former QMessageBox.warning() duplicate-error prompt (T-0032).
        if self._is_feature_name_missing() or self._check_realtime_duplicate():
            self._update_point_info_status()
            return

        # Spatial validation for drawing bounds
        drawing_name = state.get("drawing_name", "")
        is_valid, _ = self._validate_drawing_bounds(drawing_name, map_point)
        if not is_valid:
            self._is_out_of_bounds = True
            self._update_point_info_status()
            return
        self._is_out_of_bounds = False

        self._create_digitized_point_from_state(state, map_point)

    def _handle_release_mode_click(self, map_point: QgsPointXY) -> None:
        """Handle a plain canvas click while 自動連番/解除 is set to 解除 (T-0040).

        Pops up PointNameEntryDialog near the click location so the user can
        enter 点名/枝番 explicitly (instead of relying on the panel's
        edit_point_name(_sp) value, which 解除 mode leaves untouched/cleared
        rather than auto-filled -- see _apply_next_point_number). 出土形態・
        遺構名・属性・色・対象図面 are taken from the panel's current values,
        unchanged. On dialog cancel, no feature is created.

        :param map_point: Click location in standard mathematical/canvas coordinates.
        :type map_point: QgsPointXY
        """
        if self._is_feature_name_missing():
            self._update_point_info_status()
            return

        drawing_name = (
            self._get_target_drawing_name()
            if hasattr(self, "_get_target_drawing_name")
            else ""
        )
        if drawing_name == UILabels.DRAWING_UNSPECIFIED:
            drawing_name = ""

        # Spatial validation for drawing bounds
        is_valid, _ = self._validate_drawing_bounds(drawing_name, map_point)
        if not is_valid:
            self._is_out_of_bounds = True
            self._update_point_info_status()
            return
        self._is_out_of_bounds = False

        excavation_type = self.combo_excavation_type.currentText()
        feature_name = self.combo_feature_name.currentText()
        if feature_name == UILabels.FEATURE_NEW_OPTION:
            feature_name = ""

        is_sp = self._is_sp_attribute()
        last_point_name = self._get_last_created_point_name(excavation_type, feature_name, is_sp)

        dlg = PointNameEntryDialog(
            self.point_layer,
            excavation_type,
            feature_name,
            drawing_name,
            is_sp,
            self,
            initial_point_name=last_point_name,
        )
        UIStyleHelper.apply_theme(dlg)
        self._position_dialog_near_map_point(dlg, map_point)
        if dlg.exec_() != QDialog.Accepted:
            return

        point_name, branch_no = dlg.get_values()

        state = {
            "drawing_name": drawing_name,
            "excavation_type": excavation_type,
            "feature_name": feature_name,
            "color_code": self.current_feature_color.name(),
            "attribute_type": self._get_attribute_value(),
            "point_name": point_name,
            "branch_no": branch_no,
        }
        self._create_digitized_point_from_state(state, map_point)

    def _get_last_created_point_name(
        self, excavation_type: str, feature_name: str, is_sp: bool
    ) -> str:
        """Return the 点名 of the most recently digitized point within the
        given 出土形態/遺構名 group (largest point_id), for use as the initial
        value preset of PointNameEntryDialog (T-0041).

        Mirrors the group-matching loop in core_logic.get_next_point_number
        (find the feature with the max point_id among those matching
        excavation_type/feature_name), but returns the raw latest point_name
        string instead of computing the next auto-numbered value, and
        restricts the match to features whose attribute_type is (not) SP per
        ``is_sp`` so the preset always matches the widget
        PointNameEntryDialog will show (QSpinBox for non-SP, free-text for SP).

        :param excavation_type: ExcavationType.GRID.value or ExcavationType.FEATURE.value.
        :type excavation_type: str
        :param feature_name: 遺構名 (used when excavation_type is 遺構).
        :type feature_name: str
        :param is_sp: True to match SP-attribute points only, False to match
            non-SP (S/P/C) points only.
        :type is_sp: bool
        :return: Latest matching 点名 as a string, or "" if none exists yet.
        :rtype: str
        """
        if not self.point_layer or not self.point_layer.isValid():
            return ""

        max_point_id = None
        latest_point_name = None
        for feat in self.point_layer.getFeatures():
            ex_type = safe_get_str(feat, "excavation_type")
            if excavation_type == ExcavationType.GRID.value:
                if ex_type != ExcavationType.GRID.value:
                    continue
            else:
                f_name = safe_get_str(feat, "feature_name")
                if ex_type != ExcavationType.FEATURE.value or f_name != feature_name:
                    continue

            feat_is_sp = safe_get_str(feat, "attribute_type") == AttributeType.SP.value
            if feat_is_sp != is_sp:
                continue

            pid = feat["point_id"]
            if pid is None or not isinstance(pid, int):
                continue
            if max_point_id is None or pid > max_point_id:
                max_point_id = pid
                latest_point_name = feat["point_name"]

        return "" if latest_point_name is None else str(latest_point_name)

    def _position_dialog_near_map_point(self, dlg: QDialog, map_point: QgsPointXY) -> None:
        """Move ``dlg`` to appear near the screen position of ``map_point`` on the main canvas.

        Converts the clicked map coordinate to canvas pixel coordinates via
        the main canvas's coordinate transform (mirrors the
        toCanvasCoordinates() pattern used by the QgsMapCanvasItem-based
        markers in map_tool.py), then to a global screen position via
        QWidget.mapToGlobal(). As with any QDialog, the window manager is
        not guaranteed to honor the exact requested position.

        :param dlg: Dialog to reposition.
        :type dlg: QDialog
        :param map_point: Click location in map/canvas coordinates.
        :type map_point: QgsPointXY
        """
        if not hasattr(self, "map_tool") or not self.map_tool or not hasattr(self.map_tool, "canvas"):
            return
        canvas = self.map_tool.canvas
        try:
            from qgis.PyQt.QtCore import QPoint

            canvas_pt = canvas.getCoordinateTransform().transform(map_point)
            local_pt = QPoint(round(canvas_pt.x()), round(canvas_pt.y()))
            dlg.move(canvas.mapToGlobal(local_pt))
        except Exception:
            # Best-effort positioning only; fall back to Qt's default
            # placement if the canvas/coordinate transform is unavailable.
            pass

    def _create_digitized_point_from_state(self, state: Dict[str, Any], map_point: QgsPointXY) -> None:
        """Build and insert a new digitized point feature from a resolved input state dict.

        Extracted (T-0040) from the tail of _on_canvas_clicked so both the
        自動連番 flow (state built from get_digitizing_input_state) and the
        解除 flow (state built in _handle_release_mode_click from
        PointNameEntryDialog's values) share the same feature-creation code.

        :param state: Dict with drawing_name/excavation_type/feature_name/
            color_code/attribute_type/point_name/branch_no keys (see
            get_digitizing_input_state).
        :type state: Dict[str, Any]
        :param map_point: Click location in standard mathematical/canvas coordinates.
        :type map_point: QgsPointXY
        """
        drawing_name = state.get("drawing_name", "")
        if drawing_name == UILabels.DRAWING_UNSPECIFIED:
            drawing_name = ""
        excavation_type = state["excavation_type"]
        feature_name = state["feature_name"]
        color_code = state["color_code"]
        attribute_type = state["attribute_type"]
        point_name = state["point_name"]
        branch_no = state["branch_no"]

        # 1. Determine next point_id
        next_point_id = get_next_point_id(self.point_layer)

        # 2. Resolve pixel coordinates on the source drawing via the affine adapter
        _, coords = self._validate_drawing_bounds(drawing_name, map_point)
        pixel_coords = coords if coords is not None else (0.0, 0.0)

        # 3. Build the feature (pre-georeferenced: canvas coords ARE real coords)
        new_feat = build_digitized_feature(
            self.point_layer,
            next_point_id,
            map_point,
            {
                "drawing_name": drawing_name,
                "excavation_type": excavation_type,
                "feature_name": feature_name if excavation_type == ExcavationType.FEATURE.value else "",
                "color_code": color_code if excavation_type == ExcavationType.FEATURE.value else "",
                "attribute_type": attribute_type,
                "point_name": point_name,
                "branch_no": branch_no,
            },
            pixel_coords=pixel_coords,
        )

        # 4. Write the new feature to the layer
        with (self.busy_interaction_guard() if hasattr(self, "busy_interaction_guard") else nullcontext()):
            insert_feature_to_layer(self.point_layer, new_feat)

            # 5. Update UI (auto-increment point number / point info panel)
            self._on_point_digitized({
                "point_id": next_point_id,
                "drawing_name": drawing_name,
                "point_name": point_name,
                "branch_no": branch_no,
                "excavation_type": excavation_type,
                "feature_name": feature_name,
            })

    def _on_point_digitized(self, data: dict) -> None:
        """Handle point digitization completion (T-0027: no more status panel;
        the 点情報パネル preview labels are refreshed via _apply_next_point_number
        or, for branch-suffixed digitizing, explicitly below).
        """
        branch_no = data.get("branch_no", "")
        if branch_no:
            self._has_digitized_with_branch = True
        else:
            self._has_digitized_with_branch = False
            self._apply_next_point_number()
        self._refresh_point_info_labels()
        self._update_point_info_status()

    # T-0032: only the target-drawing selector remains locked while an
    # existing point is selected. T-0027/T-0023's former lock list also
    # covered 出土形態/遺構名/属性/点名/枝番 widgets, but those are now
    # directly editable during existing-point editing (T-0038: committed in
    # real time, see _commit_point_identity_if_editing/
    # _commit_attribute_fields_if_editing).
    _CATEGORY_LOCK_WIDGET_NAMES = ()

    def _set_category_widgets_locked(self, locked: bool) -> None:
        """Enable/disable the widgets that must stay locked while an existing
        point is selected (T-0023/T-0027/T-0032; see _CATEGORY_LOCK_WIDGET_NAMES).

        :param locked: True to disable (lock) the widgets, False to re-enable them.
        :type locked: bool
        """
        for name in self._CATEGORY_LOCK_WIDGET_NAMES:
            widget = getattr(self, name, None)
            if widget is not None:
                widget.setEnabled(not locked)

    @pyqtSlot(dict)
    def _on_existing_point_selected(self, data: dict) -> None:
        """Launch PointEditDialog to edit the selected point."""
        from .dialogs import PointEditDialog
        
        # Block map interaction
        if getattr(self, "map_tool", None) and hasattr(self.map_tool, "set_interaction_locked"):
            self.map_tool.set_interaction_locked(True)
            
        dialog = PointEditDialog(
            layer_manager=self.layer_manager,
            feature_data=data,
            drawing_names=self._get_drawing_layer_names(),
            parent=self
        )
        
        result = dialog.exec_()
        
        if getattr(self, "map_tool", None) and hasattr(self.map_tool, "set_interaction_locked"):
            self.map_tool.set_interaction_locked(False)
            
        if result == QDialog.Accepted:
            if dialog.dialog_action == "delete":
                self.selected_edit_point_id = data.get("feature_id")
                self._on_delete_selected_point()
            elif dialog.dialog_action == "confirm" and self.point_layer:
                fid = data.get("feature_id")
                updates = {
                    "drawing_name": dialog.feature_data["drawing_name"],
                    "excavation_type": dialog.feature_data["excavation_type"],
                    "feature_name": dialog.feature_data["feature_name"],
                    "attribute_type": dialog.feature_data["attribute_type"],
                    "point_name": dialog.feature_data["point_name"],
                    "branch_no": dialog.feature_data["branch_no"],
                }
                
                with (self.busy_interaction_guard() if hasattr(self, "busy_interaction_guard") else __import__('contextlib').nullcontext()):
                    field_names = self.point_layer.fields().names()
                    self.point_layer.startEditing()
                    for field_name, value in updates.items():
                        if field_name in field_names:
                            idx = field_names.index(field_name)
                            self.point_layer.changeAttributeValue(fid, idx, value)
                    self.point_layer.commitChanges()
                    
                    if self.is_focus_mode_active():
                        self.update_symbology_opacity()
                        
                    self.canvas.refresh()
                    
        # Reset selection state
        self._reset_point_selection()


    @pyqtSlot()
    def _on_blank_click_in_edit_mode(self) -> None:
        """Deselect the current feature on a blank-space click in edit mode.

        T-0039: CanvasDigitizingTool._handle_digitize_click() emits
        blank_click_in_edit_mode when a click while in edit mode misses
        every existing feature (snap detection failed). This clears the
        current selection (form reverts to new-point-creation display,
        selection marker cleared) via _reset_point_selection(), while
        leaving self.tab2_current_mode ("edit") untouched — only the
        mode-change handler (_on_tab2_mode_changed) may alter the mode.
        """
        if self.selected_edit_point_id is None:
            return
        self._reset_point_selection()

    def _reset_point_selection(self) -> None:
        """Reset form back to new point creation mode."""
        self.selected_edit_point_id = None
        self._selected_point_data = None
        self._set_category_widgets_locked(False)
        self._is_out_of_bounds = False

        self._apply_next_point_number()
        self.edit_branch_no.clear()
        self._has_digitized_with_branch = False
        self._refresh_point_info_labels()
        self._update_point_info_status()

        # T-0023: clear the persistent selection marker on the main canvas.
        if getattr(self, "map_tool", None) is not None:
            self.map_tool.clear_selected_marker()

    def _on_delete_selected_point(self) -> None:
        """Delete the currently selected point from point layer.

        T-0027: deletion is now immediate (no confirmation dialog), replacing
        the former QMessageBox.question() confirmation step.
        """
        if self.selected_edit_point_id is None or not self.point_layer:
            return

        with (self.busy_interaction_guard() if hasattr(self, "busy_interaction_guard") else nullcontext()):
            self.point_layer.startEditing()
            self.point_layer.deleteFeature(self.selected_edit_point_id)
            self.point_layer.commitChanges()

            self.iface.messageBar().pushMessage(
                UIMessages.MSG_DELETE_SUCCESS_TITLE,
                UIMessages.MSG_DELETE_SUCCESS,
                level=Qgis.MessageLevel.Success,
                duration=3,
            )
            self._reset_point_selection()

    def _browse_csv_path(self) -> None:
        """Browse destination path for CSV export."""
        default_dir = self.layers_dict.get("session_dir", os.path.expanduser("~"))
        filepath, _ = QFileDialog.getSaveFileName(
            self,
            UIDialogTitles.BROWSE_CSV,
            default_dir,
            UIDialogTitles.CSV_FILTER,
        )
        if filepath:
            self.edit_csv_path.setText(os.path.normpath(filepath))

    def _on_export_csv_clicked(self) -> None:
        """Export digitized points directly to CSV."""
        filepath = self.edit_csv_path.text().strip()
        if not filepath:
            self._browse_csv_path()
            filepath = self.edit_csv_path.text().strip()
            if not filepath:
                return

        encoding = "utf-8-sig" if self.radio_utf8.isChecked() else "cp932"
        success, msg = export_points_to_csv(
            self.point_layer, filepath, encoding=encoding, parent=self
        )

        if success:
            self.iface.messageBar().pushMessage(
                UIMessages.MSG_EXPORT_CSV_TITLE,
                msg,
                level=Qgis.MessageLevel.Success,
                duration=5,
            )
