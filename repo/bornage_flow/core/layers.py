# -*- coding: utf-8 -*-
"""Création des couches Parcelles (GPKG) et Bornes (CSV), formulaire et projet."""
import csv
import os
from qgis.core import (
    QgsCoordinateReferenceSystem, QgsDefaultValue, QgsEditorWidgetSetup,
    QgsFeature, QgsField, QgsFillSymbol, QgsGeometry, QgsPalLayerSettings,
    QgsPointXY, QgsProject, QgsSingleSymbolRenderer, QgsTextBufferSettings,
    QgsTextFormat, QgsVectorFileWriter, QgsVectorLayer, QgsVectorLayerSimpleLabeling,
)
from qgis.PyQt.QtCore import QUrl

from .compat import NULL, STRING
from .constants import (BASEMAPS_GROUP, CRS, DEFAULT_STATUT, F_DXF, F_OBS, F_STATUT, F_TITREF,
                        GROUP, STATUTS)


class LayerError(Exception):
    pass


class ExportResult(object):
    def __init__(self, gpkg_path, csv_path, parcelles, bornes, n_parcelles, n_bornes, skipped):
        self.gpkg_path = gpkg_path
        self.csv_path = csv_path
        self.parcelles = parcelles
        self.bornes = bornes
        self.n_parcelles = n_parcelles
        self.n_bornes = n_bornes
        self.skipped = skipped


def _polygon(parcelle):
    pts = []
    for b in parcelle.bornes:
        pt = QgsPointXY(b.x, b.y)
        if not pts or pt != pts[-1]:
            pts.append(pt)
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts.pop()
    if len(pts) < 3:
        return None
    return QgsGeometry.fromPolygonXY([pts + [pts[0]]])


def _remove_gpkg(path):
    for suffix in ("", "-wal", "-shm"):
        p = path + suffix
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                raise LayerError(f"Impossible de remplacer « {os.path.basename(path)} » : "
                                 "retirez d'abord la couche existante du projet.")


def _writer_ok(code):
    """Code retour de QgsVectorFileWriter : 0 / NoError, quelle que soit la version (enum scopé ou non)."""
    for get in (lambda: QgsVectorFileWriter.WriterError.NoError, lambda: QgsVectorFileWriter.NoError):
        try:
            return code == get()
        except AttributeError:
            continue
    try:
        return int(code) == 0
    except (TypeError, ValueError):
        return getattr(code, "value", 1) == 0


def write_gpkg(layer, path, layer_name):
    """Écrit une couche (mémoire) dans un GeoPackage neuf."""
    _remove_gpkg(path)
    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName = "GPKG"
    opts.fileEncoding = "UTF-8"
    opts.layerName = layer_name
    ctx = QgsProject.instance().transformContext()
    # V3 : QGIS >= 3.20 · V2 : 3.10 -> 3.x · l'ancienne API n'existe plus en QGIS 4
    writer = (getattr(QgsVectorFileWriter, "writeAsVectorFormatV3", None)
              or getattr(QgsVectorFileWriter, "writeAsVectorFormatV2", None))
    if writer is not None:
        res = writer(layer, path, ctx, opts)
    else:
        res = QgsVectorFileWriter.writeAsVectorFormat(layer, path, opts)
    if not _writer_ok(res[0]):
        raise LayerError(f"Écriture GeoPackage échouée : {res[1] if len(res) > 1 else res[0]}")


def export(result, out_dir, stem):
    gpkg = os.path.join(out_dir, f"{stem}_parcelles.gpkg")
    csv_path = os.path.join(out_dir, f"{stem}_bornes.csv")

    mem = QgsVectorLayer(f"Polygon?crs={CRS}", "parcelles", "memory")
    pr = mem.dataProvider()
    pr.addAttributes([QgsField(F_TITREF, STRING), QgsField(F_DXF, STRING),
                      QgsField(F_STATUT, STRING), QgsField(F_OBS, STRING)])
    mem.updateFields()
    feats, skipped = [], []
    for p in result.parcelles:
        geom = _polygon(p)
        if geom is None:
            skipped.append(p.titref)
            continue
        f = QgsFeature(mem.fields())
        f.setGeometry(geom)
        f.setAttributes([p.titref, NULL, DEFAULT_STATUT, NULL])
        feats.append(f)
    pr.addFeatures(feats)

    write_gpkg(mem, gpkg, "parcelles")

    seen, rows = set(), []
    for p in result.parcelles:
        for b in p.bornes:
            key = (b.name, b.xs, b.ys)
            if key not in seen:
                seen.add(key)
                rows.append((b.name, b.xs, b.ys))
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["name", "x", "y"])
        w.writerows(rows)

    parcelles = QgsVectorLayer(f"{gpkg}|layername=parcelles", "Parcelles", "ogr")
    uri = QUrl.fromLocalFile(csv_path).toString() + f"?delimiter=,&xField=x&yField=y&crs={CRS}&detectTypes=no"
    bornes = QgsVectorLayer(uri, "Bornes", "delimitedtext")
    if not parcelles.isValid() or not bornes.isValid():
        raise LayerError("Les fichiers ont été écrits mais n'ont pas pu être chargés dans QGIS.")

    style_neutral(parcelles)   # le style de bornage s'applique après l'étape 2
    setup_form(parcelles)
    persist_style(parcelles)
    return ExportResult(gpkg, csv_path, parcelles, bornes, len(feats), len(rows), skipped)


# ------------------------------------------------------------------ formulaire / style de base
def style_neutral(layer):
    """Style provisoire (étape 1) : le champ Bornage_Legible n'existe pas encore."""
    from qgis.PyQt.QtGui import QColor
    sym = QgsFillSymbol.createSimple({"color": "15,118,110,45", "outline_color": "#0F766E", "outline_width": "0.5"})
    layer.setRenderer(QgsSingleSymbolRenderer(sym))
    s = QgsPalLayerSettings()
    s.fieldName = F_TITREF
    fmt = QgsTextFormat()
    fmt.setSize(8)
    fmt.setColor(QColor("#1E293B"))
    buf = QgsTextBufferSettings()
    buf.setEnabled(True)
    buf.setSize(0.8)
    fmt.setBuffer(buf)
    s.setFormat(fmt)
    layer.setLabeling(QgsVectorLayerSimpleLabeling(s))
    layer.setLabelsEnabled(True)


def hide_fid(layer):
    """Masque la clé primaire « fid » du GeoPackage (table attributaire + formulaires).

    Un GeoPackage exige cette clé : elle ne peut pas être supprimée, seulement cachée."""
    try:
        fields = layer.fields()
        names = {f.name() for f in fields if f.name().lower() == "fid"}
        try:
            for i in layer.dataProvider().pkAttributeIndexes():
                names.add(fields.at(i).name())
        except Exception:
            pass
        if not names:
            return
        for n in names:
            idx = fields.indexOf(n)
            if idx >= 0:
                layer.setEditorWidgetSetup(idx, QgsEditorWidgetSetup("Hidden", {}))
        cfg = layer.attributeTableConfig()
        cfg.update(fields)
        cols = cfg.columns()
        for c in cols:
            if c.name in names:
                c.hidden = True
        cfg.setColumns(cols)
        layer.setAttributeTableConfig(cfg)
    except Exception:       # purement esthétique : ne doit jamais bloquer le workflow
        pass


def setup_form(layer):
    """Liste de valeurs, valeur par défaut et alias (idempotent)."""
    idx = layer.fields().indexOf(F_STATUT)
    if idx >= 0:
        layer.setEditorWidgetSetup(idx, QgsEditorWidgetSetup("ValueMap", {"map": [{s: s} for s in STATUTS]}))
        layer.setDefaultValueDefinition(idx, QgsDefaultValue(f"'{DEFAULT_STATUT}'"))
        layer.setFieldAlias(idx, "Statut Bornage")
    i2 = layer.fields().indexOf(F_OBS)
    if i2 >= 0:
        layer.setFieldAlias(i2, "Observation Bornage")
    i3 = layer.fields().indexOf("Bornage_Legible")
    if i3 >= 0:
        layer.setFieldAlias(i3, "Bornage Légible")
    i4 = layer.fields().indexOf(F_DXF)
    if i4 >= 0:
        layer.setFieldAlias(i4, "Consistance DXF")
    hide_fid(layer)


def persist_style(layer):
    """Enregistre style + formulaire dans le GPKG (réouverture hors projet)."""
    try:
        layer.saveStyleToDatabase("BornageFlow", "Style BornageFlow", True, "")
    except Exception:        # non bloquant : le style reste dans le projet
        pass


# ------------------------------------------------------------------ projet
def add_to_project(layer, visible=True, bottom=False, group=GROUP):
    prj = QgsProject.instance()
    root = prj.layerTreeRoot()
    grp = root.findGroup(group) or root.insertGroup(0, group)
    for node in list(grp.findLayers()):
        if node.layer() and node.layer().name() == layer.name():
            prj.removeMapLayer(node.layerId())
    prj.addMapLayer(layer, False)
    node = grp.addLayer(layer) if bottom else grp.insertLayer(0, layer)
    if node is not None:
        node.setItemVisibilityChecked(visible)


def enable_feature_count(layer):
    """Affiche le décompte des entités à côté de chaque règle dans le panneau des couches."""
    node = QgsProject.instance().layerTreeRoot().findLayer(layer.id())
    if node is not None:
        node.setCustomProperty("showFeatureCount", 0)   # bascule : force le recalcul
        node.setCustomProperty("showFeatureCount", 1)


def prepare_project_crs():
    """EPSG:26191 si le projet est vide ou ne contient que les fonds de carte (qui l'auraient mis en 3857)."""
    prj = QgsProject.instance()
    root = prj.layerTreeRoot()
    base = root.findGroup(BASEMAPS_GROUP)
    base_ids = {n.layerId() for n in base.findLayers()} if base is not None else set()
    if not (set(prj.mapLayers()) - base_ids):
        prj.setCrs(QgsCoordinateReferenceSystem(CRS))
