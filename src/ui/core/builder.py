"""
/***************************************************************************
 PointerGeocoding Plugin - CoreUI builder (PanelSpec -> real widgets)
 ***************************************************************************/

T-0045: CoreUIBuilder.build(spec, parent) turns a declarative PanelSpec
(field_spec.py) into a real vertical stack of PyQt widgets, one row per
FieldSpec, reusing UIStyleHelper's existing row/button/table helpers
(ui/style.py) as the actual widget factories. This module is a thin layer
over ui/style.py, not a replacement for it.

Event wiring is deferred: building a panel never touches the caller's
business-logic methods directly. Instead, each field that declares an
on_click/on_change hook name registers a "pending connector" closure; the
caller later attaches its real callback via ``BuiltPanel.bind(hook_name,
callback)``. This is what lets schemas.py stay a pure data file with zero
references to Tab1GeorefMixin's methods.

T-0045 追加スコープ: ``BuiltPanel`` also exposes ``get_value()``/
``set_value()``/``collect_values()`` for the value-bearing widget kinds
(LINEEDIT_ROW/COMBOBOX_ROW/SEGMENTED_TOGGLE), so callers no longer need to
keep raw widget references around just to read/write a field's value.
"""
from typing import Any, Callable, Dict, List, Optional

from qgis.gui import QgsFilterLineEdit
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
)

from ..style import UIStyleHelper
from ..constants import UIConfig
from .field_spec import ButtonDef, PanelSpec, WidgetType

_STYLE_APPLIERS = {
    "primary": UIStyleHelper.set_primary_button,
    "accent": UIStyleHelper.set_accent_button,
    "success": UIStyleHelper.set_success_button,
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

    #: WidgetType kinds get_value()/set_value()/collect_values() know how to
    #: read/write. TABLE and the pure-display/action kinds (BUTTON,
    #: BUTTON_ROW, INFO_PANEL) are intentionally excluded (see
    #: v2-coreui-plan.md's T-0045 追加スコープ note on TABLE's complex row
    #: structure staying individually handled).
    _VALUE_WIDGET_TYPES = (
        WidgetType.LINEEDIT_ROW,
        WidgetType.COMBOBOX_ROW,
        WidgetType.SEGMENTED_TOGGLE,
        WidgetType.RADIO_ROW,
        WidgetType.SPINBOX_ROW,
        WidgetType.DOUBLE_SPINBOX_ROW,
        WidgetType.COLOR_BUTTON_ROW,
    )

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

    def get(self, field_id: str) -> QWidget:
        """Return the primary built widget registered under ``field_id``."""
        return self._field_widgets[field_id]

    def get_row(self, field_id: str) -> QWidget:
        """Return the row container widget for ``field_id`` (what callers
        show()/hide() to toggle an entire row, e.g. Tab1's row_edit_layer).
        """
        return self._row_widgets[field_id]

    def get_buttons(self, field_id: str) -> List[QPushButton]:
        """Return the button list for a SEGMENTED_TOGGLE field."""
        return self._buttons_lists[field_id]

    def bind(self, hook_name: str, callback: Callable) -> None:
        """Attach ``callback`` to every pending connector registered under
        ``hook_name`` (e.g. a FieldSpec's on_click/on_change, or a
        ButtonDef's on_click). No-op if no field declared that hook name.
        """
        for connector in self._pending_hooks.get(hook_name, []):
            connector(callback)

    def get_value(self, field_id: str) -> Any:
        """Read the current value of a value-bearing field (LINEEDIT_ROW ->
        raw ``.text()``, COMBOBOX_ROW -> ``.currentText()``,
        SEGMENTED_TOGGLE -> checked segment index). Callers that need
        stripped/validated text should post-process the returned value
        themselves (get_value never strips/casts).

        :raises KeyError: if ``field_id`` was never registered.
        :raises NotImplementedError: if ``field_id``'s widget_type does not
            carry a scalar value (BUTTON/BUTTON_ROW/TABLE/INFO_PANEL).
        """
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
        raise NotImplementedError(
            f"get_value() is not supported for field '{field_id}' (widget_type={widget_type})"
        )

    def set_value(self, field_id: str, value: Any) -> None:
        """Write a value into a value-bearing field, symmetric with
        ``get_value()``.

        :raises KeyError: if ``field_id`` was never registered.
        :raises NotImplementedError: if ``field_id``'s widget_type does not
            carry a scalar value (BUTTON/BUTTON_ROW/TABLE/INFO_PANEL).
        """
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
        raise NotImplementedError(
            f"set_value() is not supported for field '{field_id}' (widget_type={widget_type})"
        )

    @staticmethod
    def _set_color_button(btn: QPushButton, color_hex: str) -> None:
        """Shared helper for COLOR_BUTTON_ROW's initial style and set_value()."""
        btn._color_hex = color_hex
        btn.setStyleSheet(f"background-color: {color_hex}; color: white; border-radius: 4px;")

    def collect_values(self) -> Dict[str, Any]:
        """Return ``{field_id: get_value(field_id)}`` for every registered
        value-bearing field (see ``_VALUE_WIDGET_TYPES``).
        """
        return {
            field_id: self.get_value(field_id)
            for field_id, widget_type in self._field_types.items()
            if widget_type in self._VALUE_WIDGET_TYPES
        }

    def set_values(self, values: Dict[str, Any]) -> None:
        """T-0048: symmetric bulk counterpart to ``collect_values()``. Calls
        ``set_value(field_id, value)`` for each entry in ``values`` whose
        ``field_id`` is a registered value-bearing field; unknown field_ids
        (e.g. a settings-dict key with no corresponding panel field) are
        silently ignored, so callers can pass a superset dict without
        filtering it first (e.g. tab3_settings.py's mode-conditional scale
        values).
        """
        for field_id, value in values.items():
            widget_type = self._field_types.get(field_id)
            if widget_type in self._VALUE_WIDGET_TYPES:
                self.set_value(field_id, value)


class CoreUIBuilder:
    """Builds a PanelSpec into a real QWidget tree. Stateless: all state
    lives in the returned BuiltPanel.
    """

    @classmethod
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
                # T-0048: also expose each ROW_GROUP sub-field's own
                # field_id/widget_type so panel.get()/get_value()/
                # set_value()/collect_values() can address it directly, as
                # if it had been declared at the top level.
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

    # -- per-WidgetType builders -------------------------------------------------
    # Each returns the widget to place directly into the panel's QVBoxLayout
    # (also used as the "row" for show()/hide() purposes).

    @staticmethod
    def _apply_button_style(button: QPushButton, style_variant: Optional[str]) -> None:
        applier = _STYLE_APPLIERS.get(style_variant)
        if applier:
            applier(button)

    @classmethod
    def _make_button(cls, b: ButtonDef, parent: QWidget, register_hook) -> QPushButton:
        btn = QPushButton(b.text, parent)
        cls._apply_button_style(btn, b.style_variant)
        btn.setEnabled(b.enabled)
        register_hook(b.on_click, lambda cb, btn=btn: btn.clicked.connect(cb))
        return btn

    @classmethod
    def _build_lineedit_row(cls, f, parent, field_widgets, buttons_lists, register_hook):
        label = QLabel(f.label, parent) if f.label else None
        edit = QgsFilterLineEdit(parent)
        if f.placeholder:
            edit.setPlaceholderText(f.placeholder)
        field_widgets[f.field_id] = edit
        if label is not None:
            # T-0046: expose the row label under f"{field_id}.label" so
            # callers that need to swap its text at runtime (e.g.
            # start_dialog.py's new/existing-session label swap) can fetch
            # it via panel.get(f"{field_id}.label") instead of keeping a
            # separately-constructed QLabel reference around.
            field_widgets[f"{f.field_id}.label"] = label
        register_hook(f.on_change, lambda cb, edit=edit: edit.textChanged.connect(cb))

        content = [(edit, 6 if f.trailing_button else 1)]
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
    def _build_button_row(cls, f, parent, field_widgets, buttons_lists, register_hook):
        row = QWidget(parent)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        if f.centered:
            # T-0047: mirrors UIStyleHelper.build_centered_button_row's
            # "stretch - buttons - stretch" pattern for modal dialogs' OK/
            # キャンセル rows (dialogs.py); left-anchored rows (e.g. Tab1's
            # rename_delete/transform_actions) leave f.centered False.
            row_layout.addStretch(1)
        for b in f.buttons:
            btn = cls._make_button(b, row, register_hook)
            field_widgets[b.field_id] = btn
            row_layout.addWidget(btn, b.stretch)
        if f.centered:
            row_layout.addStretch(1)
        return row

    @classmethod
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
    def _build_radio_row(cls, f, parent, field_widgets, buttons_lists, register_hook):
        """Build a labeled row of mutually-exclusive QRadioButtons.

        T-0046: mirrors _build_segmented_toggle's index-based get_value/
        set_value/on_change contract, but renders plain QRadioButtons in a
        build_flex_row (label + one radio per option + trailing stretch)
        instead of an iOS-style segmented button group, matching
        start_dialog.py's pre-existing "セッション種別"/"グリッドモード" look.
        """
        label = QLabel(f.label, parent) if f.label else None
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

        row = UIStyleHelper.build_flex_row(
            label,
            content,
            # T-0048 fix: mirror _build_segmented_toggle's labelless
            # main_ratio=(0, 10) so a RADIO_ROW declared without a label
            # (e.g. tab3_settings.py's point_fill_toggle/halo_toggle) does
            # not reserve an empty leading stretch sized as if a label were
            # present. Labeled RADIO_ROWs (start_dialog.py's session_type/
            # grid_mode, tab3's major_scale_mode/minor_scale_mode) keep the
            # previous UIConfig.MAIN_RATIO behavior unchanged.
            main_ratio=f.main_ratio or (UIConfig.MAIN_RATIO if f.label else (0, 10)),
            row_height=f.row_height or UIConfig.ROW_HEIGHT,
        )
        # Keep the QButtonGroup alive for the row's lifetime (it is parented
        # to `parent`, not `row`, so nothing else retains a reference to it).
        row._button_group = group
        field_widgets[f.field_id] = row
        return row

    @classmethod
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

        return UIStyleHelper.build_flex_row(
            None,
            [(container, 1)],
            main_ratio=f.main_ratio or (0, 10),
            row_height=f.row_height or UIConfig.ROW_HEIGHT,
        )

    @classmethod
    def _build_spinbox_row(cls, f, parent, field_widgets, buttons_lists, register_hook):
        """Build a labeled row wrapping a single UIStyleHelper.create_spinbox()
        QSpinBox (T-0047; e.g. dialogs.py's PointNameEntryDialog 点名 numeric
        input), analogous to _build_lineedit_row but for an int-ranged value
        instead of free text.
        """
        spin = UIStyleHelper.create_spinbox(f.spin_min, f.spin_max, f.spin_default, parent)
        spin.setEnabled(f.enabled)
        field_widgets[f.field_id] = spin
        register_hook(f.on_change, lambda cb, spin=spin: spin.valueChanged.connect(cb))
        if f.label_width is not None:
            # T-0048 (人手確認フィードバック対応): tab3_settings.py's lbl_size
            # needs to line up with the DOUBLE_SPINBOX_ROW lbl_offset beside
            # it in the same ROW_GROUP, so a fixed label_width switches this
            # to the same build_form_row() layout DOUBLE_SPINBOX_ROW/
            # COLOR_BUTTON_ROW use, instead of build_flex_row's stretch-ratio
            # layout. Screens that never set label_width (e.g. dialogs.py's
            # PointNameEntryDialog) keep the original build_flex_row look.
            return UIStyleHelper.build_form_row(f.label or "", spin, label_width=f.label_width)
        label = QLabel(f.label, parent) if f.label else None
        return UIStyleHelper.build_flex_row(
            label,
            [(spin, 1)],
            main_ratio=f.main_ratio or UIConfig.MAIN_RATIO,
            row_height=f.row_height or UIConfig.ROW_HEIGHT,
        )

    @classmethod
    def _build_section_header(cls, f, parent, field_widgets, buttons_lists, register_hook):
        """Build a non-interactive bold section-header label (T-0048; e.g.
        tab3_settings.py's "基準点"/"遺物点"/"ラベル"/"表示縮尺" separators).
        """
        header = UIStyleHelper.build_section_header(f.label or "")
        field_widgets[f.field_id] = header
        return header

    @classmethod
    def _build_double_spinbox_row(cls, f, parent, field_widgets, buttons_lists, register_hook):
        """Build a compact label+QDoubleSpinBox row via
        UIStyleHelper.build_form_row() (T-0048; e.g. tab3_settings.py's
        サイズ/線幅/間隔 numeric inputs), analogous to _build_spinbox_row but
        for float values and the denser build_form_row layout tab3 already
        used prior to CoreUI adoption.
        """
        spin = QDoubleSpinBox(parent)
        spin.setRange(f.dspin_min, f.dspin_max)
        spin.setSingleStep(f.dspin_step)
        spin.setValue(f.dspin_default)
        spin.setEnabled(f.enabled)
        field_widgets[f.field_id] = spin
        register_hook(f.on_change, lambda cb, spin=spin: spin.valueChanged.connect(cb))
        return UIStyleHelper.build_form_row(f.label or "", spin, label_width=f.label_width)

    @classmethod
    def _build_color_button_row(cls, f, parent, field_widgets, buttons_lists, register_hook):
        """Build a compact label+color-swatch QPushButton row via
        UIStyleHelper.build_form_row() (T-0048; e.g. tab3_settings.py's 線色
        pickers). The button only opens the picker (on_click); the resulting
        color is tracked on the button itself (``btn._color_hex``) and read/
        written via BuiltPanel.get_value()/set_value().
        """
        btn = QPushButton("", parent)
        BuiltPanel._set_color_button(btn, f.color_default)
        field_widgets[f.field_id] = btn
        register_hook(f.on_click, lambda cb, btn=btn: btn.clicked.connect(cb))
        return UIStyleHelper.build_form_row(f.label or "", btn, label_width=f.label_width)

    @classmethod
    def _build_row_group(cls, f, parent, field_widgets, buttons_lists, register_hook):
        """Lay ``f.sub_fields`` out side by side in one QHBoxLayout row
        (T-0048; e.g. tab3_settings.py's paired サイズ+線幅 spinboxes, 線色+
        塗り toggle, and グリッド常時/指定 radio + threshold spinbox rows).
        Each sub-field is built via its own normal WidgetType builder and
        registered under its own field_id, exactly as if it were declared
        at the top level of the PanelSpec.
        """
        row = QWidget(parent)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        for sub in f.sub_fields:
            sub_builder = cls._BUILDERS[sub.widget_type]
            sub_widget = sub_builder(sub, row, field_widgets, buttons_lists, register_hook)
            row_layout.addWidget(sub_widget, sub.stretch)
        return row

    @classmethod
    def _build_spacer(cls, f, parent, field_widgets, buttons_lists, register_hook):
        """Build an empty, value-less QWidget placeholder used as a stretch
        spacer within a ROW_GROUP's sub_fields (T-0048 人手確認フィードバック
        対応; e.g. tab3_settings.py's ref_row2, pairing a 線色 COLOR_BUTTON_ROW
        with a same-width SPACER so the row's used half lines up with the
        サイズ+線幅 row above it). Registered in field_widgets like any other
        field, but intentionally excluded from _VALUE_WIDGET_TYPES.
        """
        spacer = QWidget(parent)
        field_widgets[f.field_id] = spacer
        return spacer

    @classmethod
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


# NOTE: populated after class definition (not inside the class body) so that
# each entry is CoreUIBuilder's already-bound classmethod (cls fixed to
# CoreUIBuilder), letting CoreUIBuilder.build() call `builder_fn(f, ...)`
# without re-passing cls itself.
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
}
