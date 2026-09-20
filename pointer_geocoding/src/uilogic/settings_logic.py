"""
/***************************************************************************
 PointerGeocoding Plugin - Settings Logic (Controller)
 ***************************************************************************/

Tab 3 (環境設定) のUIイベントを受容し、ビジネスロジック（設定の読み書き、
シンボロジの更新と適用）を処理するController層です。
View層からは BuiltPanel やコールバックが DI (注入) されるため、
循環参照（Circular Import）を起こさずに安全にイベントをバインドします。
"""
from typing import Optional, Dict, Any
from qgis.PyQt.QtCore import QObject
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import QColorDialog

from ..ui.constants import UIConfig, UILabels
from ..ui.core.builder import BuiltPanel


class SettingsLogic(QObject):
    """
    環境設定ダイアログの制御・シンボロジ同期を担うControllerクラス。
    """
    def __init__(self, layer_manager: Any, iface: Any, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.layer_manager = layer_manager
        self.iface = iface
        self.parent_widget = parent
        self.canvas = self.iface.mapCanvas()

        self.tab3_panel: Optional[BuiltPanel] = None
        self.is_focus_mode_active_cb = lambda: False
        self.update_symbology_opacity_cb = lambda: None

    def bind_view_callbacks(self, callbacks: Dict[str, Any]) -> None:
        """View層から必要な情報取得メソッドやヘルパーをバインドする"""
        self.is_focus_mode_active_cb = callbacks.get("is_focus_mode_active", self.is_focus_mode_active_cb)
        self.update_symbology_opacity_cb = callbacks.get("update_symbology_opacity", self.update_symbology_opacity_cb)

    def bind_ui_panels(self, tab3_panel: BuiltPanel, btn_settings_apply) -> None:
        """Viewから BuiltPanel 等を受け取り、Controller自身でシグナルをバインドする"""
        self.tab3_panel = tab3_panel

        self.tab3_panel.bind("ref_line_color_clicked", lambda: self._on_color_pick("ref_line_color"))
        self.tab3_panel.bind("point_line_color_clicked", lambda: self._on_color_pick("point_line_color"))
        self.tab3_panel.bind("major_scale_mode_changed", self._on_major_scale_mode_changed)
        self.tab3_panel.bind("minor_scale_mode_changed", self._on_minor_scale_mode_changed)

        btn_settings_apply.clicked.connect(self._on_settings_apply_clicked)

        if self.layer_manager:
            self.layer_manager.settings_changed.connect(self._on_layer_manager_settings_changed)

    # =========================================================================
    # UI イベント受容ロジック
    # =========================================================================

    def _on_color_pick(self, field_id: str) -> None:
        current_color_hex = self.tab3_panel.get_value(field_id) or "#FFFFFF"
        if current_color_hex == "transparent":
            current_color_hex = "#FFFFFF"

        color = QColorDialog.getColor(QColor(current_color_hex), self.parent_widget, UILabels.TAB3_BTN_COLOR)
        if color.isValid():
            self.tab3_panel.set_value(field_id, color.name())

    def _on_major_scale_mode_changed(self, idx: int) -> None:
        self.tab3_panel.get("major_scale_value").setEnabled(idx == 1)

    def _on_minor_scale_mode_changed(self, idx: int) -> None:
        self.tab3_panel.get("minor_scale_value").setEnabled(idx == 1)

    # =========================================================================
    # データ同期・永続化ロジック
    # =========================================================================

    def update_settings_ui_from_dict(self, settings: Optional[Dict[str, Any]] = None) -> None:
        """ロードされた設定データを用いてUIコンポーネントの表示を更新する"""
        if settings is None:
            if self.layer_manager and hasattr(self.layer_manager, "load_settings"):
                settings = self.layer_manager.load_settings()
            else:
                return

        if not self.tab3_panel:
            return

        sc_maj = int(settings.get("scale_major_grid", -1))
        sc_min = int(settings.get("scale_minor_grid", UIConfig.SCALE_THRESHOLD))

        values = {
            "ref_sym_size": float(settings.get("ref_symbol_size", 4.0)),
            "ref_sym_linewidth": float(settings.get("ref_symbol_line_width", 1.2)),
            "ref_line_color": str(settings.get("ref_symbol_line_color", settings.get("ref_symbol_color", "#D32F2F"))),
            "point_sym_size": float(settings.get("point_symbol_size", 6.0)),
            "point_sym_linewidth": float(settings.get("point_symbol_line_width", 0.9)),
            "point_line_color": str(settings.get("point_symbol_line_color", settings.get("point_symbol_color", "#E53935"))),
            "point_fill_toggle": 0 if bool(settings.get("point_symbol_fill_enabled", False)) else 1,
            "lbl_size": int(settings.get("label_size", UIConfig.LABEL_SIZE_REF)),
            "halo_toggle": 0 if bool(settings.get("label_halo", True)) else 1,
            "lbl_offset": float(settings.get("label_offset", 1.0)),
            "major_scale_mode": 0 if sc_maj <= 0 else 1,
            "minor_scale_mode": 0 if sc_min <= 0 else 1,
        }
        if sc_maj > 0:
            values["major_scale_value"] = sc_maj
        if sc_min > 0:
            values["minor_scale_value"] = sc_min

        self.tab3_panel.set_values(values)

    def _on_settings_apply_clicked(self) -> None:
        """UIから設定値を取得し、LayerManagerを通じてJSONに保存する"""
        if not self.layer_manager or not self.layer_manager.session_dir:
            return

        values = self.tab3_panel.collect_values()

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

        self.layer_manager.ensure_json_dir()
        self.layer_manager.save_settings(new_settings)

    def _on_layer_manager_settings_changed(self, new_settings: dict) -> None:
        """設定保存完了のシグナルを受け取り、各レイヤのシンボロジを再構築する"""
        ref_layer = self.layer_manager.ref_point_layer
        if ref_layer and ref_layer.isValid():
            self.layer_manager.apply_ref_point_symbology(ref_layer, new_settings)

        point_layer = self.layer_manager.point_layer
        if point_layer and point_layer.isValid():
            self.layer_manager.apply_point_symbology(point_layer, new_settings)
            # 非表示式 (Focus Mode / 透過度) の再注入
            if self.is_focus_mode_active_cb():
                self.update_symbology_opacity_cb()
            elif self.canvas:
                self.canvas.refresh()
        elif self.canvas:
            self.canvas.refresh()