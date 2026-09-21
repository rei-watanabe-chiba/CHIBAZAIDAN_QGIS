"""
/***************************************************************************
 PointerGeocoding Plugin - CoreUI validators (generic input-validation types)
 ***************************************************************************/

T-0045-b (③): generic, presentation-agnostic Validator classes for the
"required field" / "forbidden character pattern" / "duplicate against
existing data" checks that recur across tab1/tab2/start_dialog input
handlers. Each Validator only performs the boolean judgment (via
``validate()`` -> ``ValidationResult``); it deliberately does NOT own how a
failure is displayed (QMessageBox, status panel, field focus, etc. all stay
the caller's responsibility, per the existing per-screen conventions).

DuplicateValidator is intentionally generic: it takes a caller-supplied
``exists_check`` callable rather than depending on any business-logic
function (e.g. ``logic.core.check_point_duplicate``), so it can be reused
against any "does this value already exist" question (layer names, point
identities, etc.) without coupling this module to a specific domain.

Only tab1_image.py's ``_on_confirm_image_clicked`` is wired to these
classes for now (T-0045-b scope); tab2_plot.py/start_dialog.py adoption is
deferred to T-0046/T-0047, following the same "don't fix the shape from a
single screen's example" policy already used for ``rules.py``.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
import re
from typing import Callable, Optional

from qgis.PyQt.QtWidgets import QMessageBox, QWidget


@dataclass(frozen=True)
class ValidationResult:
    """Common return type for all Validator.validate() calls.

    :ivar is_valid: True if the checked value passed validation.
    :ivar message: Optional description of the failure (callers are free to
        ignore this and display their own existing error message instead;
        it is provided for callers that do not already have a bespoke
        message).
    """

    is_valid: bool
    message: str = ""


class Validator(ABC):
    """Base type for a single, presentation-agnostic input-validation check."""

    @abstractmethod
    def validate(self, value) -> ValidationResult:
        """Judge whether ``value`` satisfies this validator's rule.

        :param value: The value to check (typically a ``str``).
        :return: A :class:`ValidationResult` describing the outcome.
        """
        raise NotImplementedError


class RequiredValidator(Validator):
    """Fails when the (string) value is empty or whitespace-only."""

    def __init__(self, message: str = "") -> None:
        self.message = message

    def validate(self, value) -> ValidationResult:
        text = value.strip() if isinstance(value, str) else value
        if not text:
            return ValidationResult(False, self.message)
        return ValidationResult(True)


class RegexValidator(Validator):
    """Checks a string value against a regular-expression pattern.

    :param pattern: Regex pattern (as accepted by ``re.search``).
    :param reject_if_match: If True (default), the value is INVALID when the
        pattern matches (e.g. a "forbidden characters" pattern). If False,
        the value is INVALID when the pattern does NOT match (e.g. a
        "must look like this" pattern).
    """

    def __init__(
        self, pattern: str, reject_if_match: bool = True, message: str = ""
    ) -> None:
        self.pattern = pattern
        self.reject_if_match = reject_if_match
        self.message = message

    def validate(self, value) -> ValidationResult:
        text = value if isinstance(value, str) else str(value)
        matched = re.search(self.pattern, text) is not None
        is_valid = (not matched) if self.reject_if_match else matched
        if not is_valid:
            return ValidationResult(False, self.message)
        return ValidationResult(True)


class DuplicateValidator(Validator):
    """Checks a value against caller-supplied existing-data duplication logic.

    :param exists_check: Callable receiving the candidate value and
        returning True if it already exists (i.e. would be a duplicate).
        Kept fully generic (no dependency on ``logic.core`` helpers such as
        ``check_point_duplicate``) so any screen can supply its own
        membership test (dict-key lookup, feature scan, etc.).
    """

    def __init__(self, exists_check: Callable[..., bool], message: str = "") -> None:
        self.exists_check = exists_check
        self.message = message

    def validate(self, value) -> ValidationResult:
        if self.exists_check(value):
            return ValidationResult(False, self.message)
        return ValidationResult(True)


def show_validation_error(
    parent: Optional[QWidget],
    title: str,
    result: ValidationResult,
    focus_widget: Optional[QWidget] = None,
) -> None:
    """Display ``result``'s failure message via ``QMessageBox.warning``.

    T-0045-b extension: pairs with the Validator classes above to collapse
    each caller's "judge -> QMessageBox.warning(...) -> setFocus()" block
    into a couple of lines. Does nothing when ``result.is_valid`` is True,
    so callers can call this unconditionally and still need their own
    ``if not result.is_valid: return`` for early-exit control flow.

    :param parent: Parent widget for the message box (may be None).
    :param title: Message box title (e.g. ``UIMessages.ERR_TITLE_INPUT``).
    :param result: The :class:`ValidationResult` to display on failure.
    :param focus_widget: Widget to call ``.setFocus()`` on after the
        message box is dismissed, if given.
    """
    if result.is_valid:
        return
    QMessageBox.warning(parent, title, result.message)
    if focus_widget is not None:
        focus_widget.setFocus()
