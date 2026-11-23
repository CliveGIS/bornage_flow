# BornageFlow

Plugin QGIS (3.10 → 4.x, Qt5 et Qt6) qui regroupe le workflow de bornage dans une seule fenêtre à 7 étapes (Lambert Nord Maroc, EPSG:26191).

## Fonctionnalités

1. Import d'un fichier DAT/TXT → couches **Parcelles** (GeoPackage) et **Bornes** (CSV), avec détection et suppression du préfixe des titref.
2. Jointure « Bornage légible » depuis un Excel / ODS / CSV, avec application de votre style.
3. Jointure « État juridique » (concaténation des lignes multiples par `|`, suppression des doublons).
4. Choix des champs de l'étiquette.
5. Plan parcellaire DXF : lignes seules, suppression de layers, chevauchement avec les parcelles, champ `Consistance_DXF`.
6. Groupe `DETAILS_BORNAGE` : couches Polygones, Lignes, Points (champ `Name`) avec styles.
7. Groupe `BASEMAPS` : Google Satellite Hybrid, Bing VirtualEarth, Esri Satellite.

> Les fonds de carte appartiennent à Google, Microsoft et Esri : vérifiez leurs conditions d'utilisation.

## Installation

- **Depuis QGIS** : *Extensions → Installer/Gérer les extensions* → rechercher « BornageFlow ».
- **Manuelle** : télécharger le `.zip` de la dernière [release](../../releases), puis *Extensions → Installer depuis un ZIP*.

## Structure du dépôt

```
bornage_flow/        # le plugin (dossier à zipper)
scripts/package.sh   # génère bornage_flow-<version>.zip
.github/workflows/   # release automatique sur tag vX.Y.Z
```

## Licence

GNU GPL v2 ou ultérieure — voir [LICENSE](LICENSE).
