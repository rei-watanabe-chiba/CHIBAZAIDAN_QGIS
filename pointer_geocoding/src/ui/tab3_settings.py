"""
/***************************************************************************
 PointerGeocoding Plugin - Tab 3 (Settings) Mixin
 ***************************************************************************/

Stage B split (mechanical, logic-preserving): extracted from main_dock.py.
Provides Tab3SettingsMixin, mixed into MainDockWidget, containing UI
construction and event handlers for Tab 3 (display & symbol settings).

T-0048: widget construction is delegated to CoreUIBuilder against the
declarative TAB3_SETTINGS_SPEC panel (schemas.py); this mixin wires the
built panel's on_click/on_change hooks to the actual business-logic
handlers below, and reads/writes settings.json values through
BuiltPanel.collect_values()/set_values() instead of per-widget
.value()/.setValue()/.isChecked() calls.
"""

from typing import Optional, Dict, Any

from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QPushButton,
    QScrollArea,
    QFrame,
    QColorDialog,
)

from .style import UIStyleHelper
from .constants import UIConfig, UILabels
from .core import CoreUIBuilder
from .schemas import TAB3_SETTINGS_SPEC


class Tab3SettingsMixin:
    """Mixin providing Tab 3 (Display & Symbol Settings) behavior for MainDockWidget."""

    # ───────────────────────────────────────────────────────────────────────────
    # Tab 3: Settings
    # ───────────────────────────────────────────────────────────────────────────

    def _create_tab3_ui(self) -> QWidget:
        """Construct Tab 3: Display & Symbol Settings.

        T-0048: widget construction is delegated to CoreUIBuilder against
        TAB3_SETTINGS_SPEC; this method binds the built panel's hooks to
        the handlers below. The 適用 button stays bespoke code here (not
        part of the schema) since its handler needs to read the whole
        panel's collect_values() output, which is naturally sequenced after
        CoreUIBuilder.build() returns.
        """
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(
            UIConfig.COMMON_MARGIN_LR,
            UIConfig.DIALOG_MARGIN,
            UIConfig.COMMON_MARGIN_LR,
            UIConfig.DIALOG_MARGIN,
        )
        layout.setSpacing(UIConfig.DIALOG_MARGIN)

        panel = CoreUIBuilder.build(TAB3_SETTINGS_SPEC, parent=container)
        self._tab3_panel = panel
        panel.bind("ref_line_color_clicked", lambda: self._on_color_pick("ref_line_color"))
        panel.bind("point_line_color_clicked", lambda: self._on_color_pick("point_line_color"))
        panel.bind("major_scale_mode_changed", self._on_major_scale_mode_changed)
        panel.bind("minor_scale_mode_changed", self._on_minor_scale_mode_changed)
        layout.addWidget(panel.widget)

        # ── Apply button ─────────────────────────────────────────────────
        self.btn_settings_apply = QPushButton(UILabels.TAB3_BTN_APPLY, container)
        UIStyleHelper.set_primary_button(self.btn_settings_apply)
        self.btn_settings_apply.clicked.connect(self._on_settings_apply_clicked)
        layout.addWidget(self.btn_settings_apply)

        layout.addStretch()
        scroll.setWidget(container)

        return scroll

    def _on_color_pick(self, field_id: str) -> None:
        """Unified color picker handler for a COLOR_BUTTON_ROW field.

        :param field_id: TAB3_SETTINGS_SPEC field_id of the color swatch
            button that was clicked (e.g. "ref_line_color").
        """
        current_color_hex = self._tab3_panel.get_value(field_id) or "#FFFFFF"
        if current_color_hex == "transparent":
            current_color_hex = "#FFFFFF"

        color = QColorDialog.getColor(QColor(current_color_hex), self, UILabels.TAB3_BTN_COLOR)
        if color.isValid():
            self._tab3_panel.set_value(field_id, color.name())

    def _on_major_scale_mode_changed(self, idx: int) -> None:
        """Enable the 大グリッド threshold spinbox only in "指定" mode
        (idx == 1), mirroring the pre-CoreUI ``radio_always.toggled``
        connection. Screen-specific glue kept out of schemas.py.
        """
        self._tab3_panel.get("major_scale_value").setEnabled(idx == 1)

    def _on_minor_scale_mode_changed(self, idx: int) -> None:
        """Enable the 小グリッド threshold spinbox only in "指定" mode
        (idx == 1); see ``_on_major_scale_mode_changed``.
        """
        self._tab3_panel.get("minor_scale_value").setEnabled(idx == 1)

    def update_settings_ui_from_dict(self, settings: Optional[Dict[str, Any]] = None) -> None:
        """Update Tab 3 setting widgets from loaded settings dictionary."""
        if settings is None:
            if self.layer_manager and hasattr(self.layer_manager, "load_settings"):
                settings = self.layer_manager.load_settings()
            else:
                return

        if not hasattr(self, "_tab3_panel"):
            return

        sc_maj = int(settings.get("scale_major_grid", -1))
        sc_min = int(settings.get("scale_minor_grid", UIConfig.SCALE_THRESHOLD))

        values = {
            "ref_sym_size": float(settings.get("ref_symbol_size", 4.0)),
            "ref_sym_linewidth": float(settings.get("ref_symbol_line_width", 1.2)),
            "ref_line_color": str(
                settings.get("ref_symbol_line_color", settings.get("ref_symbol_color", "#D32F2F"))
            ),
            "point_sym_size": float(settings.get("point_symbol_size", 6.0)),
            "point_sym_linewidth": float(settings.get("point_symbol_line_width", 0.9)),
            "point_line_color": str(
                settings.get("point_symbol_line_color", settings.get("point_symbol_color", "#E53935"))
            ),
            # RADIO_ROW fields carry an index; index 0 is the "ON" option
            # for both TAB3_POINT_FILL_ON/OFF and TAB3_LABEL_HALO_ON/OFF.
            "point_fill_toggle": 0 if bool(settings.get("point_symbol_fill_enabled", False)) else 1,
            "lbl_size": int(settings.get("label_size", UIConfig.LABEL_SIZE_REF)),
            "halo_toggle": 0 if bool(settings.get("label_halo", True)) else 1,
            "lbl_offset": float(settings.get("label_offset", 1.0)),
            # index 0 = "常時" (TAB3_SCALE_ALWAYS), index 1 = "指定"
            # (TAB3_SCALE_SPECIFY); the threshold spinbox's own value is
            # only overwritten when a specific value was actually saved
            # (sc_maj/sc_min > 0), matching the pre-CoreUI hasattr-guarded
            # conditional .setValue() calls this replaces.
            "major_scale_mode": 0 if sc_maj <= 0 else 1,
            "minor_scale_mode": 0 if sc_min <= 0 else 1,
        }
        if sc_maj > 0:
            values["major_scale_value"] = sc_maj
        if sc_min > 0:
            values["minor_scale_value"] = sc_min

        self._tab3_panel.set_values(values)

    def _on_settings_apply_clicked(self) -> None:
        """Collect UI values and persist them to settings.json.

        Step3-B: symbology re-application and canvas refresh no longer happen
        here directly — they are handled by _on_layer_manager_settings_changed,
        which is connected to LayerManager.settings_changed and fires once
        save_settings() actually persists the change.
        """
        if not self.layer_manager or not self.layer_manager.session_dir:
            return

        values = self._tab3_panel.collect_values()

        scale_major = -1 if values["major_scale_mode"] == 0 else values["major_scale_value"]
        scale_minor = -1 if values["minor_scale_mode"] == 0 else values["minor_scale_value"]

        new_settings = {
            "ref_symbol_size":           values["ref_sym_size"],
            "ref_symbol_line_width":     values["ref_sym_linewidth"],
            "ref_symbol_line_color":     values["ref_line_color"],
            "point_symbol_size":         values["point_sym_size"],
            "point_symbol_line_width":   values["point_sym_linewidth"],
            "point_symbol_fill_enabled": values["point_fill_toggle"] == 0,
            "point_symbol_line_color":   values["point_line_color"],
            "label_size":                values["lbl_size"],
            "label_halo":                values["halo_toggle"] == 0,
            "label_offset":              values["lbl_offset"],
            "scale_major_grid":          scale_major,
            "scale_minor_grid":          scale_minor,
        }

        # Persist (LayerManager.save_settings emits settings_changed on success,
        # which triggers _on_layer_manager_settings_changed below)
        self.layer_manager.ensure_json_dir()
        self.layer_manager.save_settings(new_settings)

    def _on_layer_manager_settings_changed(self, new_settings: dict) -> None:
        """Re-apply symbology and refresh the canvas after settings are persisted.

        Connected to LayerManager.settings_changed (Step3-B). Consolidates logic
        that previously ran inline at the end of _on_settings_apply_clicked.

        :param new_settings: The settings dict that was just saved.
        :type new_settings: dict
        """
        # Re-apply ref_points symbology
        ref_layer = self.layer_manager.ref_point_layer
        if ref_layer and ref_layer.isValid():
            self.layer_manager.apply_ref_point_symbology(ref_layer, new_settings)

        # Re-apply point layer symbology (grid color + symbol size + line width)
        # T-0017: symbology construction moved from CanvasDigitizingTool
        # (map_tool.py) to SymbologyMixin.apply_point_symbology, reached via
        # self.layer_manager for consistency with apply_ref_point_symbology above.
        point_layer = self.layer_manager.point_layer
        if point_layer and point_layer.isValid():
            self.layer_manager.apply_point_symbology(point_layer, new_settings)
            if hasattr(self, "is_focus_mode_active") and self.is_focus_mode_active():
                self.update_symbology_opacity()
            elif hasattr(self, "canvas") and self.canvas:
                self.canvas.refresh()
        elif hasattr(self, "canvas") and self.canvas:
            self.canvas.refresh()
