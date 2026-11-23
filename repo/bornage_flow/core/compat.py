# -*- coding: utf-8 -*-
"""Utilitaires de compatibilité QGIS 3.10 -> 4.x (Qt5 / Qt6, Python 3.6+)."""
from qgis.PyQt.QtCore import QVariant

try:                                    # QGIS 3.x (PyQt5)
    STRING = QVariant.String
except AttributeError:                  # QGIS 4 (PyQt6)
    from qgis.PyQt.QtCore import QMetaType
    STRING = QMetaType.Type.QString

try:
    from qgis.core import NULL
except ImportError:                     # sécurité
    NULL = QVariant()


def enum(cls, scope, name):
    """Valeur d'énumération Qt : style PyQt5 (Qt.Checked) ou PyQt6 (Qt.CheckState.Checked)."""
    try:
        return getattr(cls, name)
    except AttributeError:
        return getattr(getattr(cls, scope), name)
