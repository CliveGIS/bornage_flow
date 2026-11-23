# -*- coding: utf-8 -*-
"""Étape 7 : groupe BASEMAPS (fonds de carte XYZ), toujours placé tout en bas de la légende."""
from urllib.parse import quote

from qgis.core import QgsBilinearRasterResampler, QgsProject, QgsRasterLayer

from .constants import BASEMAPS_GROUP

# (nom, URL du service, zoom min, zoom max, coché ?)
# zoom max = dernier niveau où le fournisseur a réellement des tuiles. Au-delà, QGIS continue d'afficher
# le dernier niveau agrandi (sur-zoom) : le fond ne disparaît jamais. Monter ce nombre n'ajoute pas de détail
# là où l'imagerie n'existe pas : le fond y devient vide (Google) ou affiche une tuile « indisponible » (Bing, Esri).
BASEMAPS = (
    ("Google Satellite Hybrid", "https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}", 0, 20, True),
    ("Bing VirtualEarth", "http://ecn.t3.tiles.virtualearth.net/tiles/a{q}.jpeg?g=1", 1, 19, False),
    ("Esri Satellite",
     "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
     0, 17, False),    # 17 = niveau couvert presque partout ; au-delà Esri renvoie « Map data not yet available »
)


class BasemapResult(object):
    def __init__(self, added, failed):
        self.added = added      # noms ajoutés
        self.failed = failed    # noms non chargés


def _uri(url, zmin, zmax):
    return f"type=xyz&url={quote(url, safe=':/')}&zmax={zmax}&zmin={zmin}"


def _make_zoomable(lyr):
    """Aucune limite d'échelle + sur-zoom lissé (bilinéaire) au lieu de gros pixels carrés."""
    try:
        lyr.setScaleBasedVisibility(False)
    except Exception:
        pass
    try:
        rf = lyr.resampleFilter()
        if rf is not None:
            rf.setZoomedInResampler(QgsBilinearRasterResampler())
            rf.setZoomedOutResampler(QgsBilinearRasterResampler())
    except Exception:       # esthétique seulement
        pass


def _fresh_group_at_bottom():
    """Vide l'ancien groupe BASEMAPS (s'il existe) puis le recrée tout en bas : au-dessus, tout le reste."""
    prj = QgsProject.instance()
    root = prj.layerTreeRoot()
    old = root.findGroup(BASEMAPS_GROUP)
    if old is not None:
        for n in list(old.findLayers()):
            prj.removeMapLayer(n.layerId())
        root.removeChildNode(old)
    grp = root.addGroup(BASEMAPS_GROUP)          # addGroup ajoute en dernière position
    grp.setExpanded(True)
    return grp


def add_basemaps():
    prj = QgsProject.instance()
    grp = _fresh_group_at_bottom()
    added, failed = [], []
    for name, url, zmin, zmax, visible in BASEMAPS:
        lyr = QgsRasterLayer(_uri(url, zmin, zmax), name, "wms")
        if not lyr.isValid():
            failed.append(name)
            continue
        _make_zoomable(lyr)
        prj.addMapLayer(lyr, False)
        node = grp.addLayer(lyr)                 # ajout à la suite : Google reste en haut du groupe
        if node is not None:
            node.setItemVisibilityChecked(visible)
        added.append(name)
    if not added:
        root = prj.layerTreeRoot()
        root.removeChildNode(grp)
        from .layers import LayerError
        raise LayerError("Aucun fond de carte n'a pu être créé (QGIS sans le fournisseur de tuiles XYZ ?).")
    return BasemapResult(added, failed)
