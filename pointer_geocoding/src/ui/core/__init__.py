"""
/***************************************************************************
 PointerGeocoding Plugin - CoreUI (declarative UI construction engine)
 ***************************************************************************/

T-0045: "CoreUI" package. Screens describe their panels declaratively via
FieldSpec/PanelSpec (see field_spec.py); CoreUIBuilder (builder.py) turns a
PanelSpec into real PyQt widgets, reusing the existing UIStyleHelper row/
button/table helpers in ui/style.py as building blocks (this package sits
one layer above ui/style.py, it does not replace it). rules.py holds the
type contract for generic cross-panel business-logic rules (e.g. mode-driven
visibility), to be populated as later tabs (T-0046/T-0047) need them.

See .claude/state/v2-coreui-plan.md for the full architecture rationale.
"""

from .field_spec import ButtonDef, InfoLine, FieldSpec, PanelSpec, WidgetType
from .builder import BuiltPanel, CoreUIBuilder
from .rules import Rule
from .validators import (
    Validator,
    ValidationResult,
    RequiredValidator,
    RegexValidator,
    DuplicateValidator,
)

__all__ = [
    "ButtonDef",
    "InfoLine",
    "FieldSpec",
    "PanelSpec",
    "WidgetType",
    "BuiltPanel",
    "CoreUIBuilder",
    "Rule",
    "Validator",
    "ValidationResult",
    "RequiredValidator",
    "RegexValidator",
    "DuplicateValidator",
]
