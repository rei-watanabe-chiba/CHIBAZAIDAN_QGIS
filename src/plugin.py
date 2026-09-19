"""
/***************************************************************************
 PointerGeocoding Plugin - Main Plugin Lifecycle Module
 ***************************************************************************/
"""
import os
from typing import Optional, Dict, Any

from qgis.core import QgsProject, Qgis
from qgis.gui import QgisInterface
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon, QPixmap, QColor, QPainter
from qgis.PyQt.QtWidgets import QAction, QMessageBox, QToolBar

from .ui.start_dialog import StartDialog
from .layer.manager import LayerManager
from .ui.constants import UIMessages


class PointerGeocodingPlugin:
    """Main plugin entry class managing lifecycle, UI integration, and session orchestration."""

    def __init__(self, iface: QgisInterface) -> None:
        """Initialize the plugin instance.

        :param iface: QGIS interface reference.
        :type iface: QgisInterface
        """
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.action: Optional[QAction] = None
        self.toolbar: Optional[QToolBar] = None
        self.menu_name = "&点群座標取得"
        self.layer_manager = LayerManager(iface)
        self.dock_widget: Optional[Any] = None

    def _get_icon(self) -> QIcon:
        """Obtain the plugin icon from SVG/PNG file or generate a fallback icon dynamically.

        Prioritizes vector icon.svg for High DPI displays.

        :return: QIcon instance.
        :rtype: QIcon
        """
        # 1. Prioritize icon.svg for crisp High DPI scaling
        # T-0024: icon assets moved under plugin_dir/icon/ (alongside the new
        # top-row button icons image.svg/setting.svg/output.svg/save.svg).
        svg_path = os.path.join(self.plugin_dir, "icon", "icon.svg")
        if os.path.exists(svg_path):
            return QIcon(svg_path)

        # 2. Check icon.png
        png_path = os.path.join(self.plugin_dir, "icon.png")
        if os.path.exists(png_path):
            return QIcon(png_path)

        # 3. Generate a dynamic fallback icon if both files are missing
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#1976D2"))
        painter.drawEllipse(2, 2, 28, 28)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(pixmap.rect(), Qt.AlignCenter, "点")
        painter.end()
        return QIcon(pixmap)

    def initGui(self) -> None:
        """Initialize and register plugin actions directly under pluginMenu and in dedicated toolbar."""
        icon = self._get_icon()
        self.action = QAction(icon, "点群座標取得", self.iface.mainWindow())
        self.action.setObjectName("pointerGeocodingAction")
        self.action.setStatusTip("アナログ図面上の連続打刻・座標変換・CSV出力を実行します")
        self.action.triggered.connect(self.run)

        # 1. Add action directly under the "プラグイン" menu (no sub-menu)
        if self.iface.pluginMenu() is not None:
            self.iface.pluginMenu().addAction(self.action)

        # 2. Add dedicated independent toolbar for this plugin
        self.toolbar = self.iface.addToolBar("点群座標取得ツール")
        self.toolbar.setObjectName("PointerGeocodingToolbar")
        self.toolbar.addAction(self.action)

    def unload(self) -> None:
        """Remove GUI elements, unregister menus and toolbars, and close active docks."""
        if self.action is not None:
            if self.iface.pluginMenu() is not None:
                self.iface.pluginMenu().removeAction(self.action)

        if self.toolbar is not None:
            if self.action is not None:
                self.toolbar.removeAction(self.action)
            del self.toolbar
            self.toolbar = None

        if self.action is not None:
            del self.action
            self.action = None

        self._teardown_dock_widget()

    def _teardown_dock_widget(self) -> None:
        """Unregister and dispose of the main dock widget (T-0024).

        T-0024: the former left dock (self.dock_widget.left_dock,
        Qt.LeftDockWidgetArea, introduced in T-0021) has been removed; the
        plugin now registers only a single dock widget (self.dock_widget,
        Qt.RightDockWidgetArea). Its own auxiliary dialogs (image/settings/
        output) are plain child QDialogs, so Qt's normal parent-child
        cleanup via deleteLater() below is sufficient for them.
        """
        if self.dock_widget is None:
            return

        self.iface.removeDockWidget(self.dock_widget)
        self.dock_widget.deleteLater()
        self.dock_widget = None

    def run(self) -> None:
        """Execute the plugin launch sequence: check dirty state, show start dialog, and initialize session."""
        # 1. Protect unsaved changes in current QGIS project
        if QgsProject.instance().isDirty():
            reply = QMessageBox.question(
                self.iface.mainWindow(),
                UIMessages.MSG_UNSAVED_CHANGES_TITLE,
                UIMessages.MSG_UNSAVED_CHANGES,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        # 2. Display the session startup dialog
        dialog = StartDialog(self.iface.mainWindow())
        if dialog.exec_() != StartDialog.Accepted:
            return

        session_data = dialog.get_session_data()

        # 3. Process session based on type
        if session_data["session_type"] == "NEW":
            success, message, layers_dict = self.layer_manager.setup_new_session(
                parent_dir=session_data["parent_dir_path"],
                session_name=session_data["session_name"],
                image_file_path=session_data["image_file_path"],
                grid_config=session_data.get("grid_config"),
            )
        else:
            success, message, layers_dict = self.layer_manager.load_existing_session(
                session_dir=session_data["session_dir_path"],
                grid_config=session_data.get("grid_config"),
            )

        if not success:
            QMessageBox.critical(
                self.iface.mainWindow(),
                UIMessages.ERR_TITLE_SESSION,
                UIMessages.ERR_SESSION_INIT_FAILED.format(message=message),
            )
            return

        # Notify success on QGIS message bar
        self.iface.messageBar().pushMessage(
            UIMessages.MSG_TITLE_PLUGIN,
            message,
            level=Qgis.MessageLevel.Success,
            duration=5,
        )

        # 4. Initialize and show MainDockWidget if available (Step 2 integration)
        self._setup_dock_widget(layers_dict)

    def _setup_dock_widget(self, layers_dict: Optional[Dict[str, Any]]) -> None:
        """Instantiate and attach the main dock widget to the QGIS interface.

        Gracefully notifies if MainDockWidget is not yet created (during Step 1).

        T-0024: MainDockWidget is now a single QDockWidget (Qt.RightDockWidgetArea)
        hosting a top row of 画像/設定/出力/保存 buttons plus the always-visible
        main digitizing area; the former left dock (T-0021) has been removed,
        and 画像/設定/出力 now each open their own independent modeless dialog
        (built internally by MainDockWidget) instead.

        :param layers_dict: Dictionary containing session and layer references.
        :type layers_dict: Optional[Dict[str, Any]]
        """
        try:
            from .ui.dock import MainDockWidget

            self._teardown_dock_widget()

            self.dock_widget = MainDockWidget(
                self.iface, self.layer_manager, layers_dict
            )
            self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock_widget)
            self.dock_widget.show()

        except ImportError:
            # Step 1 environment: main_dock.py has not been generated yet
            self.iface.messageBar().pushMessage(
                UIMessages.MSG_TITLE_PLUGIN,
                UIMessages.MSG_STEP1_READY,
                level=Qgis.MessageLevel.Info,
                duration=7,
            )
