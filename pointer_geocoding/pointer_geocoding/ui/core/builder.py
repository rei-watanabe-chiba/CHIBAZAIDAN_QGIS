"""
/***************************************************************************
 PointerGeocoding Plugin - CoreUI builder (PanelSpec -> real widgets)
 ***************************************************************************/

CoreUIBuilder.build(spec, parent) turns a declarative PanelSpec
(field_spec.py) into a real vertical stack of PyQt widgets, one row per
FieldSpec, reusing UIStyleHelper's existing row/button/table helpers
(ui/style.py) as the actual widget factories. This module is a thin layer
over ui/style.py, not a replacement for it.
"""
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

from qgis.gui import QgsFilterLineEdit
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
    QCheckBox,        
    QListWidget,      
    QListWidgetItem,  
)

from ..style import UIStyleHelper
from ..constants import UIConfig
from .field_spec import ButtonDef, PanelSpec, WidgetType

_STYLE_APPLIERS = {
    "primary": UIStyleHelper.set_primary_button,
    "accent": UIStyleHelper.set_accent_button,
    "success": UIStyleHelper.set_success_button,
    "plain": UIStyleHelper.set_plain_button,
    "filter": UIStyleHelper.set_filter_button,
}

_RESIZE_MODES = {
    "contents": QHeaderView.ResizeToContents,
    "stretch": QHeaderView.Stretch,
}


class BuiltPanel:
    """Result of CoreUIBuilder.build(): the container widget plus lookup
    tables for retrieving individual field widgets/rows and binding event
    hooks to caller-supplied callbacks.
    """

    _VALUE_WIDGET_TYPES = (
        WidgetType.LINEEDIT_ROW,
        WidgetType.COMBOBOX_ROW,
        WidgetType.SEGMENTED_TOGGLE,
        WidgetType.RADIO_ROW,
        WidgetType.SPINBOX_ROW,
        WidgetType.DOUBLE_SPINBOX_ROW,
        WidgetType.COLOR_BUTTON_ROW,
        WidgetType.CHECKBOX_ROW,  
        WidgetType.LIST_WIDGET,   
    )

    # BuiltPanelの初期化。コンテナウィジェットとフィールド/行/ボタン/フック等の対応表を保持する。
    def __init__(
        self,
        widget: QWidget,
        field_widgets: Dict[str, QWidget],
        row_widgets: Dict[str, QWidget],
        buttons_lists: Dict[str, List[QPushButton]],
        pending_hooks: Dict[str, List[Callable[[Callable], None]]],
        field_types: Optional[Dict[str, WidgetType]] = None,
    ) -> None:
        self.widget = widget
        self._field_widgets = field_widgets
        self._row_widgets = row_widgets
        self._buttons_lists = buttons_lists
        self._pending_hooks = pending_hooks
        self._field_types = field_types or {}

    # フィールドIDに対応するウィジェットを取得する。
    def get(self, field_id: str) -> QWidget:
        return self._field_widgets[field_id]

    # フィールドIDに対応する行ウィジェットを取得する。
    def get_row(self, field_id: str) -> QWidget:
        return self._row_widgets[field_id]

    # フィールドIDに対応するボタン一覧を取得する。
    def get_buttons(self, field_id: str) -> List[QPushButton]:
        return self._buttons_lists[field_id]

    # 指定したフック名に登録済みの全コネクタへコールバックを接続する。
    def bind(self, hook_name: str, callback: Callable) -> None:
        for connector in self._pending_hooks.get(hook_name, []):
            connector(callback)

    # イベントフック名に対応するUIActionを発行し、ディスパッチャへ送信するバインディングを構築する。
    def auto_bind(self, dispatcher: Any, action_mapping: Dict[str, Callable[..., Any]]) -> None:
        """
        PanelSpecのイベントフック名に対応するUIActionを自動発行し、
        EventDispatcher (または dispatch メソッドを持つオブジェクト) へ送信するバインディングを構築する。

        Args:
            dispatcher: EventDispatcher などのディスパッチ機能を持つインスタンス
            action_mapping: { "hook_name": (*args) -> UIAction } 形式の辞書
        """
        for hook_name, action_factory in action_mapping.items():
            if hook_name not in self._pending_hooks:
                continue
                
            # クロージャの遅延評価問題を防ぐためのコールバック生成関数
            def create_bound_callback(factory=action_factory, disp=dispatcher):
                def callback(*args):
                    action = factory(*args)
                    if action is not None:
                        disp.dispatch(action)
                return callback
            
            self.bind(hook_name, create_bound_callback())

    # フィールドのウィジェット種別に応じて現在の入力値を取得する。
    def get_value(self, field_id: str) -> Any:
        widget_type = self._field_types[field_id]
        if widget_type == WidgetType.LINEEDIT_ROW:
            return self._field_widgets[field_id].text()
        if widget_type == WidgetType.COMBOBOX_ROW:
            return self._field_widgets[field_id].currentText()
        if widget_type in (WidgetType.SEGMENTED_TOGGLE, WidgetType.RADIO_ROW):
            for idx, btn in enumerate(self._buttons_lists[field_id]):
                if btn.isChecked():
                    return idx
            return -1
        if widget_type in (WidgetType.SPINBOX_ROW, WidgetType.DOUBLE_SPINBOX_ROW):
            return self._field_widgets[field_id].value()
        if widget_type == WidgetType.COLOR_BUTTON_ROW:
            return self._field_widgets[field_id]._color_hex
            
        if widget_type == WidgetType.CHECKBOX_ROW:
            return [btn.text() for btn in self._buttons_lists[field_id] if btn.isChecked()]
        if widget_type == WidgetType.LIST_WIDGET:
            lw: QListWidget = self._field_widgets[field_id]
            if lw.count() > 0 and (lw.item(0).flags() & Qt.ItemIsUserCheckable):
                return [lw.item(i).text() for i in range(lw.count()) if lw.item(i).checkState() == Qt.Checked]
            else:
                selected = lw.selectedItems()
                return selected[0].text() if selected else None
                
        raise NotImplementedError(
            f"get_value() is not supported for field '{field_id}' (widget_type={widget_type})"
        )

    # フィールドのウィジェット種別に応じて値を設定・反映する。
    def set_value(self, field_id: str, value: Any) -> None:
        widget_type = self._field_types[field_id]
        if widget_type == WidgetType.LINEEDIT_ROW:
            self._field_widgets[field_id].setText(value)
            return
        if widget_type == WidgetType.COMBOBOX_ROW:
            index = self._field_widgets[field_id].findText(value)
            if index >= 0:
                self._field_widgets[field_id].setCurrentIndex(index)
            return
        if widget_type in (WidgetType.SEGMENTED_TOGGLE, WidgetType.RADIO_ROW):
            self._buttons_lists[field_id][value].setChecked(True)
            return
        if widget_type in (WidgetType.SPINBOX_ROW, WidgetType.DOUBLE_SPINBOX_ROW):
            self._field_widgets[field_id].setValue(value)
            return
        if widget_type == WidgetType.COLOR_BUTTON_ROW:
            self._set_color_button(self._field_widgets[field_id], value)
            return
            
        if widget_type == WidgetType.CHECKBOX_ROW:
            for btn in self._buttons_lists[field_id]:
                btn.setChecked(btn.text() in value)
            return
        if widget_type == WidgetType.LIST_WIDGET:
            lw: QListWidget = self._field_widgets[field_id]
            if lw.count() > 0 and (lw.item(0).flags() & Qt.ItemIsUserCheckable):
                lw.blockSignals(True)
                for i in range(lw.count()):
                    item = lw.item(i)
                    item.setCheckState(Qt.Checked if item.text() in value else Qt.Unchecked)
                lw.blockSignals(False)
            else:
                items = lw.findItems(str(value), Qt.MatchExactly)
                if items:
                    lw.setCurrentItem(items[0])
                else:
                    lw.clearSelection()
            return
            
        raise NotImplementedError(
            f"set_value() is not supported for field '{field_id}' (widget_type={widget_type})"
        )

    @staticmethod
    # カラーボタンに色コードを保持させ、背景色スタイルを適用する。
    def _set_color_button(btn: QPushButton, color_hex: str) -> None:
        btn._color_hex = color_hex
        btn.setStyleSheet(f"background-color: {color_hex}; color: white; border-radius: 4px;")

    # 値を保持する全フィールドの現在値をまとめて辞書として取得する。
    def collect_values(self) -> Dict[str, Any]:
        return {
            field_id: self.get_value(field_id)
            for field_id, widget_type in self._field_types.items()
            if widget_type in self._VALUE_WIDGET_TYPES
        }

    # 渡された値の辞書を、対象フィールドへ一括で反映する。
    def set_values(self, values: Dict[str, Any]) -> None:
        for field_id, value in values.items():
            widget_type = self._field_types.get(field_id)
            if widget_type in self._VALUE_WIDGET_TYPES:
                self.set_value(field_id, value)


class CoreUIBuilder:
    @classmethod
    # PanelSpecの各FieldSpecからウィジェット行を組み立て、BuiltPanelとして返す。
    def build(cls, spec: PanelSpec, parent: Optional[QWidget] = None) -> BuiltPanel:
        container = QWidget(parent)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(*spec.margins)
        layout.setSpacing(spec.spacing)

        field_widgets: Dict[str, QWidget] = {}
        row_widgets: Dict[str, QWidget] = {}
        buttons_lists: Dict[str, List[QPushButton]] = {}
        pending_hooks: Dict[str, List[Callable[[Callable], None]]] = {}
        field_types: Dict[str, WidgetType] = {}

        def register_hook(hook_name: Optional[str], connector: Callable[[Callable], None]) -> None:
            if hook_name:
                pending_hooks.setdefault(hook_name, []).append(connector)

        for f in spec.fields:
            builder_fn = cls._BUILDERS[f.widget_type]
            row_widget = builder_fn(
                f, container, field_widgets, buttons_lists, register_hook
            )
            row_widgets[f.field_id] = row_widget
            field_types[f.field_id] = f.widget_type
            if f.widget_type == WidgetType.ROW_GROUP:
                for sub in f.sub_fields:
                    field_types[sub.field_id] = sub.widget_type
            layout.addWidget(row_widget)
            if not f.visible:
                row_widget.hide()

        panel = BuiltPanel(
            container, field_widgets, row_widgets, buttons_lists, pending_hooks, field_types
        )
        for rule in spec.rules:
            rule.apply(panel)
        return panel

    @staticmethod
    # スタイルバリアント名に対応するボタンスタイルを適用する。
    def _apply_button_style(button: QPushButton, style_variant: Optional[str]) -> None:
        applier = _STYLE_APPLIERS.get(style_variant)
        if applier:
            applier(button)

    @classmethod
    # ButtonDefからQPushButtonを生成し、スタイル適用とクリックフックの登録を行う。
    def _make_button(cls, b: ButtonDef, parent: QWidget, register_hook) -> QPushButton:
        btn = QPushButton(b.text, parent)
        if b.icon:
            # プラグイン直下の icon/ を絶対パスで解決(ui/core/ から3階層上がプラグインルート)
            plugin_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            btn.setIcon(QIcon(os.path.join(plugin_root, "icon", b.icon)))
        cls._apply_button_style(btn, b.style_variant)
        btn.setEnabled(b.enabled)
        register_hook(b.on_click, lambda cb, btn=btn: btn.clicked.connect(cb))
        return btn

    @classmethod
    # ラベルと複数ウィジェットを横並びに配置する行を構築する(要素数無制限のflex row)。
    def _build_flex_row_unlimited(
        cls, 
        label_text: Optional[str], 
        widgets_with_stretch: list, 
        main_ratio: Tuple[int, int], 
        row_height: Optional[int], 
        parent: QWidget
    ) -> QWidget:
        """UIStyleHelper.build_flex_rowの代替。要素数制限(3個)をなくした内部レイアウトヘルパー"""
        row_widget = QWidget(parent)
        if row_height:
            row_widget.setMinimumHeight(row_height)
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        label_stretch, content_stretch = main_ratio
        if label_text:
            lbl = QLabel(label_text, row_widget)
            row_layout.addWidget(lbl, label_stretch)
        elif label_stretch > 0:
            row_layout.addStretch(label_stretch)

        content_widget = QWidget(row_widget)
        content_layout = QHBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(8)

        for widget, stretch in widgets_with_stretch:
            if widget is not None:
                content_layout.addWidget(widget, stretch)
            else:
                content_layout.addStretch(stretch)

        row_layout.addWidget(content_widget, content_stretch)
        return row_widget

    @classmethod
    # テキスト入力欄(と任意の付随ボタン)を持つ行を構築する。
    def _build_lineedit_row(cls, f, parent, field_widgets, buttons_lists, register_hook):
        label = QLabel(f.label, parent) if f.label else None
        edit = QgsFilterLineEdit(parent)
        if f.placeholder:
            edit.setPlaceholderText(f.placeholder)
        field_widgets[f.field_id] = edit
        if label is not None:
            field_widgets[f"{f.field_id}.label"] = label
        register_hook(f.on_change, lambda cb, edit=edit: edit.textChanged.connect(cb))

        edit_stretch = (f.lineedit_stretch or 6) if f.trailing_button else 1
        content = [(edit, edit_stretch)]
        if f.trailing_button:
            btn = cls._make_button(f.trailing_button, parent, register_hook)
            field_widgets[f.trailing_button.field_id] = btn
            content.append((btn, f.trailing_button.stretch))

        return UIStyleHelper.build_flex_row(
            label,
            content,
            main_ratio=f.main_ratio or UIConfig.MAIN_RATIO,
            row_height=f.row_height or UIConfig.ROW_HEIGHT,
        )

    @classmethod
    # コンボボックスを持つ行を構築する。
    def _build_combobox_row(cls, f, parent, field_widgets, buttons_lists, register_hook):
        label = QLabel(f.label, parent) if f.label else None
        combo = QComboBox(parent)
        field_widgets[f.field_id] = combo
        register_hook(f.on_change, lambda cb, combo=combo: combo.currentIndexChanged.connect(cb))
        return UIStyleHelper.build_flex_row(
            label,
            [(combo, 1)],
            main_ratio=f.main_ratio or UIConfig.MAIN_RATIO,
            row_height=f.row_height or UIConfig.ROW_HEIGHT,
        )

    @classmethod
    # 単一ボタンウィジェットを構築する。
    def _build_button(cls, f, parent, field_widgets, buttons_lists, register_hook):
        b = ButtonDef(
            field_id=f.field_id,
            text=f.label or "",
            on_click=f.on_click,
            style_variant=f.style_variant,
            enabled=f.enabled,
        )
        btn = cls._make_button(b, parent, register_hook)
        field_widgets[f.field_id] = btn
        return btn

    @classmethod
    # 複数ボタンを横並びに配置した行を構築する。
    def _build_button_row(cls, f, parent, field_widgets, buttons_lists, register_hook):
        row = QWidget(parent)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        if f.centered:
            row_layout.addStretch(1)
        for b in f.buttons:
            btn = cls._make_button(b, row, register_hook)
            field_widgets[b.field_id] = btn
            row_layout.addWidget(btn, b.stretch)
        if f.centered:
            row_layout.addStretch(1)
        return row

    @classmethod
    # ヘッダー付きテーブルウィジェットを構築する。
    def _build_table(cls, f, parent, field_widgets, buttons_lists, register_hook):
        table = QTableWidget(0, len(f.table_headers), parent)
        table.setHorizontalHeaderLabels(f.table_headers)
        header = table.horizontalHeader()
        for col in range(len(f.table_headers)):
            token = f.table_col_resize_modes[col] if col < len(f.table_col_resize_modes) else "contents"
            header.setSectionResizeMode(col, _RESIZE_MODES.get(token, QHeaderView.ResizeToContents))
        if f.table_min_height:
            table.setMinimumHeight(f.table_min_height)
        field_widgets[f.field_id] = table
        register_hook(f.on_change, lambda cb, table=table: table.cellChanged.connect(cb))
        return table

    @classmethod
    # ラジオボタン群を持つ排他選択行を構築する。
    def _build_radio_row(cls, f, parent, field_widgets, buttons_lists, register_hook):
        group = QButtonGroup(parent)
        buttons: List[QRadioButton] = []
        content = []
        for i, option in enumerate(f.options):
            btn = QRadioButton(option, parent)
            group.addButton(btn, i)
            buttons.append(btn)
            content.append((btn, 1))
        content.append((None, 1))
        if 0 <= f.default_index < len(buttons):
            buttons[f.default_index].setChecked(True)
        buttons_lists[f.field_id] = buttons

        def connect_index_hook(cb, buttons=buttons):
            for idx, btn in enumerate(buttons):
                btn.toggled.connect(lambda checked, idx=idx, cb=cb: cb(idx) if checked else None)

        register_hook(f.on_change, connect_index_hook)

        main_ratio = f.main_ratio or (UIConfig.MAIN_RATIO if f.label else (0, 10))
        row = cls._build_flex_row_unlimited(
            f.label,
            content,
            main_ratio=main_ratio,
            row_height=f.row_height or UIConfig.ROW_HEIGHT,
            parent=parent
        )
        row._button_group = group
        field_widgets[f.field_id] = row
        return row

    @classmethod
    # セグメント切替トグルを持つ行を構築する。
    def _build_segmented_toggle(cls, f, parent, field_widgets, buttons_lists, register_hook):
        container, buttons = UIStyleHelper.build_segmented_toggle(
            f.options, default_index=f.default_index, parent=parent
        )
        field_widgets[f.field_id] = container
        buttons_lists[f.field_id] = buttons

        def connect_index_hook(cb, buttons=buttons):
            for idx, btn in enumerate(buttons):
                btn.toggled.connect(lambda checked, idx=idx, cb=cb: cb(idx) if checked else None)

        register_hook(f.on_change, connect_index_hook)

        if f.label:
            return cls._build_flex_row_unlimited(
                f.label,
                [(container, 1)],
                main_ratio=f.main_ratio or UIConfig.MAIN_RATIO,
                row_height=f.row_height or UIConfig.ROW_HEIGHT,
                parent=parent
            )

        return UIStyleHelper.build_flex_row(
            None,
            [(container, 1)],
            main_ratio=f.main_ratio or (0, 10),
            row_height=f.row_height or UIConfig.ROW_HEIGHT,
        )

    @classmethod
    # 整数スピンボックスを持つ行を構築する。
    def _build_spinbox_row(cls, f, parent, field_widgets, buttons_lists, register_hook):
        spin = UIStyleHelper.create_spinbox(f.spin_min, f.spin_max, f.spin_default, parent)
        spin.setEnabled(f.enabled)
        field_widgets[f.field_id] = spin
        register_hook(f.on_change, lambda cb, spin=spin: spin.valueChanged.connect(cb))
        if f.label_width is not None:
            return UIStyleHelper.build_form_row(f.label or "", spin, label_width=f.label_width)
        label = QLabel(f.label, parent) if f.label else None
        return UIStyleHelper.build_flex_row(
            label,
            [(spin, 1)],
            main_ratio=f.main_ratio or UIConfig.MAIN_RATIO,
            row_height=f.row_height or UIConfig.ROW_HEIGHT,
        )

    @classmethod
    # セクション見出しラベルを構築する。
    def _build_section_header(cls, f, parent, field_widgets, buttons_lists, register_hook):
        header = UIStyleHelper.build_section_header(f.label or "")
        field_widgets[f.field_id] = header
        return header

    @classmethod
    # 小数値スピンボックスを持つ行を構築する。
    def _build_double_spinbox_row(cls, f, parent, field_widgets, buttons_lists, register_hook):
        spin = QDoubleSpinBox(parent)
        spin.setRange(f.dspin_min, f.dspin_max)
        spin.setSingleStep(f.dspin_step)
        spin.setValue(f.dspin_default)
        spin.setEnabled(f.enabled)
        field_widgets[f.field_id] = spin
        register_hook(f.on_change, lambda cb, spin=spin: spin.valueChanged.connect(cb))
        return UIStyleHelper.build_form_row(f.label or "", spin, label_width=f.label_width)

    @classmethod
    # 色選択ボタンを持つ行を構築する。
    def _build_color_button_row(cls, f, parent, field_widgets, buttons_lists, register_hook):
        btn = QPushButton("", parent)
        BuiltPanel._set_color_button(btn, f.color_default)
        field_widgets[f.field_id] = btn
        register_hook(f.on_click, lambda cb, btn=btn: btn.clicked.connect(cb))
        return UIStyleHelper.build_form_row(f.label or "", btn, label_width=f.label_width)

    @classmethod
    # 複数のサブフィールドを横並びに束ねたグループ行を構築する。
    def _build_row_group(cls, f, parent, field_widgets, buttons_lists, register_hook):
        row = QWidget(parent)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        for sub in f.sub_fields:
            sub_builder = cls._BUILDERS[sub.widget_type]
            sub_widget = sub_builder(sub, row, field_widgets, buttons_lists, register_hook)
            row_layout.addWidget(sub_widget, sub.stretch)
        return row

    @classmethod
    # 空の余白用スペーサーウィジェットを構築する。
    def _build_spacer(cls, f, parent, field_widgets, buttons_lists, register_hook):
        spacer = QWidget(parent)
        field_widgets[f.field_id] = spacer
        return spacer

    @classmethod
    # 複数行の情報テキスト(区切り線・太字・折り返し等)を並べた情報パネルを構築する。
    def _build_info_panel(cls, f, parent, field_widgets, buttons_lists, register_hook):
        frame = QFrame(parent)
        UIStyleHelper.set_status_panel(frame)
        panel_layout = QVBoxLayout(frame)
        panel_layout.setContentsMargins(8, 8, 8, 8)
        panel_layout.setSpacing(4)

        for line in f.info_lines:
            if line.kind == "separator":
                hr = QFrame(frame)
                hr.setFrameShape(QFrame.HLine)
                hr.setStyleSheet("border-top: 1px dashed palette(mid); background: transparent;")
                panel_layout.addWidget(hr)
                continue

            label = QLabel(line.text, frame)
            if line.kind == "bold":
                label.setStyleSheet("font-weight: bold;")
            elif line.kind == "wrap":
                label.setWordWrap(True)
                if line.min_height:
                    label.setMinimumHeight(line.min_height)
            panel_layout.addWidget(label)
            if line.field_id:
                field_widgets[f"{f.field_id}.{line.field_id}"] = label

        field_widgets[f.field_id] = frame
        return frame

    @classmethod
    # チェックボックス群を持つ複数選択可能な行を構築する。
    def _build_checkbox_row(cls, f, parent, field_widgets, buttons_lists, register_hook):
        buttons: List[QCheckBox] = []
        content = []
        for i, option in enumerate(f.options):
            cb = QCheckBox(option, parent)
            buttons.append(cb)
            content.append((cb, 1))
        content.append((None, 1))
        
        if f.default_indices:
            for idx in f.default_indices:
                if 0 <= idx < len(buttons):
                    buttons[idx].setChecked(True)
                    
        buttons_lists[f.field_id] = buttons

        def connect_hook(cb_hook, buttons=buttons):
            for idx, btn in enumerate(buttons):
                btn.toggled.connect(lambda checked, idx=idx, cb_hook=cb_hook: cb_hook(idx, checked))

        register_hook(f.on_change, connect_hook)

        main_ratio = f.main_ratio or (UIConfig.MAIN_RATIO if f.label else (0, 10))
        row = cls._build_flex_row_unlimited(
            f.label,
            content,
            main_ratio=main_ratio,
            row_height=f.row_height or UIConfig.ROW_HEIGHT,
            parent=parent
        )
        field_widgets[f.field_id] = row
        return row

    @classmethod
    # チェック可能または単一選択可能なリストウィジェットを構築する。
    def _build_list_widget(cls, f, parent, field_widgets, buttons_lists, register_hook):
        list_widget = QListWidget(parent)
        if f.list_min_height:
            list_widget.setMinimumHeight(f.list_min_height)
        
        if f.options:
            for i, opt in enumerate(f.options):
                item = QListWidgetItem(opt, list_widget)
                if f.checkable:
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Checked if i in f.default_indices else Qt.Unchecked)
                    
        field_widgets[f.field_id] = list_widget
        
        if f.checkable:
            register_hook(f.on_change, lambda cb, lw=list_widget: lw.itemChanged.connect(cb))
        else:
            list_widget.setSelectionMode(QListWidget.SingleSelection)
            register_hook(f.on_change, lambda cb, lw=list_widget: lw.itemSelectionChanged.connect(cb))
            
        return list_widget


CoreUIBuilder._BUILDERS = {
    WidgetType.LINEEDIT_ROW: CoreUIBuilder._build_lineedit_row,
    WidgetType.COMBOBOX_ROW: CoreUIBuilder._build_combobox_row,
    WidgetType.BUTTON: CoreUIBuilder._build_button,
    WidgetType.BUTTON_ROW: CoreUIBuilder._build_button_row,
    WidgetType.TABLE: CoreUIBuilder._build_table,
    WidgetType.SEGMENTED_TOGGLE: CoreUIBuilder._build_segmented_toggle,
    WidgetType.INFO_PANEL: CoreUIBuilder._build_info_panel,
    WidgetType.RADIO_ROW: CoreUIBuilder._build_radio_row,
    WidgetType.SPINBOX_ROW: CoreUIBuilder._build_spinbox_row,
    WidgetType.SECTION_HEADER: CoreUIBuilder._build_section_header,
    WidgetType.DOUBLE_SPINBOX_ROW: CoreUIBuilder._build_double_spinbox_row,
    WidgetType.COLOR_BUTTON_ROW: CoreUIBuilder._build_color_button_row,
    WidgetType.ROW_GROUP: CoreUIBuilder._build_row_group,
    WidgetType.SPACER: CoreUIBuilder._build_spacer,
    WidgetType.CHECKBOX_ROW: CoreUIBuilder._build_checkbox_row,   
    WidgetType.LIST_WIDGET: CoreUIBuilder._build_list_widget,     
}