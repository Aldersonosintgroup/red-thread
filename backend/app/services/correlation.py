"""Cross-case correlation: finds the same person or organization appearing
in more than one case, so a facilitator, notary or clinic that recurs across
unrelated families stands out.

In-case dedup (dedup.py) merges spellings inside one case automatically.
Across cases nothing is ever merged: this only proposes links, graded by
confidence, for the investigator to confirm or separate. Decisions are keyed
by (case, folded name), not actor id, so they survive Re-read all, which
rebuilds a case's actors with new ids.

Name comparison is token by token, tuned for Spanish/Chilean records:
accents and honorifics are ignored ("Sra. Margarita Fictícia" = "MARGARITA FICTICIA"),
a surname initial matches the full surname ("Ficticia L." = "Ficticia Lobos"),
and a near-identical long token counts as a likely misspelling
("Fiticia" ~ "Ficticia"). At least two real name tokens must agree, so a shared
first name or a single common surname never links two cases on its own.
"""
import unicodedata
from collections import defaultdict
from datetime import date
from itertools import combinations

from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.models import Actor, Case, CrossCaseDecision, Document, TimelineEvent
from app.services import dedup

CONFIRMED, STRONG, POSSIBLE = "confirmed", "strong", "possible"
TIER_RANK = {CONFIRMED: 0, STRONG: 1, POSSIBLE: 2}

# Dropped before comparing: titles and the particles inside compound names
# ("María de la Luz", "Vda. de Soto"), which carry no identity.
IGNORED_TOKENS = {
    "SR", "SRA", "SRTA", "SENOR", "SENORA", "SENORITA", "DON", "DONA", "DR", "DRA", "DOCTOR", "DOCTORA",
    "LIC", "LICDA", "ABOG", "MR", "MRS", "MS", "MISS", "DE", "DEL", "LA", "LAS", "LOS", "Y", "VDA", "VIUDA",
}
MAX_VARIANTS = 12  # canonical name + aliases compared per actor


def fold_tokens(name: str) -> tuple[str, ...]:
    decomposed = unicodedata.normalize("NFKD", name or "")
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c)).upper()
    cleaned = "".join(c if c.isalnum() else " " for c in stripped)
    return tuple(t for t in cleaned.split() if t not in IGNORED_TOKENS)


def name_key(name: str) -> str:
    return " ".join(fold_tokens(name))


def _token_relation(a: str, b: str) -> str | None:
    if a == b:
        return "exact" if len(a) > 1 else "initial"
    if len(a) == 1 and b.startswith(a) or len(b) == 1 and a.startswith(b):
        return "initial"
    shorter = min(len(a), len(b))
    if shorter >= 4 and a[0] == b[0]:
        threshold = 80 if shorter >= 6 else 85
        if fuzz.ratio(a, b) >= threshold:
            return "fuzzy"
    return None


def compare_names(a: tuple[str, ...], b: tuple[str, ...], same_role: bool = False) -> tuple[str, float] | None:
    """Grade two folded names as STRONG or POSSIBLE, or None if they don't match.
    Every token of the shorter name must be accounted for in the longer one."""
    if not a or not b:
        return None
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    unused = list(long_)
    counts = {"exact": 0, "fuzzy": 0, "initial": 0}
    for token in short:
        best_i, best_rel = None, None
        for i, other in enumerate(unused):
            rel = _token_relation(token, other)
            if rel and (best_rel is None or ["exact", "fuzzy", "initial"].index(rel)
                        < ["exact", "fuzzy", "initial"].index(best_rel)):
                best_i, best_rel = i, rel
        if best_rel is None:
            return None
        counts[best_rel] += 1
        unused.pop(best_i)

    if counts["exact"] < 1 or counts["exact"] + counts["fuzzy"] < 2:
        return None
    score = 100.0 - 8 * counts["fuzzy"] - 4 * counts["initial"] - 3 * len(unused)
    strong = counts["fuzzy"] == 0 and counts["exact"] >= 2 and (
        counts["exact"] + counts["initial"] >= 3 or same_role
    )
    return (STRONG if strong else POSSIBLE), round(max(score, 0.0), 1)


def _same_role(a: Actor, b: Actor) -> bool:
    return bool(a.role and b.role and a.role.strip().lower() == b.role.strip().lower())


def _variants(actor: Actor) -> list[tuple[str, ...]]:
    names = [actor.canonical_name, *(actor.aliases or [])][:MAX_VARIANTS]
    seen, out = set(), []
    for n in names:
        tokens = fold_tokens(n)
        if tokens and tokens not in seen:
            seen.add(tokens)
            out.append(tokens)
    return out


def compare_actors(a: Actor, b: Actor) -> tuple[str, float] | None:
    best = None
    same_role = _same_role(a, b)
    for va in _variants(a):
        for vb in _variants(b):
            result = compare_names(va, vb, same_role)
            if result and (best is None or (TIER_RANK[result[0]], -result[1]) < (TIER_RANK[best[0]], -best[1])):
                best = result
    return best


def _decision_key(case_a: str, key_a: str, case_b: str, key_b: str) -> tuple[str, str, str, str]:
    return (case_a, key_a, case_b, key_b) if (case_a, key_a) <= (case_b, key_b) else (case_b, key_b, case_a, key_a)


def actor_ref(actor: Actor) -> tuple[str, str]:
    return actor.case_id, name_key(actor.canonical_name)


def load_decisions(db: Session) -> dict[tuple[str, str, str, str], str]:
    return {
        _decision_key(d.case_a_id, d.name_a, d.case_b_id, d.name_b): d.decision
        for d in db.query(CrossCaseDecision).all()
    }


def set_decision(db: Session, a: Actor, b: Actor, decision: str | None) -> None:
    """Record (or with None, clear) the investigator's call on a cross-case pair."""
    ca, ka = actor_ref(a)
    cb, kb = actor_ref(b)
    if ca == cb:
        return
    case_a, name_a, case_b, name_b = _decision_key(ca, ka, cb, kb)
    row = db.query(CrossCaseDecision).filter_by(
        case_a_id=case_a, name_a=name_a, case_b_id=case_b, name_b=name_b).first()
    if decision is None:
        if row:
            db.delete(row)
    elif row:
        row.decision = decision
    else:
        db.add(CrossCaseDecision(case_a_id=case_a, name_a=name_a, case_b_id=case_b, name_b=name_b,
                                 decision=decision))


def _candidate_pairs(actors: list[Actor]) -> set[tuple[int, int]]:
    """Blocking: only actors from different cases sharing a 3-letter prefix of
    some long token are compared, instead of every pair in the install."""
    blocks: dict[str, set[int]] = defaultdict(set)
    for i, actor in enumerate(actors):
        for variant in _variants(actor):
            for token in variant:
                if len(token) >= 4:
                    blocks[token[:3]].add(i)
    pairs = set()
    for members in blocks.values():
        for i, j in combinations(sorted(members), 2):
            if actors[i].case_id != actors[j].case_id:
                pairs.add((i, j))
    return pairs


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        self.parent[self.find(a)] = self.find(b)


def _connected(members: list[int], links: list[tuple[int, int, str]], allowed: set[str]) -> bool:
    uf = _UnionFind(max(members) + 1)
    for i, j, tier in links:
        if tier in allowed:
            uf.union(i, j)
    return len({uf.find(m) for m in members}) == 1


def _appearances(actor: Actor, documents: list[Document],
                 dates_by_doc: dict[str, list[date]]) -> tuple[int, date | None, date | None]:
    """How many committed documents name this actor, and the span of dates
    those documents record."""
    known = [dedup.normalize_name(n) for n in [actor.canonical_name, *(actor.aliases or [])] if n]
    count, dates = 0, []
    for document in documents:
        extraction = document.edited_extraction or document.raw_extraction or {}
        for entry in extraction.get("names", []):
            normalized = dedup.normalize_name(entry.get("name") or "")
            if normalized and any(fuzz.token_set_ratio(normalized, k) >= settings.dedup_fuzzy_threshold
                                  for k in known):
                count += 1
                dates.extend(dates_by_doc.get(document.id, []))
                break
    return count, (min(dates) if dates else None), (max(dates) if dates else None)


def find_recurring_actors(db: Session) -> list[dict]:
    """Groups of actors that appear in two or more cases, strongest first."""
    actors = (
        db.query(Actor).join(Case, Case.id == Actor.case_id)
        .filter(Actor.is_subject.is_(False))
        .order_by(Actor.case_id, Actor.canonical_name).all()
    )
    decisions = load_decisions(db)
    refs = [actor_ref(a) for a in actors]

    links: list[tuple[int, int, str, float]] = []
    rejected: set[tuple[int, int]] = set()
    pairs = _candidate_pairs(actors)
    # Confirmed pairs are linked even if a later rename stopped them matching.
    by_ref = defaultdict(list)
    for i, ref in enumerate(refs):
        by_ref[ref].append(i)
    for (ca, ka, cb, kb), decision in decisions.items():
        for i in by_ref.get((ca, ka), []):
            for j in by_ref.get((cb, kb), []):
                pairs.add((min(i, j), max(i, j)))

    for i, j in pairs:
        decision = decisions.get(_decision_key(*refs[i], *refs[j]))
        if decision == "rejected":
            rejected.add((i, j))
            continue
        if decision == "confirmed":
            links.append((i, j, CONFIRMED, 100.0))
            continue
        result = compare_actors(actors[i], actors[j])
        if result:
            links.append((i, j, result[0], result[1]))

    uf = _UnionFind(len(actors))
    for i, j, _, _ in links:
        uf.union(i, j)
    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(len(actors)):
        groups[uf.find(i)].append(i)

    clusters = [m for m in groups.values() if len({actors[i].case_id for i in m}) >= 2]
    if not clusters:
        return []

    case_ids = {actors[i].case_id for m in clusters for i in m}
    cases = {c.id: c for c in db.query(Case).filter(Case.id.in_(case_ids)).all()}
    docs_by_case: dict[str, list[Document]] = defaultdict(list)
    for d in (db.query(Document).filter(Document.case_id.in_(case_ids), Document.committed.is_(True))
              .order_by(Document.upload_order).all()):
        docs_by_case[d.case_id].append(d)
    dates_by_doc: dict[str, list[date]] = defaultdict(list)
    for e in db.query(TimelineEvent).filter(TimelineEvent.case_id.in_(case_ids),
                                            TimelineEvent.excluded.is_(False),
                                            TimelineEvent.event_date.isnot(None)).all():
        dates_by_doc[e.source_document_id].append(e.event_date)

    results = []
    for members in clusters:
        member_set = set(members)
        cluster_links = [(i, j, t) for i, j, t, _ in links if i in member_set and j in member_set]
        if _connected(members, cluster_links, {CONFIRMED}):
            tier = CONFIRMED
        elif _connected(members, cluster_links, {CONFIRMED, STRONG}):
            tier = STRONG
        else:
            tier = POSSIBLE
        conflict = any(i in member_set and j in member_set for i, j in rejected)

        member_rows, all_dates = [], []
        for i in members:
            a = actors[i]
            case = cases[a.case_id]
            count, first, last = _appearances(a, docs_by_case[a.case_id], dates_by_doc)
            all_dates += [d for d in (first, last) if d]
            member_rows.append({
                "actor_id": a.id, "case_id": a.case_id, "case_number": case.case_number,
                "case_title": case.title, "name": a.canonical_name, "aliases": a.aliases or [],
                "role": a.role, "document_count": count,
                "first_date": first.isoformat() if first else None,
                "last_date": last.isoformat() if last else None,
                "watchlist_category": a.watchlist_match.category.value if a.watchlist_match else None,
            })
        member_rows.sort(key=lambda r: (r["case_number"], r["name"]))
        names = [r["name"] for r in member_rows]
        display = max(set(names), key=lambda n: (names.count(n), len(n)))
        variants = sorted({n for r in member_rows for n in [r["name"], *r["aliases"]]})
        results.append({
            "id": min(actors[i].id for i in members),
            "name": display,
            "variants": variants,
            "case_count": len({r["case_id"] for r in member_rows}),
            "tier": POSSIBLE if conflict else tier,
            "has_conflict": conflict,
            "roles": sorted({r["role"] for r in member_rows if r["role"]}),
            "first_date": min(all_dates).isoformat() if all_dates else None,
            "last_date": max(all_dates).isoformat() if all_dates else None,
            "watchlist_category": next((r["watchlist_category"] for r in member_rows if r["watchlist_category"]),
                                       None),
            "members": member_rows,
            "links": [{"actor_a_id": actors[i].id, "actor_b_id": actors[j].id, "tier": t, "score": s}
                      for i, j, t, s in links if i in member_set and j in member_set],
        })

    results.sort(key=lambda r: (-r["case_count"], TIER_RANK[r["tier"]], r["name"]))
    return results


def separated_pairs(db: Session) -> list[dict]:
    """Pairs the investigator marked as different people, so they can be undone."""
    rows = db.query(CrossCaseDecision).filter(CrossCaseDecision.decision == "rejected").all()
    cases = {c.id: c for c in db.query(Case).all()}
    out = []
    for r in rows:
        if r.case_a_id in cases and r.case_b_id in cases:
            out.append({
                "id": r.id,
                "a": {"case_id": r.case_a_id, "case_number": cases[r.case_a_id].case_number, "name_key": r.name_a},
                "b": {"case_id": r.case_b_id, "case_number": cases[r.case_b_id].case_number, "name_key": r.name_b},
            })
    return out
