# -*- coding: utf-8 -*-
"""Étape 5 : plan parcellaire DXF (lignes seules), suppression de layers, chevauchements."""
import os
from collections import Counter

from qgis.core import (
    QgsCoordinateTransform, QgsFeature, QgsGeometry, QgsProject,
    QgsSpatialIndex, QgsVectorLayer,
)

from .compat import NULL
from .constants import CRS, DXF_NAME, F_DXF
from .joiner import JoinError, _check, _ensure_fields, _write
from .layers import LayerError, write_gpkg

NO_LAYER = "(sans layer)"


class DxfImport(object):
    def __init__(self, layer, gpkg_path, n_lines, n_ignored):
        self.layer = layer
        self.gpkg_path = gpkg_path
        self.n_lines = n_lines
        self.n_ignored = n_ignored      # points, textes, surfaces… non conservés


class ConsRecap(object):
    def __init__(self):
        self.n_parcelles = 0
        self.with_dxf = 0
        self.without_dxf = 0
        self.by_layer = {}              # layer -> nombre de parcelles concernées


def _is_line(geom):
    """Ligne ? Test par dimension (0 point, 1 ligne, 2 surface) : identique de QGIS 3.10 à 4.x,
    sans dépendre de QgsWkbTypes / Qgis.GeometryType dont l'API a changé."""
    try:
        return geom.constGet().dimension() == 1
    except Exception:
        return False


def _name(v):
    return NO_LAYER if v is None or v == NULL or not str(v).strip() else str(v).strip()


def format_consistance(counts):
    """{'PUITS': 3, 'SENTIER': 4} -> '3 PUITS + 4 SENTIER' (ordre alphabétique)."""
    return " + ".join(f"{n} {name}" for name, n in sorted(counts.items(), key=lambda kv: kv[0].casefold()))


def layer_field(layer):
    for f in layer.fields():
        if f.name().lower() == "layer":
            return f.name()
    raise LayerError("Le DXF ne contient pas de champ « Layer ».")


def _source_layer(path):
    """Couche « entities » du DXF (celle que QGIS affiche) via OGR."""
    names = []
    try:
        from osgeo import ogr
        ds = ogr.Open(path)
        if ds is not None:
            names = [ds.GetLayerByIndex(i).GetName() for i in range(ds.GetLayerCount())]
    except Exception:
        pass
    name = next((n for n in names if n.lower() == "entities"), names[0] if names else "entities")
    src = QgsVectorLayer(f"{path}|layername={name}", "dxf_source", "ogr")
    if not src.isValid():
        raise LayerError("DXF illisible : QGIS/GDAL n'a pas pu l'ouvrir.")
    return src


def import_lines(dxf_path):
    """Ne garde que les lignes du DXF (sans points), les copie dans <dxf>_lignes.gpkg (EPSG:26191)."""
    src = _source_layer(dxf_path)
    mem = QgsVectorLayer(f"MultiLineString?crs={CRS}", "lignes", "memory")
    pr = mem.dataProvider()
    pr.addAttributes(list(src.fields()))
    mem.updateFields()

    feats, ignored = [], 0
    for f in src.getFeatures():
        g = f.geometry()
        if g.isNull() or g.isEmpty() or not _is_line(g):
            ignored += 1
            continue
        g = QgsGeometry(g)
        try:
            if g.constGet().hasCurvedSegments():
                g = QgsGeometry(g.constGet().segmentize())
        except Exception:
            try:
                g.convertToStraightSegment()
            except Exception:
                pass
        try:
            g.get().dropZValue()
            g.get().dropMValue()
        except Exception:
            pass
        if not g.isMultipart():
            g.convertToMultiType()
        nf = QgsFeature(mem.fields())
        nf.setAttributes(f.attributes())
        nf.setGeometry(g)
        feats.append(nf)
    if not feats:
        raise LayerError("Aucune ligne trouvée dans ce DXF.")
    pr.addFeatures(feats)

    stem = os.path.splitext(os.path.basename(dxf_path))[0]
    gpkg = os.path.join(os.path.dirname(dxf_path), f"{stem}_lignes.gpkg")
    write_gpkg(mem, gpkg, "lignes")
    layer = QgsVectorLayer(f"{gpkg}|layername=lignes", DXF_NAME, "ogr")
    if not layer.isValid():
        raise LayerError("Le GeoPackage des lignes a été écrit mais n'a pas pu être chargé.")
    return DxfImport(layer, gpkg, len(feats), ignored)


def layer_counts(layer):
    """[(nom de layer, nombre d'entités)] sans doublon, triés par nom."""
    fld = layer_field(layer)
    c = Counter(_name(f[fld]) for f in layer.getFeatures())
    return sorted(c.items(), key=lambda kv: kv[0].casefold())


def delete_layers(layer, names):
    """Supprime toutes les entités dont le Layer est dans `names`. Retourne leur nombre."""
    if layer.isEditable():
        raise LayerError("La couche DXF est en mode édition : fermez l'édition avant de supprimer.")
    fld = layer_field(layer)
    targets = set(names)
    ids = [f.id() for f in layer.getFeatures() if _name(f[fld]) in targets]
    if ids and not layer.dataProvider().deleteFeatures(ids):
        raise LayerError("Suppression impossible (couche en lecture seule ?).")
    try:
        layer.dataProvider().reloadData()
    except Exception:
        pass
    layer.updateExtents()
    layer.triggerRepaint()
    return len(ids)


def compute_consistance(parcelles, dxf):
    """Compte, par parcelle et par Layer, les entités DXF qui l'intersectent -> champ Consistance_DXF."""
    _check(parcelles)
    fld = layer_field(dxf)
    (fidx,) = _ensure_fields(parcelles, [F_DXF])

    tr = None
    if dxf.crs().isValid() and parcelles.crs().isValid() and dxf.crs() != parcelles.crs():
        tr = QgsCoordinateTransform(dxf.crs(), parcelles.crs(), QgsProject.instance().transformContext())

    index, geoms = QgsSpatialIndex(), {}
    for f in dxf.getFeatures():
        g = f.geometry()
        if g.isNull() or g.isEmpty():
            continue
        if tr is not None:
            g = QgsGeometry(g)
            g.transform(tr)
        nf = QgsFeature(f.id())
        nf.setGeometry(g)
        index.addFeature(nf)
        geoms[f.id()] = (g, _name(f[fld]))

    rec, changes = ConsRecap(), {}
    for p in parcelles.getFeatures():
        rec.n_parcelles += 1
        pg, counts = p.geometry(), {}
        if not pg.isNull() and not pg.isEmpty():
            engine = QgsGeometry.createGeometryEngine(pg.constGet())
            engine.prepareGeometry()
            for fid in index.intersects(pg.boundingBox()):
                g, name = geoms[fid]
                if engine.intersects(g.constGet()):
                    counts[name] = counts.get(name, 0) + 1
        if counts:
            rec.with_dxf += 1
            for name in counts:
                rec.by_layer[name] = rec.by_layer.get(name, 0) + 1
        else:
            rec.without_dxf += 1
        changes[p.id()] = {fidx: format_consistance(counts) if counts else NULL}
    _write(parcelles, changes)
    return rec
