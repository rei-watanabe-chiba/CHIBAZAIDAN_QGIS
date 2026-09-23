"""
/***************************************************************************
 PointerGeocoding Plugin - CoreUI rules (generic business-logic rule types)
 ***************************************************************************/

Type contract for generic cross-panel business-logic rules (e.g.
mode-driven visibility). A screen with sufficiently bespoke side effects
may keep that logic as plain code rather than a Rule subclass; concrete
Rule subclasses are added once a real screen needs one.
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
