# -*- coding: utf-8 -*-
"""Jointures attributaires sur la couche Parcelles (clé : titref)."""
from collections import defaultdict

from qgis.core import QgsField

from .compat import NULL, STRING
from .constants import F_DXF, F_LEGIBLE, F_OBS, F_STATUT, F_TITREF
from .tables import norm_id, unique_values

SEP = " | "
RESERVED = {F_TITREF, F_STATUT, F_OBS, F_LEGIBLE, F_DXF}


class JoinError(Exception):
    pass


class Recap(object):
    def __init__(self, added_fields=None):
        self.merged = 0
        self.only_layer = 0
        self.only_table = 0
        self.only_table_ids = []
        self.multi = 0
        self.deduped = 0   # parcelles où au moins un doublon de valeur a été supprimé
        self.added_fields = list(added_fields or [])


def _check(layer):
    if layer is None or not layer.isValid():
        raise JoinError("Sélectionnez d'abord une couche Parcelles valide.")
    if layer.isEditable():
        raise JoinError("La couche est en mode édition : enregistrez et fermez l'édition avant la jointure.")
    if layer.fields().indexOf(F_TITREF) < 0:
        raise JoinError(f"Le champ « {F_TITREF} » est introuvable dans cette couche.")


def _ensure_fields(layer, names):
    missing = [n for n in names if layer.fields().indexOf(n) < 0]
    if missing:
        if not layer.dataProvider().addAttributes([QgsField(n, STRING) for n in missing]):
            raise JoinError("Impossible d'ajouter les champs à la couche.")
        layer.updateFields()
    return [layer.fields().indexOf(n) for n in names]


def _write(layer, changes):
    if changes and not layer.dataProvider().changeAttributeValues(changes):
        raise JoinError("Écriture des valeurs impossible (couche en lecture seule ?).")
    layer.triggerRepaint()


def _table_ids(table, id_idx):
    return {norm_id(r[id_idx]) for r in table.rows if norm_id(r[id_idx])}


def join_legible(layer, table, id_idx):
    _check(layer)
    (fidx,) = _ensure_fields(layer, [F_LEGIBLE])
    ids = _table_ids(table, id_idx)
    seen_layer, changes, rec = set(), {}, Recap()
    for feat in layer.getFeatures():
        key = norm_id(feat[F_TITREF])
        seen_layer.add(key)
        ok = key in ids
        changes[feat.id()] = {fidx: "OUI" if ok else NULL}
        rec.merged += ok
        rec.only_layer += (not ok)
    _write(layer, changes)
    missing = sorted(ids - seen_layer)
    rec.only_table, rec.only_table_ids = len(missing), missing[:15]
    return rec


def join_etat_juridique(layer, table, id_idx, col_idx_list):
    _check(layer)
    if not col_idx_list:
        raise JoinError("Sélectionnez au moins un champ à joindre.")
    names = []
    for i in col_idx_list:
        n = table.fields[i].strip()
        names.append(n + "_ej" if n in RESERVED else n)
    fidx = _ensure_fields(layer, names)

    groups = defaultdict(list)
    for r in table.rows:
        k = norm_id(r[id_idx])
        if k:
            groups[k].append(r)

    seen_layer, changes, rec = set(), {}, Recap(names)
    for feat in layer.getFeatures():
        key = norm_id(feat[F_TITREF])
        seen_layer.add(key)
        rows = groups.get(key)
        vals, had_dup = {}, False
        for ci, li in zip(col_idx_list, fidx):
            uniq, dropped = unique_values(r[ci] for r in rows) if rows else ([], 0)
            had_dup = had_dup or dropped > 0
            vals[li] = SEP.join(uniq) if uniq else NULL
        changes[feat.id()] = vals
        if rows:
            rec.merged += 1
            rec.multi += len(rows) > 1
            rec.deduped += had_dup
        else:
            rec.only_layer += 1
    _write(layer, changes)
    missing = sorted(set(groups) - seen_layer)
    rec.only_table, rec.only_table_ids = len(missing), missing[:15]
    return rec
