"""
/***************************************************************************
 PointerGeocoding Plugin - Symbology & Labeling Mixin
 ***************************************************************************/

Stage C split (mechanical, logic-preserving): extracted from
layer_manager.py. Provides SymbologyMixin, mixed into LayerManager,
containing digitized-point labeling and reference-point symbology/labeling.

Stage E: also mixed into MainDockWidget so that "symbology application"
(digitized-point labeling, reference-point symbology, and the Focus Mode
opacity override) is a single cohesive concern regardless of which widget
triggers it. build_opacity_expression()/apply_opacity_expression() were
moved here from main_dock.py's update_symbology_opacity() without changing
their expression/output semantics; main_dock.py keeps a same-named thin
delegator so Tab2/Tab3 call sites are unaffected.

T-0017 (アプローチC): map_tool.py の CanvasDigitizingTool が保持していた
digitized-point の本格的なカテゴリ分けシンボロジ(S/P/C/SP + ラベリング)、
main canvas向け基準点クロスシンボル、属性選択時の透過度切替の3メソッドを
ここへ統合した(apply_point_symbology / apply_ref_point_cross_symbology /
apply_attribute_transparency)。map_tool.py 側はジオメトリ選択・キャンバス
インタラクションに専念し、シンボロジの詳細はすべて本ファイル(LayerManager
経由)に一元化する。なお apply_ref_point_cross_symbology は、CSV由来の
基準点レイヤに使う apply_ref_point_symbology(ルールベース・大中小グリッド
表示制御あり)とは別物で、メインキャンバス上の基準点レイヤ向けの単純な
クロスシンボルである。移設時点でいずれの呼び出し元からも未使用だったが、
既存の公開APIとして挙動を変えずに移設した。
"""
# 【変更不可侵の絶対的ルール】 測量座標系（X軸=南北, Y軸=東西）を採用。QGISキャンバス上のX座標(東西)はSurvey Y、Y座標(南北)はSurvey Xに対応する。

from typing import Optional, Dict, Any, List

from qgis.core import (
    QgsVectorLayer,
    QgsPalLayerSettings,
    QgsVectorLayerSimpleLabeling,
    QgsTextFormat,
    QgsTextBufferSettings,
    QgsMarkerSymbol,
    QgsRuleBasedRenderer,
    QgsCategorizedSymbolRenderer,
    QgsRendererCategory,
    QgsSimpleMarkerSymbolLayer,
    QgsSymbolLayer,
    QgsSingleSymbolRenderer,
    QgsProperty,
    QgsSymbol,
    Qgis,
)
from qgis.PyQt.QtGui import QColor

from ..logic.core import ExcavationType, AttributeType


class SymbologyMixin:
    """Mixin providing point/reference-point symbology and labeling for LayerManager."""

    @staticmethod
    def apply_point_labeling(layer: QgsVectorLayer) -> None:
        """Apply dynamic expression-based labeling to the points layer."""
        settings = QgsPalLayerSettings()
        settings.fieldName = (
            f"CASE WHEN \"excavation_type\" = '{ExcavationType.FEATURE.value}' THEN \"feature_name\" || '_' ELSE '' END "
            "|| \"point_name\" "
            "|| CASE WHEN \"branch_no\" IS NOT NULL AND \"branch_no\" != '' THEN '-' || \"branch_no\" ELSE '' END"
        )
        settings.isExpression = True
        settings.placement = Qgis.LabelPlacement.OverPoint
        settings.yOffset = -5.0  # Slightly above the point

        text_format = QgsTextFormat()
        text_format.setSize(10)

        buffer = QgsTextBufferSettings()
        buffer.setEnabled(True)
        buffer.setSize(1.0)
        text_format.setBuffer(buffer)

        settings.setFormat(text_format)

        labeling = QgsVectorLayerSimpleLabeling(settings)
        layer.setLabelsEnabled(True)
        layer.setLabeling(labeling)

    @staticmethod
    def apply_point_symbology(
        layer: QgsVectorLayer,
        settings: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Apply categorical symbology for attribute types S, P, C, and SP.

        T-0017: moved from CanvasDigitizingTool.setup_point_layer_symbology
        (map_tool.py) without changing behavior, so that all symbology
        construction lives alongside apply_point_labeling/apply_ref_point_symbology.

        - S: Single circle (○).
        - P: Diamond (◇).
        - C: Triangle (△).
        - SP: Double concentric circle (◎).
        - Stroke color: Configurable via settings["point_symbol_line_color"] for グリッド,
          color_code for 遺構 via data-defined override.
        - Fill color: Matches stroke color if point_symbol_fill_enabled is True, else transparent.

        :param layer: Target point vector layer.
        :type layer: QgsVectorLayer
        :param settings: Optional settings dict (from settings.json). Uses point_symbol_* keys.
        :type settings: Optional[Dict[str, Any]]
        """
        if not layer or not layer.isValid():
            return

        # Resolve fill enabled flag, line color, symbol size, and line width from settings or fallback
        fill_enabled = bool((settings or {}).get("point_symbol_fill_enabled", False))
        grid_line_color = str(
            (settings or {}).get("point_symbol_line_color", (settings or {}).get("point_symbol_color", (settings or {}).get("symbol_color", "#E53935")))
        )
        sym_size = float(
            (settings or {}).get("point_symbol_size", (settings or {}).get("symbol_size", 6.0))
        )
        line_width = float(
            (settings or {}).get("point_symbol_line_width", (settings or {}).get("symbol_line_width", 0.9))
        )
        initial_fill_color = grid_line_color if fill_enabled else "transparent"

        categories: List[QgsRendererCategory] = []
        color_expr = (
            f"CASE WHEN \"excavation_type\" = '{ExcavationType.GRID.value}' THEN '{grid_line_color}' "
            "ELSE coalesce(\"color_code\", '#FF5722') END"
        )
        prop_color = QgsProperty.fromExpression(color_expr)

        # Get stroke color property key
        prop_stroke = getattr(QgsSimpleMarkerSymbolLayer, "PropertyStrokeColor", None)
        if prop_stroke is None:
            prop_stroke = getattr(QgsSymbolLayer, "PropertyStrokeColor", None)
        if prop_stroke is None and hasattr(QgsSymbolLayer, "Property"):
            prop_stroke = getattr(QgsSymbolLayer.Property, "PropertyStrokeColor", None)
        if prop_stroke is None:
            prop_stroke = 2  # Standard QgsSymbolLayer::PropertyStrokeColor enum value

        # Get fill color property key
        prop_fill = getattr(QgsSimpleMarkerSymbolLayer, "PropertyFillColor", None)
        if prop_fill is None:
            prop_fill = getattr(QgsSymbolLayer, "PropertyFillColor", None)
        if prop_fill is None and hasattr(QgsSymbolLayer, "Property"):
            prop_fill = getattr(QgsSymbolLayer.Property, "PropertyFillColor", None)
        if prop_fill is None:
            prop_fill = 1  # Standard QgsSymbolLayer::PropertyFillColor enum value

        # Determine fill property: line color expression if fill enabled, else transparent
        if fill_enabled:
            prop_fill_val = prop_color
        else:
            prop_fill_val = QgsProperty.fromValue("transparent")

        # Standard hollow/filled single shapes: S (丸), P (ダイヤ), C (三角)
        std_specs = [
            (AttributeType.S.value,  "S (丸)",    "circle",   str(sym_size)),
            (AttributeType.P.value,  "P (ダイヤ)", "diamond",  str(sym_size)),
            (AttributeType.C.value,  "C (三角)",  "triangle", str(sym_size)),
        ]

        for val, label, shape, size in std_specs:
            sym_layer = QgsSimpleMarkerSymbolLayer.create({
                "name": shape,
                "color": initial_fill_color,
                "outline_color": "#FF5722",
                "outline_width": str(line_width),
                "size": size,
            })
            sym_layer.setDataDefinedProperty(prop_stroke, prop_color)
            sym_layer.setDataDefinedProperty(prop_fill, prop_fill_val)
            symbol = QgsMarkerSymbol()
            symbol.changeSymbolLayer(0, sym_layer)
            categories.append(QgsRendererCategory(val, symbol, label))

        # SP: Double concentric circle (◎)
        sp_outer = QgsSimpleMarkerSymbolLayer.create({
            "name": "circle",
            "color": initial_fill_color,
            "outline_color": "#FF5722",
            "outline_width": str(line_width),
            "size": str(sym_size + 1.0),
        })
        sp_outer.setDataDefinedProperty(prop_stroke, prop_color)
        sp_outer.setDataDefinedProperty(prop_fill, prop_fill_val)

        sp_inner = QgsSimpleMarkerSymbolLayer.create({
            "name": "circle",
            "color": initial_fill_color,
            "outline_color": "#FF5722",
            "outline_width": str(line_width),
            "size": str(max(sym_size - 2.2, 1.5)),
        })
        sp_inner.setDataDefinedProperty(prop_stroke, prop_color)
        sp_inner.setDataDefinedProperty(prop_fill, prop_fill_val)

        sp_symbol = QgsMarkerSymbol()
        sp_symbol.changeSymbolLayer(0, sp_outer)
        sp_symbol.appendSymbolLayer(sp_inner)
        categories.append(QgsRendererCategory(AttributeType.SP.value, sp_symbol, "SP (二重丸)"))

        renderer = QgsCategorizedSymbolRenderer("attribute_type", categories)
        layer.setRenderer(renderer)

        # Configure point layer labeling synchronized with symbol stroke color
        lbl_size   = int(  (settings or {}).get("label_size",   10))
        lbl_halo   = bool( (settings or {}).get("label_halo",   True))
        lbl_offset = float((settings or {}).get("label_offset", 1.0))

        pal = QgsPalLayerSettings()
        pal.fieldName = (
            f"CASE WHEN \"excavation_type\" = '{ExcavationType.FEATURE.value}' THEN \"feature_name\" || '_' ELSE '' END "
            "|| \"point_name\" "
            "|| CASE WHEN \"branch_no\" IS NOT NULL AND \"branch_no\" != '' THEN '-' || \"branch_no\" ELSE '' END"
        )
        pal.isExpression = True
        pal.placement = Qgis.LabelPlacement.OverPoint
        pal.xOffset = lbl_offset
        pal.yOffset = -lbl_offset

        SymbologyMixin.apply_above_right_label_quadrant(pal)

        text_format = QgsTextFormat()
        text_format.setSize(lbl_size)
        text_format.setColor(QColor(grid_line_color))

        buffer = QgsTextBufferSettings()
        buffer.setEnabled(lbl_halo)
        buffer.setSize(1.0)
        buffer.setColor(QColor("white"))
        text_format.setBuffer(buffer)

        pal.setFormat(text_format)

        # Synchronize label font color with point symbol color via data-defined property
        prop_lbl_color = getattr(QgsPalLayerSettings, "Color", None)
        if prop_lbl_color is None and hasattr(QgsPalLayerSettings, "Property"):
            prop_lbl_color = getattr(QgsPalLayerSettings.Property, "Color", None)
        if prop_lbl_color is None:
            prop_lbl_color = 4

        pal.dataDefinedProperties().setProperty(prop_lbl_color, prop_color)

        labeling = QgsVectorLayerSimpleLabeling(pal)
        layer.setLabelsEnabled(True)
        layer.setLabeling(labeling)

        layer.triggerRepaint()

    @staticmethod
    def apply_ref_point_cross_symbology(layer: QgsVectorLayer) -> None:
        """Apply a simple cross symbol style for a main-canvas reference point layer.

        T-0017: moved from CanvasDigitizingTool.setup_ref_point_layer_symbology
        (map_tool.py) without changing behavior. Distinct from
        apply_ref_point_symbology(), which applies rule-based symbology (with
        大/小グリッド scale-dependent visibility) to the CSV-backed grid
        reference-point layer (LayerManager.ref_point_layer). At the time of
        this move, this method had no call sites anywhere in the codebase;
        it is preserved as-is (unused) rather than removed, since dead-code
        removal is outside this task's scope.

        :param layer: Target reference point layer.
        :type layer: QgsVectorLayer
        """
        if not layer or not layer.isValid():
            return

        sym_layer = QgsSimpleMarkerSymbolLayer.create({
            "name": "cross",
            "color": "#D32F2F",
            "outline_color": "#D32F2F",
            "outline_width": "1.2",
            "size": "7.0",
        })
        symbol = QgsMarkerSymbol()
        symbol.changeSymbolLayer(0, sym_layer)

        layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        layer.triggerRepaint()

    @staticmethod
    def apply_attribute_transparency(layer: QgsVectorLayer, selected_attribute: str) -> None:
        """Set unselected attribute category symbols to 50% opacity and selected category to 100%.

        T-0017: moved from CanvasDigitizingTool.update_attribute_transparency
        (map_tool.py) without changing behavior. At the time of this move,
        this method had no call sites anywhere in the codebase; it is
        preserved as-is (unused) rather than removed, since dead-code removal
        is outside this task's scope.

        :param layer: Point layer with QgsCategorizedSymbolRenderer.
        :type layer: QgsVectorLayer
        :param selected_attribute: Current confirmed attribute type ('S', 'P', 'C', 'SP').
        :type selected_attribute: str
        """
        if not layer or not layer.isValid():
            return

        renderer = layer.renderer()
        if not isinstance(renderer, QgsCategorizedSymbolRenderer):
            return

        for category in renderer.categories():
            sym = category.symbol().clone()
            if category.value() == selected_attribute:
                sym.setOpacity(1.0)
            else:
                sym.setOpacity(0.5)
            category.setSymbol(sym)

        layer.triggerRepaint()

    @staticmethod
    def apply_above_right_label_quadrant(pal: QgsPalLayerSettings) -> None:
        """Align label anchor so its bottom-left sits exactly at the insertion point.

        Sets the label quadrant to AboveRight (enum value 2) on the given
        QgsPalLayerSettings instance, in place. Shared by
        apply_ref_point_symbology (reference points) and apply_point_symbology
        (digitized points), which both need identical label-anchor behavior.

        :param pal: Label settings object to mutate in place.
        :type pal: QgsPalLayerSettings
        """
        try:
            quad_val = 2
            if hasattr(Qgis, "LabelQuadrantPosition") and hasattr(Qgis.LabelQuadrantPosition, "QuadrantAboveRight"):
                quad_val = Qgis.LabelQuadrantPosition.QuadrantAboveRight
            elif hasattr(QgsPalLayerSettings, "QuadrantAboveRight"):
                quad_val = QgsPalLayerSettings.QuadrantAboveRight

            if hasattr(pal, "quadrantPosition"):
                pal.quadrantPosition = quad_val
            if hasattr(pal, "quadOffset"):
                pal.quadOffset = quad_val
        except Exception:
            pass

    @staticmethod
    def apply_ref_point_symbology(
        layer: QgsVectorLayer,
        settings: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Apply cross symbol style and rule-based rendering for reference points.

        :param layer: Target reference point layer (CSV Delimited Text).
        :type layer: QgsVectorLayer
        :param settings: Optional settings dict from settings.json. Falls back to UIConfig defaults.
        :type settings: Optional[Dict[str, Any]]
        """
        if not layer or not layer.isValid():
            return

        from ..ui.main_dock import UIConfig

        # Resolve display values from settings or UIConfig defaults
        sym_size    = float((settings or {}).get("ref_symbol_size",       (settings or {}).get("symbol_size", UIConfig.SYMBOL_SIZE_REF)))
        line_width  = float((settings or {}).get("ref_symbol_line_width",  (settings or {}).get("symbol_line_width", 1.2)))
        line_color  = str(  (settings or {}).get("ref_symbol_line_color",  (settings or {}).get("ref_symbol_color", "#D32F2F")))
        lbl_size    = int(  (settings or {}).get("label_size",             UIConfig.LABEL_SIZE_REF))
        lbl_halo    = bool( (settings or {}).get("label_halo",             True))
        lbl_offset  = float((settings or {}).get("label_offset",           1.0))
        scale_major = int(  (settings or {}).get("scale_major_grid",       -1))
        scale_minor = int(  (settings or {}).get("scale_minor_grid",       UIConfig.SCALE_THRESHOLD))

        symbol = QgsMarkerSymbol.createSimple({
            "name": "cross",
            "color": line_color,
            "outline_color": line_color,
            "outline_width": str(line_width),
            "size": str(sym_size),
        })

        root_rule = QgsRuleBasedRenderer.Rule(None)

        # Rule 1: Subgrid "00" — visibility controlled by scale_major_grid
        rule1 = QgsRuleBasedRenderer.Rule(symbol.clone())
        rule1.setLabel("Subgrid 00")
        rule1.setFilterExpression('"小グリッド" = \'00\'')
        if scale_major > 0:
            rule1.setMinimumScale(scale_major)
        root_rule.appendChild(rule1)

        # Rule 2: Subgrid != "00" — visibility controlled by scale_minor_grid
        rule2 = QgsRuleBasedRenderer.Rule(symbol.clone())
        rule2.setLabel("Subgrid non-00")
        rule2.setFilterExpression('"小グリッド" != \'00\'')
        if scale_minor > 0:
            rule2.setMinimumScale(scale_minor)
        root_rule.appendChild(rule2)

        renderer = QgsRuleBasedRenderer(root_rule)
        layer.setRenderer(renderer)

        pal = QgsPalLayerSettings()
        # Label format: [大グリッドＸ][大グリッドＹ]-[小グリッド]  e.g. "5C-00"
        pal.fieldName = '"大グリッドＸ" || "大グリッドＹ" || \'-\' || "小グリッド"'
        pal.isExpression = True
        pal.placement = Qgis.LabelPlacement.OverPoint

        # Quadrant placement - we don't use Quadrant enum to avoid missing constant issues.
        # Instead, we just offset the label X right and Y up (negative Y).
        pal.xOffset = lbl_offset
        pal.yOffset = -lbl_offset

        SymbologyMixin.apply_above_right_label_quadrant(pal)

        text_format = QgsTextFormat()
        text_format.setSize(lbl_size)
        text_format.setColor(QColor(line_color))

        buffer = QgsTextBufferSettings()
        buffer.setEnabled(lbl_halo)
        buffer.setSize(1.0)
        buffer.setColor(QColor("white"))
        text_format.setBuffer(buffer)

        pal.setFormat(text_format)

        labeling = QgsVectorLayerSimpleLabeling(pal)
        layer.setLabelsEnabled(True)
        layer.setLabeling(labeling)
        layer.triggerRepaint()

    @staticmethod
    def build_opacity_expression(
        is_focus_on: bool,
        filters: Optional[Dict[str, Any]],
        slider_val: int = 0,
    ) -> str:
        """Build the QgsProperty expression string controlling per-category point opacity.

        Constructs a CASE WHEN expression string based on filter criteria:
        - attributes: IN clause for matching attribute types
        - excavation_types & feature_names: composite OR condition for excavation types and features
        - drawing_name: exact match if drawing_name is non-empty
        - non-matching points evaluate to slider_val (0 by default, for complete transparency)

        :param is_focus_on: Whether display filter / Focus Mode is currently active.
        :type is_focus_on: bool
        :param filters: Dict with keys 'attributes', 'excavation_types', 'feature_names',
            and optionally 'drawing_name'.
        :type filters: Optional[Dict[str, Any]]
        :param slider_val: Opacity percentage (0-100) applied to non-matching points (default: 0).
        :type slider_val: int
        :return: Expression string suitable for QgsProperty.fromExpression().
        :rtype: str
        """
        if not is_focus_on:
            return "100"

        filters = filters or {}

        def _escape_sql(s: str) -> str:
            return s.replace("'", "''")

        # 1. 属性条件 (IN 句)
        raw_attrs = filters.get("attributes")
        if raw_attrs is None and "attribute_type" in filters:
            raw_attrs = [filters["attribute_type"]] if filters["attribute_type"] else []
        attrs = [str(a).strip() for a in raw_attrs if a] if raw_attrs is not None else []
        if attrs:
            escaped_attrs = ", ".join(f"'{_escape_sql(a)}'" for a in attrs)
            attr_expr = f"\"attribute_type\" IN ({escaped_attrs})"
        else:
            attr_expr = "1 = 0"

        # 2. 出土形態・遺構名複合OR条件
        raw_excs = filters.get("excavation_types")
        if raw_excs is None and "excavation_type" in filters:
            raw_excs = [filters["excavation_type"]] if filters["excavation_type"] else []
        excs = [str(e).strip() for e in raw_excs if e] if raw_excs is not None else []

        raw_feats = filters.get("feature_names")
        if raw_feats is None and "feature_name" in filters:
            raw_feats = [filters["feature_name"]] if filters["feature_name"] else []
        feats = [str(f).strip() for f in raw_feats if f] if raw_feats is not None else []

        ex_parts = []
        if ExcavationType.GRID.value in excs:
            ex_parts.append(f"\"excavation_type\" = '{ExcavationType.GRID.value}'")
        if ExcavationType.FEATURE.value in excs:
            if feats:
                escaped_feats = ", ".join(f"'{_escape_sql(f)}'" for f in feats)
                ex_parts.append(
                    f"(\"excavation_type\" = '{ExcavationType.FEATURE.value}' AND \"feature_name\" IN ({escaped_feats}))"
                )
            else:
                ex_parts.append(f"(\"excavation_type\" = '{ExcavationType.FEATURE.value}' AND 1 = 0)")

        if not ex_parts:
            ex_expr = "1 = 0"
        elif len(ex_parts) == 1:
            ex_expr = ex_parts[0]
        else:
            ex_expr = f"({' OR '.join(ex_parts)})"

        # 3. 対象図面条件 (target_drawing_name が None ではない場合に追加)
        target_drawing = filters.get("target_drawing_name")
        drawing_expr = None
        
        if target_drawing is not None:
            d_name = target_drawing.strip()
            if not d_name or d_name == "-- 未指定 --":
                # 未指定時は、図面に紐づいていない（NULLまたは空）点を抽出
                drawing_expr = "(\"drawing_name\" IS NULL OR \"drawing_name\" = '')"
            else:
                drawing_expr = f"\"drawing_name\" = '{_escape_sql(d_name)}'"

        conditions = [attr_expr, ex_expr]
        if drawing_expr:
            conditions.append(drawing_expr)

        condition_str = " AND ".join(conditions)
        return f"CASE WHEN {condition_str} THEN 100 ELSE {slider_val} END"

    @staticmethod
    def apply_opacity_expression(layer: QgsVectorLayer, expr: str) -> None:
        """Apply a QgsProperty opacity expression to every category symbol and label of a layer.

        Overrides each category symbol's opacity and label opacity via data-defined
        properties built from ``expr`` (as produced by build_opacity_expression()),
        then re-sets the renderer and labeling on the layer and triggers a repaint.

        :param layer: Point layer with QgsCategorizedSymbolRenderer.
        :type layer: QgsVectorLayer
        :param expr: Expression string evaluating to an opacity percentage (0-100).
        :type expr: str
        """
        if not layer or not layer.isValid():
            return

        renderer = layer.renderer()
        if not isinstance(renderer, QgsCategorizedSymbolRenderer):
            return

        prop = QgsProperty.fromExpression(expr)

        # Retrieve PropertyOpacity enum key safely
        prop_key = getattr(QgsSymbol, "PropertyOpacity", None)
        if prop_key is None and hasattr(QgsSymbol, "Property"):
            prop_key = getattr(QgsSymbol.Property, "PropertyOpacity", None)
        if prop_key is None:
            prop_key = 1

        for idx, category in enumerate(renderer.categories()):
            sym = category.symbol().clone()
            if sym:
                if prop_key is not None:
                    sym.setDataDefinedProperty(prop_key, prop)
                renderer.updateCategorySymbol(idx, sym)

        # Re-set modified renderer to layer
        layer.setRenderer(renderer.clone())

        # Synchronize label opacity with symbol opacity expression
        try:
            labeling = layer.labeling()
            if labeling is not None and hasattr(labeling, "settings"):
                pal_settings = labeling.settings()
                if pal_settings is not None:
                    prop_lbl_opacity = getattr(QgsPalLayerSettings, "LabelOpacity", None)
                    if prop_lbl_opacity is None and hasattr(QgsPalLayerSettings, "Property"):
                        prop_lbl_opacity = getattr(QgsPalLayerSettings.Property, "LabelOpacity", None)
                    if prop_lbl_opacity is None:
                        prop_lbl_opacity = getattr(QgsPalLayerSettings, "Opacity", None)
                    if prop_lbl_opacity is None and hasattr(QgsPalLayerSettings, "Property"):
                        prop_lbl_opacity = getattr(QgsPalLayerSettings.Property, "Opacity", None)
                    if prop_lbl_opacity is None and hasattr(QgsPalLayerSettings, "PropertyOpacity"):
                        prop_lbl_opacity = getattr(QgsPalLayerSettings.PropertyOpacity, None)
                    if prop_lbl_opacity is None:
                        prop_lbl_opacity = 15  # QgsPalLayerSettings::PropertyOpacity enum value

                    pal_settings.dataDefinedProperties().setProperty(prop_lbl_opacity, prop)
                    layer.setLabeling(QgsVectorLayerSimpleLabeling(pal_settings))
                    layer.setLabelsEnabled(True)
        except Exception:
            pass

        # Trigger canvas repaint
        layer.triggerRepaint()
