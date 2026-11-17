"""Génération des PDF (ReportLab) : facture A4 et reçu de caisse (ticket 80 mm).

Fonctions pures : aucune lecture en base, tout est passé en paramètre.
Le logo (`logo_path`) est posé en filigrane, derrière le contenu ; s'il est absent ou
illisible, le document est produit sans filigrane.
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.pdfbase.pdfmetrics import stringWidth

from app.core.utils import format_date, format_fcfa, format_local
from app.core.watermark import draw_watermark, watermark_callbacks
from app.models import Payment, Sale, SaleLine

BLUE = colors.HexColor("#2B7FC2")
BLUE_SOFT = colors.HexColor("#D6EAF8")
# Version translucide pour les lignes de tableau : le filigrane reste visible au travers.
BLUE_SOFT_GLASS = colors.Color(0.839, 0.918, 0.973, alpha=0.55)
ROSE = colors.HexColor("#C8435D")
GREY = colors.HexColor("#6C7F90")


def _taxe_text(sale: Sale, libelle: str) -> str:
    pourcent = sale.taux_taxe_bp / 100
    return f"{libelle} ({pourcent:g} %)"


def _payment_rows(payments: list[Payment]) -> list[list[str]]:
    rows = []
    for p in payments:
        sign = "-" if p.type == "REMBOURSEMENT" else ""
        label = f"{p.method_libelle}" + (" (remboursement)" if sign else "")
        rows.append([
            format_local(p.date_paiement),
            label,
            f"{sign}{format_fcfa(p.montant)}",
        ])
    return rows


def build_invoice_pdf(
    path: Path,
    *,
    pharmacie: dict[str, str],
    numero_facture: str,
    emise_le: str,
    sale: Sale,
    lines: list[SaleLine],
    payments: list[Payment],
    client_nom: str | None,
    client_telephone: str | None,
    taxe_libelle: str,
    logo_path: Path | None = None,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)

    styles = getSampleStyleSheet()
    normal = ParagraphStyle(
        "n", parent=styles["Normal"], fontName="Helvetica", fontSize=9.5
    )
    muted = ParagraphStyle("m", parent=normal, textColor=GREY)
    right = ParagraphStyle("r", parent=normal, alignment=TA_RIGHT)
    big = ParagraphStyle(
        "b", parent=normal, fontName="Helvetica-Bold",
        fontSize=18, leading=22, textColor=BLUE,
    )
    title = ParagraphStyle(
        "t", parent=big, alignment=TA_RIGHT, fontSize=14, leading=18
    )

    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"Facture {numero_facture}",
    )
    story: list = []

    identite = [
        Paragraph(escape(pharmacie.get("nom") or "Pharmacie"), big)
    ]

    for key in ("adresse", "telephone", "mention"):
        if pharmacie.get(key):
            identite.append(Paragraph(escape(pharmacie[key]), muted))

    meta = [
        Paragraph(f"FACTURE N° {escape(numero_facture)}", title),
        Paragraph(f"Date : {format_local(emise_le)}", right),
        Paragraph(f"Vente N° {escape(sale.numero_vente)}", right),
        Paragraph(f"Vendeur : {escape(sale.user_nom)}", right),
    ]

    header = Table([[identite, meta]], colWidths=[82 * mm, 92 * mm])
    header.setStyle(
        TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")])
    )
    story += [header, Spacer(1, 6 * mm)]

    client_lines = [Paragraph("<b>Client</b>", normal)]
    client_lines.append(
        Paragraph(escape(client_nom or "Client comptoir"), normal)
    )

    if client_telephone:
        client_lines.append(Paragraph(escape(client_telephone), muted))

    story += [*client_lines, Spacer(1, 5 * mm)]

    if sale.is_cancelled:
        story += [
            Paragraph(
                f"<b>VENTE ANNULÉE</b> : {escape(sale.motif_annulation or '')}",
                ParagraphStyle(
                    "c", parent=normal, textColor=ROSE, fontSize=11
                ),
            ),
            Spacer(1, 4 * mm),
        ]

    data = [[
        "Désignation", "Lot", "Qté", "Prix unit.", "Remise", "Montant"
    ]]

    for line in lines:
        data.append([
            Paragraph(escape(line.product_nom), normal),
            line.numero_lot,
            f"{line.quantite} {line.unite}",
            format_fcfa(line.prix_unitaire),
            format_fcfa(line.remise) if line.remise else "",
            format_fcfa(line.montant_ligne),
        ])

    table = Table(
        data,
        repeatRows=1,
        colWidths=[
            62 * mm, 22 * mm, 22 * mm,
            26 * mm, 20 * mm, 22 * mm,
        ],
    )
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        # None = ligne transparente (le filigrane se voit) ; l'autre est translucide.
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [None, BLUE_SOFT_GLASS]),
        ("LINEBELOW", (0, -1), (-1, -1), 0.6, BLUE),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story += [table, Spacer(1, 5 * mm)]

    totals = [
        ["Montant brut", format_fcfa(sale.montant_brut)]
    ]

    if sale.remise_globale:
        totals.append([
            "Remise globale", f"-{format_fcfa(sale.remise_globale)}"
        ])

    if sale.taux_taxe_bp:
        totals.append([
            _taxe_text(sale, taxe_libelle), format_fcfa(sale.taxes)
        ])

    totals.append(["NET À PAYER", format_fcfa(sale.montant_net)])
    totals.append(["Payé", format_fcfa(sale.montant_paye)])

    if not sale.is_cancelled:
        totals.append(["Reste à payer", format_fcfa(sale.reste)])

    totals_table = Table(
        totals, colWidths=[110 * mm, 44 * mm], hAlign="RIGHT"
    )
    net_row = [
        i for i, row in enumerate(totals) if row[0] == "NET À PAYER"
    ][0]

    totals_table.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("FONTNAME", (0, net_row), (-1, net_row), "Helvetica-Bold"),
        ("BACKGROUND", (0, net_row), (-1, net_row), BLUE_SOFT_GLASS),
        (
            "TEXTCOLOR", (0, -1), (-1, -1),
            ROSE if (not sale.is_cancelled and sale.reste) else colors.black,
        ),
    ]))
    story += [totals_table, Spacer(1, 6 * mm)]

    if payments:
        story.append(Paragraph("<b>Paiements</b>", normal))

        pay_table = Table(
            [["Date", "Moyen", "Montant"], *_payment_rows(payments)],
            colWidths=[40 * mm, 80 * mm, 34 * mm],
            hAlign="LEFT",
        )
        pay_table.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, BLUE),
            ("ALIGN", (2, 0), (2, -1), "RIGHT"),
        ]))
        story.append(pay_table)

    story += [
        Spacer(1, 10 * mm),
        Paragraph("Merci de votre confiance.", muted),
    ]

    doc.build(story, **watermark_callbacks(logo_path))
    return path


def build_receipt_pdf(
    path: Path,
    *,
    pharmacie: dict[str, str],
    sale: Sale,
    lines: list[SaleLine],
    payments: list[Payment],
    taxe_libelle: str,
    monnaie: int = 0,
    logo_path: Path | None = None,
) -> Path:
    """Reçu simplifié (preuve de paiement) au format ticket 80 mm."""
    path.parent.mkdir(parents=True, exist_ok=True)

    width = 80 * mm
    row = 4.6 * mm

    n_rows = (
        12 + 3 * len(lines) + len(payments)
        + (1 if sale.remise_globale else 0)
    )
    n_rows += 1 if sale.taux_taxe_bp else 0
    n_rows += 2 if sale.is_cancelled else 0
    height = max(90 * mm, n_rows * row + 14 * mm)

    pdf = canvas.Canvas(str(path), pagesize=(width, height))
    pdf.setTitle(f"Reçu {sale.numero_vente}")
    # Filigrane en premier : tout le texte du ticket est dessiné par-dessus.
    draw_watermark(pdf, width, height, logo_path, page_ratio=0.80, opacity=0.12)

    margin = 5 * mm
    y = height - 8 * mm

    def center(
        text: str, font: str = "Helvetica", size: float = 8.5
    ) -> None:
        nonlocal y
        pdf.setFont(font, size)
        pdf.drawCentredString(width / 2, y, text)
        y -= row

    def left_right(
        left: str,
        right: str,
        font: str = "Helvetica",
        size: float = 8.5,
    ) -> None:
        nonlocal y
        pdf.setFont(font, size)
        pdf.drawString(margin, y, left)
        pdf.drawRightString(width - margin, y, right)
        y -= row

    def rule() -> None:
        nonlocal y
        pdf.setDash(1, 2)
        pdf.line(margin, y + row / 2, width - margin, y + row / 2)
        pdf.setDash()
        y -= row * 0.3

    center(pharmacie.get("nom") or "Pharmacie", "Helvetica-Bold", 11)

    for key in ("adresse", "telephone", "mention"):
        if pharmacie.get(key):
            center(pharmacie[key][:44], size=7.5)

    rule()
    center("REÇU DE PAIEMENT", "Helvetica-Bold", 9)
    left_right("N°", sale.numero_vente)
    left_right("Date", format_local(sale.date_vente))
    left_right("Vendeur", sale.user_nom[:26])

    if sale.client_nom:
        left_right("Client", sale.client_nom[:26])

    if sale.is_cancelled:
        center("*** VENTE ANNULÉE ***", "Helvetica-Bold", 9)

    rule()

    for line in lines:
        pdf.setFont("Helvetica", 8)
        pdf.drawString(margin, y, line.product_nom[:40])
        y -= row

        # --- Traçabilité : lot vendu + péremption ---------------------------------
        lot_font, lot_size = "Helvetica-Bold", 7.5
        peremption = f"exp. {format_date(line.date_peremption)}" if line.date_peremption else ""
        room = width - 2 * margin - (stringWidth(peremption, lot_font, lot_size) + 6 if peremption else 0)
        lot_text = f"  Lot {line.numero_lot}"
        if stringWidth(lot_text, lot_font, lot_size) > room:
            while lot_text and stringWidth(lot_text + "...", lot_font, lot_size) > room:
                lot_text = lot_text[:-1]
            lot_text += "..."
        pdf.setFont(lot_font, lot_size)
        pdf.drawString(margin, y, lot_text)
        if peremption:
            pdf.drawRightString(width - margin, y, peremption)
        y -= row
        # --------------------------------------------------------------------------

        left_right(
            f"  {line.quantite} {line.unite} x {format_fcfa(line.prix_unitaire)}",
            format_fcfa(line.montant_ligne),
            size=8,
        )

    rule()
    left_right("Brut", format_fcfa(sale.montant_brut))

    if sale.remise_globale:
        left_right("Remise", f"-{format_fcfa(sale.remise_globale)}")

    if sale.taux_taxe_bp:
        left_right(
            _taxe_text(sale, taxe_libelle), format_fcfa(sale.taxes)
        )

    left_right(
        "NET À PAYER",
        format_fcfa(sale.montant_net),
        "Helvetica-Bold",
        9.5,
    )

    for p in payments:
        sign = "-" if p.type == "REMBOURSEMENT" else ""
        left_right(
            p.method_libelle[:22],
            f"{sign}{format_fcfa(p.montant)}",
            size=8,
        )

    if monnaie:
        left_right("Monnaie rendue", format_fcfa(monnaie))

    if not sale.is_cancelled and sale.reste:
        left_right(
            "Reste à payer",
            format_fcfa(sale.reste),
            "Helvetica-Bold",
            9,
        )

    rule()
    center("Merci de votre visite", size=8)

    pdf.save()
    return path