"""
/***************************************************************************
 PointerGeocoding Plugin - GeoPackage & Spatial Index Cache Mixin
 ***************************************************************************/

Stage C split (mechanical, logic-preserving): extracted from
layer_manager.py. Provides GpkgCacheMixin, mixed into LayerManager,
containing GeoPackage creation/migration and the QgsSpatialIndex /
attribute-cache Observer pattern that keeps them in sync with the points
layer.
"""
# 【変更不可侵の絶対的ルール】 測量座標系（X軸=南北, Y軸=東西）を採用。QGISキャンバス上のX座標(東西)はSurvey Y、Y座標(南北)はSurvey Xに対応する。

import os
from typing import Any, Tuple

from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsVectorFileWriter,
    QgsField,
    QgsFeature,
    QgsGeometry,
    QgsSpatialIndex,
    NULL,
)
from qgis.PyQt.QtCore import QVariant

from .models import get_local_crs


class GpkgCacheMixin:
    """Mixin providing GeoPackage schema management and spatial index/attribute
    cache Observer synchronization for LayerManager."""

    @staticmethod
    def create_gpkg_layer(layer: QgsVectorLayer, gpkg_path: str, layer_name: str) -> Tuple[bool, str]:
        """Export or append a vector layer into a GeoPackage using writeAsVectorFormatV3."""
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = layer_name

        if os.path.exists(gpkg_path):
            options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
        else:
            options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile

        options.fileEncoding = "UTF-8"

        context = QgsProject.instance().transformContext()
        result = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer, gpkg_path, context, options
        )
        error = result[0] if isinstance(result, tuple) else result
        error_msg = result[1] if isinstance(result, tuple) and len(result) > 1 else str(error)
        return error == QgsVectorFileWriter.NoError, error_msg

    @classmethod
    def create_initial_gpkg(cls, gpkg_path: str) -> Tuple[bool, str]:
        """Create initial 'points' schema inside the GeoPackage.

        Note: ref_points is now loaded directly from the CSV grid file (Delimited Text Provider)
        and is NOT persisted in the GeoPackage.
        # 【変更不可侵の絶対的ルール】 測量座標系（X軸=南北, Y軸=東西）を採用。QGISキャンバス上のX座標(東西)はSurvey Y、Y座標(南北)はSurvey Xに対応する。
        """
        local_crs = get_local_crs()

        # Initialize 'points' schema (Point digitizing layer) with drawing_name column
        point_layer = QgsVectorLayer("Point?crs=", "points", "memory")
        point_layer.setCrs(local_crs)
        point_pr = point_layer.dataProvider()
        point_fields = [
            QgsField("point_id", QVariant.Int),
            QgsField("drawing_name", QVariant.String),
            QgsField("excavation_type", QVariant.String),
            QgsField("feature_name", QVariant.String),
            QgsField("color_code", QVariant.String),
            QgsField("attribute_type", QVariant.String),
            QgsField("point_name", QVariant.String),
            QgsField("branch_no", QVariant.String),
            QgsField("canvas_x", QVariant.Double),
            QgsField("canvas_y", QVariant.Double),
            QgsField("real_x", QVariant.Double),
            QgsField("real_y", QVariant.Double),
            QgsField("pixel_x", QVariant.Double),
            QgsField("pixel_y", QVariant.Double),
        ]
        point_pr.addAttributes(point_fields)
        point_layer.updateFields()

        success, msg = cls.create_gpkg_layer(point_layer, gpkg_path, "points")
        if not success:
            return False, f"pointsレイヤ作成失敗: {msg}"

        return True, ""

    @staticmethod
    def check_and_migrate_point_layer(layer: QgsVectorLayer) -> bool:
        """Verify existence of required columns (drawing_name, pixel_x, pixel_y) and add them automatically if missing.

        :param layer: Target point vector layer.
        :type layer: QgsVectorLayer
        :return: True if columns are present or successfully added.
        :rtype: bool
        """
        if not layer or not layer.isValid():
            return False
        fields = layer.fields()
        pr = layer.dataProvider()
        if pr is None:
            return False

        new_fields = []
        if fields.indexFromName("drawing_name") == -1:
            new_fields.append(QgsField("drawing_name", QVariant.String))
        if fields.indexFromName("pixel_x") == -1:
            new_fields.append(QgsField("pixel_x", QVariant.Double))
        if fields.indexFromName("pixel_y") == -1:
            new_fields.append(QgsField("pixel_y", QVariant.Double))

        if new_fields:
            success = pr.addAttributes(new_fields)
            layer.updateFields()
            return bool(success)

        return True

    @staticmethod
    def _extract_field_str(feat: QgsFeature, field_name: str) -> str:
        """Extract trimmed string representation from feature field, handling NULL and QVariant."""
        if field_name not in feat.fields().names():
            return ""
        val = feat[field_name]
        if val is None or val == NULL:
            return ""
        s = str(val).strip()
        return "" if s.lower() == "null" else s

    @staticmethod
    def _safe_str(val: Any) -> str:
        """Normalize arbitrary attribute value to string, handling NULL."""
        if val is None or val == NULL:
            return ""
        s = str(val).strip()
        return "" if s.lower() == "null" else s

    def init_spatial_index_and_cache(self) -> None:
        """Construct QgsSpatialIndex and in-memory caches, and register Observer signal hooks."""
        if not self.point_layer or not self.point_layer.isValid():
            self.spatial_index = None
            self.attr_cache.clear()
            self.geom_cache.clear()
            return

        # 1. Automatic schema migration
        self.check_and_migrate_point_layer(self.point_layer)

        # 2. Detach existing signal hooks if any
        self._disconnect_point_layer_signals()

        # 3. Initialize spatial index
        self.spatial_index = QgsSpatialIndex(self.point_layer.getFeatures())

        # 4. Populate attribute cache and geometry cache
        self.attr_cache.clear()
        self.geom_cache.clear()
        for feat in self.point_layer.getFeatures():
            fid = feat.id()
            self.attr_cache[fid] = {
                "drawing_name": self._extract_field_str(feat, "drawing_name"),
                "excavation_type": self._extract_field_str(feat, "excavation_type"),
                "feature_name": self._extract_field_str(feat, "feature_name"),
                "attribute_type": self._extract_field_str(feat, "attribute_type"),
            }
            if feat.hasGeometry() and not feat.geometry().isEmpty():
                self.geom_cache[fid] = QgsGeometry(feat.geometry())

        # 5. Connect layer signals for dynamic background synchronization
        self.point_layer.featureAdded.connect(self._on_feature_added)
        self.point_layer.featuresDeleted.connect(self._on_features_deleted)
        self.point_layer.attributeValueChanged.connect(self._on_attribute_changed)
        self.point_layer.geometryChanged.connect(self._on_geometry_changed)
        self._signals_connected = True

    def _disconnect_point_layer_signals(self) -> None:
        """Safely detach Observer signal connections from the point layer."""
        if self._signals_connected and self.point_layer and self.point_layer.isValid():
            try:
                self.point_layer.featureAdded.disconnect(self._on_feature_added)
            except (TypeError, RuntimeError):
                pass
            try:
                self.point_layer.featuresDeleted.disconnect(self._on_features_deleted)
            except (TypeError, RuntimeError):
                pass
            try:
                self.point_layer.attributeValueChanged.disconnect(self._on_attribute_changed)
            except (TypeError, RuntimeError):
                pass
            try:
                self.point_layer.geometryChanged.disconnect(self._on_geometry_changed)
            except (TypeError, RuntimeError):
                pass
            self._signals_connected = False

    def _on_feature_added(self, fid: int) -> None:
        """Synchronize spatial index and caches when a new feature is added."""
        if not self.point_layer or not self.point_layer.isValid():
            return
        feat = self.point_layer.getFeature(fid)
        if not feat.isValid():
            return

        if self.spatial_index is not None and feat.hasGeometry():
            self.spatial_index.addFeature(feat)

        self.attr_cache[fid] = {
            "drawing_name": self._extract_field_str(feat, "drawing_name"),
            "excavation_type": self._extract_field_str(feat, "excavation_type"),
            "feature_name": self._extract_field_str(feat, "feature_name"),
            "attribute_type": self._extract_field_str(feat, "attribute_type"),
        }
        if feat.hasGeometry() and not feat.geometry().isEmpty():
            self.geom_cache[fid] = QgsGeometry(feat.geometry())

    def _on_features_deleted(self, fids: Any) -> None:
        """Synchronize spatial index and caches when features are deleted."""
        fid_list = list(fids) if hasattr(fids, "__iter__") else [fids]
        for fid in fid_list:
            if self.spatial_index is not None:
                if (geom := self.geom_cache.get(fid)) and not geom.isEmpty():
                    del_feat = QgsFeature(fid)
                    del_feat.setGeometry(geom)
                    self.spatial_index.deleteFeature(del_feat)
            self.attr_cache.pop(fid, None)
            self.geom_cache.pop(fid, None)

    def _on_attribute_changed(self, fid: int, idx: int, value: Any) -> None:
        """Synchronize attribute cache when monitored fields change."""
        if not self.point_layer or not self.point_layer.isValid():
            return
        fields = self.point_layer.fields()
        if idx < 0 or idx >= fields.count():
            return
        field_name = fields.field(idx).name()
        if field_name in ("drawing_name", "excavation_type", "feature_name", "attribute_type"):
            if fid in self.attr_cache:
                self.attr_cache[fid][field_name] = self._safe_str(value)
            else:
                feat = self.point_layer.getFeature(fid)
                if feat.isValid():
                    self.attr_cache[fid] = {
                        "drawing_name": self._extract_field_str(feat, "drawing_name"),
                        "excavation_type": self._extract_field_str(feat, "excavation_type"),
                        "feature_name": self._extract_field_str(feat, "feature_name"),
                        "attribute_type": self._extract_field_str(feat, "attribute_type"),
                    }
                    if feat.hasGeometry() and not feat.geometry().isEmpty():
                        self.geom_cache[fid] = QgsGeometry(feat.geometry())

    def _on_geometry_changed(self, fid: int, geom: QgsGeometry) -> None:
        """Synchronize spatial index and geometry cache when feature geometry is modified."""
        if self.spatial_index is not None:
            if (old_geom := self.geom_cache.get(fid)) and not old_geom.isEmpty():
                old_feat = QgsFeature(fid)
                old_feat.setGeometry(old_geom)
                self.spatial_index.deleteFeature(old_feat)
            if geom and not geom.isEmpty():
                new_feat = QgsFeature(fid)
                new_feat.setGeometry(geom)
                self.spatial_index.addFeature(new_feat)
        if geom and not geom.isEmpty():
            self.geom_cache[fid] = QgsGeometry(geom)
        else:
            self.geom_cache.pop(fid, None)
