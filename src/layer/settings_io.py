"""
/***************************************************************************
 PointerGeocoding Plugin - Settings & Image Metadata Mixin
 ***************************************************************************/

Stage C split (mechanical, logic-preserving): extracted from
layer_manager.py. Provides SettingsMetadataMixin, mixed into LayerManager,
containing settings.json and image_metadata.json persistence.
"""
# 【変更不可侵の絶対的ルール】 測量座標系（X軸=南北, Y軸=東西）を採用。QGISキャンバス上のX座標(東西)はSurvey Y、Y座標(南北)はSurvey Xに対応する。

import os
from typing import Optional, Tuple, Dict, Any, List, Union

from .models import PluginSettings, ImageLayerMeta, safe_json_load, safe_json_save


class SettingsMetadataMixin:
    """Mixin providing plugin settings and image metadata persistence for LayerManager."""

    def get_settings_path(self) -> Optional[str]:
        """Return the absolute path to settings.json."""
        if not self.session_json_dir:
            return None
        return os.path.join(self.session_json_dir, "settings.json")

    # Default settings values
    DEFAULT_SETTINGS: Dict[str, Any] = PluginSettings().to_dict()

    def load_settings(self) -> Dict[str, Any]:
        """Load settings from json/settings.json.

        Falls back to DEFAULT_SETTINGS for any missing key.

        :return: Settings dictionary.
        :rtype: Dict[str, Any]
        """
        result = dict(self.DEFAULT_SETTINGS)
        stored = safe_json_load(self.get_settings_path())
        if stored is not None:
            try:
                result.update(stored)
            except Exception:
                pass
        return result

    def load_settings_dataclass(self) -> PluginSettings:
        """Load settings from json/settings.json as a PluginSettings instance.

        :return: Typed PluginSettings instance.
        :rtype: PluginSettings
        """
        return PluginSettings.from_dict(self.load_settings())

    def save_settings(self, settings: Union[PluginSettings, Dict[str, Any]]) -> bool:
        """Persist settings to json/settings.json.

        :param settings: PluginSettings dataclass or settings dictionary to save.
        :type settings: Union[PluginSettings, Dict[str, Any]]
        :return: True if saved successfully.
        :rtype: bool
        """
        if not (path := self.get_settings_path()):
            return False
        try:
            data = settings.to_dict() if isinstance(settings, PluginSettings) else settings
            if not safe_json_save(path, data, ensure_dir=True):
                return False
            self.settings_changed.emit(data)
            return True
        except Exception:
            return False

    def ensure_json_dir(self) -> None:
        """Create the session json/ directory if it does not exist."""
        if self.session_json_dir:
            os.makedirs(self.session_json_dir, exist_ok=True)
            # Write defaults if settings.json is absent
            if (path := self.get_settings_path()) and not os.path.exists(path):
                self.save_settings(PluginSettings())

    def get_image_metadata_path(self) -> Optional[str]:
        """Get the path to image_metadata.json."""
        if not self.session_image_dir:
            return None
        return os.path.join(self.session_image_dir, "image_metadata.json")

    def load_image_metadata(self) -> Dict[str, Any]:
        """Load image metadata from JSON file."""
        return safe_json_load(self.get_image_metadata_path(), default={})

    def save_image_metadata(self, metadata: Dict[str, Any]) -> bool:
        """Save image metadata to JSON file.

        Note: this is the single point where image_metadata.json is actually
        written, so update_image_metadata()/delete_image_metadata() (which both
        delegate here) also trigger metadata_updated via this method — they do
        not emit it a second time themselves.
        """
        if not (path := self.get_image_metadata_path()):
            return False
        try:
            if not safe_json_save(path, metadata):
                return False
            # Step3-B: this method saves the whole metadata dict rather than a
            # single named entry, so a specific layer name isn't always known
            # here; callers with a specific name (e.g. delete_image_metadata)
            # emit their own more specific signal in addition to this one.
            self.metadata_updated.emit("")
            return True
        except Exception:
            return False

    def update_image_metadata(
        self,
        layer_name: str,
        file_path: str,
        ref_points: List[Dict[str, Any]],
        affine_params: Optional[Tuple[float, float, float, float, float, float]] = None,
    ) -> bool:
        """Update or add metadata for a specific image layer using ImageLayerMeta."""
        meta = self.load_image_metadata()
        entry = ImageLayerMeta(
            file_path=file_path,
            ref_points=ref_points,
            affine_params=list(affine_params) if affine_params else None,
        )
        meta[layer_name] = entry.to_dict()
        return self.save_image_metadata(meta)

    def delete_image_metadata(self, layer_name: str) -> bool:
        """Remove metadata for a specific image layer."""
        meta = self.load_image_metadata()
        if layer_name in meta:
            del meta[layer_name]
            success = self.save_image_metadata(meta)
            if success:
                self.layer_deleted.emit(layer_name)
            return success
        return True
