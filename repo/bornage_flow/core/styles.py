# -*- coding: utf-8 -*-
"""Application des styles QML de l'utilisateur (dossier styles/).

Le QML est importé via QgsMapLayer.importNamedStyle(QDomDocument) et NON via
loadNamedStyle(chemin) : sur une couche GeoPackage, loadNamedStyle relit d'abord
le style enregistré dans la base (« Loaded from Provider ») et ignore le fichier.
"""
import json
import os

from qgis.PyQt.QtXml import QDomDocument

from . import qml_adapt
from .layers import LayerError, enable_feature_count, hide_fid, persist_style, setup_form

STYLE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "styles")
BORNES_QML = os.path.join(STYLE_DIR, "bornes.qml")
PARCELLES_QML = os.path.join(STYLE_DIR, "parcelles.qml")
DXF_QML = os.path.join(STYLE_DIR, "dxf.qml")
DETAILS_QML = {
    "Polygones": os.path.join(STYLE_DIR, "Polygones_Style.qml"),
    "Lignes": os.path.join(STYLE_DIR, "Lignes_Style.qml"),
    "Points": os.path.join(STYLE_DIR, "Points_Style.qml"),
}
LABEL_KEY = "bornageflow/label_map"
LABEL_KEYS = ("id", "prenom", "nom", "parcelle", "dxf")


def _import(layer, xml_text):
    doc = QDomDocument()
    try:
        doc.setContent(xml_text)
    except Exception as e:      # Qt6 : l'API setContent a changé de signature selon les versions
        raise LayerError(f"Fichier de style QML illisible : {e}")
    if doc.documentElement().isNull():
        raise LayerError("Fichier de style QML illisible.")
    res = layer.importNamedStyle(doc)
    ok, msg = res if isinstance(res, tuple) else (bool(res), "")
    if not ok:
        raise LayerError(f"Style non appliqué : {msg}")


def apply_bornes_style(layer):
    _import(layer, qml_adapt.load_qml(BORNES_QML))
    layer.triggerRepaint()


def apply_dxf_style(layer):
    """Style DXF de l'utilisateur (ligne blanche + étiquette Layer/Text)."""
    _import(layer, qml_adapt.load_qml(DXF_QML))
    if layer.renderer() is None:
        raise LayerError("Le style DXF n'a pas été appliqué.")
    hide_fid(layer)
    layer.triggerRepaint()


def apply_details_style(layer, kind):
    """Style préféré de l'utilisateur pour la couche Polygones / Lignes / Points de DETAILS_BORNAGE."""
    _import(layer, qml_adapt.load_qml(DETAILS_QML[kind]))
    if layer.renderer() is None:
        raise LayerError(f"Le style « {kind} » n'a pas été appliqué.")
    hide_fid(layer)
    layer.triggerRepaint()
    persist_style(layer)


def get_label_map(layer):
    """Choix d'étiquette mémorisé sur la couche, sinon pré-sélection par préfixe."""
    names = [f.name() for f in layer.fields()]
    guess = qml_adapt.guess_label_map(names)
    try:
        stored = json.loads(layer.customProperty(LABEL_KEY, "") or "{}")
    except ValueError:
        stored = {}
    lm = {}
    for k in LABEL_KEYS:
        v = stored.get(k)
        if v is None or (v and v not in names) or (k == "id" and not v):
            v = guess[k]
        lm[k] = v
    return lm


def apply_parcelles_style(layer, label_map=None):
    """Ensemble de règles du QML utilisateur + étiquette. Retourne les champs d'étiquette."""
    lm = label_map if label_map is not None else get_label_map(layer)
    fields = qml_adapt.ordered(lm)
    dxf_field = lm.get("dxf", "")
    _import(layer, qml_adapt.adapt_parcelles(PARCELLES_QML, fields, dxf_field))
    r = layer.renderer()
    if r is None or r.type() != "RuleRenderer":
        raise LayerError("L'ensemble de règles du style n'a pas été appliqué.")
    if label_map is not None:       # mémorisé seulement si l'utilisateur l'a choisi (étape 4)
        layer.setCustomProperty(LABEL_KEY, json.dumps(lm))
    setup_form(layer)       # l'import du style ne doit pas défaire le formulaire
    layer.triggerRepaint()
    enable_feature_count(layer)
    persist_style(layer)
    return fields + ([dxf_field] if dxf_field else [])
