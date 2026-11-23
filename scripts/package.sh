#!/usr/bin/env bash
# Génère le ZIP à uploader sur plugins.qgis.org (dossier racine = bornage_flow/)
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION=$(grep -E '^version=' bornage_flow/metadata.txt | cut -d= -f2 | tr -d '\r ')
find bornage_flow -name '__pycache__' -type d -prune -exec rm -rf {} +
rm -f "bornage_flow-${VERSION}.zip"
zip -r "bornage_flow-${VERSION}.zip" bornage_flow -x '*.pyc' '*/__pycache__/*' '*.DS_Store'
echo "OK -> bornage_flow-${VERSION}.zip"
