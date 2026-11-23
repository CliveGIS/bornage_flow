# -*- coding: utf-8 -*-
"""Adaptation du style QML « Parcelles » de l'utilisateur aux champs du plugin.

Python pur (sans QGIS) pour rester testable.

Correspondances (shapefile de l'utilisateur -> champs du plugin) :
    "BORNAGE LE" -> Bornage_Legible
    "Statu Born" -> Statut_Bornage
    "Observatio" -> Observation_Bornage
Les champs d'identité de l'étiquette (« Prénom (F… », « Nom (F) », « Nom Plle (… »)
sont retrouvés par préfixe parmi les champs joints de l'état juridique.
"""
import re
import unicodedata
import xml.etree.ElementTree as ET

from .constants import DEFAULT_STATUT, F_DXF, F_LEGIBLE, F_OBS, F_STATUT, F_TITREF

DOCTYPE = "<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>\n"
LABEL_PREFIXES = ("prenom (f", "nom (f)", "nom plle (")


# ------------------------------------------------------------------ compatibilité des QML entre versions
# Les QML enregistrés par QGIS récent décrivent les symboles en <Option name=… value=…> et les couleurs
# en « r,g,b,a,rgb:… » : un QGIS ancien (3.10…) ne relit pas ces propriétés (symboles par défaut).
# Le format <prop k=… v=…> + « r,g,b,a » est lu par TOUTES les versions, de 3.10 à 4.x.
_COLOR_EXTRA = re.compile(r"^(\d+,\d+,\d+,\d+),[a-z]+:[^\"]*$")


def _legacy_symbol_props(root):
    for layer in list(root.iter("layer")) + list(root.iter("effect")):   # couches de symbole + effets
        for i, child in enumerate(list(layer)):
            if child.tag != "Option" or child.get("type") != "Map":
                continue
            opts = list(child)
            if any(len(o) for o in opts):          # structure imbriquée : on ne touche pas
                break
            layer.remove(child)
            for j, o in enumerate(opts):
                prop = ET.Element("prop")
                prop.set("k", o.get("name", ""))
                prop.set("v", o.get("value", ""))
                layer.insert(i + j, prop)
            break


def _short_colors(root):
    for el in root.iter():
        for k, v in list(el.attrib.items()):
            m = _COLOR_EXTRA.match(v)
            if m:
                el.set(k, m.group(1))


def normalize(root):
    """Rend un QML (quelle que soit la version de QGIS qui l'a écrit) lisible de QGIS 3.10 à 4.x."""
    _legacy_symbol_props(root)
    _short_colors(root)
    return root


def load_qml(path):
    """QML normalisé, prêt pour importNamedStyle()."""
    return DOCTYPE + ET.tostring(normalize(ET.parse(path).getroot()), encoding="unicode")


def _q(name):
    return '"' + name.replace('"', '""') + '"'


RENAMES = (
    ('"BORNAGE LE"', _q(F_LEGIBLE)),
    ('"Statu Born"', _q(F_STATUT)),
    ('"Observatio"', _q(F_OBS)),
)


def _plain(s):
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


def guess_label_map(field_names):
    """Pré-sélection : retrouve par préfixe les champs d'identité (modifiable à l'étape 4)."""
    def find(prefix):
        return next((n for n in field_names if _plain(n).startswith(prefix)), "")
    return {"id": F_TITREF, "prenom": find("prenom (f"), "nom": find("nom (f)"), "parcelle": find("nom plle ("),
            "dxf": F_DXF if F_DXF in field_names else ""}


def ordered(label_map):
    """Ordre d'affichage du style d'origine : ID, Prénom, Nom, Nom parcelle (sans doublon)."""
    out = []
    for k in ("id", "prenom", "nom", "parcelle"):
        v = label_map.get(k)
        if v and v not in out:
            out.append(v)
    return out


def label_fields(field_names):
    return ordered(guess_label_map(field_names))


def _expr(fields, with_obs, dxf=""):
    """concat(ID, Prénom, Nom, Nom parcelle [, Consistance DXF] [, Observation]) — un champ par ligne.

    La ligne « Consistance DXF » n'apparaît que si elle n'est pas vide (pas de ligne blanche)."""
    expr = ", '\\n', ".join(_q(f) for f in fields)
    if dxf:
        q = _q(dxf)
        expr += f", if({q} IS NULL OR {q} = '', '', '\\n' || {q})"
    if with_obs:
        expr += ", '\\n', " + _q(F_OBS)
    return "concat(" + expr + ")"


def adapt_parcelles(qml_path, fields, dxf_field=""):
    """fields : champs de l'étiquette, dans l'ordre d'affichage (voir ordered()).

    dxf_field : champ « Consistance DXF » ajouté en dernière ligne (avant l'observation)."""
    root = normalize(ET.parse(qml_path).getroot())
    obs_empty = f'({_q(F_OBS)} IS NULL OR {_q(F_OBS)} = \'\')'
    obs_filled = f'({_q(F_OBS)} IS NOT NULL AND {_q(F_OBS)} <> \'\')'

    # --- symbologie
    renderer = root.find("renderer-v2")
    for rule in renderer.iter("rule"):
        flt = rule.get("filter")
        if not flt:
            continue
        for old, new in RENAMES:
            flt = flt.replace(old, new)
        if rule.get("label") == "BORNAGE LEGIBLE":
            # Le plugin met « Sans Résultat » par défaut (le QML d'origine supposait NULL).
            flt = flt.replace(
                f'{_q(F_STATUT)} IS NULL',
                f'({_q(F_STATUT)} IS NULL OR {_q(F_STATUT)} = \'{DEFAULT_STATUT}\')')
        rule.set("filter", flt)

    # --- étiquettes
    labeling = root.find("labeling")
    for rule in labeling.iter("rule"):
        flt = rule.get("filter")
        if not flt:
            continue
        with_obs = "IS NOT NULL" in flt
        rule.set("filter", obs_filled if with_obs else obs_empty)
        style = rule.find("settings/text-style")
        style.set("fieldName", _expr(fields, with_obs, dxf_field))
        style.set("isExpression", "1")

    return DOCTYPE + ET.tostring(root, encoding="unicode")
