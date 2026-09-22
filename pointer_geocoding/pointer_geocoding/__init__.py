"""
/***************************************************************************
 PointerGeocoding Plugin
                                 A QGIS plugin
 点群座標取得プラグイン (アナログ図面連続打刻・座標変換・CSV出力)
 ***************************************************************************/
"""
from typing import Any
from qgis.PyQt.QtCore import QCoreApplication, Qt

# Enable High DPI pixmaps safely if not already enabled
if hasattr(Qt, "AA_UseHighDpiPixmaps"):
    if not QCoreApplication.testAttribute(Qt.AA_UseHighDpiPixmaps):
        QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)


def classFactory(iface: Any) -> Any:
    """Load PointerGeocoding plugin class from plugin.py.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    :return: PointerGeocodingPlugin instance.
    :rtype: PointerGeocodingPlugin
    """
    from .plugin import PointerGeocodingPlugin
    return PointerGeocodingPlugin(iface)
