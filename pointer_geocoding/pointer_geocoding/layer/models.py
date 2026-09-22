"""
/***************************************************************************
 PointerGeocoding Plugin - Layer Manager Data Models
 ***************************************************************************/

Stage C split (mechanical, logic-preserving): extracted from
layer_manager.py. Contains the plain dataclasses and small standalone
helper functions used throughout LayerManager and its mixins, with no
dependency on LayerManager itself or on any of its mixin modules.
"""
# 【変更不可侵の絶対的ルール】 測量座標系（X軸=南北, Y軸=東西）を採用。QGISキャンバス上のX座標(東西)はSurvey Y、Y座標(南北)はSurvey Xに対応する。

import os
import json
from dataclasses import dataclass, field, asdict, fields
from typing import Optional, Dict, Any, List
from contextlib import contextmanager

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsSettings,
)


def safe_json_load(path: Optional[str], default: Any = None) -> Any:
    """Safely load JSON data from a file path.

    Mirrors the read+parse portion of the JSON-loading pattern previously
    duplicated across settings/metadata loaders: returns `default` if `path`
    is falsy, the file does not exist, or the read/parse raises any exception.

    :param path: Absolute path to the JSON file, or None/empty.
    :type path: Optional[str]
    :param default: Value returned when the file is missing or unreadable.
    :type default: Any
    :return: Parsed JSON data, or `default`.
    :rtype: Any
    """
    if not path or not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def safe_json_save(path: Optional[str], data: Any, ensure_dir: bool = False) -> bool:
    """Safely write `data` as JSON to `path`.

    Mirrors the write portion of the JSON-saving pattern previously duplicated
    across settings/metadata savers: returns False if `path` is falsy or the
    write raises any exception (e.g. missing parent directory, permission
    error, non-serializable data).

    :param path: Absolute destination path, or None/empty.
    :type path: Optional[str]
    :param data: JSON-serializable data to write.
    :type data: Any
    :param ensure_dir: If True, create the parent directory (and any missing
        intermediate directories) before writing, matching callers that
        previously called os.makedirs() themselves.
    :type ensure_dir: bool
    :return: True if the write succeeded, False otherwise.
    :rtype: bool
    """
    if not path:
        return False
    try:
        if ensure_dir:
            os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        return True
    except Exception:
        return False


@dataclass
class PluginSettings:
    """Dataclass representing user configurable plugin settings."""
    ref_symbol_size: float = 4.0
    ref_symbol_line_width: float = 1.2
    ref_symbol_line_color: str = "#D32F2F"
    point_symbol_size: float = 6.0
    point_symbol_line_width: float = 0.9
    point_symbol_fill_enabled: bool = False
    point_symbol_line_color: str = "#E53935"
    label_size: int = 10
    label_halo: bool = True
    label_offset: float = 1.0
    scale_major_grid: int = -1    # -1 = always visible
    scale_minor_grid: int = 500   # scale denominator threshold

    def to_dict(self) -> Dict[str, Any]:
        """Convert settings to standard dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PluginSettings":
        """Instantiate settings from a dictionary, filtering unknown keys."""
        valid_fields = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)

    def get(self, key: str, default: Any = None) -> Any:
        """Dictionary-compatible .get() method."""
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        """Dictionary-compatible indexing."""
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)

    def __setitem__(self, key: str, value: Any) -> None:
        """Dictionary-compatible assignment."""
        setattr(self, key, value)

    def __contains__(self, key: str) -> bool:
        """Dictionary-compatible 'in' operator."""
        return hasattr(self, key)


@dataclass
class RefPointMeta:
    """Metadata representation for an individual reference point."""
    name: str = ""
    pixel_x: float = 0.0
    pixel_y: float = 0.0
    real_x: float = 0.0
    real_y: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert reference point metadata to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RefPointMeta":
        """Construct RefPointMeta from dictionary."""
        return cls(
            name=str(data.get("name", "")),
            pixel_x=float(data.get("pixel_x", 0.0)),
            pixel_y=float(data.get("pixel_y", 0.0)),
            real_x=float(data.get("real_x", 0.0)),
            real_y=float(data.get("real_y", 0.0)),
        )


@dataclass
class ImageLayerMeta:
    """Metadata representation for an individual georeferenced image layer."""
    file_path: str = ""
    ref_points: List[Dict[str, Any]] = field(default_factory=list)
    affine_params: Optional[List[float]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert image layer metadata to dictionary."""
        return {
            "file_path": self.file_path,
            "ref_points": self.ref_points,
            "affine_params": self.affine_params,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ImageLayerMeta":
        """Construct ImageLayerMeta from dictionary."""
        return cls(
            file_path=str(data.get("file_path", "")),
            ref_points=list(data.get("ref_points", [])),
            affine_params=list(data["affine_params"]) if data.get("affine_params") else None,
        )

    def get(self, key: str, default: Any = None) -> Any:
        """Dictionary-compatible .get() method."""
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        """Dictionary-compatible indexing."""
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)

    def __setitem__(self, key: str, value: Any) -> None:
        """Dictionary-compatible assignment."""
        setattr(self, key, value)

    def __contains__(self, key: str) -> bool:
        """Dictionary-compatible 'in' operator."""
        return hasattr(self, key)


# Custom local orthogonal coordinate reference system (Transverse Mercator on GRS80)
LOCAL_CRS_PROJ = "+proj=tmerc +lat_0=0 +lon_0=0 +k=1 +x_0=0 +y_0=0 +ellps=GRS80 +units=m +no_defs"


def get_local_crs() -> QgsCoordinateReferenceSystem:
    """Return the custom local orthogonal CRS (GRS80 Transverse Mercator).
    # 【変更不可侵の絶対的ルール】 測量座標系（X軸=南北, Y軸=東西）を採用。QGISキャンバス上のX座標(東西)はSurvey Y、Y座標(南北)はSurvey Xに対応する。
    """
    crs = QgsCoordinateReferenceSystem()
    crs.createFromProj(LOCAL_CRS_PROJ)
    if not crs.isValid():
        crs.createFromString(LOCAL_CRS_PROJ)
    return crs


@contextmanager
def suppress_crs_prompt():
    """Context manager to temporarily suppress the QGIS CRS selection prompt.

    Restores the original user setting upon exit.
    """
    settings = QgsSettings()
    original_prompt = settings.value("/Projections/promptWhenNoCrs", True, type=bool)
    settings.setValue("/Projections/promptWhenNoCrs", False)
    try:
        yield
    finally:
        settings.setValue("/Projections/promptWhenNoCrs", original_prompt)
