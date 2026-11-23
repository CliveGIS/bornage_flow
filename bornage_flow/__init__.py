# -*- coding: utf-8 -*-
import configparser
import os


def _min_version():
    """Version minimale lue dans metadata.txt (source unique)."""
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(os.path.join(os.path.dirname(__file__), "metadata.txt"), encoding="utf-8")
    txt = cp.get("general", "qgisMinimumVersion", fallback="3.10").strip()
    p = (txt.split(".") + ["0", "0"])[:3]
    return int(p[0]) * 10000 + int(p[1]) * 100 + int(p[2]), txt


class _TooOldQgis:
    """Remplace le plugin sur une version de QGIS trop ancienne : alerte, aucun chargement."""

    def __init__(self, iface, min_txt, current):
        self.iface, self.min_txt, self.current = iface, min_txt, current

    def initGui(self):
        from qgis.PyQt.QtCore import QTimer
        from qgis.PyQt.QtWidgets import QMessageBox
        msg = (f"BornageFlow nécessite QGIS {self.min_txt} ou supérieur.\n"
               f"Version détectée : {self.current}.\n\n"
               "Le plugin est désactivé. Mettez à jour QGIS pour l'utiliser.")
        QTimer.singleShot(0, lambda: QMessageBox.critical(self.iface.mainWindow(), "BornageFlow — QGIS trop ancien", msg))

    def unload(self):
        pass


def classFactory(iface):
    from qgis.core import Qgis
    min_int, min_txt = _min_version()
    if Qgis.QGIS_VERSION_INT < min_int:
        return _TooOldQgis(iface, min_txt, Qgis.QGIS_VERSION)
    from .plugin import BornageFlowPlugin
    return BornageFlowPlugin(iface)
