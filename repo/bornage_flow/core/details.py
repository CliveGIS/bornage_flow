# -*- coding: utf-8 -*-
"""Étape 6 : groupe DETAILS_BORNAGE = 3 couches (Polygones, Lignes, Points) à un seul champ « Name ».

Les 3 couches sont dans un même GeoPackage. Un GeoPackage existant n'est JAMAIS écrasé :
les détails déjà saisis sont conservés et simplement rechargés.
"""
import os

from qgis.core import QgsProject, QgsVectorLayer

from . import layers, styles
from .constants import CRS, DETAILS_GPKG, DETAILS_GROUP, F_NAME
from .layers import LayerError

KINDS = ("Polygones", "Lignes", "Points")     # ordre de création : Points finit au-dessus


class DetailsResult(object):
    def __init__(self, gpkg_path, layers_, created, counts, warnings):
        self.gpkg_path = gpkg_path
        self.layers = layers_            # {nom: QgsVectorLayer}
        self.created = created           # True = GeoPackage neuf, False = existant réutilisé
        self.counts = counts             # {nom: nombre d'entités}
        self.warnings = warnings


def gpkg_path(folder):
    return os.path.join(folder, DETAILS_GPKG)


def _existing_tables(path):
    from osgeo import ogr
    ds = ogr.Open(path)
    if ds is None:
        raise LayerError(f"« {os.path.basename(path)} » existe mais n'est pas un GeoPackage lisible.")
    names = [ds.GetLayerByIndex(i).GetName() for i in range(ds.GetLayerCount())]
    ds = None
    return names


def _create_tables(path, missing):
    """Crée dans le GeoPackage (neuf ou existant) les tables manquantes, avec le seul champ « Name »."""
    from osgeo import ogr, osr
    geom = {"Polygones": ogr.wkbPolygon, "Lignes": ogr.wkbLineString, "Points": ogr.wkbPoint}
    srs = osr.SpatialReference()
    if srs.ImportFromEPSG(int(CRS.split(":")[1])) != 0:
        raise LayerError(f"Système de coordonnées {CRS} introuvable dans cette installation.")
    if hasattr(srs, "SetAxisMappingStrategy"):                       # GDAL 3+ : ordre X/Y traditionnel
        srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    if os.path.exists(path):
        ds = ogr.Open(path, 1)
    else:
        ds = ogr.GetDriverByName("GPKG").CreateDataSource(path)
    if ds is None:
        raise LayerError("Impossible d'écrire le GeoPackage (dossier protégé ou fichier verrouillé ?).")
    for name in missing:
        lyr = ds.CreateLayer(name, srs, geom[name], ["GEOMETRY_NAME=geom"])
        if lyr is None:
            ds = None
            raise LayerError(f"Création de la couche « {name} » impossible.")
        lyr.CreateField(ogr.FieldDefn(F_NAME, ogr.OFTString))
    ds.FlushCache()
    ds = None                                                        # referme et libère le fichier


def _release_project_layers():
    """Retire du projet les couches déjà présentes dans le groupe (leurs données restent dans le GPKG)."""
    prj = QgsProject.instance()
    grp = prj.layerTreeRoot().findGroup(DETAILS_GROUP)
    if grp is None:
        return
    nodes = [n for n in grp.findLayers() if n.layer() is not None]
    for n in nodes:
        if n.layer().isEditable():
            raise LayerError(f"La couche « {n.layer().name()} » est en cours d'édition : "
                             "enregistrez et fermez l'édition avant de recharger le groupe.")
    for n in nodes:
        prj.removeMapLayer(n.layerId())


def setup(folder):
    """Crée (ou recharge) le groupe DETAILS_BORNAGE dans le projet. Retourne un DetailsResult."""
    if not folder or not os.path.isdir(folder):
        raise LayerError("Choisissez d'abord un dossier valide pour le GeoPackage.")
    if not os.access(folder, os.W_OK):
        raise LayerError(f"Le dossier n'est pas accessible en écriture :<br>{folder}")
    path = gpkg_path(folder)

    _release_project_layers()
    existed = os.path.exists(path)
    missing = [k for k in KINDS if not existed or k not in _existing_tables(path)]
    if missing:
        _create_tables(path, missing)

    layers.prepare_project_crs()
    loaded, counts, warnings = {}, {}, []
    for kind in KINDS:
        lyr = QgsVectorLayer(f"{path}|layername={kind}", kind, "ogr")
        if not lyr.isValid():
            raise LayerError(f"La couche « {kind} » n'a pas pu être chargée depuis le GeoPackage.")
        if lyr.fields().indexOf(F_NAME) < 0:
            warnings.append(f"« {kind} » n'a pas de champ « {F_NAME} » : étiquette inactive.")
        try:
            styles.apply_details_style(lyr, kind)
        except Exception as e:
            warnings.append(f"Style « {kind} » non appliqué : {e}")
        layers.add_to_project(lyr, group=DETAILS_GROUP)
        loaded[kind] = lyr
        counts[kind] = lyr.featureCount()
    return DetailsResult(path, loaded, not existed, counts, warnings)
