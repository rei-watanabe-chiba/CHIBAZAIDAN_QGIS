"""
/***************************************************************************
 PointerGeocoding Plugin - CoreUI rules (generic business-logic rule types)
 ***************************************************************************/

T-0045: type contract only. tab1_image_schema.py does not currently need any
generic rule (Tab1's new/edit mode switch has enough bespoke side effects --
clearing ref_points_data, reloading the edit-layer combo, etc. -- that it
stays as plain code in Tab1GeorefMixin._on_tab1_mode_changed(), per the
CoreUI plan's "画面固有の例外は素のPyQtコードとして残してよい" escape hatch).

Concrete rules (e.g. ModeVisibilityRule, RealtimeCommitRule,
DuplicateValidationRule for Tab2's new/edit mode) are intentionally deferred
to T-0047, once a second/third real usage confirms the right shape instead
of guessing it from a single screen.
"""
from abc import ABC, abstractmethod


class Rule(ABC):
    """Base type for a CoreUI generic business-logic rule.

    A concrete Rule inspects/wires a BuiltPanel (e.g. connecting signals
    between fields, or toggling row visibility based on another field's
    value) once PanelSpec construction has completed. See
    CoreUIBuilder.build(), which calls ``rule.apply(panel)`` for each entry
    in ``PanelSpec.rules``.
    """

    @abstractmethod
    def apply(self, panel) -> None:
        """Wire this rule's behavior onto an already-built BuiltPanel.

        :param panel: The BuiltPanel instance (see builder.py) to attach
            behavior to.
        """
        raise NotImplementedError
