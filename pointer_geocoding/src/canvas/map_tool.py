"""
/***************************************************************************
 PointerGeocoding Plugin - Custom Map Digitizing and Georeferencing Tools
 ***************************************************************************/
"""
# 【変更不可侵の絶対的ルール】 測量座標系（X軸=南北, Y軸=東西）を採用。QGISキャンバス上のX座標(東西)はSurvey Y、Y座標(南北)はSurvey Xに対応する。

import math
from typing import Optional, Any, Dict, List, Tuple

from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsRectangle,
    QgsFeatureRequest,
    QgsCoordinateReferenceSystem,
    QgsSpatialIndex,
    QgsSymbol,
)
from qgis.gui import (
    QgsMapTool,
    QgsMapCanvas,
    QgsMapMouseEvent,
    QgsVertexMarker,
    QgsMapCanvasItem,
)
from qgis.PyQt.QtCore import Qt, pyqtSignal, QRectF
from qgis.PyQt.QtGui import QColor, QCursor, QFont, QPainter
from qgis.PyQt.QtWidgets import QInputDialog, QWidget

from ..logic.core import ExcavationType

class PreviewTextItem(QgsMapCanvasItem):
    """Temporary canvas item to display text labels for reference points."""
    def __init__(self, canvas: QgsMapCanvas, map_pt: QgsPointXY, text: str, font_size: int = 10):
        super().__init__(canvas)
        self.map_pt = map_pt
        self.text = text
        self.font = QFont("sans-serif", font_size)
        self.font.setBold(True)
        self.setPos(self.toCanvasCoordinates(self.map_pt))

    def paint(self, painter: QPainter, option: Any = None, widget: Optional[QWidget] = None) -> None:
        painter.setFont(self.font)
        painter.setPen(QColor("#D32F2F"))
        # Offset to top right
        painter.drawText(10, -10, self.text)

    def boundingRect(self) -> QRectF:
        return QRectF(0, -30, 150, 40)

    def updatePosition(self) -> None:
        self.setPos(self.toCanvasCoordinates(self.map_pt))


class ImageGeorefTool(QgsMapTool):
    """Custom QgsMapTool for picking reference points on the temporary preview canvas.

    Translates preview canvas coordinates into image pixel coordinates (X, Y)
    where (0, 0) is the top-left of the image. Provides 15px hover snap detection and visual box marker.
    """

    point_clicked = pyqtSignal(float, float)  # Emits (pixel_x, pixel_y)

    def __init__(self, canvas: QgsMapCanvas, raster_layer: QgsRasterLayer) -> None:
        """Initialize preview georeferencing tool.

        :param canvas: Preview map canvas instance.
        :type canvas: QgsMapCanvas
        :param raster_layer: The unreferenced raster layer being previewed.
        :type raster_layer: QgsRasterLayer
        """
        super().__init__(canvas)
        self.canvas = canvas
        self.raster_layer = raster_layer
        self.markers: List[QgsVertexMarker] = []
        self.text_items: List[PreviewTextItem] = []
        self.ref_points_data: List[Dict[str, Any]] = []

        # Highlight marker for snapping on hover
        self.snap_marker = QgsVertexMarker(self.canvas)
        self.snap_marker.setIconType(QgsVertexMarker.ICON_BOX)
        self.snap_marker.setColor(QColor("#D32F2F"))
        self.snap_marker.setPenWidth(2)
        self.snap_marker.setIconSize(14)
        self.snap_marker.hide()

    def set_ref_points_data(self, ref_points_data: List[Dict[str, Any]]) -> None:
        """Update reference points list for hover snapping.

        :param ref_points_data: List of reference point dicts.
        :type ref_points_data: List[Dict[str, Any]]
        """
        self.ref_points_data = ref_points_data

    def activate(self) -> None:
        """Called when tool is activated on the preview canvas."""
        super().activate()
        self.setCursor(Qt.CrossCursor)

    def deactivate(self) -> None:
        """Called when tool is deactivated."""
        if self.snap_marker:
            self.snap_marker.hide()
        super().deactivate()

    def set_interaction_locked(self, locked: bool) -> None:
        """Lock or unlock canvas interactions during heavy operations."""
        self._interaction_locked = locked
        if locked:
            if self.snap_marker:
                self.snap_marker.hide()
            self.setCursor(Qt.WaitCursor)
        else:
            self.setCursor(Qt.CrossCursor)

    def canvasMoveEvent(self, event: QgsMapMouseEvent) -> None:
        """Highlight nearby reference points within 15px with visual box marker on hover."""
        if getattr(self, "_interaction_locked", False):
            if self.snap_marker:
                self.snap_marker.hide()
            return

        if not self.ref_points_data:
            if self.snap_marker:
                self.snap_marker.hide()
            self.setCursor(Qt.CrossCursor)
            return

        extent = self.raster_layer.extent()
        w = float(self.raster_layer.width())
        h = float(self.raster_layer.height())
        if w <= 0 or h <= 0 or extent.width() <= 0 or extent.height() <= 0:
            if self.snap_marker:
                self.snap_marker.hide()
            self.setCursor(Qt.CrossCursor)
            return

        mouse_screen = event.pos()
        snapped_pt: Optional[QgsPointXY] = None
        min_dist = float("inf")

        for rdata in self.ref_points_data:
            rx = float(rdata.get("pixel_x", 0.0))
            ry = float(rdata.get("pixel_y", 0.0))
            r_map_x = extent.xMinimum() + (rx / w) * extent.width()
            r_map_y = extent.yMaximum() - (ry / h) * extent.height()
            r_screen = self.toCanvasCoordinates(QgsPointXY(r_map_x, r_map_y))

            dist = math.hypot(
                mouse_screen.x() - r_screen.x(),
                mouse_screen.y() - r_screen.y(),
            )
            if dist <= 15.0 and dist < min_dist:
                min_dist = dist
                snapped_pt = QgsPointXY(r_map_x, r_map_y)

        if snapped_pt is not None:
            self.snap_marker.setCenter(snapped_pt)
            self.snap_marker.show()
            self.setCursor(Qt.PointingHandCursor)
        else:
            if self.snap_marker:
                self.snap_marker.hide()
            self.setCursor(Qt.CrossCursor)

    def canvasReleaseEvent(self, event: QgsMapMouseEvent) -> None:
        """Process mouse release event on the preview canvas to emit pixel coordinates."""
        if getattr(self, "_interaction_locked", False):
            return

        if event.button() != Qt.LeftButton:
            return

        map_point = self.toMapCoordinates(event.pos())
        if not self.raster_layer or not self.raster_layer.isValid():
            self.point_clicked.emit(map_point.x(), abs(map_point.y()))
            return

        extent = self.raster_layer.extent()
        w = float(self.raster_layer.width())
        h = float(self.raster_layer.height())

        if extent.width() > 0 and extent.height() > 0 and w > 0 and h > 0:
            pixel_x = (map_point.x() - extent.xMinimum()) / (extent.width() / w)
            pixel_y = (extent.yMaximum() - map_point.y()) / (extent.height() / h)
        else:
            pixel_x = map_point.x()
            pixel_y = abs(map_point.y())

        # Clamp within pixel bounds
        pixel_x = max(0.0, min(w, pixel_x))
        pixel_y = max(0.0, min(h, pixel_y))

        self.point_clicked.emit(pixel_x, pixel_y)

    def add_point_marker(self, pixel_x: float, pixel_y: float, name: str = "") -> None:
        """Place a visual vertex marker on the preview canvas at the given pixel location.

        :param pixel_x: X pixel coordinate.
        :type pixel_x: float
        :param pixel_y: Y pixel coordinate.
        :type pixel_y: float
        :param name: Label text for the point.
        :type name: str
        """
        if not self.raster_layer or not self.raster_layer.isValid():
            return

        extent = self.raster_layer.extent()
        w = float(self.raster_layer.width())
        h = float(self.raster_layer.height())
        if w <= 0 or h <= 0:
            return

        map_x = extent.xMinimum() + (pixel_x / w) * extent.width()
        map_y = extent.yMaximum() - (pixel_y / h) * extent.height()
        map_pt = QgsPointXY(map_x, map_y)

        # Import UIConfig lazily to avoid circular imports if any, or directly if okay.
        # Actually it's easier to just use hardcoded default or import.
        from ..ui.dock import UIConfig

        marker = QgsVertexMarker(self.canvas)
        marker.setIconType(QgsVertexMarker.ICON_CROSS)
        marker.setColor(QColor("#D32F2F"))
        marker.setPenWidth(2)
        # Convert mm to approx pixels or use fixed size, here UIConfig says 4.0 but that's for QgsSymbol.
        # Let's use 12 for canvas vertex marker.
        marker.setIconSize(12)
        marker.setCenter(map_pt)
        marker.show()
        self.markers.append(marker)

        if name:
            label = PreviewTextItem(self.canvas, map_pt, name, font_size=UIConfig.LABEL_SIZE_REF)
            self.text_items.append(label)

    def clear_markers(self) -> None:
        """Remove all visual vertex markers from the preview canvas scene."""
        for m in self.markers:
            try:
                self.canvas.scene().removeItem(m)
            except Exception:
                pass
        self.markers.clear()
        
        for t in self.text_items:
            try:
                self.canvas.scene().removeItem(t)
            except Exception:
                pass
        self.text_items.clear()
        self.markers.clear()

    def clean_up(self) -> None:
        """Clean up map tool markers."""
        self.clear_markers()
        if self.snap_marker:
            try:
                self.canvas.scene().removeItem(self.snap_marker)
            except Exception:
                pass
            self.snap_marker = None


class CanvasDigitizingTool(QgsMapTool):
    """Custom QgsMapTool for continuous artifact point digitizing on the main canvas.

    Integrates QgsSpatialIndex for high-performance hover snapping,
    supports Focus Mode category filtering, and records canvas/real-world coordinates.
    """

    # Step3: canvas_clicked notifies the dock of a plain click (no existing point hit).
    # Feature validation/construction/layer writes are handled by
    # MainDockWidget._on_canvas_clicked, not by this tool.
    canvas_clicked = pyqtSignal(QgsPointXY)
    existing_point_selected = pyqtSignal(dict)
    # T-0039: emitted when a blank-space click occurs while in edit mode
    # (snap-to-existing-feature detection missed). Edit mode itself is
    # kept; only the dock widget's currently-selected feature should be
    # deselected in response (see Tab2DigitizingMixin._reset_point_selection).
    blank_click_in_edit_mode = pyqtSignal()

    def __init__(
        self,
        canvas: QgsMapCanvas,
        point_layer: QgsVectorLayer,
        dock_widget: Optional[QWidget] = None,
        layer_manager: Optional[Any] = None,
    ) -> None:
        """Initialize the digitizing map tool.

        :param canvas: Main map canvas instance.
        :type canvas: QgsMapCanvas
        :param point_layer: Vector layer for digitized points.
        :type point_layer: QgsVectorLayer
        :param dock_widget: Reference to the main dock widget for state synchronization.
        :type dock_widget: Optional[QWidget]
        :param layer_manager: Optional LayerManager instance with spatial index and caches.
        :type layer_manager: Optional[Any]
        """
        super().__init__(canvas)
        self.canvas = canvas
        self.point_layer = point_layer
        self.dock_widget = dock_widget
        self.layer_manager = layer_manager or (
            getattr(dock_widget, "layer_manager", None) if dock_widget else None
        )

        # Highlight vertex marker on hover
        self.hover_marker = QgsVertexMarker(self.canvas)
        self.hover_marker.setIconType(QgsVertexMarker.ICON_BOX)
        self.hover_marker.setColor(QColor("#D32F2F"))
        self.hover_marker.setPenWidth(2)
        self.hover_marker.setIconSize(14)
        self.hover_marker.hide()

        # T-0023: Selected-point marker (same red box style as hover_marker),
        # displayed persistently while an existing point is selected for
        # editing/number-correction/deletion, independent of mouse hover.
        # Cleared on: selecting another point, a plain canvas click, or the
        # dock's "reset" button (see MainDockWidget._reset_point_selection).
        self.selected_marker = QgsVertexMarker(self.canvas)
        self.selected_marker.setIconType(QgsVertexMarker.ICON_BOX)
        self.selected_marker.setColor(QColor("#D32F2F"))
        self.selected_marker.setPenWidth(2)
        self.selected_marker.setIconSize(14)
        self.selected_marker.hide()

        # Focus mode state cache, pushed one-way from MainDockWidget via
        # update_focus_state() (Step3: replaces pulling dock_widget getters).
        self._focus_active: bool = False
        self._focus_filter: Dict[str, str] = {}

        # Initialize categorised symbology for point layer (T-0017: symbology
        # construction now lives in SymbologyMixin/symbology_mixin.py, mixed
        # into LayerManager; this tool only delegates to it).
        if self.layer_manager and hasattr(self.layer_manager, "apply_point_symbology"):
            current_settings = (
                self.layer_manager.load_settings()
                if hasattr(self.layer_manager, "load_settings")
                else None
            )
            self.layer_manager.apply_point_symbology(self.point_layer, current_settings)

    def activate(self) -> None:
        """Called when the map tool becomes active."""
        super().activate()
        self.setCursor(Qt.CrossCursor)

    def deactivate(self) -> None:
        """Called when the map tool is deactivated."""
        if self.hover_marker:
            self.hover_marker.hide()
        if self.selected_marker:
            self.selected_marker.hide()
        super().deactivate()

    def show_selected_marker(self, map_point: QgsPointXY) -> None:
        """Display the persistent selection marker at the given point (T-0023).

        :param map_point: Location of the selected existing point (canvas coordinates).
        :type map_point: QgsPointXY
        """
        if self.selected_marker:
            self.selected_marker.setCenter(map_point)
            self.selected_marker.show()

    def clear_selected_marker(self) -> None:
        """Hide the persistent selection marker (T-0023).

        Called when selection is cleared: another point is selected (marker is
        immediately repositioned instead), a plain canvas click occurs, or the
        dock's "reset" button is pressed.
        """
        if self.selected_marker:
            self.selected_marker.hide()

    def update_focus_state(self, active: bool, filters: Dict[str, Any]) -> None:
        """Receive Focus Mode state pushed from MainDockWidget and cache it locally.

        Called by MainDockWidget whenever the focus toggle or display filter
        settings change, so this tool never needs to call back into the dock widget to read UI state.

        :param active: Whether Focus Mode is currently active.
        :type active: bool
        :param filters: Dict with filter criteria ('attributes', 'excavation_types', 'feature_names', 'drawing_name').
        :type filters: Dict[str, Any]
        """
        self._focus_active = bool(active)
        self._focus_filter = dict(filters) if filters else {}

    # T-0017: setup_point_layer_symbology/setup_ref_point_layer_symbology/
    # update_attribute_transparency were moved to SymbologyMixin
    # (symbology_mixin.py) as apply_point_symbology/apply_ref_point_cross_symbology/
    # apply_attribute_transparency, reached via self.layer_manager. This tool's
    # responsibility is now limited to geometry selection and canvas interaction;
    # symbology details are consolidated in symbology_mixin.py.

    def find_nearest_feature_id(
        self, map_point: QgsPointXY
    ) -> Optional[Tuple[int, float]]:
        """Find closest feature ID to map_point within 15px using QgsSpatialIndex.

        Applies focus mode category filtering using the state most recently pushed
        via update_focus_state(), falling back to overall nearest point within 15px
        if no filtered match is found.

        :param map_point: Target point in map canvas coordinates.
        :type map_point: QgsPointXY
        :return: Tuple of (feature_id, distance) if found within tolerance, None otherwise.
        :rtype: Optional[Tuple[int, float]]
        """
        lm = self.layer_manager or (
            getattr(self.dock_widget, "layer_manager", None) if self.dock_widget else None
        )
        if lm is None or lm.spatial_index is None:
            return None

        radius = 15.0 * self.canvas.mapUnitsPerPixel()
        search_rect = QgsRectangle(
            map_point.x() - radius,
            map_point.y() - radius,
            map_point.x() + radius,
            map_point.y() + radius,
        )

        # 1. Fast bounding box intersection query via QgsSpatialIndex
        candidate_ids = lm.spatial_index.intersects(search_rect)
        if not candidate_ids:
            return None

        # 2. Focus mode filtering (state pushed one-way from the dock via update_focus_state)
        is_focus_active = self._focus_active
        focus_filter: Dict[str, Any] = self._focus_filter if is_focus_active else {}

        valid_ids: List[int] = []
        attr_cache = getattr(lm, "attr_cache", {})

        if is_focus_active:
            req_drawing = (focus_filter.get("drawing_name") or "").strip()
            if req_drawing == "-- 未指定 --":
                req_drawing = ""

            raw_attrs = focus_filter.get("attributes")
            if raw_attrs is None and "attribute_type" in focus_filter:
                raw_attrs = [focus_filter["attribute_type"]] if focus_filter["attribute_type"] else []
            req_attrs = set(raw_attrs) if raw_attrs is not None else None

            raw_excs = focus_filter.get("excavation_types")
            if raw_excs is None and "excavation_type" in focus_filter:
                raw_excs = [focus_filter["excavation_type"]] if focus_filter["excavation_type"] else []
            req_excs = set(raw_excs) if raw_excs is not None else None

            raw_feats = focus_filter.get("feature_names")
            if raw_feats is None and "feature_name" in focus_filter:
                raw_feats = [focus_filter["feature_name"]] if focus_filter["feature_name"] else []
            req_feats = set(raw_feats) if raw_feats is not None else None

            for fid in candidate_ids:
                cached = attr_cache.get(fid)
                if cached is not None:
                    c_drawing = cached.get("drawing_name", "").strip()
                    c_excavation = cached.get("excavation_type", "").strip()
                    c_feature = cached.get("feature_name", "").strip()
                    c_attribute = cached.get("attribute_type", "").strip()

                    # 1. 図面判定 (req_drawing が指定されている場合のみ一致を確認)
                    if req_drawing and c_drawing != req_drawing:
                        continue

                    # 2. 属性判定
                    if req_attrs is not None and c_attribute not in req_attrs:
                        continue

                    # 3. 出土形態判定
                    if req_excs is not None and c_excavation not in req_excs:
                        continue

                    # 4. 遺構名判定 (出土形態が遺構の場合)
                    if c_excavation == ExcavationType.FEATURE.value:
                        if req_feats is not None and c_feature not in req_feats:
                            continue

                    valid_ids.append(fid)

        # 3. Calculate exact Euclidean distance for candidates and select nearest
        pt_geom = QgsGeometry.fromPointXY(map_point)
        geom_cache = getattr(lm, "geom_cache", {})
        
        def find_best(fids: List[int]) -> Optional[Tuple[int, float]]:
            best_fid = None
            min_dist = float("inf")
            for fid in fids:
                geom = geom_cache.get(fid)
                if geom is None and self.point_layer and self.point_layer.isValid():
                    f = self.point_layer.getFeature(fid)
                    if f.isValid():
                        geom = f.geometry()
                if geom and geom.type() == 0:
                    dist = geom.distance(pt_geom)
                    if dist < min_dist:
                        min_dist = dist
                        best_fid = fid
            if best_fid is not None and min_dist <= radius:
                return best_fid, min_dist
            return None

        # First try to find among valid_ids (focused)
        if is_focus_active:
            # フィルターON時は、条件に合致した(valid_ids)フィーチャのみを対象とする
            # （対象外フィーチャへのフォールバック検索は行わない）
            return find_best(valid_ids)
        else:
            # フィルターOFF時は、周辺の全フィーチャ(candidate_ids)を対象とする
            return find_best(candidate_ids)

    def find_nearest_feature(
        self, layer: QgsVectorLayer, map_point: QgsPointXY
    ) -> Optional[Tuple[QgsFeature, float]]:
        """Backward-compatible helper returning (QgsFeature, distance).

        :param layer: Target vector layer.
        :type layer: QgsVectorLayer
        :param map_point: Coordinate in canvas map coordinates.
        :type map_point: QgsPointXY
        :return: (QgsFeature, distance) if found, None otherwise.
        :rtype: Optional[Tuple[QgsFeature, float]]
        """
        nearest = self.find_nearest_feature_id(map_point)
        if nearest is not None and layer and layer.isValid():
            fid, dist = nearest
            feat = layer.getFeature(fid)
            if feat.isValid():
                return feat, dist
        return None

    def set_interaction_locked(self, locked: bool) -> None:
        """Lock or unlock canvas interactions during heavy operations."""
        current_count = getattr(self, "_interaction_lock_count", 0)
        if locked:
            current_count += 1
        else:
            current_count = max(0, current_count - 1)
        self._interaction_lock_count = current_count
        self._interaction_locked = (current_count > 0)

        if self._interaction_locked:
            if hasattr(self, "hover_marker") and self.hover_marker:
                self.hover_marker.hide()
            self.setCursor(Qt.WaitCursor)
        else:
            self.setCursor(Qt.CrossCursor)

    @property
    def is_interaction_locked(self) -> bool:
        return getattr(self, "_interaction_locked", False)

    def canvasMoveEvent(self, event: QgsMapMouseEvent) -> None:
        """Handle mouse movement: highlight nearby points within 15px tolerance using QgsSpatialIndex.

        T-0039b: mirrors the mode branching in _handle_digitize_click(). In
        "new" mode, snap detection is skipped entirely so no hover marker
        is ever shown (consistent with clicks never snapping to existing
        features in this mode). In "edit" mode, hover snap detection and
        the red hover marker remain unchanged.
        """
        if getattr(self, "_interaction_locked", False):
            if hasattr(self, "hover_marker") and self.hover_marker:
                self.hover_marker.hide()
            return

        mode = "new"
        if self.dock_widget:
            if hasattr(self.dock_widget, "tab2_state"):
                mode = self.dock_widget.tab2_state.current_mode
            else:
                mode = getattr(self.dock_widget, "tab2_current_mode", "new")
        if mode not in ("new", "edit"):
            mode = "new"

        if mode == "new":
            if getattr(self, "hover_marker", None) is not None:
                self.hover_marker.hide()
            self.setCursor(Qt.CrossCursor)
            return

        map_point = self.toMapCoordinates(event.pos())
        nearest = self.find_nearest_feature_id(map_point)

        if nearest is not None:
            fid, _ = nearest
            lm = self.layer_manager or (
                getattr(self.dock_widget, "layer_manager", None) if self.dock_widget else None
            )
            geom = getattr(lm, "geom_cache", {}).get(fid) if lm else None
            if geom is None and self.point_layer:
                f = self.point_layer.getFeature(fid)
                geom = f.geometry()

            if geom and geom.type() == 0:  # Point geometry
                pt = geom.asPoint()
                self.hover_marker.setCenter(pt)
                self.hover_marker.show()
                self.setCursor(Qt.PointingHandCursor)
                return

        self.hover_marker.hide()
        self.setCursor(Qt.CrossCursor)

    def canvasReleaseEvent(self, event: QgsMapMouseEvent) -> None:
        """Handle mouse button release: route to continuous digitizing logic."""
        if getattr(self, "_interaction_locked", False):
            return

        if event.button() != Qt.LeftButton:
            return

        map_point = self.toMapCoordinates(event.pos())
        self._handle_digitize_click(map_point)

    def _handle_digitize_click(self, map_point: QgsPointXY) -> None:
        """Process click event on main georeferenced canvas.

        T-0037: click behavior now branches on the dock widget's
        tab2_current_mode ("new" / "edit", set by
        Tab2DigitizingMixin._on_tab2_mode_changed):

        - "new" mode: existing-feature snap detection is skipped entirely;
          every click is treated as a plain canvas click and forwarded to
          MainDockWidget._on_canvas_clicked for new-point digitizing.
        - "edit" mode: only existing-feature snap detection is performed;
          a hit selects the point via existing_point_selected as before.
          A miss (blank click) never creates a new point; per T-0039 it
          emits blank_click_in_edit_mode so the dock widget can clear the
          current selection while remaining in edit mode.

        Falls back to "new" mode if tab2_current_mode is missing or holds
        an unexpected value (defensive default, mirroring T-0036's
        default_index=0 = new mode).
        """
        if not self.dock_widget:
            return

        mode = "new"
        if self.dock_widget:
            if hasattr(self.dock_widget, "tab2_state"):
                mode = self.dock_widget.tab2_state.current_mode
            else:
                mode = getattr(self.dock_widget, "tab2_current_mode", "new")
        if mode not in ("new", "edit"):
            mode = "new"

        if mode == "new":
            # New mode: always a plain canvas click, no snap-to-existing-
            # feature check. Input validation, duplicate checking, feature
            # construction and the layer write are all handled by
            # MainDockWidget._on_canvas_clicked (Step3: event-driven
            # decoupling — this tool no longer reads dock_widget state or
            # touches point_layer directly).
            self.clear_selected_marker()
            self.canvas_clicked.emit(map_point)
            return

        # Edit mode: only snap-to-existing-feature selection; a blank-space
        # click never creates a new point, but per T-0039 it does emit
        # blank_click_in_edit_mode so the dock widget clears the current
        # selection (the mode itself stays "edit").
        nearest = self.find_nearest_feature_id(map_point)
        if nearest is not None:
            fid, _ = nearest
            feat = self.point_layer.getFeature(fid)
            if feat.isValid():
                data = {
                    "point_id": feat["point_id"],
                    "drawing_name": (
                        feat["drawing_name"]
                        if "drawing_name" in feat.fields().names()
                        else ""
                    ),
                    "excavation_type": feat["excavation_type"],
                    "feature_name": feat["feature_name"],
                    "color_code": feat["color_code"],
                    "attribute_type": feat["attribute_type"],
                    "point_name": feat["point_name"],
                    "branch_no": feat["branch_no"],
                    "canvas_x": feat["canvas_x"],
                    "canvas_y": feat["canvas_y"],
                    "feature_id": feat.id(),
                }
                # T-0023: show the persistent selection marker at the hit point's
                # exact stored location (independent of hover, remains until
                # selection changes).
                self.show_selected_marker(QgsPointXY(feat["canvas_x"], feat["canvas_y"]))
                self.existing_point_selected.emit(data)
        else:
            # Blank click while in edit mode: keep edit mode active, but let
            # the dock widget clear any currently-selected feature (T-0039).
            self.blank_click_in_edit_mode.emit()

    def clean_up(self) -> None:
        """Remove canvas vertex markers safely."""
        if self.hover_marker:
            try:
                self.canvas.scene().removeItem(self.hover_marker)
            except Exception:
                pass
            self.hover_marker = None
        if self.selected_marker:
            try:
                self.canvas.scene().removeItem(self.selected_marker)
            except Exception:
                pass
            self.selected_marker = None
