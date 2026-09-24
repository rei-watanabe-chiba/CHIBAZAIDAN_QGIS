"""
/***************************************************************************
 PointerGeocoding Plugin - UI Style Helper (Material & High DPI Adaptation)
 ***************************************************************************/
"""
import os
from typing import Optional, Tuple, List, Any, Callable, Iterable
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QWidget,
    QPushButton,
    QLabel,
    QFrame,
    QVBoxLayout,
    QHBoxLayout,
    QSpinBox,
    QComboBox,
    QLineEdit,
    QButtonGroup,
    QMessageBox,
    QListWidget,
    QListWidgetItem,
    QTableWidget,
    QTableWidgetItem,
)
from .constants import UIConfig


class UIStyleHelper:
    """Manages Material Design-inspired styling compatible with both QGIS light and dark themes.

    Uses QGIS system palette roles and relative font metrics without hardcoding fixed backgrounds.
    """

    @classmethod
    # QGISのライト/ダークテーマ双方に対応したQSSスタイルシートを生成する。
    def get_style_sheet(cls) -> str:
        """Generate a theme-agnostic QSS stylesheet referencing Qt palette roles.

        :return: QSS stylesheet string.
        :rtype: str
        """
        icon_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icon"
        )
        up_arrow_path = os.path.join(icon_dir, "spin_up_arrow.svg").replace(os.sep, "/")
        down_arrow_path = os.path.join(icon_dir, "spin_down_arrow.svg").replace(os.sep, "/")
        up_arrow_pressed_path = os.path.join(
            icon_dir, "spin_up_arrow_pressed.svg"
        ).replace(os.sep, "/")
        down_arrow_pressed_path = os.path.join(
            icon_dir, "spin_down_arrow_pressed.svg"
        ).replace(os.sep, "/")
        # NOTE: the bulk of this QSS template uses literal `{`/`}` for rule
        # blocks, so a plain f-string/str.format() would require escaping
        # every one of them. Instead we keep this a plain triple-quoted
        # string with unique %%-style placeholders substituted via
        # str.replace() below.
        return """
        /* General Widget Typography & Spacing */
        QWidget {
            font-size: 9pt;
        }

        /* Group Boxes - Simple frameless container with uniform horizontal padding */
        QGroupBox {
            border: none;
            padding: 0px 6px;
        }

        /* Input Controls - Rounded, padded, base-palette responsive */
        QLineEdit, QgsFilterLineEdit, QComboBox {
            background-color: palette(base);
            color: palette(text);
            border: 1px solid palette(mid);
            border-radius: 4px;
            padding: 0px 8px;
            min-height: 28px;
            selection-background-color: palette(highlight);
            selection-color: palette(highlighted-text);
        }

        QLineEdit:focus, QgsFilterLineEdit:focus, QComboBox:focus {
            border: 1.5px solid palette(highlight);
        }

        /* Disabled inputs: neutral translucent gray (theme-independent).
           QDoubleSpinBox keeps the native look; QSpinBox has its own
           :disabled rule below, next to its other rules (see Core §5-2). */
        QLineEdit:disabled, QgsFilterLineEdit:disabled, QComboBox:disabled {
            background-color: rgba(128, 128, 128, 0.18);
            color: palette(disabled-text);
        }

        /* Point-name search input inside the status panel: 30% white so the
           panel color shows through. Declared after :disabled so it wins on
           equal specificity (also while the whole dock is disabled). */
        QgsFilterLineEdit[searchInput="true"], QgsFilterLineEdit[searchInput="true"]:disabled {
            background-color: rgba(255, 255, 255, 0.3);
        }

        /* QSpinBox base styling. NOTE: only the outer box and the
           up/down button sub-control geometry are styled here; arrow
           glyphs are handled separately below. */
        QSpinBox {
            background-color: palette(base);
            color: palette(text);
            border: 1px solid palette(mid);
            border-radius: 4px;
            padding: 0px 4px;
            padding-right: 20px;
            min-height: 28px;
            min-width: 70px;
            selection-background-color: palette(highlight);
            selection-color: palette(highlighted-text);
        }

        QSpinBox:focus {
            border: 1.5px solid palette(highlight);
        }

        /* Disabled QSpinBox: same neutral gray as the other disabled inputs
           above. A disabled widget has no focus border, so the Core §5-2
           item 4 conflict concern (clash with the focus frame) does not
           apply. Only background-color is set; text color is left as is. */
        QSpinBox:disabled {
            background-color: rgba(128, 128, 128, 0.18);
        }

        /* up-button/down-button each declare their own subcontrol-position;
           without it, the buttons render visually detached from the box
           with no working hover/click hit area. border-left forms a subtle
           divider from the text area, and only the outer corners get
           border-radius so the buttons still read as part of the same
           rounded box. */
        QSpinBox::up-button {
            subcontrol-origin: border;
            subcontrol-position: top right;
            width: 18px;
            border-left: 1px solid palette(mid);
            border-top-right-radius: 4px;
        }

        QSpinBox::down-button {
            subcontrol-origin: border;
            subcontrol-position: bottom right;
            width: 18px;
            border-left: 1px solid palette(mid);
            border-bottom-right-radius: 4px;
        }

        /* Arrow glyphs are supplied via real SVG image files under
           src/icon/ (spin_up_arrow.svg / spin_down_arrow.svg), not CSS
           border-triangle tricks or embedded base64 data-URIs: both are
           unreliable against Qt's QSS engine (the border-triangle hack
           renders as a solid block rather than a triangle on QSpinBox
           arrow sub-controls; QSS url() does not reliably load embedded
           data URIs -- see QTBUG-51081). Resolved to an absolute,
           forward-slash path at runtime below (__UP_ARROW_PATH__ /
           __DOWN_ARROW_PATH__ placeholders substituted via str.replace()
           after this template). Both files are fixed 8x6 triangles filled
           with a neutral gray (#6B6B6B); this is a fixed, theme-non-adaptive
           color (does not follow palette(text) / dark-light mode), which is
           an accepted trade-off. */
        QSpinBox::up-arrow {
            image: url(__UP_ARROW_PATH__);
            width: 8px;
            height: 6px;
        }

        QSpinBox::down-arrow {
            image: url(__DOWN_ARROW_PATH__);
            width: 8px;
            height: 6px;
        }

        /* Press-state feedback uses a darker-filled SVG swap on
           ::up-arrow:pressed / ::down-arrow:pressed rather than a
           background-color change, avoiding box-model overlap with the
           focus border since only the small arrow image changes. width/
           height are redeclared explicitly since Qt does not reliably
           carry over sub-control properties across state changes in this
           stylesheet. */
        QSpinBox::up-arrow:pressed {
            image: url(__UP_ARROW_PRESSED_PATH__);
            width: 8px;
            height: 6px;
        }

        QSpinBox::down-arrow:pressed {
            image: url(__DOWN_ARROW_PRESSED_PATH__);
            width: 8px;
            height: 6px;
        }

        /* Default Buttons */
        QPushButton {
            background-color: palette(button);
            color: palette(button-text);
            border: 1px solid palette(mid);
            border-radius: 4px;
            min-height: 28px;
        }

        QPushButton:hover {
            background-color: rgba(128, 128, 128, 0.15);
        }

        QPushButton:pressed {
            background-color: rgba(128, 128, 128, 0.28);
        }

        QPushButton:disabled {
            opacity: 0.5;
            color: palette(disabled-text);
        }

        /* Plain Buttons (base-colored background while enabled) */
        QPushButton[plain="true"]:enabled {
            background-color: palette(base);
        }

        QPushButton[plain="true"]:enabled:hover {
            background-color: rgba(128, 128, 128, 0.15);
        }

        QPushButton[plain="true"]:enabled:pressed {
            background-color: rgba(128, 128, 128, 0.28);
        }

        /* Filter Toggle Button (blue while checked; border/padding inherited) */
        QPushButton[filterToggle="true"]:checked {
            background-color: #1976D2;
            color: #FFFFFF;
            font-weight: bold;
        }

        QPushButton[filterToggle="true"]:checked:hover {
            background-color: #1565C0;
        }

        /* Tab Widget Styling */
        QTabWidget::pane {
            border: 1px solid palette(mid);
            border-radius: 4px;
            top: -1px;
        }

        QTabBar::tab {
            background-color: palette(window);
            color: palette(window-text);
            border: 1px solid palette(mid);
            border-bottom: none;
            border-top-left-radius: 4px;
            border-top-right-radius: 4px;
            padding: 6px 14px;
            margin-right: 2px;
        }

        QTabBar::tab:selected {
            background-color: palette(base);
            border-bottom: 2px solid #1976D2;
            font-weight: bold;
        }

        QTabBar::tab:hover:!selected {
            background-color: rgba(128, 128, 128, 0.1);
        }

        /* Banner Labels (Themed with transparency) */
        QLabel[banner="info"] {
            background-color: rgba(2, 136, 209, 0.12);
            border: 1px solid rgba(2, 136, 209, 0.4);
            border-radius: 4px;
            padding: 6px 8px;
            color: palette(window-text);
            font-weight: bold;
        }

        QLabel[banner="success"] {
            background-color: rgba(46, 125, 50, 0.14);
            border: 1px solid rgba(46, 125, 50, 0.45);
            border-radius: 4px;
            padding: 6px 8px;
            color: palette(window-text);
            font-weight: bold;
        }

        QLabel[banner="warning"] {
            background-color: rgba(198, 40, 40, 0.14);
            border: 1px solid rgba(198, 40, 40, 0.45);
            border-radius: 4px;
            padding: 6px 8px;
            color: palette(window-text);
            font-weight: bold;
        }

        /* Status Panel (Flat design container with color-coded left border) */
        QFrame[statusPanel="true"] {
            background-color: rgba(128, 128, 128, 0.08);
            border-left: 3px solid palette(highlight);
            border-radius: 4px;
            border-top-left-radius: 0px;
            border-bottom-left-radius: 0px;
            padding: 6px 8px;
        }

        QFrame[statusType="info"] {
            border-left: 3px solid #1976D2;
            background-color: rgba(25, 118, 210, 0.08);
        }

        QFrame[statusType="success"] {
            border-left: 3px solid #2E7D32;
            background-color: rgba(46, 125, 50, 0.08);
        }

        QFrame[statusType="error"] {
            border-left: 3px solid #C62828;
            background-color: rgba(198, 40, 40, 0.08);
        }

        QFrame[statusType="warning"] {
            border-left: 3px solid #F57C00;
            background-color: rgba(245, 124, 0, 0.08);
        }

        /* Scroll Area without outer ugly borders */
        QScrollArea {
            border: none;
            background: transparent;
        }

        /* Left icon rail navigation buttons (図面管理・設定 side panel
           toggles). Checked state indicates the corresponding side panel is
           currently open. */
        QToolButton[navButton="true"] {
            background-color: transparent;
            color: palette(window-text);
            border: none;
            border-radius: 4px;
            padding: 4px 2px;
        }

        QToolButton[navButton="true"]:hover {
            background-color: rgba(128, 128, 128, 0.15);
        }

        QToolButton[navButton="true"]:checked {
            background-color: palette(highlight);
            color: palette(highlighted-text);
            font-weight: bold;
        }

        /* Segmented Toggle Container */
        QWidget[segmentedContainer="true"] {
            background-color: rgba(128, 128, 128, 0.15);
            border-radius: 6px;
        }

        /* Segmented Toggle Buttons */
        QPushButton[segmentedButton="true"] {
            background-color: transparent;
            color: palette(text);
            border: none;
            border-radius: 4px;
            min-height: 24px;
        }

        QPushButton[segmentedButton="true"]:hover {
            background-color: rgba(128, 128, 128, 0.1);
        }

        QPushButton[segmentedButton="true"]:checked {
            background-color: palette(base);
            color: palette(text);
            border: 1px solid rgba(0, 0, 0, 0.1);
            font-weight: bold;
        }

        QPushButton[segmentedButton="true"]:disabled {
            color: palette(disabled, text);
        }

        /* Segmented Toggle checked tones (same dark colors as the info-panel statusType left border) */
        QPushButton[segmentedButton="true"][segmentTone="info"]:checked {
            background-color: #1976D2;
            color: #FFFFFF;
        }

        QPushButton[segmentedButton="true"][segmentTone="warning"]:checked {
            background-color: #F57C00;
            color: #FFFFFF;
        }

        QPushButton[segmentedButton="true"][segmentTone="info"]:checked:hover {
            background-color: #1565C0;
        }

        QPushButton[segmentedButton="true"][segmentTone="warning"]:checked:hover {
            background-color: #E65100;
        }
        """.replace("__UP_ARROW_PATH__", up_arrow_path).replace(
            "__DOWN_ARROW_PATH__", down_arrow_path
        ).replace("__UP_ARROW_PRESSED_PATH__", up_arrow_pressed_path).replace(
            "__DOWN_ARROW_PRESSED_PATH__", down_arrow_pressed_path
        )

    @staticmethod
    # QMessageBox.critical()呼び出しをまとめたエラーダイアログ表示のラッパー。
    def show_error_dialog(parent: Optional[QWidget], title: str, message: str) -> None:
        """Thin wrapper around QMessageBox.critical() to consolidate error dialog presentation.

        :param parent: Parent QWidget for the dialog.
        :type parent: Optional[QWidget]
        :param title: Dialog title text.
        :type title: str
        :param message: Dialog message text.
        :type message: str
        """
        QMessageBox.critical(parent, title, message)

    @staticmethod
    # QMessageBox.warning()呼び出しをまとめた警告ダイアログ表示のラッパー。
    def show_warning_dialog(parent: Optional[QWidget], title: str, message: str) -> None:
        """Thin wrapper around QMessageBox.warning() to consolidate warning dialog presentation.

        :param parent: Parent QWidget for the dialog.
        :type parent: Optional[QWidget]
        :param title: Dialog title text.
        :type title: str
        :param message: Dialog message text.
        :type message: str
        """
        QMessageBox.warning(parent, title, message)

    @classmethod
    # 対象ウィジェットとその子階層にテーマ非依存のスタイルを適用する。
    def apply_theme(cls, widget: QWidget) -> None:
        """Apply theme-agnostic styling to the target widget and polish its hierarchy.

        :param widget: Target QWidget (e.g. QDialog or QDockWidget).
        :type widget: QWidget
        """
        if widget:
            widget.setStyleSheet(cls.get_style_sheet())

    @staticmethod
    # ネイティブ矢印コントロール付きの標準化されたQSpinBoxを生成する。
    def create_spinbox(
        min_val: int = 0,
        max_val: int = 999999,
        default_val: int = 0,
        parent: Optional[QWidget] = None,
    ) -> QSpinBox:
        """Factory method to create a standardized QSpinBox with native controls.

        :param min_val: Minimum spinbox value.
        :type min_val: int
        :param max_val: Maximum spinbox value.
        :type max_val: int
        :param default_val: Initial spinbox value.
        :type default_val: int
        :param parent: Optional parent QWidget.
        :type parent: Optional[QWidget]
        :return: Configured QSpinBox instance.
        :rtype: QSpinBox
        """
        spin = QSpinBox(parent)
        spin.setRange(min_val, max_val)
        spin.setValue(default_val)
        return spin

    @staticmethod
    # 左端に色分けボーダーを持つフラットデザインのステータスパネルを生成する。
    def create_status_panel(
        text: str = "",
        status_type: str = "info",
        parent: Optional[QWidget] = None,
    ) -> Tuple[QFrame, QLabel]:
        """Create a flat-design status container panel with a color-coded left border.

        :param text: Initial label text.
        :type text: str
        :param status_type: Status category ('info', 'success', 'error', 'warning').
        :type status_type: str
        :param parent: Optional parent widget.
        :type parent: Optional[QWidget]
        :return: Tuple containing (container QFrame, text QLabel).
        :rtype: Tuple[QFrame, QLabel]
        """
        frame = QFrame(parent)
        frame.setProperty("statusPanel", True)
        frame.setProperty("statusType", status_type)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        label = QLabel(text, frame)
        label.setWordWrap(True)
        layout.addWidget(label)

        frame.style().polish(frame)
        return frame, label

    @staticmethod
    # 既存のステータスパネルコンテナのテキストと状態別スタイルを更新する。
    def update_status_panel(
        frame: QFrame,
        label: QLabel,
        text: str,
        status_type: str = "info",
    ) -> None:
        """Update text and border status style for an existing status panel container.

        :param frame: Target container QFrame.
        :type frame: QFrame
        :param label: Target text QLabel inside container.
        :type label: QLabel
        :param text: New text to display.
        :type text: str
        :param status_type: Status category ('info', 'success', 'error', 'warning').
        :type status_type: str
        """
        label.setText(text)
        frame.setProperty("statusType", status_type)
        frame.style().unpolish(frame)
        frame.style().polish(frame)

    @staticmethod
    # QPushButtonをプライマリアクションボタンとしてマークする。
    def set_primary_button(button: QPushButton) -> None:
        """Mark a QPushButton as a primary action button."""
        button.setProperty("primary", True)
        button.style().polish(button)

    @staticmethod
    # QPushButtonを成功/保存アクションボタンとしてマークする。
    def set_success_button(button: QPushButton) -> None:
        """Mark a QPushButton as a success/save action button."""
        button.setProperty("success", True)
        button.style().polish(button)

    @staticmethod
    # QPushButtonをアクセント/エクスポートアクションボタンとしてマークする。
    def set_accent_button(button: QPushButton) -> None:
        """Mark a QPushButton as an accent/export action button."""
        button.setProperty("accent", True)
        button.style().polish(button)

    @staticmethod
    # QPushButtonを有効時に背景がベース色(白系)になるボタンとしてマークする。
    def set_plain_button(button: QPushButton) -> None:
        """Mark a QPushButton as a plain button (base-colored background while enabled)."""
        button.setProperty("plain", True)
        button.style().unpolish(button)
        button.style().polish(button)

    @staticmethod
    # QPushButtonをフィルターON/OFFトグルボタン(ON時に青背景)としてマークする。
    def set_filter_button(button: QPushButton) -> None:
        """Mark a QPushButton as a filter toggle (blue background while checked)."""
        button.setProperty("filterToggle", True)
        button.style().unpolish(button)
        button.style().polish(button)

    @staticmethod
    # セグメントトグルボタンに選択中の色調("info"/"warning")プロパティを設定する。
    def set_segment_tone(button: QPushButton, tone: str) -> None:
        """Set the checked-state tone ("info"/"warning") of a segmented toggle button."""
        button.setProperty("segmentTone", tone)
        button.style().unpolish(button)
        button.style().polish(button)

    @staticmethod
    # バナーQLabelに動的なステータス種別プロパティを設定する。
    def set_banner_status(label: QLabel, status: str) -> None:
        """Set dynamic status property on a banner QLabel ('info', 'success', 'warning').

        :param label: Target QLabel.
        :param status: Status string ('info', 'success', 'warning').
        """
        label.setProperty("banner", status)
        label.style().unpolish(label)
        label.style().polish(label)

    @staticmethod
    # QFrameをステータスパネルとしてマークする。
    def set_status_panel(frame: QWidget) -> None:
        """Mark a QFrame as a status panel."""
        frame.setProperty("statusPanel", True)
        frame.style().polish(frame)

    @staticmethod
    # 入力ウィジェットに赤いエラー強調ボーダーを付与/解除する。
    def set_error_border(widget: QWidget, has_error: bool) -> None:
        """Apply/remove a red error-highlight border on an input widget.

        Used by Tab2's 点情報パネル real-time validation to flag combo_feature_name
        (遺構名未指定) and the active point-name input (点名重複) without relying
        on a QMessageBox/dialog interruption.

        :param widget: Target input widget (e.g. QComboBox, QLineEdit, QSpinBox).
        :type widget: QWidget
        :param has_error: True to apply the red border, False to clear it back
            to the widget's normal (theme-driven) style.
        :type has_error: bool
        """
        widget.setStyleSheet("border: 2px solid #C62828;" if has_error else "")

    @staticmethod
    # 任意の太字タイトル付きセパレータウィジェットを構築する。
    def build_separator(
        parent: Optional[QWidget] = None, title_text: Optional[str] = None
    ) -> QWidget:
        """Build a flexible separator widget with optional bold title header.

        Applies UIConfig.SEPARATOR_MARGIN to top and bottom margins. When
        title_text is provided, includes a bold QLabel with
        UIConfig.HEADER_LINE_SPACING before the horizontal line.

        :param parent: Optional parent widget.
        :type parent: Optional[QWidget]
        :param title_text: Optional header title text.
        :type title_text: Optional[str]
        :return: Container widget containing the separator (and optional title).
        :rtype: QWidget
        """
        container = QWidget(parent)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, UIConfig.SEPARATOR_MARGIN, 0, UIConfig.SEPARATOR_MARGIN)
        layout.setSpacing(0)

        if title_text:
            label = QLabel(title_text, container)
            label.setStyleSheet("font-weight: bold;")
            layout.addWidget(label)
            layout.addSpacing(UIConfig.HEADER_LINE_SPACING)

        line = QFrame(container)
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)

        return container


    @staticmethod
    # チェック可能なQToolButtonを左アイコンレールのナビゲーションボタンとしてマークする。
    def set_nav_button(button: QWidget) -> None:
        """Mark a checkable QToolButton as a left icon-rail navigation button.

        Used by the collapsible side panel (図面管理・設定), whose
        open/closed state is reflected by the button's checked state.
        """
        button.setProperty("navButton", True)
        button.style().polish(button)

    @staticmethod
    # メインラベルと要素コンテナから成る標準化されたフレックス風の横並び行を構築する。
    def build_flex_row(
        main_label: Optional[QLabel],
        child_configs: list,
        main_ratio: Tuple[int, int] = (2, 8),
        row_height: int = 32,
    ) -> QWidget:
        """Build a standardized flexbox-style horizontal row widget with a main label and element container.

        :param main_label: Left-side label widget (can be None).
        :type main_label: Optional[QLabel]
        :param child_configs: List of tuples (widget or None, stretch_ratio) for up to 3 elements.
        :type child_configs: list
        :param main_ratio: Stretch ratio between main_label and element container. Default is (2, 8).
        :type main_ratio: Tuple[int, int]
        :param row_height: Fixed height for the row widget. Default is 32.
        :type row_height: int
        :return: Composite QWidget containing the row layout.
        :rtype: QWidget
        """
        row_widget = QWidget()
        row_widget.setMinimumHeight(row_height)
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        label_stretch, content_stretch = main_ratio
        if main_label is not None:
            row_layout.addWidget(main_label, label_stretch)
        elif label_stretch > 0:
            row_layout.addStretch(label_stretch)

        content_widget = QWidget(row_widget)
        content_layout = QHBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(8)

        for item in child_configs[:3]:
            widget, stretch = item
            if widget is not None:
                content_layout.addWidget(widget, stretch)
            else:
                content_layout.addStretch(stretch)

        row_layout.addWidget(content_widget, content_stretch)
        return row_widget

    @staticmethod
    # サブラベルと入力ウィジェットを組み合わせたサブコンテナを構築する。
    def build_child_container(
        sub_label: Optional[QLabel],
        input_widget: QWidget,
    ) -> QWidget:
        """Build a sub-container pairing a sub-label with an input widget.

        :param sub_label: Sub-label displayed before the input widget.
        :type sub_label: Optional[QLabel]
        :param input_widget: Target input widget.
        :type input_widget: QWidget
        :return: Container QWidget holding the label and input.
        :rtype: QWidget
        """
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        if sub_label is not None:
            layout.addWidget(sub_label, 0)
        layout.addWidget(input_widget, 1)

        return container

    @staticmethod
    # プレーンテキストのラベルと単一の入力ウィジェットを組み合わせたフォーム行を構築する。
    def build_form_row(
        label_text: str,
        widget: QWidget,
        spacing: int = 4,
        label_width: Optional[int] = None,
    ) -> QWidget:
        """Build a labeled form row pairing a plain-text label with a single input widget.

        Higher-level convenience wrapper around build_child_container() that also
        constructs the QLabel from a plain string, consolidating the common
        "label text + single input widget" row-building pattern repeated across
        Tab1-Tab3 UI construction code.

        :param label_text: Text for the leading label (omitted entirely if falsy).
        :type label_text: str
        :param widget: Input widget to pair with the label.
        :type widget: QWidget
        :param spacing: Horizontal spacing between label and widget. Default is 4.
        :type spacing: int
        :param label_width: Optional fixed pixel width for the generated
            QLabel, so labels of differing character count (e.g. the
            settings panel's サイズ/線幅/線色/間隔) line up their input
            widgets at the same x-offset across rows. None (the default)
            keeps the label at its natural width.
        :type label_width: Optional[int]
        :return: Composite QWidget containing the label + widget row.
        :rtype: QWidget
        """
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(spacing)
        if label_text:
            label = QLabel(label_text)
            if label_width is not None:
                label.setFixedWidth(label_width)
            layout.addWidget(label)
        layout.addWidget(widget, 1)
        return container

    @staticmethod
    # 設定グループを視覚的に区切るための太字セクションヘッダーQLabelを構築する。
    def build_section_header(title: str) -> QLabel:
        """Build a bold section header QLabel used to visually separate settings groups.

        :param title: Header text.
        :type title: str
        :return: Configured QLabel.
        :rtype: QLabel
        """
        header = QLabel(title)
        header.setStyleSheet(
            "font-weight: bold; margin-top: 10px; padding-bottom: 3px;"
        )
        return header

    @staticmethod
    # シグナルをブロックしながらQComboBoxを文字列リストでクリア・再構築する。
    def repopulate_combo_box(
        combo: QComboBox,
        items: List[str],
        preserve_current: bool = True,
    ) -> None:
        """Clear and repopulate a QComboBox with a list of string items while blocking signals.

        Consolidates the "rebuild a combo box from a fresh list of layer/entry
        names" pattern used for both the Tab2 target-drawing selector and the
        Tab1 edit-layer selector.

        :param combo: Target QComboBox.
        :type combo: QComboBox
        :param items: New list of string items to populate.
        :type items: List[str]
        :param preserve_current: If True, keep the previously selected text when
            it still exists among the new items (falling back to index 0
            otherwise). If False, simply repopulate without restoring selection.
        :type preserve_current: bool
        """
        current_val = combo.currentText() if preserve_current else None

        combo.blockSignals(True)
        combo.clear()
        for item in items:
            combo.addItem(item)

        if preserve_current:
            if current_val in items:
                combo.setCurrentText(current_val)
            elif items:
                combo.setCurrentIndex(0)

        combo.blockSignals(False)

    @staticmethod
    # シグナルをブロックしながらQListWidgetをチェック可能な項目でクリア・再構築する。
    def repopulate_checkable_list(
        list_widget: QListWidget,
        entries: List[Tuple[str, Any, bool]],
    ) -> None:
        """Clear and repopulate a QListWidget with checkable items while blocking signals.

        :param list_widget: Target QListWidget.
        :type list_widget: QListWidget
        :param entries: List of tuples (text, user_data, is_checked). user_data is
            stored under Qt.UserRole on each created item (e.g. a layer id).
        :type entries: List[Tuple[str, Any, bool]]
        """
        list_widget.blockSignals(True)
        list_widget.clear()
        for text, user_data, is_checked in entries:
            item = QListWidgetItem(text, list_widget)
            item.setData(Qt.UserRole, user_data)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if is_checked else Qt.Unchecked)
        list_widget.blockSignals(False)

    @staticmethod
    # チェック可能なQListWidgetItemから(ユーザーデータ, チェック有無)を取得する。
    def get_checkable_item_state(item: QListWidgetItem) -> Tuple[Any, bool]:
        """Extract (user_data, is_checked) from a checkable QListWidgetItem.

        Consolidates the small "read Qt.UserRole payload + checked flag" pattern
        used whenever a QListWidget item's checkState changes.

        :param item: Source QListWidgetItem.
        :type item: QListWidgetItem
        :return: Tuple of (user_data stored under Qt.UserRole, is_checked).
        :rtype: Tuple[Any, bool]
        """
        return item.data(Qt.UserRole), (item.checkState() == Qt.Checked)

    @staticmethod
    # シグナルをブロックしながらQTableWidgetの行をデータソースからクリア・再構築する。
    def rebuild_table_rows(
        table: QTableWidget,
        row_count: int,
        row_builder: Callable[[int], Iterable[Optional[QTableWidgetItem]]],
    ) -> None:
        """Clear and rebuild a QTableWidget's rows from a data source while blocking signals.

        Consolidates the "clear all rows, then re-insert one row per data entry"
        pattern used for data-driven tables (e.g. the Tab1 reference points table).

        :param table: Target QTableWidget.
        :type table: QTableWidget
        :param row_count: Number of rows to (re)build.
        :type row_count: int
        :param row_builder: Callable(row_index) -> iterable of QTableWidgetItem
            (or None) for each column of that row, in column order. A None entry
            leaves the corresponding cell unset.
        :type row_builder: Callable[[int], Iterable[Optional[QTableWidgetItem]]]
        """
        table.blockSignals(True)
        table.setRowCount(0)
        for i in range(row_count):
            table.insertRow(i)
            for column, cell_item in enumerate(row_builder(i)):
                if cell_item is not None:
                    table.setItem(i, column, cell_item)
        table.blockSignals(False)

    @staticmethod
    # ベクタレイヤのフィールドから抽出した一意なソート済み値でQComboBoxを構築する。
    def populate_combo_from_layer_field(
        combo: QComboBox,
        layer: Any,
        field_name: str,
        leading_item: Optional[str] = None,
        target_list: Optional[list] = None,
    ) -> None:
        """Populate a QComboBox with unique sorted string values extracted from a vector layer field.

        Consolidates the "scan a layer's features for unique non-empty values of
        a given field, then repopulate a combo box (optionally with a fixed
        leading entry such as a '新規作成' option), while also recording each
        restored value into an external tracking list" pattern.

        :param combo: Target QComboBox.
        :type combo: QComboBox
        :param layer: Source vector layer (duck-typed: must support getFeatures()).
        :type layer: Any
        :param field_name: Name of the feature attribute field to extract unique values from.
        :type field_name: str
        :param leading_item: Optional fixed item always added first (e.g. "新規作成").
        :type leading_item: Optional[str]
        :param target_list: Optional external list that each restored value is also appended to.
        :type target_list: Optional[list]
        """
        values = set()
        for feat in layer.getFeatures():
            val = str(feat[field_name] or "").strip()
            if val:
                values.add(val)

        combo.blockSignals(True)
        combo.clear()
        if leading_item is not None:
            combo.addItem(leading_item)
        for v in sorted(values):
            combo.addItem(v)
            if target_list is not None:
                target_list.append(v)
        combo.blockSignals(False)

    @staticmethod
    # ダイアログのアクションボタン用に中央揃え・等幅の行レイアウトを構築する。
    def build_centered_button_row(
        buttons: List[QPushButton],
        spacing: int = 12,
        button_stretch: int = 1,
    ) -> QHBoxLayout:
        """Build a centered, equal-width row layout for dialog action buttons.

        Mirrors the "stretch(1) - button - button - stretch(1)" pattern used
        by StartDialog's OK/Cancel row (start_dialog.py) so confirmation
        dialogs across the plugin share the same centered button alignment
        instead of left/right-anchored or edge-to-edge button rows.

        :param buttons: Ordered list of QPushButton widgets to place in the row.
        :type buttons: List[QPushButton]
        :param spacing: Horizontal spacing between buttons. Default is 12.
        :type spacing: int
        :param button_stretch: Stretch factor applied to each button. Default is 1.
        :type button_stretch: int
        :return: QHBoxLayout containing the centered buttons (not yet attached
            to a parent layout; caller adds it via addLayout()).
        :rtype: QHBoxLayout
        """
        row_layout = QHBoxLayout()
        row_layout.setSpacing(spacing)
        row_layout.addStretch(1)
        for button in buttons:
            row_layout.addWidget(button, button_stretch)
        row_layout.addStretch(1)
        return row_layout

    @staticmethod
    # iOS風のセグメント化トグルボタングループを構築する。
    def build_segmented_toggle(
        options: List[str], default_index: int = 0, parent: Optional[QWidget] = None
    ) -> Tuple[QWidget, List[QPushButton]]:
        """Build an iOS-style segmented toggle button group.
        
        :param options: List of string labels for the buttons.
        :type options: List[str]
        :param default_index: The index of the button to check initially. Default is 0.
        :type default_index: int
        :param parent: Optional parent widget.
        :type parent: Optional[QWidget]
        :return: Tuple containing the container QWidget and the list of QPushButton objects.
        :rtype: Tuple[QWidget, List[QPushButton]]
        """
        container = QWidget(parent)
        container.setProperty("segmentedContainer", True)
        
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        
        button_group = QButtonGroup(container)
        button_group.setExclusive(True)
        
        buttons = []
        for i, option in enumerate(options):
            btn = QPushButton(option, container)
            btn.setProperty("segmentedButton", True)
            btn.setCheckable(True)
            btn.setSizePolicy(btn.sizePolicy().Policy.Expanding, btn.sizePolicy().Policy.Preferred)
            button_group.addButton(btn, i)
            layout.addWidget(btn)
            buttons.append(btn)
            
        if 0 <= default_index < len(buttons):
            buttons[default_index].setChecked(True)
            
        # Retain reference to button_group to prevent garbage collection
        container._button_group = button_group
        container.style().polish(container)
        
        return container, buttons

