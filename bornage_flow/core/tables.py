# -*- coding: utf-8 -*-
"""Lecture des tableurs (Excel / ODS / CSV) et normalisation des identifiants."""
import csv
import os
import re


class TableError(Exception):
    pass


class Table(object):
    def __init__(self, fields, rows):
        self.fields = fields
        self.rows = rows


def norm_id(v):
    """Identifiant comparable : texte sans espaces, '772.0' -> '772'."""
    if v is None:
        return ""
    s = str(v).strip()
    if s.upper() == "NULL":
        return ""
    if re.fullmatch(r"-?\d+\.0+", s):
        s = s.split(".")[0]
    return s


def _dedup_key(v):
    """Clé de comparaison : espaces normalisés, insensible à la casse."""
    return " ".join(str(v).split()).casefold()


def unique_values(values):
    """Valeurs non vides, sans doublon (ordre d'apparition conservé).

    ['Hassan', 'Said', 'Hassan', ''] -> ['Hassan', 'Said']
    Retourne (liste_unique, nb_doublons_supprimés).
    """
    seen, out, dropped = set(), [], 0
    for v in values:
        s = " ".join(str(v).split())
        if not s or s.upper() == "NULL":
            continue
        k = _dedup_key(s)
        if k in seen:
            dropped += 1
            continue
        seen.add(k)
        out.append(s)
    return out, dropped


def _is_csv(path):
    return os.path.splitext(path)[1].lower() in (".csv", ".txt", ".tsv")


def _read_csv_text(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise TableError("Encodage du fichier non reconnu.")


def _open_ogr(path):
    """Ouvre un classeur via OGR en forçant la 1re ligne comme noms de colonnes.

    Sans HEADERS=FORCE, le pilote XLSX/ODS « devine » : si la 1re ligne ne se distingue
    pas des suivantes (ex. une seule colonne d'identifiants), elle est lue comme une
    donnée et les colonnes s'appellent Field1, Field2… Avec FORCE, la 1re ligne est
    toujours l'en-tête et n'est jamais comptée comme une ligne de données.
    """
    try:
        from osgeo import gdal, ogr
    except ImportError:
        raise TableError("GDAL/OGR indisponible pour lire ce format.")
    opts = ["HEADERS=FORCE"] if os.path.splitext(path)[1].lower() in (".xlsx", ".xlsm", ".ods") else []
    if opts:
        ds = gdal.OpenEx(path, gdal.OF_VECTOR, open_options=opts)   # OpenEx est dans gdal, pas dans ogr
        if ds is not None:
            return ds
    return ogr.Open(path)


def list_sheets(path):
    if _is_csv(path):
        return [os.path.basename(path)]
    ds = _open_ogr(path)
    if ds is None:
        hint = (" Les anciens .xls ne sont pas lus par GDAL : enregistrez le fichier en .xlsx, .ods ou .csv."
                if path.lower().endswith(".xls") else "")
        raise TableError("Impossible d'ouvrir le fichier (format non supporté par cette installation GDAL ?)." + hint)
    names = [ds.GetLayerByIndex(i).GetName() for i in range(ds.GetLayerCount())]
    if not names:
        raise TableError("Aucune feuille trouvée.")
    return names


def _cell(v):
    if v is None:
        return ""
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else repr(v)
    return str(v).strip()


def read_table(path, sheet=None):
    if _is_csv(path):
        text = _read_csv_text(path)
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        rows = [r for r in csv.reader(text.splitlines(), dialect)]
        rows = [r for r in rows if any(c.strip() for c in r)]
        if not rows:
            raise TableError("Fichier vide.")
        fields = [c.strip() or f"colonne_{i + 1}" for i, c in enumerate(rows[0])]
        body = rows[1:]
    else:
        ds = _open_ogr(path)
        if ds is None:
            raise TableError("Impossible d'ouvrir le fichier.")
        lyr = ds.GetLayerByName(sheet) if sheet else ds.GetLayerByIndex(0)
        if lyr is None:
            raise TableError("Feuille introuvable.")
        defn = lyr.GetLayerDefn()
        fields = [defn.GetFieldDefn(i).GetName() for i in range(defn.GetFieldCount())]
        body = [[_cell(f.GetField(i)) for i in range(len(fields))] for f in lyr]
    width = len(fields)
    body = [([c.strip() for c in r] + [""] * width)[:width] for r in body]
    return Table(fields, body)
