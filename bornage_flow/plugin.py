# -*- coding: utf-8 -*-
import os
from qgis.PyQt.QtGui import QIcon
try:                                    # Qt6 / QGIS 4
    from qgis.PyQt.QtGui import QAction
except ImportError:                     # Qt5 / QGIS 3
    from qgis.PyQt.QtWidgets import QAction


class BornageFlowPlugin:
    MENU = "&BornageFlow"

    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dialog = None
        self.plugin_dir = os.path.dirname(__file__)

    def initGui(self):
        icon = QIcon(os.path.join(self.plugin_dir, "icon.svg"))
        self.action = QAction(icon, "BornageFlow", self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu(self.MENU, self.action)

    def unload(self):
        if self.action:
            self.iface.removeToolBarIcon(self.action)
            self.iface.removePluginMenu(self.MENU, self.action)
            self.action = None
        if self.dialog:
            self.dialog.close()
            self.dialog.deleteLater()
            self.dialog = None

    def run(self):
        if self.dialog is None:
            from .ui.main_dialog import BornageFlowDialog
            self.dialog = BornageFlowDialog(self.iface, self.iface.mainWindow())
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
