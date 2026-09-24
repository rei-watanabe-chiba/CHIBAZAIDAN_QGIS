"""
/***************************************************************************
 PointerGeocoding Plugin - Main Dock Standalone Dialog Classes (View)
 ***************************************************************************/

各種ダイアログのUI構築モジュールです。ビジネスロジックは dialogs_logic.py へ分離されています。
"""
# 【変更不可侵の絶対的ルール】 測量座標系（X軸=南北, Y軸=東西）を採用。QGISキャンバス上のX座標(東西)はSurvey Y、Y座標(南北)はSurvey Xに対応する。

import re
from typing import Optional, Dict, Any, List, Callable, Tuple

from qgis.core import QgsRasterLayer
from qgis.gui import QgsMapCanvas
from qgis.PyQt.QtCore import Qt, pyqtSlot, pyqtSignal, QRegExp, QPoint
from qgis.PyQt.QtGui import QRegExpValidator, QColor
from qgis.PyQt.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QSpinBox, QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QColorDialog, QCheckBox, QRadioButton, QButtonGroup, QListWidget,
    QListWidgetItem, QGroupBox, QComboBox
)

try:
    from qgis.PyQt.QtGui import QRegularExpressionValidator
    from qgis.PyQt.QtCore import QRegularExpression
    HAS_QT_REGEX = True
except ImportError:
    from qgis.PyQt.QtGui import QRegExpValidator
    from qgis.PyQt.QtCore import QRegExp
    HAS_QT_REGEX = False

from ..canvas.map_tool import ImageGeorefTool
from .style import UIStyleHelper
from ..logic.core import ExcavationType, AttributeType
from .constants import UIConfig, UILabels, UIMessages, UIPlaceholders, UIDialogSizes, UIDialogTitles
from .core.builder import CoreUIBuilder
from .core.field_spec import ButtonDef, FieldSpec, PanelSpec, WidgetType
from ..uilogic.dialogs_logic import GridInputLogic, PointNameEntryLogic, FeatureManageLogic, PointEditLogic

# =========================================================================
# CoreUI Schemas for Dialogs (Co-location)
# =========================================================================

GRID_INPUT_ACTIONS_SPEC = PanelSpec(
    panel_id="grid_input_actions",
    fields=[
        FieldSpec(
            field_id="dialog_actions",
            widget_type=WidgetType.BUTTON_ROW,
            centered=True,
            buttons=[
                ButtonDef(
                    field_id="confirm",
                    text=UILabels.BTN_CONFIRM,
                    style_variant="primary",
                    on_click="confirm_clicked",
                    enabled=False,
                ),
                ButtonDef(field_id="cancel", text=UILabels.BTN_CANCEL, on_click="cancel_clicked"),
            ],
        ),
    ],
)

POINT_NAME_ENTRY_SPEC = PanelSpec(
    panel_id="point_name_entry",
    fields=[
        FieldSpec(
            field_id="point_name",
            widget_type=WidgetType.SPINBOX_ROW,
            label=UILabels.POINT_NAME,
            spin_min=1,
            spin_max=999999,
            spin_default=1,
        ),
        FieldSpec(
            field_id="point_name_sp",
            widget_type=WidgetType.LINEEDIT_ROW,
            label=UILabels.POINT_NAME,
            placeholder=UIPlaceholders.POINT_NAME_SP,
        ),
        FieldSpec(
            field_id="branch_no",
            widget_type=WidgetType.LINEEDIT_ROW,
            label=UILabels.BRANCH_NO,
            placeholder=UIPlaceholders.BRANCH_NO,
        ),
    ],
)

POINT_NAME_ENTRY_ACTIONS_SPEC = PanelSpec(
    panel_id="point_name_entry_actions",
    fields=[
        FieldSpec(
            field_id="dialog_actions",
            widget_type=WidgetType.BUTTON_ROW,
            centered=True,
            buttons=[
                ButtonDef(
                    field_id="ok", text=UILabels.BTN_CONFIRM, style_variant="primary", on_click="ok_clicked"
                ),
                ButtonDef(field_id="cancel", text=UILabels.BTN_CANCEL, on_click="cancel_clicked"),
            ],
        ),
    ],
)

FEATURE_MANAGE_SPEC = PanelSpec(
    panel_id="feature_manage",
    fields=[
        FieldSpec(
            field_id="feature_list",
            widget_type=WidgetType.TABLE,
            table_headers=["遺構名リスト"],
            table_col_resize_modes=["stretch"]
        ),
        FieldSpec(
            field_id="feature_name",
            widget_type=WidgetType.LINEEDIT_ROW,
            label="遺構名:",
            placeholder=UIPlaceholders.NEW_FEATURE,
            on_change="feature_name_changed"
        ),
        FieldSpec(
            field_id="feature_color",
            widget_type=WidgetType.COLOR_BUTTON_ROW,
            label="カラー:",
            color_default="#FF5722",
            on_click="color_clicked"
        ),
        FieldSpec(
            field_id="actions",
            widget_type=WidgetType.BUTTON_ROW,
            centered=True,
            buttons=[
                ButtonDef(field_id="confirm", text=UILabels.BTN_CONFIRM, style_variant="primary", on_click="confirm_clicked"),
                ButtonDef(field_id="cancel", text=UILabels.BTN_CANCEL, on_click="cancel_clicked")
            ]
        )
    ]
)

DISPLAY_FILTER_SPEC = PanelSpec(
    panel_id="display_filter",
    fields=[
        FieldSpec(field_id="sep_attr", widget_type=WidgetType.SECTION_HEADER, label=UILabels.FILTER_ATTRIBUTES),
        FieldSpec(
            field_id="attributes",
            widget_type=WidgetType.CHECKBOX_ROW,
            options=[AttributeType.S.value, AttributeType.P.value, AttributeType.C.value, AttributeType.SP.value],
            default_indices=[0, 1, 2, 3]
        ),
        FieldSpec(field_id="sep_excav", widget_type=WidgetType.SECTION_HEADER, label=UILabels.FILTER_EXCAVATION),
        FieldSpec(
            field_id="excavation_types",
            widget_type=WidgetType.CHECKBOX_ROW,
            options=[ExcavationType.FEATURE.value, ExcavationType.GRID.value],
            default_indices=[0, 1]
        ),
        FieldSpec(field_id="sep_feat", widget_type=WidgetType.SECTION_HEADER, label=UILabels.FILTER_FEATURE),
        FieldSpec(
            field_id="feature_names",
            widget_type=WidgetType.LIST_WIDGET,
            checkable=True,
            list_min_height=150
        ),
        FieldSpec(field_id="sep_draw", widget_type=WidgetType.SECTION_HEADER, label=UILabels.FILTER_TARGET_DRAWING),
        FieldSpec(
            field_id="target_drawing",
            widget_type=WidgetType.RADIO_ROW,
            options=[UILabels.FILTER_DRAWING_SELECTED, UILabels.FILTER_DRAWING_ALL],
            default_index=0
        ),
        FieldSpec(field_id="spacer", widget_type=WidgetType.SPACER),
        FieldSpec(
            field_id="actions",
            widget_type=WidgetType.BUTTON_ROW,
            centered=False,
            buttons=[
                ButtonDef(field_id="clear_all", text=UILabels.BTN_CLEAR_ALL, on_click="clear_all_clicked"),
                ButtonDef(field_id="confirm", text=UILabels.BTN_CONFIRM, style_variant="primary", on_click="confirm_clicked"),
                ButtonDef(field_id="cancel", text=UILabels.BTN_CANCEL, on_click="cancel_clicked")
            ]
        )
    ]
)

POINT_EDIT_SPEC = PanelSpec(
    panel_id="point_edit",
    fields=[
        FieldSpec(
            field_id="attribute_code",
            widget_type=WidgetType.COMBOBOX_ROW,
            label=UILabels.ATTRIBUTE_CODE,
            on_change="category_changed"
        ),
        FieldSpec(
            field_id="excavation_type",
            widget_type=WidgetType.COMBOBOX_ROW,
            label=UILabels.EXCAVATION_TYPE,
            on_change="excavation_type_changed"
        ),
        FieldSpec(
            field_id="feature_name",
            widget_type=WidgetType.COMBOBOX_ROW,
            label=UILabels.FEATURE_SELECTOR,
            on_change="feature_combo_changed"
        ),
        FieldSpec(
            field_id="point_name",
            widget_type=WidgetType.SPINBOX_ROW,
            label=UILabels.POINT_NAME,
            spin_min=1,
            spin_max=999999,
            spin_default=1,
            on_change="point_name_changed"
        ),
        FieldSpec(
            field_id="point_name_sp",
            widget_type=WidgetType.LINEEDIT_ROW,
            label=UILabels.POINT_NAME,
            placeholder=UIPlaceholders.POINT_NAME_SP,
            on_change="point_name_sp_changed",
            visible=False
        ),
        FieldSpec(
            field_id="branch_no",
            widget_type=WidgetType.LINEEDIT_ROW,
            label=UILabels.BRANCH_NO,
            placeholder=UIPlaceholders.BRANCH_NO,
            on_change="branch_no_changed"
        ),
        FieldSpec(
            field_id="drawing_name",
            widget_type=WidgetType.COMBOBOX_ROW,
            label="対象図面",
            on_change="drawing_name_changed"
        ),
        FieldSpec(
            field_id="dialog_actions",
            widget_type=WidgetType.BUTTON_ROW,
            centered=False,
            buttons=[
                ButtonDef(field_id="confirm", text=UILabels.BTN_CONFIRM, style_variant="primary", on_click="confirm_clicked"),
                ButtonDef(field_id="cancel", text=UILabels.BTN_CANCEL, on_click="cancel_clicked")
            ]
        )
    ]
)

# =========================================================================

class ModelessSectionDialog(QDialog):
    # モーダレスな汎用セクションダイアログの初期化。タイトル・コンテンツウィジェット・表示/クローズ時コールバックを設定。
    def __init__(self, title: str, content_widget: QWidget, on_show=None, on_close=None, parent=None, width=None, height=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint)
        if width is not None and height is not None: self.resize(width, height)
        self._on_show = on_show
        self._on_close = on_close

        layout = QVBoxLayout(self)
        layout.setContentsMargins(UIConfig.COMMON_MARGIN_LR, UIConfig.DIALOG_MARGIN, UIConfig.COMMON_MARGIN_LR, UIConfig.DIALOG_MARGIN)
        layout.addWidget(content_widget)

    # ダイアログ表示時に on_show コールバックを呼び出す。
    def showEvent(self, event):
        super().showEvent(event)
        if self._on_show: self._on_show()

    # ダイアログを閉じる際に非表示化し、on_close コールバックを呼び出す。
    def closeEvent(self, event):
        self.hide()
        event.accept()
        if self._on_close: self._on_close()


class ImageDialog(QDialog):
    # georef_tool(setup_raster毎に再生成される)の ref_point_moved を中継する。(index, pixel_x, pixel_y)
    ref_point_moved = pyqtSignal(int, float, float)

    # 画像ジオリファレンス用ダイアログの初期化。プレビューキャンバスとコンテンツウィジェットを配置。
    def __init__(self, content_widget: QWidget, on_show=None, on_close=None, parent=None, width=None, height=None):
        super().__init__(parent)
        self.setWindowTitle(UILabels.TAB_1_TITLE)
        self.resize(UIDialogSizes.IMAGE_DIALOG_WIDTH, UIDialogSizes.IMAGE_DIALOG_HEIGHT)
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint)
        if width is not None and height is not None: self.resize(width, height)
        self._on_show = on_show
        self._on_close = on_close

        layout = QHBoxLayout(self)
        layout.setContentsMargins(UIConfig.COMMON_MARGIN_LR, UIConfig.DIALOG_MARGIN, UIConfig.COMMON_MARGIN_LR, UIConfig.DIALOG_MARGIN)
        layout.setSpacing(UIConfig.DIALOG_MARGIN)

        layout.addWidget(content_widget, 1)

        preview_container = QWidget(self)
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        lbl_hint = QLabel(UILabels.PREVIEW_HINT, preview_container)
        lbl_hint.setWordWrap(True)
        preview_layout.addWidget(lbl_hint)

        self.canvas = QgsMapCanvas(preview_container)
        self.canvas.setMinimumSize(400, 300)
        preview_layout.addWidget(self.canvas, 1)

        layout.addWidget(preview_container, 1)
        self.raster_layer = None
        self.georef_tool = None
        self.preview_image_path = ""

    # ラスタレイヤーをプレビューキャンバスに設定し、ジオリファレンス用マップツールを紐付ける。
    def setup_raster(self, raster_layer, point_clicked_callback, ref_points_data=None, source_path: str = ""):
        self.clean_up()
        self.raster_layer = raster_layer
        self.preview_image_path = source_path
        self.canvas.setLayers([self.raster_layer])
        self.canvas.setExtent(self.raster_layer.extent())
        self.canvas.refresh()
        self.georef_tool = ImageGeorefTool(self.canvas, self.raster_layer, label_font_size=UIConfig.LABEL_SIZE_REF)
        if ref_points_data: self.georef_tool.set_ref_points_data(ref_points_data)
        self.canvas.setMapTool(self.georef_tool)
        self.georef_tool.point_clicked.connect(point_clicked_callback)
        self.georef_tool.ref_point_moved.connect(self.ref_point_moved)

    # ジオリファレンスツールへ参照点データを設定する。
    def set_ref_points_data(self, ref_points_data):
        if self.georef_tool: self.georef_tool.set_ref_points_data(ref_points_data)

    # ピクセル座標に近い既存基準点のインデックスをジオリファレンスツールへ問い合わせる(無ければNone)。
    def find_snapped_ref_point(self, pixel_x, pixel_y):
        if self.georef_tool: return self.georef_tool.find_snapped_index_at_pixel(pixel_x, pixel_y)
        return None

    # プレビューキャンバス上に参照点マーカーを追加する。
    def add_marker(self, pixel_x, pixel_y, name=""):
        if self.georef_tool: self.georef_tool.add_point_marker(pixel_x, pixel_y, name)

    # プレビューキャンバス上のマーカーをすべてクリアする。
    def clear_markers(self):
        if self.georef_tool: self.georef_tool.clear_markers()

    # マップツール・レイヤー・キャンバスの状態を解放してクリーンアップする。
    def clean_up(self):
        if self.georef_tool:
            if self.canvas:
                self.canvas.unsetMapTool(self.georef_tool)
            self.georef_tool.clean_up()
            self.georef_tool = None
        if self.canvas:
            self.canvas.setLayers([])
        self.raster_layer = None
        self.preview_image_path = ""

    # ダイアログ表示時に on_show コールバックを呼び出す。
    def showEvent(self, event):
        super().showEvent(event)
        if self._on_show: self._on_show()

    # ダイアログを閉じる際に非表示化し、on_close コールバックを呼び出す。
    def closeEvent(self, event):
        self.hide()
        event.accept()
        if self._on_close: self._on_close()


class TwoDigitSpinBox(QSpinBox):
    # 数値を2桁ゼロ埋め文字列として表示する。
    def textFromValue(self, val: int) -> str: return f"{val:02d}"
    # 表示文字列を数値に変換する(不正な場合は0を返す)。
    def valueFromText(self, text: str) -> int:
        try: return int(text)
        except ValueError: return 0


class GridInputDialog(QDialog):
    # グリッド座標入力ダイアログの初期化。ロジック構築・UI構築・初期値設定を行う。
    def __init__(self, layer_manager, existing_point=None, existing_names=None, parent=None):
        super().__init__(parent)
        self.layer_manager = layer_manager
        self.existing_point = existing_point
        self.existing_names = existing_names or []
        self.dialog_action = "cancel"
        self.result_grid_name = ""
        self.result_real_x = None
        self.result_real_y = None

        self.logic = GridInputLogic(layer_manager, self.existing_names, self)

        self.setWindowTitle(UILabels.GRID_DIALOG_TITLE)
        self.setModal(True)
        self.setMinimumWidth(UIDialogSizes.GRID_DIALOG_MIN_WIDTH)

        self._init_ui()
        UIStyleHelper.apply_theme(self)
        self._populate_initial_values()

    # グリッドX/Y/枝番の入力欄と削除・確定ボタン、ステータスパネルを構築する。
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(UIConfig.COMMON_MARGIN_LR, UIConfig.DIALOG_MARGIN, UIConfig.COMMON_MARGIN_LR, UIConfig.DIALOG_MARGIN)

        tier1_box = QWidget(self)
        tier1_vlayout = QVBoxLayout(tier1_box)
        header_layout = QHBoxLayout()
        for lbl in (UILabels.GRID_X_LABEL, UILabels.GRID_Y_LABEL, UILabels.GRID_SUB_LABEL):
            w = QLabel(lbl, tier1_box)
            w.setStyleSheet("font-weight: bold; font-size: 8.5pt;")
            w.setAlignment(Qt.AlignCenter)
            header_layout.addWidget(w, 1)
        tier1_vlayout.addLayout(header_layout)

        inputs_layout = QHBoxLayout()
        
        # --- グリッドデータのX座標(数値)の最小値・最大値を取得 ---
        grid_data = getattr(self.layer_manager, "grid_data", {})
        if grid_data:
            gxs = [k[0] for k in grid_data.keys()]
            min_gx = min(gxs)
            max_gx = max(gxs)
        else:
            min_gx = 1
            max_gx = max(1, getattr(self.layer_manager, "max_gx", 100))
            
        self.spin_x = UIStyleHelper.create_spinbox(min_gx, max_gx, min_gx, tier1_box)
        self.spin_x.valueChanged.connect(self._validate_and_lookup)

        self.edit_y = QLineEdit(tier1_box)
        self.edit_y.setPlaceholderText("A")
        self.edit_y.setAlignment(Qt.AlignCenter)
        if HAS_QT_REGEX:
            self.edit_y.setValidator(QRegularExpressionValidator(QRegularExpression(r"[A-Za-z]+"), self.edit_y))
        else:
            self.edit_y.setValidator(QRegExpValidator(QRegExp(r"[A-Za-z]+"), self.edit_y))
        self.edit_y.textChanged.connect(self._on_y_changed)

        self.spin_sub = TwoDigitSpinBox(tier1_box)
        self.spin_sub.setRange(0, 99)
        self.spin_sub.valueChanged.connect(self._validate_and_lookup)

        inputs_layout.addWidget(self.spin_x, 1)
        inputs_layout.addWidget(self.edit_y, 1)
        inputs_layout.addWidget(self.spin_sub, 1)
        tier1_vlayout.addLayout(inputs_layout)
        layout.addWidget(tier1_box)

        self.btn_delete_point = QPushButton(UILabels.BTN_DELETE_SELECTED_POINT, self)
        self.btn_delete_point.setStyleSheet("background-color: #D32F2F; color: #FFFFFF; font-weight: bold; border-radius: 4px;")
        self.btn_delete_point.clicked.connect(self._on_delete_point_clicked)
        if not self.existing_point: self.btn_delete_point.hide()
        layout.addWidget(self.btn_delete_point)

        actions_panel = CoreUIBuilder.build(GRID_INPUT_ACTIONS_SPEC, parent=self)
        self.btn_confirm = actions_panel.get("confirm")
        actions_panel.bind("confirm_clicked", self._on_confirm_clicked)
        actions_panel.bind("cancel_clicked", self.reject)
        layout.addWidget(actions_panel.widget)

        self.panel_status, self.lbl_status = UIStyleHelper.create_status_panel("", "info", self)
        layout.addWidget(self.panel_status)

    # 既存点編集時は名称を分解して初期値をセットし、新規時はデフォルト値を設定する。
    def _populate_initial_values(self):
        if self.existing_point:
            name = str(self.existing_point.get("name", "")).strip()
            m = re.match(r"^(\d+)-?([A-Za-z]+)-?(\d{1,2})$", name)
            if m:
                self.spin_x.setValue(int(m.group(1)))
                self.edit_y.setText(m.group(2).upper())
                self.spin_sub.setValue(int(m.group(3)))
        else:
            default_y = "A"
            unique_gy = getattr(self.layer_manager, "unique_gy", set())
            if unique_gy: default_y = sorted(list(unique_gy))[0]
            self.edit_y.setText(default_y)
            
            # --- 初期値としてX座標の最小値をセット ---
            grid_data = getattr(self.layer_manager, "grid_data", {})
            if grid_data:
                gxs = [k[0] for k in grid_data.keys()]
                self.spin_x.setValue(min(gxs))
                
        self._validate_and_lookup()

    @pyqtSlot(str)
    # Y座標入力を大文字に変換しつつ、入力値の検証・座標参照を行う。
    def _on_y_changed(self, text):
        upper = text.upper()
        if upper != text:
            pos = self.edit_y.cursorPosition()
            self.edit_y.setText(upper)
            self.edit_y.setCursorPosition(pos)
        self._validate_and_lookup()

    # 入力されたグリッド座標を検証し、実座標を検索してステータス表示・確定ボタン状態を更新する。
    def _validate_and_lookup(self):
        gx = self.spin_x.value()
        gy = self.edit_y.text().strip().upper()
        sub_grid = self.spin_sub.value()
        
        is_valid, msg, status, real_x, real_y = self.logic.validate_and_lookup(gx, gy, sub_grid)
        
        UIStyleHelper.update_status_panel(self.panel_status, self.lbl_status, msg, status)
        self.btn_confirm.setEnabled(is_valid)
        
        if is_valid:
            self.result_grid_name = f"{gx}-{gy}-{sub_grid:02d}"
            self.result_real_x = real_x
            self.result_real_y = real_y

    # 削除確認ダイアログを表示し、承認されれば削除アクションとしてダイアログを終了する。
    def _on_delete_point_clicked(self):
        if QMessageBox.question(self, UIMessages.MSG_CONFIRM_TITLE, UIMessages.MSG_CONFIRM_DELETE_REF, QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self.dialog_action = "delete"
            self.accept()

    # 確定アクションとしてダイアログを終了する。
    def _on_confirm_clicked(self):
        self.dialog_action = "confirm"
        self.accept()


class FeatureManageDialog(QDialog):
    # 遺構名作成・編集ダイアログの初期化。ロジック構築とテーブル初期表示を行う。
    def __init__(self, parent=None, feature_colors=None, on_update_callback=None, initial_feature=None):
        super().__init__(parent)
        self.feature_colors = dict(feature_colors) if feature_colors else {}
        self.on_update_callback = on_update_callback
        self.result_text = ""
        self.result_feature_name = ""
        self.result_color = "#FF5722"
        self.current_selected_mode = "new"
        self.current_selected_feature = ""
        self.current_color = "#FF5722"

        self.logic = FeatureManageLogic(self.feature_colors, self)

        self.setWindowTitle(UILabels.FEATURE_MANAGE_DIALOG_TITLE)
        self.setModal(True)
        self.resize(360, 440)
        
        self._init_ui()
        self._populate_table(select_feature=initial_feature)

    # 遺構名テーブル・名称入力・カラー選択・確定/キャンセルボタンを構築しイベントを紐付ける。
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(UIConfig.COMMON_MARGIN_LR, UIConfig.DIALOG_MARGIN, UIConfig.COMMON_MARGIN_LR, UIConfig.DIALOG_MARGIN)

        self.lbl_header = QLabel("遺構名作成・編集", self)
        f = self.lbl_header.font()
        f.setBold(True)
        self.lbl_header.setFont(f)
        layout.addWidget(self.lbl_header)

        self.panel = CoreUIBuilder.build(FEATURE_MANAGE_SPEC, parent=self)
        layout.addWidget(self.panel.widget)
        
        self.table_features = self.panel.get("feature_list")
        self.table_features.verticalHeader().setVisible(False)
        self.table_features.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_features.setSelectionMode(QTableWidget.SingleSelection)
        # TABLEはデフォルトでcellChangedにフックされるため、itemSelectionChangedは手動で紐付け
        self.table_features.itemSelectionChanged.connect(self._on_table_selection_changed)

        self.edit_name = self.panel.get("feature_name")
        if HAS_QT_REGEX:
            self.edit_name.setValidator(QRegularExpressionValidator(QRegularExpression(r"^[A-Za-z0-9_-]+$"), self.edit_name))
        else:
            self.edit_name.setValidator(QRegExpValidator(QRegExp(r"^[A-Za-z0-9_-]+$"), self.edit_name))

        self.btn_color = self.panel.get("feature_color")

        # STATUS PANEL
        self.panel_status, self.lbl_status = UIStyleHelper.create_status_panel("", "info", self)
        layout.insertWidget(2, self.panel_status)

        self.panel.bind("color_clicked", self._on_pick_color)
        self.panel.bind("feature_name_changed", self._on_realtime_validate)
        self.panel.bind("confirm_clicked", self._on_confirm_clicked)
        self.panel.bind("cancel_clicked", self.reject)

        self.btn_confirm = self.panel.get("confirm")

    # 「新規作成」行と既存遺構名の一覧をテーブルへ反映し、選択行を設定する。
    def _populate_table(self, select_feature=None):
        self.table_features.blockSignals(True)
        try:
            self.table_features.setRowCount(0)
            self.table_features.insertRow(0)
            item_new = QTableWidgetItem("新規作成")
            item_new.setFlags(item_new.flags() & ~Qt.ItemIsEditable)
            self.table_features.setItem(0, 0, item_new)

            target_row = 0
            for i, feat_name in enumerate(sorted(self.feature_colors.keys()), start=1):
                self.table_features.insertRow(i)
                item = QTableWidgetItem(feat_name)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table_features.setItem(i, 0, item)
                if select_feature == feat_name: target_row = i
            self.table_features.setCurrentCell(target_row, 0)
        finally:
            self.table_features.blockSignals(False)
        self._on_table_selection_changed()

    # カラー選択ボタンの表示色を現在の選択色に更新する。
    def _update_color_button(self):
        h = self.current_color or "#FF5722"
        self.panel.set_value("feature_color", h)

    # カラーピッカーを表示し、選択された色を現在色として反映する。
    def _on_pick_color(self):
        c = QColorDialog.getColor(QColor(self.current_color or "#FF5722"), self, UIDialogTitles.COLOR_PICKER)
        if c.isValid():
            self.current_color = c.name()
            self._update_color_button()
            self._on_realtime_validate()

    # テーブルの選択行に応じて新規/既存モードを切り替え、名称・色欄を更新する。
    def _on_table_selection_changed(self):
        row = self.table_features.currentRow()
        if row <= 0:
            self.current_selected_mode = "new"
            self.current_selected_feature = ""
            self.edit_name.blockSignals(True)
            self.edit_name.clear()
            self.edit_name.blockSignals(False)
            self.current_color = "#FF5722"
        else:
            item = self.table_features.item(row, 0)
            feat_name = item.text() if item else ""
            self.current_selected_mode = "existing"
            self.current_selected_feature = feat_name
            self.edit_name.blockSignals(True)
            self.edit_name.setText(feat_name)
            self.edit_name.blockSignals(False)
            self.current_color = self.feature_colors.get(feat_name, "#FF5722")
            
        self._update_color_button()
        self._on_realtime_validate()

    # 入力中の遺構名をリアルタイムに検証し、ステータス・確定ボタン状態を更新する。
    def _on_realtime_validate(self, *args):
        text = self.edit_name.text().strip()
        is_valid, msg, status = self.logic.validate_feature_name(text, self.current_selected_mode, self.current_selected_feature)
        UIStyleHelper.update_status_panel(self.panel_status, self.lbl_status, msg, status)
        self.btn_confirm.setEnabled(is_valid)

    # 新規作成なら結果を確定、既存編集ならコールバック経由で更新しテーブルを再表示する。
    def _on_confirm_clicked(self):
        text = self.edit_name.text().strip()
        if self.current_selected_mode == "new":
            self.result_text = text
            self.result_feature_name = text
            self.result_color = self.current_color
            self.accept()
        else:
            old_name = self.current_selected_feature
            new_color = self.current_color
            if self.on_update_callback:
                self.on_update_callback(old_name, text, new_color)
            if old_name in self.feature_colors: del self.feature_colors[old_name]
            self.feature_colors[text] = new_color
            self.current_selected_feature = text
            self._populate_table(select_feature=text)

FeatureCreateDialog = FeatureManageDialog


class PointNameEntryDialog(QDialog):
    # 点名称・枝番入力ダイアログの初期化。SP属性かどうかで入力欄を切り替え、イベントを紐付ける。
    def __init__(self, point_layer, excavation_type, feature_name, drawing_name="", is_sp_attribute=False, parent=None, initial_point_name="", popup_pos: Optional[QPoint] = None):
        super().__init__(parent)
        self.is_sp_attribute = is_sp_attribute
        self.result_point_name = ""
        self.result_branch_no = ""

        self.logic = PointNameEntryLogic(point_layer, excavation_type, feature_name, drawing_name, is_sp_attribute, self)

        self.setWindowTitle(UILabels.POINT_NAME_ENTRY_DIALOG_TITLE)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(UIConfig.COMMON_MARGIN_LR, UIConfig.DIALOG_MARGIN, UIConfig.COMMON_MARGIN_LR, UIConfig.DIALOG_MARGIN)
        
        self.input_panel = CoreUIBuilder.build(POINT_NAME_ENTRY_SPEC, parent=self)
        self.spin_point_name = self.input_panel.get("point_name")
        self.edit_point_name_sp = self.input_panel.get("point_name_sp")
        self.edit_branch_no = self.input_panel.get("branch_no")

        if self.is_sp_attribute:
            self.edit_point_name_sp.setValidator(QRegExpValidator(QRegExp(r"^[A-Za-z0-9_-]+$"), self.edit_point_name_sp))
            if initial_point_name: self.edit_point_name_sp.setText(initial_point_name)
            self.input_panel.get_row("point_name").hide()
            self.edit_point_name_sp.textChanged.connect(self._on_realtime_validate)
        else:
            if initial_point_name and initial_point_name.isdigit():
                self.spin_point_name.setValue(int(initial_point_name))
            self.input_panel.get_row("point_name_sp").hide()
            self.spin_point_name.valueChanged.connect(self._on_realtime_validate)

        self.edit_branch_no.textChanged.connect(self._on_realtime_validate)
        layout.addWidget(self.input_panel.widget)

        self.panel_status, self.lbl_status = UIStyleHelper.create_status_panel("", "info", self)
        layout.addWidget(self.panel_status)

        actions_panel = CoreUIBuilder.build(POINT_NAME_ENTRY_ACTIONS_SPEC, parent=self)
        self.btn_ok = actions_panel.get("ok")
        actions_panel.bind("ok_clicked", self._on_ok_clicked)
        actions_panel.bind("cancel_clicked", self.reject)
        layout.addWidget(actions_panel.widget)

        self._on_realtime_validate()

        if popup_pos is not None:
            self.move(popup_pos)

    # SP属性かどうかに応じて点名称の入力値を文字列として取得する。
    def _get_point_name_text(self):
        return self.edit_point_name_sp.text().strip() if self.is_sp_attribute else str(self.spin_point_name.value())

    # 入力中の点名称・枝番をリアルタイムに検証し、ステータス・OKボタン状態を更新する。
    def _on_realtime_validate(self, *args):
        pname = self._get_point_name_text()
        branch = self.edit_branch_no.text().strip()

        is_valid, msg = self.logic.validate_inputs(pname, branch)
        if not is_valid:
            UIStyleHelper.update_status_panel(self.panel_status, self.lbl_status, msg, "error")
            self.btn_ok.setEnabled(False)
        else:
            UIStyleHelper.update_status_panel(self.panel_status, self.lbl_status, "", "info")
            self.btn_ok.setEnabled(True)

    # 入力値を最終検証し、有効なら結果を確定してダイアログを終了する。
    def _on_ok_clicked(self):
        pname = self._get_point_name_text()
        branch = self.edit_branch_no.text().strip()
        is_valid, msg = self.logic.validate_inputs(pname, branch)
        
        if is_valid:
            self.result_point_name = pname
            self.result_branch_no = branch
            self.accept()
        else:
            UIStyleHelper.update_status_panel(self.panel_status, self.lbl_status, msg, "error")

    # 確定した点名称・枝番の結果を返す。
    def get_values(self):
        return self.result_point_name, self.result_branch_no

class DisplayFilterDialog(QDialog):
    """Modal dialog for configuring display filters (FEAT-05)."""

    # 表示フィルタ設定ダイアログの初期化。初期フィルタの有無に応じて値を設定する。
    def __init__(
        self,
        parent: Optional[QWidget] = None,
        feature_names: Optional[List[str]] = None,
        initial_filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(UILabels.FILTER_DIALOG_TITLE)
        self.setModal(True)
        self.resize(320, 460)

        self._all_feature_names: List[str] = list(feature_names or [])
        self._init_ui()
        UIStyleHelper.apply_theme(self)

        if initial_filters:
            self.set_filters(initial_filters)
        else:
            default_filters = {
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
                "feature_names": list(self._all_feature_names),
                "target_drawing": UILabels.FILTER_DRAWING_SELECTED,
            }
            self.set_filters(default_filters)

    # 属性・掘削種別・遺構名一覧・対象図面のフィルタUIを構築し、ボタンイベントを紐付ける。
    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(UIConfig.COMMON_MARGIN_LR, UIConfig.DIALOG_MARGIN, UIConfig.COMMON_MARGIN_LR, UIConfig.DIALOG_MARGIN)
        layout.setSpacing(0)

        self.panel = CoreUIBuilder.build(DISPLAY_FILTER_SPEC, parent=self)
        layout.addWidget(self.panel.widget)
        
        self.list_features = self.panel.get("feature_names")
        self.list_features.setSelectionMode(QListWidget.NoSelection)
        self._populate_feature_list(self._all_feature_names)
        
        self.panel.bind("clear_all_clicked", self._on_clear_all_clicked)
        self.panel.bind("confirm_clicked", self.accept)
        self.panel.bind("cancel_clicked", self.reject)

    # 全フィルタ項目を初期状態(すべて選択)にリセットする。
    def _on_clear_all_clicked(self) -> None:
        self.panel.set_values({
            "attributes": [AttributeType.S.value, AttributeType.P.value, AttributeType.C.value, AttributeType.SP.value],
            "excavation_types": [ExcavationType.FEATURE.value, ExcavationType.GRID.value],
            "feature_names": self._all_feature_names,
            "target_drawing": 0
        })

    # 遺構名一覧をチェック付きリストとして再構築する。
    def _populate_feature_list(self, feature_names: List[str]) -> None:
        self.list_features.clear()
        for name in sorted(feature_names):
            item = QListWidgetItem(name, self.list_features)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)

    # 遺構名候補を更新し、リストを再構築する。
    def set_feature_names(self, feature_names: List[str]) -> None:
        self._all_feature_names = list(feature_names)
        self._populate_feature_list(self._all_feature_names)

    # 与えられたフィルタ値をUIへ反映する。
    def set_filters(self, filters: Dict[str, Any]) -> None:
        attrs = filters.get("attributes", [AttributeType.S.value, AttributeType.P.value, AttributeType.C.value, AttributeType.SP.value])
        excs = filters.get("excavation_types", [ExcavationType.FEATURE.value, ExcavationType.GRID.value])
        feats = filters.get("feature_names", self._all_feature_names)
        target_draw = filters.get("target_drawing", UILabels.FILTER_DRAWING_SELECTED)
        
        self.panel.set_values({
            "attributes": attrs,
            "excavation_types": excs,
            "feature_names": feats,
            "target_drawing": 1 if target_draw == UILabels.FILTER_DRAWING_ALL else 0
        })

    # UIの現在値からフィルタ設定を取得して返す。
    def get_filters(self) -> Dict[str, Any]:
        vals = self.panel.collect_values()
        target_drawing = UILabels.FILTER_DRAWING_ALL if vals.get("target_drawing") == 1 else UILabels.FILTER_DRAWING_SELECTED
        
        return {
            "attributes": vals.get("attributes", []),
            "excavation_types": vals.get("excavation_types", []),
            "feature_names": vals.get("feature_names", []),
            "target_drawing": target_drawing,
        }


class PointEditDialog(QDialog):
    """FEAT-01: Modal dialog for Point Editing"""
    # 点情報編集ダイアログの初期化。ロジック構築・UI構築・初期値反映を行う。
    def __init__(self, layer_manager, feature_data, drawing_names, parent=None, bulk_count: int = 0):
        super().__init__(parent)
        self.layer_manager = layer_manager
        self.feature_data = dict(feature_data)
        self.drawing_names = drawing_names
        self.dialog_action = "cancel"  # "confirm", "cancel"
        # 複数点の一括変更モード(bulk_count>=1)。0のときは従来の単一点編集。
        self.bulk_count = int(bulk_count or 0)
        self.bulk_updates: Dict[str, Any] = {}  # 一括変更モードで確定時に、変更された項目のみを保持する

        self.logic = PointEditLogic(self.layer_manager, self)
        
        self.setWindowTitle(UILabels.BULK_EDIT_TITLE if self.bulk_count else "点情報編集")
        self.setModal(True)
        self.setMinimumWidth(360)
        
        self._init_ui()
        UIStyleHelper.apply_theme(self)
        self._populate_initial_values()
        
    # 属性・掘削種別・遺構名・点名称・枝番・図面選択の各UIと確定/キャンセルボタンを構築し、イベントを紐付ける。
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(UIConfig.COMMON_MARGIN_LR, UIConfig.DIALOG_MARGIN, UIConfig.COMMON_MARGIN_LR, UIConfig.DIALOG_MARGIN)

        initial_status = UILabels.BULK_EDIT_STATUS.format(count=self.bulk_count) if self.bulk_count else "入力値で更新"
        self.panel_status, self.lbl_status = UIStyleHelper.create_status_panel(initial_status, "info", self)
        layout.addWidget(self.panel_status)

        self.panel = CoreUIBuilder.build(POINT_EDIT_SPEC, parent=self)
        layout.addWidget(self.panel.widget)
        
        self.combo_attribute = self.panel.get("attribute_code")
        if self.bulk_count:
            self.combo_attribute.addItem(UILabels.BULK_KEEP, None)
        for value in UILabels.ATTRIBUTE_OPTIONS:
            # 一括変更ではSPへの変更は行わない
            if self.bulk_count and value == AttributeType.SP.value:
                continue
            self.combo_attribute.addItem(UILabels.ATTRIBUTE_DISPLAY_MAP.get(value, value), value)

        self.combo_excavation_type = self.panel.get("excavation_type")
        if self.bulk_count:
            self.combo_excavation_type.addItem(UILabels.BULK_KEEP)
        self.combo_excavation_type.addItems(UILabels.EXCAVATION_OPTIONS)

        self.combo_feature_name = self.panel.get("feature_name")
        if self.bulk_count:
            self.combo_feature_name.addItem(UILabels.BULK_KEEP)
        self.combo_feature_name.addItem(UILabels.UNREGISTERED)

        self.edit_point_name = self.panel.get("point_name")
        self.edit_point_name_sp = self.panel.get("point_name_sp")
        if HAS_QT_REGEX:
            self.edit_point_name_sp.setValidator(QRegularExpressionValidator(QRegularExpression(r"^[A-Za-z0-9_-]+$"), self.edit_point_name_sp))
        else:
            self.edit_point_name_sp.setValidator(QRegExpValidator(QRegExp(r"^[A-Za-z0-9_-]+$"), self.edit_point_name_sp))
            
        self.edit_branch_no = self.panel.get("branch_no")
        
        self.combo_drawing_name = self.panel.get("drawing_name")
        if self.bulk_count:
            self.combo_drawing_name.addItem(UILabels.BULK_KEEP)
        self.combo_drawing_name.addItem(UILabels.DRAWING_UNSPECIFIED)
        for name in self.drawing_names:
            if name != UILabels.DRAWING_UNSPECIFIED:
                self.combo_drawing_name.addItem(name)

        self.btn_confirm = self.panel.get("confirm")

        self.panel.bind("category_changed", self._on_category_changed)
        self.panel.bind("excavation_type_changed", self._on_excavation_type_changed)
        self.panel.bind("feature_combo_changed", self._validate)
        self.panel.bind("point_name_changed", self._validate)
        self.panel.bind("point_name_sp_changed", self._validate)
        self.panel.bind("branch_no_changed", self._validate)
        self.panel.bind("drawing_name_changed", self._validate)

        self.panel.bind("confirm_clicked", self._on_confirm_clicked)
        self.panel.bind("cancel_clicked", self.reject)

    # 編集対象の点情報からUI各項目に初期値を反映する。
    def _populate_initial_values(self):
        if self.bulk_count:
            self._populate_bulk_initial_values()
            return
        d_name = self.feature_data.get("drawing_name", "").strip()
        target_name = d_name if d_name else UILabels.DRAWING_UNSPECIFIED
        idx = self.combo_drawing_name.findText(target_name)
        if idx >= 0: self.combo_drawing_name.setCurrentIndex(idx)
        
        if self.layer_manager and hasattr(self.layer_manager, "point_layer"):
            layer = self.layer_manager.point_layer
            if layer and layer.isValid():
                idx = layer.fields().indexOf("feature_name")
                if idx >= 0:
                    names = set(layer.uniqueValues(idx))
                    for name in sorted(names):
                        if str(name).strip() and str(name).strip() not in (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成")):
                            self.combo_feature_name.addItem(str(name).strip())
        
        ex_type = str(self.feature_data.get("excavation_type") or ExcavationType.GRID.value)
        self.combo_excavation_type.setCurrentText(ex_type)
        
        if ex_type == ExcavationType.FEATURE.value:
            feat_name = str(self.feature_data.get("feature_name") or "")
            if feat_name and self.combo_feature_name.findText(feat_name) < 0:
                self.combo_feature_name.addItem(feat_name)
            self.combo_feature_name.setCurrentText(feat_name if feat_name else UILabels.UNREGISTERED)
            
        attr_type = str(self.feature_data.get("attribute_type") or AttributeType.S.value)
        idx = self.combo_attribute.findData(attr_type)
        if idx >= 0: self.combo_attribute.setCurrentIndex(idx)
        
        pname_raw = str(self.feature_data.get("point_name") or "")
        if attr_type == AttributeType.SP.value:
            self.edit_point_name_sp.setText(pname_raw)
        else:
            try: p_val = int(pname_raw or 1)
            except ValueError: p_val = 1
            self.edit_point_name.setValue(p_val)
            
        self.edit_branch_no.setText(str(self.feature_data.get("branch_no") or ""))
        
        self._on_category_changed()
        self._on_excavation_type_changed()
        self._validate()

    # 一括変更モードの初期値を反映する(全項目「変更しない」、点名・枝番の行は非表示)。
    def _populate_bulk_initial_values(self):
        if self.layer_manager and hasattr(self.layer_manager, "point_layer"):
            layer = self.layer_manager.point_layer
            if layer and layer.isValid():
                idx = layer.fields().indexOf("feature_name")
                if idx >= 0:
                    names = set(layer.uniqueValues(idx))
                    for name in sorted(names):
                        if str(name).strip() and str(name).strip() not in (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成")):
                            self.combo_feature_name.addItem(str(name).strip())
        for combo in (self.combo_attribute, self.combo_excavation_type, self.combo_feature_name, self.combo_drawing_name):
            combo.setCurrentIndex(0)
        for row_id in ("point_name", "point_name_sp", "branch_no"):
            self.panel.get_row(row_id).setVisible(False)
        self._on_excavation_type_changed()

    # 一括変更モードの入力検証。変更項目が無い・遺構名が未指定の場合は確定不可とする(重複等は確定後にスキップ判定される)。
    def _validate_bulk(self):
        updates = self._collect_bulk_updates()
        is_valid = bool(updates)
        msg = UILabels.BULK_EDIT_STATUS.format(count=self.bulk_count)
        status = "info"
        is_feat_err = False
        if updates.get("excavation_type") == ExcavationType.FEATURE.value and updates.get("feature_name") == "":
            is_valid = False
            is_feat_err = True
            msg = UILabels.STATUS_ERR_FEATURE_REQUIRED
            status = "error"
        UIStyleHelper.set_error_border(self.combo_feature_name, is_feat_err)
        UIStyleHelper.update_status_panel(self.panel_status, self.lbl_status, msg, status)
        self.btn_confirm.setEnabled(is_valid)

    # 一括変更モードで「変更しない」以外が選ばれた項目のみを辞書で返す。
    def _collect_bulk_updates(self) -> Dict[str, Any]:
        keep = UILabels.BULK_KEEP
        updates: Dict[str, Any] = {}
        attr = self.combo_attribute.currentData()
        if attr is not None:
            updates["attribute_type"] = attr
        ex_type = self.combo_excavation_type.currentText()
        if ex_type != keep:
            updates["excavation_type"] = ex_type
        # 出土形態がグリッドに変更される場合、遺構名は変更対象外(ロジック側で空にされる)
        feat = self.combo_feature_name.currentText().strip()
        if feat != keep and ex_type != ExcavationType.GRID.value:
            updates["feature_name"] = "" if feat in (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成")) else feat
        d_name = self.combo_drawing_name.currentText().strip()
        if d_name != keep:
            updates["drawing_name"] = "" if d_name == UILabels.DRAWING_UNSPECIFIED else d_name
        return updates

    # 属性(SPかどうか)の変更に応じて点名称の入力欄表示を切り替え、検証を行う。
    def _on_category_changed(self, *args):
        if self.bulk_count:
            self._validate()
            return
        is_sp = (self.combo_attribute.currentData() == AttributeType.SP.value)
        self.panel.get_row("point_name").setVisible(not is_sp)
        self.panel.get_row("point_name_sp").setVisible(is_sp)
        self._validate()

    # 掘削種別の変更に応じて遺構名欄の表示可否を切り替え、検証を行う。
    def _on_excavation_type_changed(self, *args):
        if self.bulk_count:
            # 一括変更: 「グリッド」に変更する場合のみ遺構名欄を隠す(「変更しない」「遺構」では表示)
            is_grid = (self.combo_excavation_type.currentText() == ExcavationType.GRID.value)
            self.panel.get_row("feature_name").setVisible(not is_grid)
            self._validate()
            return
        is_feature = (self.combo_excavation_type.currentText() == ExcavationType.FEATURE.value)
        self.panel.get_row("feature_name").setVisible(is_feature)
        self._validate()

    # 現在の属性種別に応じた点名称の入力値を取得する。
    def _get_current_point_name(self) -> str:
        if self.combo_attribute.currentData() == AttributeType.SP.value:
            return self.edit_point_name_sp.text().strip()
        else:
            return str(self.edit_point_name.value())

    # 入力内容を検証し、エラー枠表示・ステータス・確定ボタン状態を更新する。
    def _validate(self, *args):
        if self.bulk_count:
            self._validate_bulk()
            return
        point_name = self._get_current_point_name()
        branch_no = self.edit_branch_no.text().strip()
        ex_type = self.combo_excavation_type.currentText()
        feat_name = self.combo_feature_name.currentText().strip()
        if feat_name in (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成")):
            feat_name = ""
        drawing_name = self.combo_drawing_name.currentText().strip()
        if drawing_name == UILabels.DRAWING_UNSPECIFIED:
            drawing_name = ""
            
        attr_type = self.combo_attribute.currentData()
        exclude_id = self.feature_data.get("feature_id")

        is_valid, msg, status, is_feat_err, is_dup_err = self.logic.validate_inputs(
            ex_type, feat_name, attr_type, point_name, branch_no, drawing_name, exclude_id
        )

        UIStyleHelper.set_error_border(self.combo_feature_name, is_feat_err)
        
        is_sp = (attr_type == AttributeType.SP.value)
        UIStyleHelper.set_error_border(self.edit_point_name, is_dup_err and not is_sp)
        UIStyleHelper.set_error_border(self.edit_point_name_sp, is_dup_err and is_sp)
        UIStyleHelper.set_error_border(self.edit_branch_no, is_dup_err)

        UIStyleHelper.update_status_panel(self.panel_status, self.lbl_status, msg, status)
        self.btn_confirm.setEnabled(is_valid)
        
    # 入力値をfeature_dataへ反映し、確定アクションとしてダイアログを終了する。
    def _on_confirm_clicked(self):
        self.dialog_action = "confirm"
        if self.bulk_count:
            self.bulk_updates = self._collect_bulk_updates()
            self.accept()
            return
        self.feature_data["attribute_type"] = self.combo_attribute.currentData()
        self.feature_data["excavation_type"] = self.combo_excavation_type.currentText()
        feat_name = self.combo_feature_name.currentText().strip()
        if feat_name in (UILabels.UNREGISTERED, getattr(UILabels, "FEATURE_NEW_OPTION", "新規作成")):
            feat_name = ""
        self.feature_data["feature_name"] = feat_name if self.feature_data["excavation_type"] == ExcavationType.FEATURE.value else ""
        self.feature_data["point_name"] = self._get_current_point_name()
        self.feature_data["branch_no"] = self.edit_branch_no.text().strip()
        d_name = self.combo_drawing_name.currentText().strip()
        if d_name == UILabels.DRAWING_UNSPECIFIED: d_name = ""
        self.feature_data["drawing_name"] = d_name
        self.accept()