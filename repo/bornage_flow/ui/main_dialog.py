# -*- coding: utf-8 -*-
import os

from qgis.core import QgsCoordinateTransform, QgsProject, QgsVectorLayer
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QScrollArea, QTabWidget, QVBoxLayout, QWidget,
)

from ..core import basemaps as basemaps_core
from ..core import details as details_core
from ..core import dxf as dxf_core
from ..core import joiner, layers, styles
from ..core.compat import enum as _enum
from ..core.constants import DXF_NAME, F_LEGIBLE, F_TITREF
from ..core.dat_parser import parse_dat, parse_prefixes, scan_prefixes
from ..core.tables import TableError, list_sheets, read_table


def _q(scope, name):
    return _enum(Qt, scope, name)


CHECKED = _q("CheckState", "Checked")
UNCHECKED = _q("CheckState", "Unchecked")
USER_CHECKABLE = _q("ItemFlag", "ItemIsUserCheckable")
WAIT_CURSOR = _q("CursorShape", "WaitCursor")
USER_ROLE = _q("ItemDataRole", "UserRole")
NO_FRAME = _enum(QFrame, "Shape", "NoFrame")

# Couleurs tirées de la palette QGIS (clair ou sombre) : jamais de blanc/noir codé en dur.
QSS = """
QLabel#title { font-size: 17px; font-weight: 700; color: #14B8A6; }
QLabel#hint { font-size: 11px; }
QTabWidget::pane { border: 1px solid palette(mid); border-radius: 6px; top: -1px; }
QTabBar::tab { padding: 6px 10px; border: none; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { border-bottom: 2px solid #14B8A6; }
QLineEdit, QComboBox, QListWidget {
    border: 1px solid palette(mid); border-radius: 5px; padding: 4px 6px;
    background: palette(base); color: palette(text); }
QComboBox QAbstractItemView {
    background: palette(base); color: palette(text);
    selection-background-color: palette(highlight); selection-color: palette(highlighted-text); }
QListWidget::item { padding: 2px; }
QPushButton { border: 1px solid palette(mid); border-radius: 5px; padding: 5px 12px;
    background: palette(button); color: palette(button-text); }
QPushButton:hover { border-color: #14B8A6; }
QPushButton#primary { background: #0F766E; color: #FFFFFF; border: none; font-weight: 700; padding: 7px 16px; }
QPushButton#primary:hover { background: #0D9488; }
QPushButton#link { border: none; background: transparent; color: #14B8A6; padding: 2px 6px; }
"""


def _card(label, kind, html):
    c = {"ok": "#16A34A", "warn": "#D97706", "err": "#DC2626"}[kind]
    label.setStyleSheet(
        f"QLabel {{ background: palette(base); color: palette(text); border: 1px solid palette(mid); "
        f"border-left: 4px solid {c}; border-radius: 5px; padding: 8px; }}")
    label.setText(html)
    label.setVisible(True)


def _scroll(widget):
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(NO_FRAME)
    sa.setWidget(widget)
    return sa


def _new_card():
    l = QLabel()
    l.setWordWrap(True)
    l.setVisible(False)
    l.setTextInteractionFlags(_q("TextInteractionFlag", "TextSelectableByMouse"))
    return l


def _hint(text):
    l = QLabel(text)
    l.setObjectName("hint")
    l.setWordWrap(True)
    return l


class TablePicker(QWidget):
    """Fichier tableur + feuille + colonne d'identifiant."""
    loaded = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._table = None
        self._path = ""
        self.path_edit = QLineEdit()
        self.path_edit.setReadOnly(True)
        self.path_edit.setPlaceholderText("Fichier Excel (.xlsx, .xls, .ods) ou CSV — 1re ligne = noms de colonnes")
        browse = QPushButton("Parcourir…")
        browse.clicked.connect(self._browse)
        self.sheet = QComboBox()
        self.idcol = QComboBox()
        self.sheet.currentIndexChanged.connect(self._load_sheet)

        g = QGridLayout(self)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(6)
        g.addWidget(QLabel("Fichier"), 0, 0)
        g.addWidget(self.path_edit, 0, 1)
        g.addWidget(browse, 0, 2)
        g.addWidget(QLabel("Feuille"), 1, 0)
        g.addWidget(self.sheet, 1, 1, 1, 2)
        g.addWidget(QLabel("Colonne ID"), 2, 0)
        g.addWidget(self.idcol, 2, 1, 1, 2)
        g.setColumnStretch(1, 1)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choisir un tableur", "",
            "Tableurs (*.xlsx *.xlsm *.xls *.ods *.csv *.txt *.tsv);;Tous les fichiers (*)")
        if not path:
            return
        try:
            sheets = list_sheets(path)
        except TableError as e:
            self.window()._warn(str(e))
            return
        self._path = path
        self.path_edit.setText(path)
        self.sheet.blockSignals(True)
        self.sheet.clear()
        self.sheet.addItems(sheets)
        self.sheet.blockSignals(False)
        self._load_sheet()

    def _load_sheet(self):
        if not self._path:
            return
        try:
            self._table = read_table(self._path, self.sheet.currentText())
        except Exception as e:
            self._table = None
            self.window()._warn(f"Lecture impossible : {e}")
            return
        self.idcol.blockSignals(True)
        self.idcol.clear()
        self.idcol.addItems(self._table.fields)
        guess = next((i for i, f in enumerate(self._table.fields)
                      if f.strip().lower() in ("titref", "titre", "titre_foncier", "id", "num", "numero", "n°")), 0)
        self.idcol.setCurrentIndex(guess)
        self.idcol.blockSignals(False)
        self.loaded.emit()

    def table(self):
        return self._table

    def id_index(self):
        return self.idcol.currentIndex()


class BornageFlowDialog(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self._parcelles_id = None
        self._dxf_id = None
        self._out_dir = ""          # dossier de travail (celui du DAT / du DXF)
        self.setWindowTitle("BornageFlow")
        self.resize(720, 560)
        self.setMinimumSize(640, 420)
        self.setStyleSheet(QSS)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        head = QHBoxLayout()
        t = QLabel("BornageFlow")
        t.setObjectName("title")
        s = QLabel("DAT → Parcelles & Bornes → jointures → DXF → détails → fonds")
        s.setObjectName("hint")
        head.addWidget(t)
        head.addWidget(s)
        head.addStretch(1)
        root.addLayout(head)

        self.tabs = QTabWidget()
        self.tabs.addTab(_scroll(self._tab_import()), "1 · Import DAT")
        self.tabs.addTab(_scroll(self._tab_legible()), "2 · Bornage légible")
        self.tabs.addTab(_scroll(self._tab_juridique()), "3 · État juridique")
        self.tabs.addTab(_scroll(self._tab_etiquette()), "4 · Étiquette")
        self.tabs.addTab(_scroll(self._tab_dxf()), "5 · DXF")
        self.tabs.addTab(_scroll(self._tab_details()), "6 · Détails")
        self.tabs.addTab(_scroll(self._tab_basemaps()), "7 · Fonds")
        bar = self.tabs.tabBar()
        # Gras via la police du widget et non via le QSS : en Qt5 (QGIS 3.x) un « font-weight » QSS rend le texte
        # plus large que l'onglet calculé avec la police normale, d'où le texte rogné.
        font = bar.font()
        font.setBold(True)
        bar.setFont(font)
        bar.setElideMode(_q("TextElideMode", "ElideNone"))
        bar.setUsesScrollButtons(True)                          # flèches si la fenêtre est trop étroite
        bar.setExpanding(False)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self.tabs, 1)

    def _on_tab_changed(self, i):
        if i == 3:
            self._refresh_label_fields()
        elif i == 5 and not self.det_dir.text().strip():
            self.det_dir.setText(self._default_details_dir())

    def _zoom_to(self, layer):
        """Zoom sur la couche, en convertissant l'emprise vers le CRS du canvas (ex. fonds en EPSG:3857)."""
        canvas = self.iface.mapCanvas()
        ext = layer.extent()
        dest = canvas.mapSettings().destinationCrs()
        if dest.isValid() and layer.crs().isValid() and dest != layer.crs():
            try:
                tr = QgsCoordinateTransform(layer.crs(), dest, QgsProject.instance().transformContext())
                ext = tr.transformBoundingBox(ext)
            except Exception:
                pass
        canvas.setExtent(ext)
        canvas.refresh()

    def _warn(self, msg):
        QMessageBox.warning(self, "BornageFlow", msg)

    def _work_layer(self):
        """Couche Parcelles : celle de l'étape 1, sinon une couche du projet ayant le champ titref."""
        prj = QgsProject.instance()
        if self._parcelles_id:
            l = prj.mapLayer(self._parcelles_id)
            if l is not None and l.isValid():
                return l
        cands = [l for l in prj.mapLayers().values()
                 if isinstance(l, QgsVectorLayer) and l.isValid() and l.fields().indexOf(F_TITREF) >= 0]
        cands.sort(key=lambda l: l.name() != "Parcelles")
        return cands[0] if cands else None

    NO_LAYER = ("Aucune couche Parcelles trouvée.<br>Importez d'abord un fichier DAT (étape 1), "
                "ou chargez une couche contenant le champ « titref ».")

    # ------------------------------------------------------------ onglet 1
    def _tab_import(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)
        v.addWidget(_hint("Choisissez le fichier DAT/TXT : il est lu automatiquement puis converti en "
                          "Parcelles (GeoPackage, EPSG:26191) et Bornes (CSV), enregistrés dans son dossier."))
        row = QHBoxLayout()
        row.addWidget(QLabel("Fichier DAT"))
        self.dat_edit = QLineEdit()
        self.dat_edit.setReadOnly(True)
        self.dat_edit.setPlaceholderText("Fichier .dat / .txt")
        b1 = QPushButton("Parcourir…")
        b1.clicked.connect(self._browse_dat)
        row.addWidget(self.dat_edit, 1)
        row.addWidget(b1)
        v.addLayout(row)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Préfixe à supprimer"))
        self.prefix_edit = QLineEdit()
        self.prefix_edit.setPlaceholderText("ex. P, Plle — détecté automatiquement, modifiable (vide = aucun)")
        row2.addWidget(self.prefix_edit, 1)
        v.addLayout(row2)
        self.prefix_info = _hint("Le titref doit être un numéro seul (774). Un préfixe comme P774 ou Plle774 "
                                 "est détecté à l'ouverture du fichier puis retiré à l'import.")
        v.addWidget(self.prefix_info)
        go = QPushButton("Importer et convertir")
        go.setObjectName("primary")
        go.clicked.connect(self._run_import)
        v.addWidget(go)
        self.card1 = _new_card()
        v.addWidget(self.card1)
        v.addStretch(1)
        return w

    def _browse_dat(self):
        path, _ = QFileDialog.getOpenFileName(self, "Fichier DAT/TXT", "",
                                              "DAT / TXT (*.dat *.DAT *.txt *.TXT);;Tous (*)")
        if path:
            self.dat_edit.setText(path)
            self._detect_prefix(path)

    def _detect_prefix(self, path):
        """Détection automatique du préfixe (P, Plle…) devant les numéros de titref."""
        try:
            found = scan_prefixes(path)
        except Exception:
            self.prefix_edit.clear()
            self.prefix_info.setText("Détection du préfixe impossible (le fichier sera contrôlé à l'import).")
            return
        if found:
            self.prefix_edit.setText(", ".join(p for p, _ in found))
            self.prefix_info.setText("Préfixe détecté : " + ", ".join(f"<b>{p}</b> ({n} titref)" for p, n in found)
                                     + ". Il sera supprimé à l'import ; corrigez ou videz le champ si besoin.")
        else:
            self.prefix_edit.clear()
            self.prefix_info.setText("Aucun préfixe détecté : les titref sont déjà des numéros seuls.")

    def _run_import(self):
        path = self.dat_edit.text().strip()
        if not os.path.isfile(path):
            _card(self.card1, "warn", "Choisissez d'abord un fichier DAT/TXT.")
            return
        out_dir = os.path.dirname(path)
        self._out_dir = out_dir
        if not os.access(out_dir, os.W_OK):
            _card(self.card1, "err", f"Le dossier du fichier DAT n'est pas accessible en écriture :<br>{out_dir}")
            return
        stem = os.path.splitext(os.path.basename(path))[0]
        QApplication.setOverrideCursor(WAIT_CURSOR)
        try:
            result = parse_dat(path, parse_prefixes(self.prefix_edit.text()))
            layers.prepare_project_crs()
            exp = layers.export(result, out_dir, stem)
            styles.apply_bornes_style(exp.bornes)
            layers.add_to_project(exp.parcelles)
            layers.add_to_project(exp.bornes, visible=False)   # Bornes décochée par défaut
            self._parcelles_id = exp.parcelles.id()
            self._zoom_to(exp.parcelles)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            _card(self.card1, "err", f"<b>Échec de l'import</b><br>{e}")
            return
        QApplication.restoreOverrideCursor()
        notes = list(result.warnings)
        pre = (f"<br>Préfixe supprimé : " + ", ".join(f"{p} ({n})" for p, n in result.stripped.items())
               if result.stripped else "")
        if exp.skipped:
            notes.append(f"{len(exp.skipped)} parcelle(s) sans polygone valide ignorée(s).")
        extra = "<br><span style='color:#D97706'>" + "<br>".join(notes[:8]) + "</span>" if notes else ""
        _card(self.card1, "ok",
              f"<b>Fichier importé avec succès</b><br>"
              f"<b>{exp.n_parcelles}</b> Parcelles + <b>{exp.n_bornes}</b> Bornes — fichiers prêts.<br>"
              f"<small>{os.path.basename(exp.gpkg_path)}<br>{os.path.basename(exp.csv_path)}<br>"
              f"Dossier : {out_dir}</small>{pre}{extra}")
        self.tabs.setCurrentIndex(1)

    # ------------------------------------------------------------ onglet 2
    def _tab_legible(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)
        v.addWidget(_hint("Liste Excel des parcelles éligibles au bornage. « Bornage_Legible » vaut OUI si le "
                          "titref existe dans l'Excel, sinon NULL. Votre style est ensuite appliqué."))
        self.pick2 = TablePicker()
        v.addWidget(self.pick2)
        go = QPushButton("Joindre")
        go.setObjectName("primary")
        go.clicked.connect(self._run_legible)
        v.addWidget(go)
        self.card2 = _new_card()
        v.addWidget(self.card2)
        v.addStretch(1)
        return w

    def _recap_html(self, rec, title):
        extra = ""
        if rec.multi:
            extra += f"<br>▸ <b>{rec.multi}</b> parcelle(s) avec plusieurs lignes (valeurs jointes par « | »)"
        if rec.deduped:
            extra += f"<br>▸ <b>{rec.deduped}</b> parcelle(s) avec valeurs répétées : doublons supprimés"
        ids = ""
        if rec.only_table_ids:
            more = " …" if rec.only_table > len(rec.only_table_ids) else ""
            ids = f"<br><small>Absents de Parcelles : {', '.join(rec.only_table_ids)}{more}</small>"
        return (f"<b>{rec.merged}</b> parcelle(s) {title}<br>"
                f"▸ <b>{rec.only_layer}</b> parcelle(s) dans Parcelles, absentes de l'Excel<br>"
                f"▸ <b>{rec.only_table}</b> parcelle(s) dans l'Excel, absentes de Parcelles{extra}{ids}")

    def _run_legible(self):
        t = self.pick2.table()
        if t is None:
            _card(self.card2, "warn", "Choisissez d'abord le fichier Excel.")
            return
        lyr = self._work_layer()
        if lyr is None:
            _card(self.card2, "warn", self.NO_LAYER)
            return
        try:
            rec = joiner.join_legible(lyr, t, self.pick2.id_index())
        except Exception as e:
            _card(self.card2, "err", f"<b>Échec de la jointure</b><br>{e}")
            return
        html = "<b>Jointure terminée</b><br>" + self._recap_html(rec, "fusionnée(s) avec succès")
        kind = "ok"
        try:
            styles.apply_parcelles_style(lyr)
            html += ("<br><small>Style appliqué. Les parcelles non éligibles sont masquées : cochez "
                     "« NOT LEGIBLE » dans la légende pour les afficher. Le décompte apparaît à côté de chaque règle.</small>")
        except Exception as e:
            kind = "warn"
            html += f"<br>Jointure faite, mais le style n'a pas pu être appliqué : {e}"
        _card(self.card2, kind, html)

    # ------------------------------------------------------------ onglet 3
    def _tab_juridique(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)
        v.addWidget(_hint("Jointure de l'état juridique sur le titref. Si un ID apparaît sur plusieurs lignes, "
                          "les valeurs distinctes de chaque champ sont concaténées avec « | » (les doublons sont supprimés)."))
        self.pick3 = TablePicker()
        self.pick3.loaded.connect(self._fill_fields)
        self.pick3.idcol.currentIndexChanged.connect(self._fill_fields)
        v.addWidget(self.pick3)

        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("Champs à joindre"))
        hdr.addStretch(1)
        for text, state in (("Tout", CHECKED), ("Aucun", UNCHECKED)):
            b = QPushButton(text)
            b.setObjectName("link")
            b.clicked.connect(lambda _=False, s=state: self._set_all(s))
            hdr.addWidget(b)
        v.addLayout(hdr)
        self.fields_list = QListWidget()
        self.fields_list.setMinimumHeight(110)
        v.addWidget(self.fields_list, 1)

        go = QPushButton("Joindre")
        go.setObjectName("primary")
        go.clicked.connect(self._run_juridique)
        v.addWidget(go)
        self.card3 = _new_card()
        v.addWidget(self.card3)
        return w

    def _fill_fields(self):
        t = self.pick3.table()
        self.fields_list.clear()
        if t is None:
            return
        idi = self.pick3.id_index()
        for i, name in enumerate(t.fields):
            if i == idi:
                continue
            it = QListWidgetItem(name)
            it.setData(USER_ROLE, i)
            it.setFlags(it.flags() | USER_CHECKABLE)
            it.setCheckState(CHECKED)
            self.fields_list.addItem(it)

    def _set_all(self, state):
        for i in range(self.fields_list.count()):
            self.fields_list.item(i).setCheckState(state)

    def _run_juridique(self):
        t = self.pick3.table()
        if t is None:
            _card(self.card3, "warn", "Choisissez d'abord le fichier Excel.")
            return
        lyr = self._work_layer()
        if lyr is None:
            _card(self.card3, "warn", self.NO_LAYER)
            return
        cols = [self.fields_list.item(i).data(USER_ROLE)
                for i in range(self.fields_list.count())
                if self.fields_list.item(i).checkState() == CHECKED]
        try:
            rec = joiner.join_etat_juridique(lyr, t, self.pick3.id_index(), cols)
        except Exception as e:
            _card(self.card3, "err", f"<b>Échec de la jointure</b><br>{e}")
            return
        html = (f"<b>Jointure terminée</b> — {len(rec.added_fields)} champ(s) ajouté(s)<br>"
                + self._recap_html(rec, "fusionnée(s) avec succès"))
        html += "<br><small>Étape suivante : choisissez les champs de l'étiquette (onglet 4).</small>"
        _card(self.card3, "ok", html)
        self._refresh_label_fields()

    # ------------------------------------------------------------ onglet 4
    LABEL_ROWS = (("id", "ID parcelle", False), ("nom", "Nom requérant", True),
                  ("prenom", "Prénom requérant", True), ("parcelle", "Nom parcelle", True),
                  ("dxf", "Consistance DXF", True))

    def _tab_etiquette(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)
        v.addWidget(_hint("Choisissez les champs exacts de la couche Parcelles à afficher dans l'étiquette "
                          "(leur nom varie selon l'Excel). Affichage, un champ par ligne : ID, Prénom, Nom, "
                          "Nom parcelle, Consistance DXF (si renseignée) ; l'observation s'ajoute en rouge "
                          "quand elle existe."))
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(6)
        self.lbl_combos = {}
        for r, (key, text, optional) in enumerate(self.LABEL_ROWS):
            g.addWidget(QLabel(text), r, 0)
            cb = QComboBox()
            self.lbl_combos[key] = cb
            g.addWidget(cb, r, 1)
        g.setColumnStretch(1, 1)
        v.addLayout(g)
        go = QPushButton("Appliquer l'étiquette")
        go.setObjectName("primary")
        go.clicked.connect(self._run_label)
        v.addWidget(go)
        self.card4 = _new_card()
        v.addWidget(self.card4)
        v.addStretch(1)
        self._refresh_label_fields()
        return w

    def _refresh_label_fields(self):
        """Remplit les listes avec les champs actuels de Parcelles (garde le choix mémorisé)."""
        lyr = self._work_layer()
        names = [f.name() for f in lyr.fields() if f.name().lower() != "fid"] if lyr is not None else []
        lm = styles.get_label_map(lyr) if lyr is not None else {}
        for key, text, optional in self.LABEL_ROWS:
            cb = self.lbl_combos[key]
            cb.blockSignals(True)
            cb.clear()
            if optional:
                cb.addItem("— aucun —", "")
            for n in names:
                cb.addItem(n, n)
            idx = cb.findData(lm.get(key, ""))
            cb.setCurrentIndex(idx if idx >= 0 else 0)
            cb.blockSignals(False)

    def _run_label(self):
        lyr = self._work_layer()
        if lyr is None:
            _card(self.card4, "warn", self.NO_LAYER)
            return
        if lyr.fields().indexOf(F_LEGIBLE) < 0:
            _card(self.card4, "warn", "Faites d'abord l'étape 2 : le style de bornage s'appuie sur "
                                      "le champ « Bornage_Legible ».")
            return
        lm = {k: (cb.itemData(cb.currentIndex()) or "") for k, cb in self.lbl_combos.items()}
        if not lm.get("id"):
            _card(self.card4, "warn", "Choisissez le champ ID parcelle.")
            return
        try:
            used = styles.apply_parcelles_style(lyr, lm)
        except Exception as e:
            _card(self.card4, "err", f"<b>Échec de l'étiquette</b><br>{e}")
            return
        _card(self.card4, "ok", "<b>Étiquette appliquée</b><br>" + " + ".join(used))

    # ------------------------------------------------------------ onglet 5
    def _tab_dxf(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)
        v.addWidget(_hint("Plan parcellaire DXF : seules les lignes sont conservées (points ignorés), dans un "
                          "GeoPackage à côté du DXF (le DXF d'origine n'est jamais modifié). Supprimez ensuite les "
                          "layers inutiles, puis détectez les entités qui chevauchent chaque parcelle."))
        row = QHBoxLayout()
        row.addWidget(QLabel("Fichier DXF"))
        self.dxf_edit = QLineEdit()
        self.dxf_edit.setReadOnly(True)
        self.dxf_edit.setPlaceholderText("Plan parcellaire .dxf")
        b = QPushButton("Parcourir…")
        b.clicked.connect(self._browse_dxf)
        row.addWidget(self.dxf_edit, 1)
        row.addWidget(b)
        v.addLayout(row)
        go = QPushButton("Importer les lignes")
        go.setObjectName("primary")
        go.clicked.connect(self._run_dxf_import)
        v.addWidget(go)
        self.card5a = _new_card()
        v.addWidget(self.card5a)

        v.addWidget(QLabel("<b>Layers à supprimer</b>"))
        self.dxf_list = QListWidget()
        self.dxf_list.setMinimumHeight(100)
        v.addWidget(self.dxf_list, 1)
        bd = QPushButton("Supprimer les layers cochés")
        bd.clicked.connect(self._run_dxf_delete)
        v.addWidget(bd)
        self.card5b = _new_card()
        v.addWidget(self.card5b)

        v.addWidget(QLabel("<b>Chevauchement avec les parcelles</b>"))
        gi = QPushButton("Détecter les entités par parcelle")
        gi.setObjectName("primary")
        gi.clicked.connect(self._run_dxf_intersect)
        v.addWidget(gi)
        self.card5c = _new_card()
        v.addWidget(self.card5c)
        return w

    def _dxf_layer(self):
        prj = QgsProject.instance()
        if self._dxf_id:
            l = prj.mapLayer(self._dxf_id)
            if l is not None and l.isValid():
                return l
        for l in prj.mapLayersByName(DXF_NAME):
            if isinstance(l, QgsVectorLayer) and l.isValid():
                return l
        return None

    NO_DXF = "Importez d'abord les lignes du DXF (bouton « Importer les lignes »)."

    def _browse_dxf(self):
        path, _ = QFileDialog.getOpenFileName(self, "Plan parcellaire DXF", "", "DXF (*.dxf *.DXF);;Tous (*)")
        if path:
            self.dxf_edit.setText(path)

    def _fill_dxf_layers(self, layer):
        self.dxf_list.clear()
        for name, n in dxf_core.layer_counts(layer):
            it = QListWidgetItem(f"{name}   ·   {n} entité(s)")
            it.setData(USER_ROLE, name)
            it.setFlags(it.flags() | USER_CHECKABLE)
            # PLLE = mêmes parcelles que le DAT : pré-coché
            it.setCheckState(CHECKED if name.strip().upper() == "PLLE" else UNCHECKED)
            self.dxf_list.addItem(it)

    def _run_dxf_import(self):
        path = self.dxf_edit.text().strip()
        if not os.path.isfile(path):
            _card(self.card5a, "warn", "Choisissez d'abord un fichier DXF.")
            return
        if not os.access(os.path.dirname(path), os.W_OK):
            _card(self.card5a, "err", "Le dossier du DXF n'est pas accessible en écriture.")
            return
        self._out_dir = self._out_dir or os.path.dirname(path)
        QApplication.setOverrideCursor(WAIT_CURSOR)
        try:
            res = dxf_core.import_lines(path)
            styles.apply_dxf_style(res.layer)
            layers.add_to_project(res.layer, bottom=True)
            self._dxf_id = res.layer.id()
            self._fill_dxf_layers(res.layer)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            _card(self.card5a, "err", f"<b>Échec de l'import DXF</b><br>{e}")
            return
        QApplication.restoreOverrideCursor()
        _card(self.card5a, "ok",
              f"<b>{res.n_lines}</b> ligne(s) importée(s) — <b>{res.n_ignored}</b> autre(s) entité(s) "
              f"(points, textes…) ignorée(s).<br><small>{os.path.basename(res.gpkg_path)}</small>")

    def _run_dxf_delete(self):
        lyr = self._dxf_layer()
        if lyr is None:
            _card(self.card5b, "warn", self.NO_DXF)
            return
        names = [self.dxf_list.item(i).data(USER_ROLE) for i in range(self.dxf_list.count())
                 if self.dxf_list.item(i).checkState() == CHECKED]
        if not names:
            _card(self.card5b, "warn", "Cochez au moins un layer à supprimer.")
            return
        try:
            n = dxf_core.delete_layers(lyr, names)
            self._fill_dxf_layers(lyr)
            styles.apply_dxf_style(lyr)
        except Exception as e:
            _card(self.card5b, "err", f"<b>Échec de la suppression</b><br>{e}")
            return
        _card(self.card5b, "ok", f"<b>{n}</b> entité(s) supprimée(s) : {', '.join(names)}.")

    def _run_dxf_intersect(self):
        lyr, dxf = self._work_layer(), self._dxf_layer()
        if lyr is None:
            _card(self.card5c, "warn", self.NO_LAYER)
            return
        if dxf is None:
            _card(self.card5c, "warn", self.NO_DXF)
            return
        QApplication.setOverrideCursor(WAIT_CURSOR)
        try:
            rec = dxf_core.compute_consistance(lyr, dxf)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            _card(self.card5c, "err", f"<b>Échec de la détection</b><br>{e}")
            return
        QApplication.restoreOverrideCursor()
        html = (f"<b>{rec.with_dxf}</b> parcelle(s) avec entités DXF (champ « Consistance DXF » renseigné)<br>"
                f"▸ <b>{rec.without_dxf}</b> parcelle(s) sans aucune entité")
        if rec.by_layer:
            top = sorted(rec.by_layer.items(), key=lambda kv: -kv[1])[:10]
            html += "<br><small>Parcelles concernées par layer : " + ", ".join(f"{k} ({n})" for k, n in top) + "</small>"
        kind = "ok"
        if lyr.fields().indexOf(F_LEGIBLE) >= 0:
            try:
                styles.apply_parcelles_style(lyr)      # ajoute la ligne « Consistance DXF » à l'étiquette
                html += "<br><small>Étiquette mise à jour : la consistance DXF s'affiche sous le nom.</small>"
            except Exception as e:
                kind = "warn"
                html += f"<br>Champ rempli, mais l'étiquette n'a pas pu être mise à jour : {e}"
        else:
            html += "<br><small>Faites l'étape 2 pour que l'étiquette affiche la consistance DXF.</small>"
        self._refresh_label_fields()
        _card(self.card5c, kind, html)

    # ------------------------------------------------------------ onglet 6
    def _default_details_dir(self):
        if self._out_dir and os.path.isdir(self._out_dir):
            return self._out_dir
        home = QgsProject.instance().homePath()
        return home if home and os.path.isdir(home) else ""

    def _tab_details(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)
        v.addWidget(_hint("Pendant le bornage, de nouveaux détails peuvent apparaître sur le terrain. Cette étape crée "
                          "le groupe « DETAILS_BORNAGE » avec 3 couches vides (Polygones, Lignes, Points), chacune avec "
                          "un seul champ « Name » (affiché en étiquette), dans un même GeoPackage. Votre style préféré "
                          "est appliqué à chaque couche."))
        row = QHBoxLayout()
        row.addWidget(QLabel("Dossier du GeoPackage"))
        self.det_dir = QLineEdit()
        self.det_dir.setPlaceholderText("Dossier où enregistrer DETAILS_BORNAGE.gpkg")
        b = QPushButton("Parcourir…")
        b.clicked.connect(self._browse_details)
        row.addWidget(self.det_dir, 1)
        row.addWidget(b)
        v.addLayout(row)
        v.addWidget(_hint("Si DETAILS_BORNAGE.gpkg existe déjà dans ce dossier, il n'est jamais écrasé : "
                          "les détails déjà saisis sont conservés et rechargés."))
        go = QPushButton("Créer le groupe DETAILS_BORNAGE")
        go.setObjectName("primary")
        go.clicked.connect(self._run_details)
        v.addWidget(go)
        self.card6 = _new_card()
        v.addWidget(self.card6)
        v.addStretch(1)
        return w

    def _browse_details(self):
        start = self.det_dir.text().strip() or self._default_details_dir()
        path = QFileDialog.getExistingDirectory(self, "Dossier du GeoPackage DETAILS_BORNAGE", start)
        if path:
            self.det_dir.setText(path)

    def _run_details(self):
        folder = self.det_dir.text().strip() or self._default_details_dir()
        self.det_dir.setText(folder)
        QApplication.setOverrideCursor(WAIT_CURSOR)
        try:
            res = details_core.setup(folder)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            _card(self.card6, "err", f"<b>Échec de la création du groupe</b><br>{e}")
            return
        QApplication.restoreOverrideCursor()
        rows = "<br>".join(f"▸ <b>{k}</b> : {res.counts[k]} entité(s)" for k in details_core.KINDS)
        head = "Groupe créé" if res.created else "Groupe rechargé (GeoPackage existant conservé)"
        notes = "<br><span style='color:#D97706'>" + "<br>".join(res.warnings) + "</span>" if res.warnings else ""
        _card(self.card6, "warn" if res.warnings else "ok",
              f"<b>{head}</b> — DETAILS_BORNAGE<br>{rows}<br>"
              f"<small>{os.path.basename(res.gpkg_path)}<br>Dossier : {os.path.dirname(res.gpkg_path)}<br>"
              "Pour ajouter un détail : sélectionnez la couche, activez l'édition (crayon), dessinez l'objet puis "
              f"renseignez « Name ».</small>{notes}")

    # ------------------------------------------------------------ onglet 7
    def _tab_basemaps(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)
        v.addWidget(_hint("Ajoute le groupe « BASEMAPS » avec 3 fonds de carte en ligne, placé tout en bas de la "
                          "légende pour que vos couches restent au-dessus : Google Satellite Hybrid (affiché), "
                          "Bing VirtualEarth et Esri Satellite (décochés : cochez-les pour changer de fond). "
                          "Une connexion Internet est nécessaire."))
        go = QPushButton("Ajouter les fonds de carte")
        go.setObjectName("primary")
        go.clicked.connect(self._run_basemaps)
        v.addWidget(go)
        self.card7 = _new_card()
        v.addWidget(self.card7)
        v.addStretch(1)
        return w

    def _run_basemaps(self):
        try:
            res = basemaps_core.add_basemaps()
        except Exception as e:
            _card(self.card7, "err", f"<b>Échec</b><br>{e}")
            return
        html = ("<b>Groupe BASEMAPS ajouté</b> (en bas de la légende)<br>"
                + "<br>".join(f"▸ {n}" + (" — <b>affiché</b>" if n == basemaps_core.BASEMAPS[0][0] else " — décoché")
                              for n in res.added))
        if res.failed:
            html += "<br><span style='color:#D97706'>Non chargé : " + ", ".join(res.failed) + "</span>"
        _card(self.card7, "warn" if res.failed else "ok", html)
