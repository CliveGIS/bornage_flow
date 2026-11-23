# -*- coding: utf-8 -*-
"""Lecture du fichier DAT/TXT (Python pur, sans dépendance QGIS).

Structure d'un bloc (répétée jusqu'à la fin du fichier) :
    ligne 1 : titref
    ligne 2 : Mappe
    ligne 3 : Opération
    ligne 4 : Consistance
    ligne 5 : Nombre_Bornes (N)
    N lignes : NomBorne X Y     (EPSG:26191)
"""
import re
from collections import Counter


class DatError(Exception):
    pass


class Borne(object):
    def __init__(self, name, x, y, xs, ys):
        self.name = name
        self.x = x
        self.y = y
        self.xs = xs   # texte d'origine normalisé (point décimal)
        self.ys = ys


class Parcelle(object):
    def __init__(self, titref, mappe="", operation="", consistance=""):
        self.titref = titref
        self.mappe = mappe
        self.operation = operation
        self.consistance = consistance
        self.bornes = []


class ParseResult(object):
    def __init__(self, parcelles, warnings, stripped=None):
        self.parcelles = parcelles
        self.warnings = warnings
        self.stripped = stripped or {}   # préfixe supprimé -> nombre de titref

    @property
    def n_bornes_total(self):
        return sum(len(p.bornes) for p in self.parcelles)


# ------------------------------------------------------------------ préfixes du titref
# Préfixe = lettres seules (P, Plle, Parcelle…), séparateur facultatif, puis un chiffre :
#   P774 · Plle774 · Plle 774 · P-774 · P.774  ->  774
_SEP = r"[\s.\-_:°/]*"
_PREFIX_RE = re.compile(r"^([^\W\d_]+)" + _SEP + r"(?=\d)")


def detect_prefixes(titrefs):
    """Préfixes alphabétiques trouvés devant un numéro : [(préfixe, nombre)], du plus fréquent au moins."""
    c, shown = Counter(), {}
    for t in titrefs:
        m = _PREFIX_RE.match(t.strip())
        if m:
            k = m.group(1).casefold()
            c[k] += 1
            shown.setdefault(k, m.group(1))
    return [(shown[k], n) for k, n in c.most_common()]


def parse_prefixes(text):
    """« P, Plle » -> ['P', 'Plle'] (séparateurs : virgule, point-virgule, espace)."""
    return [p for p in re.split(r"[,;\s]+", text or "") if p]


def strip_prefix(titref, prefixes):
    """Retire un des préfixes (insensible à la casse) s'il est suivi d'un numéro. Retourne (titref, préfixe|None)."""
    t = titref.strip()
    for p in sorted(prefixes, key=len, reverse=True):
        m = re.match(re.escape(p) + _SEP + r"(?=\d)", t, re.IGNORECASE)
        if m:
            return t[m.end():], p
    return t, None


def scan_prefixes(path):
    """Détection automatique (sans rien écrire) : lit le DAT et liste les préfixes présents."""
    result = parse_dat(path)
    return detect_prefixes(p.titref for p in result.parcelles)


def read_text(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise DatError("Encodage du fichier non reconnu.")


def _num(token, lineno):
    t = token.strip().replace(",", ".")
    try:
        return t, float(t)
    except ValueError:
        raise DatError(f"Ligne {lineno} : coordonnée invalide « {token} ».")


def _parse_borne(line, lineno):
    tokens = [t for t in re.split(r"[\s;]+", line.strip()) if t]
    if len(tokens) < 3:
        raise DatError(f"Ligne {lineno} : borne attendue « Nom X Y », trouvé « {line.strip()} ».")
    xs, x = _num(tokens[-2], lineno)
    ys, y = _num(tokens[-1], lineno)
    return Borne(" ".join(tokens[:-2]), x, y, xs, ys)


def parse_dat(path, prefixes=None):
    """prefixes : liste de préfixes à retirer des titref (None/vide = aucun)."""
    lines = read_text(path).splitlines()
    n = len(lines)
    i = 0
    parcelles, warnings = [], []
    seen, stripped = set(), Counter()
    prefixes = list(prefixes or [])

    while True:
        while i < n and not lines[i].strip():
            i += 1
        if i >= n:
            break
        if i + 4 >= n:
            raise DatError(f"Ligne {i + 1} : bloc incomplet (5 lignes d'en-tête attendues).")
        titref, mappe, operation, consistance = (lines[i + k].strip() for k in range(4))
        m = re.search(r"\d+", lines[i + 4])
        if not m:
            raise DatError(f"Ligne {i + 5} : Nombre_Bornes attendu, trouvé « {lines[i + 4].strip()} ».")
        count = int(m.group())
        i += 5
        if prefixes:
            titref, used = strip_prefix(titref, prefixes)
            if used:
                stripped[used] += 1

        p = Parcelle(titref, mappe, operation, consistance)
        while len(p.bornes) < count:
            while i < n and not lines[i].strip():
                i += 1
            if i >= n:
                raise DatError(f"Fin de fichier : « {titref} » annonce {count} bornes, {len(p.bornes)} lues.")
            p.bornes.append(_parse_borne(lines[i], i + 1))
            i += 1

        if titref in seen:
            warnings.append(f"Titref en double : {titref}")
        seen.add(titref)
        if count < 3:
            warnings.append(f"{titref} : {count} borne(s), polygone impossible (ignoré).")
        parcelles.append(p)

    if not parcelles:
        raise DatError("Aucun bloc trouvé : le fichier est vide ou mal structuré.")
    return ParseResult(parcelles, warnings, dict(stripped))
