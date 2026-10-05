from __future__ import annotations

import os

from qgis.PyQt.QtCore import QCoreApplication, Qt
from qgis.PyQt.QtGui import QAction, QIcon
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.core import QgsApplication

from .core.language_service import PyQGISLanguageService

from .ui.main_window import IDEMainWindow


class QGISPythonIDE:
    """Entry point del plugin QGIS Python IDE."""

    MENU_TITLE = "&QGIS Python IDE Pro"
    ACTION_OBJECT_NAME = "qgisPythonIdeProAction"
    WINDOW_TITLE = "QGIS Python IDE Pro"

    def __init__(self, iface):
        self.iface = iface
        self.window: IDEMainWindow | None = None
        self.action: QAction | None = None
        # Cache per tutta la vita del plugin: chiudere la finestra non richiede
        # una nuova introspezione delle librerie QGIS.
        self.language_service = PyQGISLanguageService()

    # ------------------------------------------------------------------
    # Translation
    # ------------------------------------------------------------------

    def tr(self, text: str) -> str:
        return QCoreApplication.translate(
            "QGISPythonIDE",
            text,
        )

    # ------------------------------------------------------------------
    # GUI
    # ------------------------------------------------------------------

    def initGui(self) -> None:
        """
        Inizializza l'azione e la voce di menu del plugin.
        Evita di creare una seconda icona se il plugin è già attivo.
        """
        if self.action is not None:
            QMessageBox.information(
                self.iface.mainWindow(),
                self.tr("QGIS Python IDE Pro"),
                self.tr(
                    "QGIS Python IDE Pro è già attivo."
                ),
            )
            return

        existing_action = self._find_existing_action()

        if existing_action is not None:
            QMessageBox.information(
                self.iface.mainWindow(),
                self.tr("QGIS Python IDE Pro"),
                self.tr(
                    "QGIS Python IDE Pro è già attivo."
                ),
            )
            return

        icon = QIcon(self._icon_path())

        self.action = QAction(
            icon,
            self.tr("QGIS Python IDE Pro"),
            self.iface.mainWindow(),
        )

        self.action.setObjectName(
            self.ACTION_OBJECT_NAME
        )

        self.action.setToolTip(
            self.tr(
                "IDE Python professionale per QGIS 4 / Qt6"
            )
        )

        self.action.setStatusTip(
            self.tr("Apri QGIS Python IDE Pro")
        )

        self.action.triggered.connect(self.run)

        self.iface.addToolBarIcon(self.action)

        self.iface.addPluginToMenu(
            self.tr(self.MENU_TITLE),
            self.action,
        )

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------

    def _icon_path(self) -> str:
        return os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "icon.svg",
        )

    def _find_existing_action(self):
        """
        Cerca nella finestra principale di QGIS un'azione già
        registrata con l'objectName del plugin.
        """
        main_window = self.iface.mainWindow()

        if main_window is None:
            return None

        actions = main_window.findChildren(QAction)

        for action in actions:
            try:
                if action.objectName() == self.ACTION_OBJECT_NAME:
                    return action
            except RuntimeError:
                continue

        return None

    # ------------------------------------------------------------------
    # Window
    # ------------------------------------------------------------------

    def run(self) -> None:
        if self.window is None:
            self.window = IDEMainWindow(self.iface, self.language_service)

            self.window.setAttribute(
                Qt.WidgetAttribute.WA_DeleteOnClose,
                True,
            )

        try:
            self.window.show()
            self.window.raise_()
            self.window.activateWindow()
        except RuntimeError:
            self.window = IDEMainWindow(self.iface, self.language_service)

            self.window.setAttribute(
                Qt.WidgetAttribute.WA_DeleteOnClose,
                True,
            )

            self.window.show()
            self.window.raise_()
            self.window.activateWindow()

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def unload(self) -> None:
        """
        Rimuove completamente il plugin dalla GUI di QGIS.
        """

        window = self.window
        self.window = None

        if window is not None:
            try:
                window.close()
            except RuntimeError:
                window = None
            except Exception as error:
                QgsApplication.messageLog().logMessage(
                    f"Errore chiusura finestra: {error}",
                    "QGIS Python IDE",
                )

            if window is not None:
                try:
                    window.deleteLater()
                except RuntimeError:
                    window = None

        action = self.action
        self.action = None

        if action is not None:
            try:
                self.iface.removePluginMenu(
                    self.tr(self.MENU_TITLE),
                    action,
                )
            except Exception as error:
                QgsApplication.messageLog().logMessage(
                    f"Errore rimozione menu: {error}",
                    "QGIS Python IDE",
                )

            try:
                self.iface.removeToolBarIcon(action)
            except Exception as error:
                QgsApplication.messageLog().logMessage(
                    f"Errore rimozione toolbar: {error}",
                    "QGIS Python IDE",
                )

            try:
                action.deleteLater()
            except RuntimeError:
                return