"""AI case analysis: a narrative summary and investigative hypotheses drawn
strictly from the reviewed case record.

Grounding rules enforced here, not just requested in the prompt:

* Input is only what the investigator has reviewed: committed documents,
  non-excluded timeline events, actors, flags and discrepancies. Unreviewed
  AI readings never reach the analysis.
* Every item in that record carries a citation ID (D documents, E timeline
  events, F flags, A actors, X discrepancies). Every citation in the answer
  is checked against those IDs after generation; invented ones are removed
  and a statement left with no valid source is marked unsupported.
* Each saved report keeps the model, time, language and a hash of the exact
  input, so what a hypothesis was based on can be shown later.
"""
import hashlib
import json
import logging
from datetime import datetime

import anthropic

from app.core.config import settings
from app.models.models import Case
from app.services.discrepancy import build_discrepancy_groups
from app.services.ollama_client import OPENAI_COMPATIBLE, VisionProviderError, gemini_text_json, openai_compatible_chat

logger = logging.getLogger("redthread.analysis")

DISCLAIMER = {
    "en": ("AI-generated analysis for investigative direction only. It is not evidence, not a legal finding, and "
           "not a conclusion that any person committed wrongdoing. It is limited to the reviewed case record, which "
           "may itself contain reading errors. Every statement must be verified against the original documents."),
    "es": ("Análisis generado por IA, solo como orientación para la investigación. No constituye evidencia, ni una "
           "conclusión jurídica, ni la constatación de que una persona haya cometido un delito. Se limita al registro "
           "revisado del caso, que puede contener errores de lectura. Cada afirmación debe verificarse con los "
           "documentos originales."),
}

LANGUAGE_NAMES = {"en": "English", "es": "Spanish (neutral Latin American, suitable for Chile)"}


class AnalysisError(Exception):
    pass


def _sources_schema() -> dict:
    return {"type": "array", "items": {"type": "string"}}


def _evidence_schema() -> dict:
    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {"statement": {"type": "string"}, "sources": _sources_schema()},
            "required": ["statement", "sources"],
            "additionalProperties": False,
        },
    }


REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "established_facts": _evidence_schema(),
        "hypotheses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "explanation": {"type": "string"},
                    "supporting_evidence": _evidence_schema(),
                    "contradicting_evidence": _evidence_schema(),
                    "benign_explanations": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "string", "enum": ["low", "moderate", "high"]},
                    "would_confirm": {"type": "array", "items": {"type": "string"}},
                    "would_refute": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "explanation", "supporting_evidence", "contradicting_evidence",
                             "benign_explanations", "confidence", "would_confirm", "would_refute"],
                "additionalProperties": False,
            },
        },
        "gaps": {"type": "array", "items": {"type": "string"}},
        "next_steps": {"type": "array", "items": {"type": "string"}},
        "data_quality_notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "established_facts", "hypotheses", "gaps", "next_steps", "data_quality_notes"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You assist a forensic investigator reviewing a historical adoption case (typically \
Chile to the United States, 1970s-1990s). You receive the case's reviewed record and produce a careful \
analysis of what the record shows and what may have happened.

Rules:
- Use only the case record provided. Do not add outside facts about the people, organizations or events \
named in it. General knowledge of how adoptions and legal procedures normally work may be used to explain \
why something is unusual, and must be presented as general context, not as a fact of this case.
- Cite sources for every fact and every piece of evidence, using the bracketed IDs from the record \
(e.g. "D4", "E12", "F2"). Cite only IDs that appear in the record.
- Keep established facts (directly stated in the record) separate from inferences and hypotheses.
- For every hypothesis, give the evidence for it, the evidence against it or that it leaves unexplained, \
plausible benign explanations, and what would confirm or refute it. Rate confidence conservatively: "high" \
only when several independent documents agree and nothing contradicts them.
- The record was produced by reading scanned documents and may contain transcription errors, ambiguous \
dates, or duplicated documents. Say so where it matters, in data_quality_notes.
- Use careful, trauma-informed language: describe irregularities and anomalies; do not label people as \
criminals or state that trafficking occurred. Refer to people by the role they hold in the documents.
- The investigator's own notes, if present, are context, not evidence; do not cite them as a source.
- Statements (T IDs) were entered by the investigator. A TESTIMONY is evidence of what a person said, not proof \
that it is true: weigh it by whether it is first-hand, how it was obtained, and whether it is corroborated, and \
say so. A VERIFIED FINDING is a fact the investigator established by the stated method (e.g. a DNA test or \
registry check); treat it as established, cite it, and note what it contradicts in the documents.
- Write the whole report in {language}. Keep names, document titles and quotations exactly as in the record."""


def _date(value) -> str:
    return value.isoformat() if value else "undated"


def build_dossier(case: Case) -> tuple[str, set[str], int]:
    """The reviewed case record as text with citation IDs. Returns the text,
    the set of valid IDs, and how many documents it covers."""
    lines: list[str] = []
    valid: set[str] = set()
    subject = case.subject

    lines.append(f"CASE {case.case_number}: {case.title}")
    if subject:
        lines.append(f"SUBJECT: {subject.full_name}; aliases: {', '.join(subject.aliases or []) or 'none'}; "
                     f"date of birth: {_date(subject.date_of_birth)}; place of birth: {subject.birth_place or 'unknown'}")
        if subject.notes:
            lines.append(f"Subject notes: {subject.notes}")
    if case.notes:
        lines.append(f"INVESTIGATOR NOTES (context only, not a source): {case.notes}")

    committed = sorted((d for d in case.documents if d.committed), key=lambda d: d.upload_order)
    doc_ids = {}
    lines.append("\nDOCUMENTS (reviewed and committed by the investigator)")
    for n, document in enumerate(committed, start=1):
        cid = f"D{n}"
        doc_ids[document.id] = cid
        valid.add(cid)
        x = document.edited_extraction or document.raw_extraction or {}
        lines.append(f"[{cid}] {document.filename} | type: {x.get('doc_type') or document.doc_type or 'unknown'}"
                     + (" | manual entry, no scan" if not document.has_file else ""))
        if x.get("raw_text_notes"):
            lines.append(f"  description: {x['raw_text_notes']}")
        names = [f"{n_['name']} ({n_.get('role') or 'role unknown'})" for n_ in x.get("names", []) if n_.get("name")]
        if names:
            lines.append(f"  names: {'; '.join(names)}")
        dates = [f"{d.get('label')}: {d.get('date') or 'unreadable'}" + (f' (written "{d["raw"]}")' if d.get("raw") else "")
                 for d in x.get("dates", [])]
        if dates:
            lines.append(f"  dates: {'; '.join(dates)}")
        for t in x.get("financial_transactions", []):
            lines.append(f"  payment: {t.get('amount') or '?'} {t.get('currency') or ''} for {t.get('description') or '?'}"
                         f"; case number nearby: {t.get('linked_case_number') or 'none'}")
        if x.get("legal_references"):
            lines.append(f"  legal references: {'; '.join(x['legal_references'])}")

    lines.append("\nTIMELINE (events from committed documents; excluded noise omitted)")
    events = sorted((e for e in case.timeline_events if not e.excluded),
                    key=lambda e: (e.event_date is None, e.event_date or datetime.min.date()))
    for n, event in enumerate(events, start=1):
        cid = f"E{n}"
        valid.add(cid)
        source = doc_ids.get(event.source_document_id, "no source")
        lines.append(f"[{cid}] {_date(event.event_date)} | {event.event_type} | {event.description} | from {source}")

    lines.append("\nACTORS (people and organizations, deduplicated)")
    docs_by_actor: dict[str, set[str]] = {}
    for edge in case.edges:
        if edge.document_id in doc_ids:
            docs_by_actor.setdefault(edge.target_actor_id, set()).add(doc_ids[edge.document_id])
    for n, actor in enumerate(sorted(case.actors, key=lambda a: (not a.is_subject, a.canonical_name)), start=1):
        cid = f"A{n}"
        valid.add(cid)
        watch = ""
        if actor.watchlist_match:
            tier = actor.watchlist_match.category.value
            watch = f" | on investigator's watchlist ({tier} tier, {actor.watchlist_match_score:.0f}% name match)"
        aliases = f" | also written: {', '.join(actor.aliases)}" if actor.aliases else ""
        seen = f" | in {', '.join(sorted(docs_by_actor.get(actor.id, [])))}" if docs_by_actor.get(actor.id) else ""
        lines.append(f"[{cid}] {actor.canonical_name} | {'SUBJECT' if actor.is_subject else actor.role or 'role unknown'}"
                     f"{aliases}{watch}{seen}")

    lines.append("\nFLAGS (raised by the app's rules)")
    grouped: dict[tuple, list] = {}
    for flag in case.flags:
        grouped.setdefault((flag.severity.value, flag.title), []).append(flag)
    for n, ((severity, title), flags) in enumerate(sorted(grouped.items()), start=1):
        cid = f"F{n}"
        valid.add(cid)
        sources = sorted({doc_ids[f.related_document_id] for f in flags if f.related_document_id in doc_ids})
        lines.append(f"[{cid}] {severity} | {title} | {flags[0].description}"
                     + (f" | raised by {', '.join(sources)}" if sources else ""))

    lines.append("\nSTATEMENTS AND FINDINGS (entered by the investigator; not from scanned documents)")
    if not case.statements:
        lines.append("none")
    for n, statement in enumerate(case.statements, start=1):
        cid = f"T{n}"
        valid.add(cid)
        kind = "TESTIMONY" if statement.kind == "testimony" else "VERIFIED FINDING"
        who = statement.source_name or "unnamed source"
        if statement.source_relationship:
            who += f" ({statement.source_relationship})"
        details = [f"{'said by' if statement.kind == 'testimony' else 'verified by'} {who}",
                   f"date: {_date(statement.statement_date)}"]
        if statement.method:
            details.append(f"how: {statement.method}")
        if statement.kind == "testimony":
            details.append(f"basis: {statement.basis or 'unknown'}")
        details.append(f"status: {statement.status}")
        linked = [doc_ids[d] for d in statement.related_document_ids or [] if d in doc_ids]
        if linked:
            details.append(f"{statement.relation} {', '.join(linked)}")
        lines.append(f"[{cid}] {kind} | \"{' '.join(statement.statement.split())}\" | " + " | ".join(details))

    lines.append("\nDISCREPANCIES (same fact recorded differently)")
    n = 0
    for group in build_discrepancy_groups(case):
        if not group.get("is_contradictory"):
            continue
        n += 1
        cid = f"X{n}"
        valid.add(cid)
        values = "; ".join(f"{r['value']} ({doc_ids.get(r['document_id'], '?')})" for r in group["rows"])
        lines.append(f"[{cid}] {group['field']}: {values}")
    if n == 0:
        lines.append("none")

    return "\n".join(lines), valid, len(committed)


def check_citations(report: dict, valid: set[str]) -> dict:
    """Drop citations to IDs that are not in the record and mark statements
    left without any valid source. Returns counts for the saved report."""
    removed = unsupported = 0

    def clean(items: list[dict]) -> None:
        nonlocal removed, unsupported
        for item in items:
            sources = [s.strip().strip("[]") for s in item.get("sources", [])]
            kept = [s for s in sources if s in valid]
            removed += len(sources) - len(kept)
            item["sources"] = kept
            item["unsupported"] = not kept
            unsupported += not kept

    clean(report.get("established_facts", []))
    for hypothesis in report.get("hypotheses", []):
        clean(hypothesis.get("supporting_evidence", []))
        clean(hypothesis.get("contradicting_evidence", []))
    return {"removed_invalid_citations": removed, "unsupported_statements": unsupported}


async def generate_analysis(case: Case, language: str) -> dict:
    if language not in LANGUAGE_NAMES:
        raise AnalysisError("Language must be 'en' or 'es'")
    provider = settings.ai_provider
    if provider not in ("claude", "gemini", *OPENAI_COMPATIBLE):
        raise AnalysisError(
            "Case analysis needs a cloud AI (Claude, Grok, OpenAI, Gemini or a custom provider): the built-in local "
            "engine is too small to reason reliably across a whole case. Choose one in Settings (the case record, "
            "as text, is then sent to that provider).")
    if provider == "claude" and not settings.anthropic_api_key:
        raise AnalysisError("Claude API key not configured (Settings).")

    dossier, valid_ids, document_count = build_dossier(case)
    if document_count == 0:
        raise AnalysisError("No reviewed documents yet. Commit at least one document before running an analysis.")
    input_hash = hashlib.sha256(dossier.encode("utf-8")).hexdigest()

    system = SYSTEM_PROMPT.format(language=LANGUAGE_NAMES[language])
    user = f"CASE RECORD\n\n{dossier}\n\nAnalyse this case."
    if provider == "claude":
        text, model = await _claude_analysis(system, user)
    else:
        # Other providers may ignore a response schema, so it is also spelled
        # out in the prompt, and the reply is normalized to it afterwards.
        user += "\n\nReply with only a JSON object matching this JSON schema:\n" + json.dumps(REPORT_SCHEMA)
        try:
            if provider == "gemini":
                text, model = await gemini_text_json(system, user, REPORT_SCHEMA, timeout=600.0)
            else:
                messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
                text, model = await openai_compatible_chat(provider, messages, REPORT_SCHEMA, timeout=600.0)
        except VisionProviderError as exc:
            raise AnalysisError(str(exc)) from exc
        model = f"{provider}:{model}"
    try:
        report = normalize_report(json.loads(_strip_fences(text)))
    except (json.JSONDecodeError, TypeError) as exc:
        raise AnalysisError("The analysis came back in an unexpected format. Try again.") from exc

    citation_check = check_citations(report, valid_ids)
    return {
        "report": report,
        "citation_check": citation_check,
        "disclaimer": DISCLAIMER[language],
        "language": language,
        "model": model,
        "input_hash": input_hash,
        "document_count": document_count,
        "dossier": dossier,  # what the analysis was based on, kept with it
    }


async def _claude_analysis(system: str, user: str) -> tuple[str, str]:
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=600.0, max_retries=2)
    try:
        async with client.beta.messages.stream(
            model=settings.claude_vision_model,
            max_tokens=32000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=system,
            output_config={"effort": "high", "format": {"type": "json_schema", "schema": REPORT_SCHEMA}},
            messages=[{"role": "user", "content": user}],
        ) as stream:
            message = await stream.get_final_message()
    except anthropic.AuthenticationError as exc:
        raise AnalysisError("Claude rejected the API key. Re-enter it in Settings.") from exc
    except anthropic.RateLimitError as exc:
        raise AnalysisError("Claude rate limit reached. Try again in a minute.") from exc
    except anthropic.APIStatusError as exc:
        raise AnalysisError(f"Claude request failed ({exc.status_code}): {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise AnalysisError("Could not reach Claude. Check the internet connection.") from exc
    finally:
        await client.close()

    if message.stop_reason == "refusal":
        raise AnalysisError("Claude declined to analyse this case.")
    if message.stop_reason == "max_tokens":
        raise AnalysisError("The analysis was cut off before it finished. Try again.")
    return next((b.text for b in message.content if b.type == "text"), ""), message.model


def _strip_fences(text: str) -> str:
    """Some models wrap JSON in a code fence despite being asked not to."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    return text


def _strings(value) -> list[str]:
    return [str(v) for v in value if v not in (None, "")] if isinstance(value, list) else []


def _evidence(value) -> list[dict]:
    out = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, dict) and item.get("statement"):
            out.append({"statement": str(item["statement"]), "sources": _strings(item.get("sources"))})
        elif isinstance(item, str) and item:
            out.append({"statement": item, "sources": []})  # no sources: will be marked unsupported
    return out


def normalize_report(raw) -> dict:
    """Coerce a reply into REPORT_SCHEMA's shape. Claude is held to the schema
    by the API; other providers may drop fields or use near-miss types, and
    the screen and the citation check rely on the exact shape."""
    if not isinstance(raw, dict):
        raise TypeError("report is not a JSON object")
    hypotheses = []
    for h in raw.get("hypotheses") if isinstance(raw.get("hypotheses"), list) else []:
        if not isinstance(h, dict) or not h.get("title"):
            continue
        confidence = str(h.get("confidence", "")).lower()
        hypotheses.append({
            "title": str(h["title"]),
            "explanation": str(h.get("explanation") or ""),
            "supporting_evidence": _evidence(h.get("supporting_evidence")),
            "contradicting_evidence": _evidence(h.get("contradicting_evidence")),
            "benign_explanations": _strings(h.get("benign_explanations")),
            "confidence": confidence if confidence in ("low", "moderate", "high") else "low",
            "would_confirm": _strings(h.get("would_confirm")),
            "would_refute": _strings(h.get("would_refute")),
        })
    return {
        "summary": str(raw.get("summary") or ""),
        "established_facts": _evidence(raw.get("established_facts")),
        "hypotheses": hypotheses,
        "gaps": _strings(raw.get("gaps")),
        "next_steps": _strings(raw.get("next_steps")),
        "data_quality_notes": _strings(raw.get("data_quality_notes")),
    }
