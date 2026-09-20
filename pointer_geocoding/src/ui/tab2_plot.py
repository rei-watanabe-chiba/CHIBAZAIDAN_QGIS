"""
/***************************************************************************
 PointerGeocoding Plugin - Tab 2 (Digitizing) Facade
 ***************************************************************************/

Stage C split: The monolithic Tab2DigitizingMixin has been modularized.
This file now acts as a facade, aggregating the three separated domain mixins
(DigitizingCore, DisplayFilter, and Export) to maintain compatibility with 
MainDockWidget and avoid breaking existing imports.
"""

from .tab2.tab2_digitizing_mixin import Tab2DigitizingCoreMixin
from .tab2.tab2_display_filter_mixin import Tab2DisplayFilterMixin
from .tab2.tab2_export_mixin import Tab2ExportMixin


class Tab2DigitizingMixin(
    Tab2DigitizingCoreMixin,
    Tab2DisplayFilterMixin,
    Tab2ExportMixin
):
    """Facade mixin integrating all Tab 2 functional mixins.
    Mixed into MainDockWidget to provide complete Tab 2 behavior.
    """
    pass