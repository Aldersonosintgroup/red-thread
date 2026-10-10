"""Professionally formatted PDF case report, built with ReportLab (pure
Python, no native GTK/Pango dependency — chosen over WeasyPrint for a clean
Windows install)."""
from xml.sax.saxutils import escape
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
)

from app.models.models import Case

SEVERITY_COLORS = {
    "CRITICAL": colors.HexColor("#b91c1c"),
    "HIGH": colors.HexColor("#c2410c"),
    "MEDIUM": colors.HexColor("#a16207"),
    "LOW": colors.HexColor("#4b5563"),
}


def _severity_str(flag) -> str:
    return flag.severity.value if hasattr(flag.severity, "value") else flag.severity


def build_case_pdf(case: Case, score: dict) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.75 * inch, bottomMargin=0.75 * inch)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("RTTitle", parent=styles["Title"], textColor=colors.HexColor("#111827"))
    h2 = ParagraphStyle("RTH2", parent=styles["Heading2"], spaceBefore=14, spaceAfter=6)
    body = styles["BodyText"]

    elements = []
    elements.append(Paragraph("The Red Thread — Case Report", title_style))
    elements.append(Paragraph(f"Case {case.case_number}: {case.title}", styles["Heading3"]))
    elements.append(Spacer(1, 12))

    if case.subject:
        elements.append(Paragraph("Subject Profile", h2))
        subj_rows = [
            ["Full Name", case.subject.full_name],
            ["Aliases", ", ".join(case.subject.aliases or []) or "—"],
            ["Date of Birth", str(case.subject.date_of_birth or "—")],
            ["Birth Place", case.subject.birth_place or "—"],
        ]
        elements.append(_simple_table(subj_rows))

    elements.append(Paragraph("Case Irregularity Score", h2))
    score_rows = [
        ["Category", "Score", "Weight"],
        ["Timeline", f"{score['timeline_score']:.1f}", "25%"],
        ["Entity Match", f"{score['entity_match_score']:.1f}", "35%"],
        ["Financial", f"{score['financial_score']:.1f}", "20%"],
        ["Contradictions", f"{score['contradiction_score']:.1f}", "15%"],
        ["Legal", f"{score['legal_score']:.1f}", "5%"],
        ["TOTAL", f"{score['total_score']:.1f}", "100%"],
    ]
    elements.append(_simple_table(score_rows, header=True))

    elements.append(Paragraph("Case Actors", h2))
    actor_rows = [["Name", "Role", "Watchlist Match"]]
    for actor in case.actors:
        watchlist = ""
        if actor.watchlist_match:
            cat = actor.watchlist_match.category
            watchlist = f"{cat.value if hasattr(cat, 'value') else cat} — {actor.watchlist_match.name}"
        actor_rows.append([actor.canonical_name, actor.role or "—", watchlist or "—"])
    elements.append(_simple_table(actor_rows, header=True))

    elements.append(PageBreak())
    elements.append(Paragraph("Irregularity & Anomaly Flags", h2))
    if not case.flags:
        elements.append(Paragraph("No flags recorded for this case.", body))
    for flag in sorted(case.flags, key=lambda f: _severity_str(f)):
        sev = _severity_str(flag)
        color = SEVERITY_COLORS.get(sev, colors.black)
        style = ParagraphStyle("FlagTitle", parent=body, textColor=color, fontName="Helvetica-Bold")
        elements.append(Paragraph(f"[{sev}] {flag.title}", style))
        elements.append(Paragraph(flag.description or "", body))
        elements.append(Spacer(1, 8))

    if case.statements:
        elements.append(Paragraph("Testimony & Verified Findings", h2))
        elements.append(Paragraph(
            "Entered by the investigator. Testimony records what a person said and is not proof on its own; "
            "verified findings were established by the method stated.", body))
        elements.append(Spacer(1, 6))
        doc_names = {d.id: d.filename for d in case.documents}
        for statement in case.statements:
            kind = "TESTIMONY" if statement.kind == "testimony" else "VERIFIED FINDING"
            who = statement.source_name or "unnamed source"
            if statement.source_relationship:
                who += f" ({statement.source_relationship})"
            meta = [("Said by " if statement.kind == "testimony" else "Verified by ") + who]
            if statement.statement_date:
                meta.append(statement.statement_date.isoformat())
            if statement.method:
                meta.append(statement.method)
            if statement.kind == "testimony":
                meta.append(f"{statement.basis or 'unknown'} basis, {statement.status}")
            linked = [doc_names[d] for d in statement.related_document_ids or [] if d in doc_names]
            if linked:
                meta.append(f"{statement.relation}: {', '.join(linked)}")
            elements.append(Paragraph(f"<b>[{kind}]</b> {escape(statement.statement)}", body))
            elements.append(Paragraph(escape(" · ".join(meta)), body))
            elements.append(Spacer(1, 8))

    elements.append(Paragraph("Timeline", h2))
    timeline_rows = [["Event", "Date", "Description"]]
    for event in sorted(case.timeline_events, key=lambda e: e.event_date or e.event_date.__class__.min):
        timeline_rows.append([event.event_type, str(event.event_date or "—"), event.description or ""])
    if len(timeline_rows) > 1:
        elements.append(_simple_table(timeline_rows, header=True))
    else:
        elements.append(Paragraph("No timeline events recorded.", body))

    doc.build(elements)
    return buffer.getvalue()


def _simple_table(rows: list[list[str]], header: bool = False) -> Table:
    table = Table(rows, hAlign="LEFT")
    style = [
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]
    if header:
        style += [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ]
    table.setStyle(TableStyle(style))
    return table
