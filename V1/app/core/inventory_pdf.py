"""Export PDF de la fiche d'inventaire général (ReportLab), format A4 paysage.

Module pur : aucune dépendance à Qt ni à la base de données. Il reçoit une
`InventorySheet` (voir app/services/inventory.py) et, facultativement, les quantités
comptées (stock physique) et les observations saisies à l'écran, indexées par `lot_id`.

Modes :
  * fiche remplie : stock physique et écart renseignés à partir de `physiques` ;
  * fiche vierge (`blank_count=True`) : ces deux colonnes restent vides pour un comptage
    à la main. La fiche est complétée par des lignes vides jusqu'à `min_rows` lignes.

Le logo (`logo_path`) est posé en filigrane sur chaque page, derrière le tableau ; s'il est
absent ou illisible, la fiche est produite sans filigrane.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from app.core.watermark import draw_watermark
from app.services.inventory import InventoryRow, InventorySheet

GREEN_DARK = colors.HexColor("#1B5E40")
GREEN_HEADER = colors.HexColor("#DDEAE2")
ZEBRA = colors.HexColor("#F6F9F7")
# Version translucide pour les lignes alternées : le filigrane reste visible au travers.
ZEBRA_GLASS = colors.Color(0.965, 0.976, 0.969, alpha=0.5)
GRID = colors.HexColor("#4A4A4A")
RED = colors.HexColor("#B3261E")

PAGE = landscape(A4)
MARGIN_X = 24  # marges réduites : tableau plus large
TOP_BLOCK = 118  # hauteur réservée au titre et aux lignes d'information
BOTTOM_BLOCK = 44  # hauteur réservée au pied de page

HEADERS = [
    "N°", "Code", "Désignation du produit / matériel", "Unité", "Stock initial",
    "Entrées", "Sorties", "Stock théorique", "Stock physique", "Écart",
    "Date de péremption", "Observations",
]
# Largeur utile : 841,89 - 2 x 24 = 793,9 pt (total ci-dessous = 793 pt).
COL_WIDTHS = [26, 76, 166, 46, 52, 48, 48, 56, 56, 40, 70, 109]

_CELL = ParagraphStyle("cell", fontName="Helvetica", fontSize=8, leading=10)
_HEAD = ParagraphStyle(
    "head", fontName="Helvetica-Bold", fontSize=7.5, leading=9, alignment=TA_CENTER,
    textColor=colors.HexColor("#1F2A24"),
)


def _fmt_date(value: str) -> str:
    year, month, day = value.split("-")
    return f"{day}/{month}/{year}"


def _p(text: str, style: ParagraphStyle = _CELL) -> Paragraph:
    return Paragraph(escape(text), style)


class _NumberedCanvas(canvas.Canvas):
    """Canevas en deux passes pour afficher « Page x / y » et le pied de page."""

    footer_text = ""

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self._saved: list[dict] = []

    def showPage(self) -> None:  # noqa: N802 (nom imposé par ReportLab)
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            self._draw_footer(total)
            super().showPage()
        super().save()

    def _draw_footer(self, total: int) -> None:
        width, _ = PAGE
        self.setFont("Helvetica-Bold", 8)
        self.setFillColor(colors.black)
        self.drawString(MARGIN_X, 30, "Contrôle :")
        self.setFont("Helvetica", 8)
        self.drawString(
            MARGIN_X + 42, 30,
            "Stock théorique = Stock initial + Entrées - Sorties.  "
            "Écart : Stock physique - Stock théorique.",
        )
        self.setFillColor(colors.HexColor("#555555"))
        self.drawRightString(width - MARGIN_X, 30, f"Page {self._pageNumber} / {total}")


def _draw_header(sheet: InventorySheet, generated: datetime, logo_path: Path | None = None):
    def draw(c: canvas.Canvas, _doc: BaseDocTemplate) -> None:
        width, height = PAGE
        # Filigrane en premier : titre, tableau et pied de page sont dessinés par-dessus.
        draw_watermark(c, width, height, logo_path, page_ratio=0.60, opacity=0.12)
        c.saveState()
        c.setFillColor(GREEN_DARK)
        c.setFont("Times-Bold", 20)
        c.drawCentredString(width / 2, height - 46, sheet.organisation.upper())
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 12)
        c.drawCentredString(width / 2, height - 64, "FICHE D’INVENTAIRE GÉNÉRAL")
        c.setFont("Helvetica", 8.5)
        c.drawString(
            MARGIN_X, height - 86,
            f"Service : {sheet.service}      Catégorie : {sheet.categorie}      "
            f"Période : du {sheet.date_debut:%d/%m/%Y} au {sheet.date_fin:%d/%m/%Y}",
        )
        c.drawString(
            MARGIN_X, height - 102,
            f"Édité le {generated:%d/%m/%Y à %H:%M}      "
            f"Magasin / Salle : ______________________      "
            f"Responsable : {sheet.responsable}",
        )
        c.restoreState()

    return draw


def _build_table(
    rows: list[InventoryRow],
    physiques: Mapping[int, int | None],
    observations: Mapping[int, str],
    blank_count: bool,
    min_rows: int,
) -> Table:
    data: list[list[object]] = [[_p(h, _HEAD) for h in HEADERS]]
    red_cells: list[tuple[int, int]] = []

    for index, row in enumerate(rows, start=1):
        physique = None if blank_count else physiques.get(row.lot_id)
        ecart = None if physique is None else physique - row.stock_theorique
        if ecart is not None and ecart < 0:
            red_cells.append((9, index))
        data.append(
            [
                str(index), _p(row.code), _p(row.designation), row.unite,
                str(row.stock_initial), str(row.entrees), str(row.sorties),
                str(row.stock_theorique),
                "" if physique is None else str(physique),
                "" if ecart is None else f"{ecart:+d}" if ecart else "0",
                _fmt_date(row.date_peremption),
                _p("" if blank_count else observations.get(row.lot_id, "")),
            ]
        )

    # Fiche à remplir à la main : lignes vides numérotées jusqu'au minimum.
    for index in range(len(rows) + 1, max(min_rows, len(rows)) + 1):
        data.append([str(index)] + [""] * (len(HEADERS) - 1))

    table = Table(data, colWidths=COL_WIDTHS, repeatRows=1)
    style = [
        ("GRID", (0, 0), (-1, -1), 0.5, GRID),
        ("BACKGROUND", (0, 0), (-1, 0), GREEN_HEADER),
        ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
        ("VALIGN", (0, 1), (-1, -1), "MIDDLE"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("ALIGN", (0, 1), (1, -1), "LEFT"),
        ("ALIGN", (3, 1), (3, -1), "CENTER"),
        ("ALIGN", (4, 1), (9, -1), "RIGHT"),
        ("ALIGN", (10, 1), (10, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        # None = ligne transparente (le filigrane se voit) ; l'autre est translucide.
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [None, ZEBRA_GLASS]),
    ]
    for column, line in red_cells:
        style.append(("TEXTCOLOR", (column, line), (column, line), RED))
    table.setStyle(TableStyle(style))
    return table


def _signatures() -> KeepTogether:
    line = "__________________________"
    style = ParagraphStyle("sig", fontName="Helvetica", fontSize=8.5, leading=14)
    return KeepTogether(
        [
            Spacer(1, 14),
            Paragraph(f"Inventaire réalisé par : {line}&nbsp;&nbsp;&nbsp;&nbsp;"
                      f"Vérifié par : {line}&nbsp;&nbsp;&nbsp;&nbsp;"
                      "Date : ____ / ____ / ______", style),
            Paragraph(f"Signature du responsable : {line}____________", style),
        ]
    )


def export_inventory_pdf(
    sheet: InventorySheet,
    path: str | Path,
    physiques: Mapping[int, int | None] | None = None,
    observations: Mapping[int, str] | None = None,
    blank_count: bool = False,
    min_rows: int = 16,
    generated: datetime | None = None,
    logo_path: str | Path | None = None,
) -> Path:
    """Écrit la fiche d'inventaire en PDF et retourne le chemin du fichier."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    generated = generated or datetime.now()

    doc = BaseDocTemplate(
        str(target),
        pagesize=PAGE,
        leftMargin=MARGIN_X, rightMargin=MARGIN_X,
        topMargin=TOP_BLOCK, bottomMargin=BOTTOM_BLOCK,
        title=f"Fiche d'inventaire - {sheet.organisation}",
        author=sheet.responsable,
    )
    width, height = PAGE
    frame = Frame(
        MARGIN_X, BOTTOM_BLOCK, width - 2 * MARGIN_X, height - TOP_BLOCK - BOTTOM_BLOCK,
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
    )
    doc.addPageTemplates(
        [
            PageTemplate(
                id="fiche",
                frames=[frame],
                onPage=_draw_header(sheet, generated, Path(logo_path) if logo_path else None),
            )
        ]
    )
    story = [
        _build_table(sheet.rows, physiques or {}, observations or {}, blank_count, min_rows),
        _signatures(),
    ]
    doc.build(story, canvasmaker=_NumberedCanvas)
    return target