"""Deterministic selection of explicit-commitment sentences from official text.

No model is involved: every candidate is a whole sentence copied from the
stored official document, so the quote is verbatim by construction (and is
re-checked by the caller). The heuristics only decide *which* sentences look
like pledges in the sense of Royed (1996): a first-person commitment to an
action, ideally with a concrete instrument or number.

The output is a proposal for editors, never a verdict. Classification fields
derived here (topic, specificity) are flagged as automatic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from backend.app.scoring.types import PledgeSpecificity

EXTRACTOR_VERSION = "pledge-candidates/v1"

# First-person plural or governmental commitment markers (Italian).
_COMMITMENT = re.compile(
    r"\b("
    r"ci impegneremo|ci impegniamo|intendiamo|intende|vogliamo|"
    r"faremo|introdurremo|porteremo|lavoreremo|approveremo|ridurremo|"
    r"aumenteremo|realizzeremo|metteremo|sosterremo|rafforzeremo|"
    r"istituiremo|rivedremo|semplificheremo|abbasseremo|estenderemo|"
    r"interverremo|investiremo|tuteleremo|garantiremo|riformeremo|"
    r"è nostra intenzione|il nostro obiettivo è|il governo si impegna"
    r")\b",
    re.IGNORECASE,
)

# Concrete instruments: the sentence names something one could check.
_CONCRETE = re.compile(
    r"\b(legge|riforma|decreto|fondo|tassa|imposta|aliquota|cuneo|"
    r"pension\w*|reddito|bonus|assegno|tariff\w*|bollett\w*|"
    r"assunzion\w*|investiment\w*|piano|codice|registro|commissione|"
    r"presidenzialismo|autonomia|flat tax|iva|irpef|pnrr|euro|miliard\w*)\b",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"\d")

# Rhetoric that makes a sentence unverifiable on its own.
_VAGUE = re.compile(
    r"\b(nazione|patria|orgoglio|speranza|destino|futuro dei nostri|"
    r"rimettere in piedi|grande|straordinari\w*|storic\w*)\b",
    re.IGNORECASE,
)

# Comparative Agendas Project major topics, matched on Italian keywords.
_TOPICS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (code, re.compile(pattern, re.IGNORECASE))
    for code, pattern in (
        ("8", r"\b(energi\w*|bollett\w*|gas|rinnovabil\w*|nucleare)\b"),
        ("9", r"\b(immigra\w*|migranti|sbarchi|confini|frontier\w*)\b"),
        ("12", r"\b(giustizia|magistrat\w*|carcer\w*|processo|reato|reati|criminalit\w*|mafi\w*)\b"),
        ("3", r"\b(sanit\w*|ospedal\w*|medic\w*|salute|pronto soccorso)\b"),
        ("6", r"\b(scuol\w*|istruzione|universit\w*|studenti|insegnanti|docenti)\b"),
        ("13", r"\b(pension\w*|famigli\w*|natalit\w*|povert\w*|reddito di cittadinanza|disabil\w*|assegno)\b"),
        ("5", r"\b(lavor\w*|occupazion\w*|salari\w*|stipendi|cuneo)\b"),
        ("14", r"\b(casa|case|abitativ\w*|mutui|affitt\w*)\b"),
        ("15", r"\b(impres\w*|aziend\w*|pmi|commercio|burocrazia)\b"),
        ("16", r"\b(difesa|forze armate|militar\w*|nato)\b"),
        ("17", r"\b(ricerca|digital\w*|tecnolog\w*|innovazion\w*|banda ultralarga)\b"),
        ("7", r"\b(ambient\w*|clima\w*|dissesto|inquinamento)\b"),
        ("10", r"\b(trasport\w*|infrastruttur\w*|ferrovi\w*|autostrad\w*|ponte sullo stretto|porti)\b"),
        ("19", r"\b(europ\w*|ucrain\w*|internazional\w*|politica estera|alleat\w*)\b"),
        ("20", r"\b(presidenzialismo|costituzion\w*|autonomia|istituzion\w*|pubblica amministrazione|regioni)\b"),
        ("4", r"\b(agricol\w*|agroalimentar\w*|pesca)\b"),
        ("23", r"\b(cultura\w*|turism\w*|patrimonio)\b"),
        ("1", r"\b(tass\w*|fisc\w*|impost\w*|aliquot\w*|flat tax|iva|irpef|debito|inflazione|deficit)\b"),
    )
)

_SENTENCE_END = re.compile(r"(?<=[.!;])\s+(?=[A-ZÀ-ÖØ-Ý«\"“])")


@dataclass(frozen=True, slots=True)
class PledgeCandidate:
    sentence: str
    title: str
    topic_code: str | None
    specificity: PledgeSpecificity
    score: float
    position: int


def split_sentences(text: str) -> list[tuple[int, str]]:
    """(offset, sentence) pairs, offsets into ``text``. Paragraph breaks also split."""

    result: list[tuple[int, str]] = []
    for paragraph in re.finditer(r"[^\n]+", text):
        base = paragraph.start()
        chunk = paragraph.group(0)
        start = 0
        for boundary in _SENTENCE_END.finditer(chunk):
            sentence = chunk[start:boundary.start()].strip()
            if sentence:
                result.append((base + start, sentence))
            start = boundary.end()
        tail = chunk[start:].strip()
        if tail:
            result.append((base + start, tail))
    return result


def _title(sentence: str, limit: int = 96) -> str:
    text = sentence.rstrip(" .;!")
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(",;:")
    return f"{cut}…"


def _topic(sentence: str) -> str | None:
    for code, pattern in _TOPICS:
        if pattern.search(sentence):
            return code
    return None


def score_sentence(sentence: str) -> tuple[float, PledgeSpecificity] | None:
    if not 70 <= len(sentence) <= 420 or "?" in sentence:
        return None
    if not _COMMITMENT.search(sentence):
        return None
    concrete = len(_CONCRETE.findall(sentence))
    numbers = 1 if _NUMBER.search(sentence) else 0
    vague = len(_VAGUE.findall(sentence))
    score = 1.0 + 1.2 * min(concrete, 3) + 1.5 * numbers - 1.0 * vague
    if score < 2.0:
        return None
    specificity = (
        PledgeSpecificity.HIGH if numbers or concrete >= 2 else PledgeSpecificity.MEDIUM
    )
    return score, specificity


def select_pledge_candidates(
    text: str, *, limit: int = 12, per_topic: int = 2
) -> list[PledgeCandidate]:
    scored: list[PledgeCandidate] = []
    seen: set[str] = set()
    for position, sentence in split_sentences(text):
        key = re.sub(r"\W+", " ", sentence.casefold()).strip()
        if key in seen:
            continue
        seen.add(key)
        result = score_sentence(sentence)
        if result is None:
            continue
        score, specificity = result
        scored.append(
            PledgeCandidate(
                sentence=sentence,
                title=_title(sentence),
                topic_code=_topic(sentence),
                specificity=specificity,
                score=score,
                position=position,
            )
        )
    scored.sort(key=lambda item: (-item.score, item.position))
    chosen: list[PledgeCandidate] = []
    per_topic_count: dict[str | None, int] = {}
    for candidate in scored:
        if per_topic_count.get(candidate.topic_code, 0) >= per_topic:
            continue
        chosen.append(candidate)
        per_topic_count[candidate.topic_code] = per_topic_count.get(candidate.topic_code, 0) + 1
        if len(chosen) >= limit:
            break
    return sorted(chosen, key=lambda item: item.position)
