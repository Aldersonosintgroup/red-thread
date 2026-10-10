"""Actor deduplication: merges name variants like 'John Carter' and 'JOHN CARTER'
into a single canonical Actor node, using normalization + fuzzy matching.

Uses token-set matching rather than plain character-ratio matching, because
real extracted names vary in ways plain ratio handles badly: word order
("RIVERA-SOTO, ANA LUCIA" vs "Ana Lucia Rivera-Soto") and partial
names (one document capturing "Clara Fuentes", another "Clara Fuentes
Rojas"). Token-set comparison tokenizes both names and scores by token
overlap, which is robust to both.
"""
import re

from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.models import Actor
from app.models.models import WatchlistEntity

# Suggestions are reviewed by a human before merging, so this can be far more
# permissive than the auto-merge-on-commit threshold — a false positive here
# just costs one "reject" click, not a wrongful silent merge.
SUGGESTION_MIN_SCORE = 70.0
MAX_SUGGESTIONS = 50


def normalize_name(name: str) -> str:
    name = name.strip()
    name = re.sub(r"[-,./]", " ", name)  # hyphenated surnames, punctuation -> word boundaries
    name = re.sub(r"\s+", " ", name)
    return name.upper().strip()


def _best_match(normalized: str, candidates_by_item: list[tuple]) -> tuple[object | None, float]:
    best_item = None
    best_score = 0.0
    for item, names in candidates_by_item:
        for candidate in names:
            score = fuzz.token_set_ratio(normalized, normalize_name(candidate))
            if score > best_score:
                best_score = score
                best_item = item
    return best_item, best_score


def find_matching_actor(db: Session, case_id: str, raw_name: str) -> Actor | None:
    """Find an existing actor in this case that raw_name should merge into."""
    normalized = normalize_name(raw_name)
    actors = db.query(Actor).filter(Actor.case_id == case_id).all()
    candidates = [(a, [a.canonical_name] + (a.aliases or [])) for a in actors]
    best_match, best_score = _best_match(normalized, candidates)

    if best_match and best_score >= settings.dedup_fuzzy_threshold:
        return best_match
    return None


def merge_alias_into_actor(db: Session, actor: Actor, raw_name: str) -> None:
    aliases = set(actor.aliases or [])
    if raw_name not in aliases and raw_name != actor.canonical_name:
        aliases.add(raw_name)
        actor.aliases = list(aliases)


def match_watchlist(db: Session, name: str) -> tuple[WatchlistEntity | None, float]:
    """Fuzzy-match a canonical actor name against the private watchlist."""
    normalized = normalize_name(name)
    entities = db.query(WatchlistEntity).all()
    candidates = [(e, [e.name] + (e.aliases or [])) for e in entities]
    best_entity, best_score = _best_match(normalized, candidates)

    if best_entity and best_score >= settings.watchlist_fuzzy_threshold:
        return best_entity, best_score
    return None, 0.0


def find_merge_suggestions(db: Session, case_id: str) -> list[dict]:
    """Candidate duplicate pairs among this case's existing actors, for a
    human to review and accept/reject — never auto-applied."""
    actors = db.query(Actor).filter(Actor.case_id == case_id).order_by(Actor.canonical_name).all()
    normalized_names = {a.id: normalize_name(a.canonical_name) for a in actors}

    suggestions = []
    for i, a in enumerate(actors):
        for b in actors[i + 1:]:
            score = fuzz.token_set_ratio(normalized_names[a.id], normalized_names[b.id])
            if score >= SUGGESTION_MIN_SCORE:
                suggestions.append({"actor_a": a, "actor_b": b, "score": round(score, 1)})

    suggestions.sort(key=lambda s: s["score"], reverse=True)
    return suggestions[:MAX_SUGGESTIONS]
