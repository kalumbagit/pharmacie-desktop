"""Charte graphique (bleu clair + rouge rosé) et petits composants d'interface réutilisables."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QLocale, Qt, QDate
from PySide6.QtGui import QBrush, QColor, QResizeEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QDateEdit,
)

# --- Palette ---------------------------------------------------------------
BLUE = "#3F9BE0"  # bleu clair : couleur principale
BLUE_DARK = "#2B7FC2"
BLUE_SOFT = "#D6EAF8"
BLUE_LIGHT = "#EEF6FD"
BG = "#F4F9FD"
ROSE = "#E8627A"  # rouge rosé : accent, actions sensibles, erreurs
ROSE_DARK = "#C8435D"
ROSE_LIGHT = "#FDE8EC"
TEXT = "#22313F"
MUTED = "#6C7F90"
BORDER = "#C8DDEE"


def stylesheet() -> str:
    return f"""
    QWidget {{ color: {TEXT}; font-size: 14px; }}
    QMainWindow {{ background: {BG}; }}
    QWidget#content {{ background: {BG}; }}

    QFrame#sidebar {{ background: {BLUE_SOFT}; border-right: 1px solid {BORDER}; }}
    QScrollArea#pagescroll {{ background: transparent; border: none; }}
    QScrollArea#pagescroll > QWidget > QWidget {{ background: transparent; }}
    QFrame#card {{ background: white; border: 1px solid {BORDER}; border-radius: 12px; }}

    QLabel#title {{ font-size: 22px; font-weight: 700; color: {BLUE_DARK}; }}
    QLabel#appname {{ font-size: 20px; font-weight: 800; color: {BLUE_DARK}; }}
    QLabel#muted {{ color: {MUTED}; }}
    QLabel#error {{ color: {ROSE_DARK}; font-weight: 600; }}

    QPushButton {{
        background: {BLUE}; color: white; border: none; border-radius: 6px;
        padding: 8px 16px; font-weight: 600;
    }}
    QPushButton:hover {{ background: {BLUE_DARK}; }}
    QPushButton:disabled {{ background: {BORDER}; color: {MUTED}; }}
    QPushButton[variant="secondary"] {{
        background: white; color: {BLUE_DARK}; border: 1px solid {BLUE};
    }}
    QPushButton[variant="secondary"]:hover {{ background: {BLUE_LIGHT}; }}
    QPushButton[variant="secondary"]:disabled {{
        background: white; color: {MUTED}; border: 1px solid {BORDER};
    }}
    QPushButton[variant="danger"] {{ background: {ROSE}; color: white; }}
    QPushButton[variant="danger"]:hover {{ background: {ROSE_DARK}; }}

    QPushButton[nav="item"] {{
        background: transparent; color: {TEXT}; text-align: left;
        padding: 10px 14px; border-radius: 8px; font-weight: 500;
    }}
    QPushButton[nav="item"]:hover {{ background: {BLUE_LIGHT}; }}
    QPushButton[nav="item"]:checked {{ background: {BLUE}; color: white; font-weight: 700; }}
    QPushButton[nav="logout"] {{
        background: transparent; color: {ROSE_DARK}; text-align: left;
        padding: 10px 14px; border-radius: 8px; font-weight: 600;
    }}
    QPushButton[nav="logout"]:hover {{ background: {ROSE_LIGHT}; }}

    QLineEdit, QComboBox, QSpinBox {{
        background: white; border: 1px solid {BORDER}; border-radius: 6px;
        padding: 7px 10px; selection-background-color: {BLUE};
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 1px solid {BLUE}; }}
    QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{
        background: {BLUE_LIGHT}; color: {MUTED};
    }}
    QComboBox::drop-down {{ border: none; width: 24px; }}
    QComboBox QAbstractItemView {{
        background: white; selection-background-color: {BLUE_SOFT}; selection-color: {TEXT};
    }}
    QSpinBox::up-button, QSpinBox::down-button {{ width: 0px; border: none; }}
    /* Le champ interne des QSpinBox / QComboBox éditables ne doit pas hériter du cadre. */
    QSpinBox QLineEdit, QComboBox QLineEdit {{
        border: none; padding: 0; background: transparent;
    }}
    QCheckBox {{ spacing: 8px; }}

    QTableWidget {{
        background: white; alternate-background-color: {BLUE_LIGHT};
        border: 1px solid {BORDER}; border-radius: 8px; gridline-color: {BLUE_SOFT};
        selection-background-color: {BLUE_SOFT}; selection-color: {TEXT};
    }}
    QHeaderView::section {{
        background: {BLUE_SOFT}; color: {TEXT}; border: none;
        border-bottom: 2px solid {BLUE}; padding: 8px; font-weight: 700;
    }}

    QScrollBar:vertical {{ background: transparent; width: 12px; margin: 0; }}
    QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 0; }}
    QScrollBar::handle {{
        background: {BORDER}; border-radius: 5px; min-height: 30px; min-width: 30px;
    }}
    QScrollBar::handle:hover {{ background: {BLUE}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0px; height: 0px; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}


    QFrame#kpi {{
        background: white;
        border: 1px solid {BORDER};
        border-radius: 10px;
    }}

    QFrame#kpi[alert="yes"] {{
        background: {ROSE_LIGHT};
        border: 1px solid {ROSE};
    }}

    QFrame#panel {{
        background: white;
        border: 1px solid {BORDER};
        border-radius: 10px;
    }}

    QLabel#kpiLabel {{
        color: {MUTED};
        font-weight: 600;
    }}

    QLabel#kpiValue {{
        font-size: 24px;
        font-weight: 800;
        color: {BLUE_DARK};
    }}

    QLabel#kpiValue[alert="yes"] {{
        color: {ROSE_DARK};
    }}

    QLabel#kpiHint {{
        color: {MUTED};
        font-size: 12px;
    }}
    
    QLabel#sectionTitle {{
        font-size: 15px;
        font-weight: 700;
        color: {TEXT};
    }}

    QLabel#bigTotal {{
        font-size: 30px;
        font-weight: 800;
        color: {BLUE_DARK};
    }}

    QLabel#bigChange {{
        font-size: 24px;
        font-weight: 800;
        color: {ROSE_DARK};
    }}

    QScrollArea#pagescroll {{
        background: transparent;
    }}


    QMessageBox {{ background: white; }}
    QMessageBox QPushButton {{ min-width: 80px; }}
    """


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setStyleSheet(stylesheet())


# --- Composants ---------------------------------------------------------------
def make_button(text: str, variant: str = "primary") -> QPushButton:
    """variant : « primary » (bleu), « secondary » (contour) ou « danger » (rouge rosé)."""
    button = QPushButton(text)
    button.setProperty("variant", variant)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def make_label(text: str, kind: str = "") -> QLabel:
    """kind : « title », « muted » ou « error »."""
    label = QLabel(text)
    if kind:
        label.setObjectName(kind)
    label.setWordWrap(True)
    return label


def make_spin(maximum: int = 100_000_000, minimum: int = 0, suffix: str = "") -> QSpinBox:
    """Champ numérique entier (montants en FCFA, quantités), milliers séparés à la française.
    Les flèches sont masquées en QSS : `NoButtons` écrase la zone de texte avec une feuille
    de style."""
    spin = QSpinBox()
    spin.setRange(minimum, maximum)
    spin.setSuffix(suffix)
    spin.setGroupSeparatorShown(True)
    spin.setLocale(QLocale(QLocale.Language.French, QLocale.Country.Cameroon))
    spin.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    return spin

def make_date_edit(today: bool = True) -> QDateEdit:
    """Champ de saisie de date au format français (JJ/MM/AAAA), avec calendrier."""
    date_edit = QDateEdit()

    date_edit.setDisplayFormat("dd/MM/yyyy")
    date_edit.setCalendarPopup(True)

    if today:
        date_edit.setDate(QDate.currentDate())

    date_edit.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    return date_edit

class DataTable(QTableWidget):
    """Tableau en lecture seule qui remplit toujours la largeur disponible.

    Pourquoi une classe dédiée : `resizeColumnsToContents()` fixe des largeurs en pixels et
    `setStretchLastSection(True)` ne les rattrape PAS s'il est déjà actif (Qt ignore un
    réglage identique). Résultat : le tableau se rétrécit au contenu à chaque rechargement.
    Ici, la largeur est calculée explicitement : contenu d'abord, puis l'espace restant est
    donné à `stretch_column`. Si le contenu dépasse la fenêtre, un défilement horizontal
    apparaît, sans aucun texte tronqué.
    """

    def __init__(self, columns: Sequence[str], stretch_column: int | None = None) -> None:
        super().__init__(0, len(columns))
        self.setHorizontalHeaderLabels(list(columns))
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        header = self.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._stretch_column = stretch_column
        self._content_widths: list[int] = []

    def set_stretch_column(self, column: int | None) -> None:
        self._stretch_column = column

    def fit(self) -> None:
        """À appeler après chaque remplissage : mesure le contenu puis répartit l'espace."""
        self.resizeColumnsToContents()
        self._content_widths = [self.columnWidth(c) for c in range(self.columnCount())]
        self._distribute()

    def _distribute(self) -> None:
        count = self.columnCount()
        if not count or len(self._content_widths) != count:
            return
        widths = list(self._content_widths)
        extra = self.viewport().width() - sum(widths)
        if extra > 0:
            target = self._stretch_column if self._stretch_column is not None else count - 1
            widths[min(max(target, 0), count - 1)] += extra
        for column, width in enumerate(widths):
            if self.columnWidth(column) != width:
                self.setColumnWidth(column, width)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 (nom imposé par Qt)
        super().resizeEvent(event)
        self._distribute()  # fenêtre agrandie, réduite ou affichée pour la première fois


def make_table(columns: Sequence[str], stretch_column: int | None = None) -> DataTable:
    """Tableau en lecture seule, une ligne sélectionnable à la fois.
    `stretch_column` : colonne qui absorbe l'espace libre (par défaut la dernière)."""
    return DataTable(columns, stretch_column)


def fit_columns(table: QTableWidget, stretch_column: int | None = None) -> None:
    """Ajuste les colonnes après un remplissage (voir DataTable)."""
    if not isinstance(table, DataTable):
        raise TypeError("fit_columns attend un tableau créé par make_table().")
    if stretch_column is not None:
        table.set_stretch_column(stretch_column)
    table.fit()



def fill_row(
    table: QTableWidget,
    row: int,
    cells: Sequence[str],
    *,
    foreground: str | None = None,
    background: str | None = None,
    right: Sequence[int] = (),
) -> None:
    """Remplit une ligne.
    
    `foreground` : couleur du texte.
    `background` : couleur de fond des cellules.
    `right` : colonnes alignées à droite (montants, quantités).
    """
    for column, text in enumerate(cells):
        item = QTableWidgetItem(text)

        if foreground:
            item.setForeground(QBrush(QColor(foreground)))

        if background:
            item.setBackground(QBrush(QColor(background)))

        if column in right:
            item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )

        table.setItem(row, column, item)


def selected_index(table: QTableWidget) -> int | None:
    """Index de la ligne sélectionnée, ou None."""
    rows = table.selectionModel().selectedRows()
    return rows[0].row() if rows else None


def password_edit() -> QLineEdit:
    field = QLineEdit()
    field.setEchoMode(QLineEdit.EchoMode.Password)
    return field


class CardPage(QWidget):
    """Page centrée avec une carte blanche : connexion, formulaires, messages."""

    def __init__(self, title: str, subtitle: str = "", width: int = 460) -> None:
        super().__init__()
        page = QVBoxLayout(self)
        page.setContentsMargins(0, 0, 0, 0)
        # Défilement vertical : les longs formulaires restent utilisables sur petit écran.
        scroll = QScrollArea()
        scroll.setObjectName("pagescroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        page.addWidget(scroll)
        inner = QWidget()
        scroll.setWidget(inner)
        outer = QVBoxLayout(inner)
        outer.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)

        self.card = QFrame()
        self.card.setObjectName("card")
        self.card.setFixedWidth(width)
        self.body = QVBoxLayout(self.card)
        self.body.setContentsMargins(28, 28, 28, 28)
        self.body.setSpacing(12)

        row.addWidget(self.card)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(2)

        self.body.addWidget(make_label(title, "title"))
        if subtitle:
            self.body.addWidget(make_label(subtitle, "muted"))
        self.form = QFormLayout()
        self.form.setSpacing(10)
        self.body.addLayout(self.form)
        self.error = make_label("", "error")
        self.body.addWidget(self.error)

    def set_error(self, message: str) -> None:
        self.error.setText(message)

    def add_buttons(self, *buttons: QPushButton) -> None:
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addStretch(1)
        for button in buttons:
            row.addWidget(button)
        self.body.addLayout(row)

