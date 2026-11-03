"""The "Modelli di scrittura" rules, as checks the console can run.

Each check returns findings. ``error`` findings block approval (a sheet with
open square brackets cannot be published, a news item needs sources from both
sides); ``warning`` findings are shown to the writer and to the verifier, who
decides. The wording follows the guide so editors recognise the rule.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Iterable

from backend.app.services.reference_profile_audit import is_complete_source_url


@dataclass(frozen=True, slots=True)
class Finding:
    level: str  # "error" | "warning"
    code: str
    message: str
    field: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


OPEN_BRACKETS = re.compile(r"\[[^\]]*\]")
SHORT_DATE = re.compile(r"(?<![\d/])\d{1,2}/\d{1,2}(?:/\d{2,4})?(?![\d/])")
# Rule 7 (titoli neutri) and the "prima e dopo" table.
LOADED_TITLE_WORDS = (
    "finalmente", "scandalo", "storico", "storica", "attacca", "affonda", "boccia",
    "trionfa", "stravince", "umiliato", "umiliata", "regalo", "tradita", "tradito",
    "shock", "bufera",
)
# Rule 1 and the Politico model: no judgements.
JUDGEMENT_WORDS = (
    "brillante", "controverso", "controversa", "estremo", "estrema", "corrotto",
    "corrotta", "geniale", "disastroso", "disastrosa", "vergognoso", "vergognosa",
)
# Rule 2: every opinion has a name.
UNATTRIBUTED = ("si dice", "molti pensano", "secondo molti", "tutti sanno", "probabilmente")

NEWS_BLOCKS: tuple[tuple[str, str, int, int], ...] = (
    ("perche", "Perché ne parliamo", 40, 60),
    ("fatto", "Il fatto", 80, 120),
    ("cosa_cambia", "Cosa cambia per te", 80, 120),
    ("destra", "Cosa dice la destra", 60, 90),
    ("sinistra", "Cosa dice la sinistra", 60, 90),
    ("altri", "Cosa dicono gli altri", 40, 70),
    ("numeri", "I numeri e l'impatto economico", 60, 100),
    ("cosa_succede", "Cosa succede adesso", 30, 60),
)
NEWS_TOTAL_WORDS = (450, 700)
SOURCE_AREAS = {
    "istituzionale": "Istituzionale",
    "agenzia": "Agenzia",
    "centrodestra": "Stampa di centrodestra",
    "centrosinistra": "Stampa di centrosinistra",
    "tecnica": "Tecnica",
    "altro": "Altro",
}


def words(text: str | None) -> int:
    return len(re.findall(r"\w+", text or ""))


def _contains(text: str, terms: Iterable[str]) -> list[str]:
    lowered = f" {text.casefold()} "
    return [term for term in terms if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", lowered)]


def text_findings(text: str | None, *, field: str, title: bool = False) -> list[Finding]:
    text = text or ""
    findings: list[Finding] = []
    for match in OPEN_BRACKETS.findall(text):
        findings.append(
            Finding("error", "parentesi_aperte", f"Parte da compilare ancora aperta: {match[:80]}", field)
        )
        break
    if SHORT_DATE.search(text):
        findings.append(
            Finding("warning", "data_abbreviata", "Le date si scrivono per esteso: «16 settembre 2026», mai «16/9».", field)
        )
    for term in _contains(text, LOADED_TITLE_WORDS if title else ()):
        findings.append(Finding("warning", "titolo_non_neutro", f"Titolo non neutro: «{term}». Il titolo dice cosa è successo, non cosa pensare.", field))
    for term in _contains(text, JUDGEMENT_WORDS):
        findings.append(Finding("warning", "giudizio", f"Giudizio da evitare: «{term}». Solo fatti verificabili.", field))
    for term in _contains(text, UNATTRIBUTED):
        findings.append(Finding("warning", "non_attribuito", f"Opinione senza nome: «{term}». Ogni opinione ha un nome e un ruolo.", field))
    return findings


def source_findings(sources: list[dict], *, field: str = "fonti", minimum: int = 1) -> list[Finding]:
    usable = [item for item in sources if item.get("url") and is_complete_source_url(str(item["url"]))]
    findings: list[Finding] = []
    if len(usable) < minimum:
        findings.append(
            Finding(
                "error",
                "fonte_mancante",
                "Serve una fonte con link alla pagina che riporta il fatto (non la home di un sito)."
                if minimum == 1
                else f"Servono almeno {minimum} fonti con link alla pagina che riporta il fatto.",
                field,
            )
        )
    for item in sources:
        if item.get("url") and not is_complete_source_url(str(item["url"])):
            findings.append(Finding("error", "fonte_generica", f"«{item.get('name') or item['url']}» punta a una home o a una sezione: serve la pagina precisa.", field))
    return findings


def is_official_publication(post: dict) -> bool:
    """A feed card that only announces an official list, not a political news analysis."""

    card = post.get("card") or {}
    return card.get("category") == "pubblicazione"


def news_findings(post: dict) -> list[Finding]:
    """Checks for the "Modello Notizia" (nine blocks)."""

    blocks = post.get("blocks") or {}
    official = is_official_publication(post)
    findings = text_findings(post.get("title"), field="titolo", title=True)
    if len(post.get("title") or "") > 90:
        findings.append(Finding("warning", "titolo_lungo", "Il titolo supera i 90 caratteri.", "titolo"))
    findings += text_findings(blocks.get("sommario"), field="sommario")
    if not (blocks.get("sommario") or "").strip():
        findings.append(Finding("error", "blocco_vuoto", "Manca il sommario: chi ha deciso cosa, quando.", "sommario"))
    required_empty = {"fatto", "cosa_cambia"} if official else {"fatto", "cosa_cambia", "destra", "sinistra"}
    total = 0
    for key, label, low, high in NEWS_BLOCKS:
        text = blocks.get(key) or ""
        if key == "fatto":
            text = f"{text}\n{blocks.get('perche_deciso') or ''}"
        count = words(text)
        total += count
        findings += text_findings(text, field=key)
        if not text.strip():
            level = "error" if key in required_empty else "warning"
            findings.append(Finding(level, "blocco_vuoto", f"Blocco vuoto: «{label}». Se uno schieramento non si è espresso, lo si scrive.", key))
        elif count < low * 0.75 or count > high * 1.25:
            findings.append(Finding("warning", "lunghezza", f"«{label}»: {count} parole, indicazione {low}–{high}.", key))
    if total and not NEWS_TOTAL_WORDS[0] <= total <= NEWS_TOTAL_WORDS[1]:
        findings.append(Finding("warning", "lunghezza_totale", f"Lunghezza totale {total} parole, indicazione 450–700.", None))
    right, left = blocks.get("destra") or "", blocks.get("sinistra") or ""
    if right.strip() and left.strip():
        right_words, left_words = words(right), words(left)
        ratio = max(right_words, left_words) / max(1, min(right_words, left_words))
        if ratio > 1.3:
            findings.append(Finding("warning", "equilibrio", f"Destra {right_words} parole, sinistra {left_words}: stesso spazio per tutti.", "sinistra"))
        right_points, left_points = _points(right), _points(left)
        if right_points != left_points:
            findings.append(Finding("warning", "equilibrio_punti", f"Destra {right_points} punti, sinistra {left_points}: stesso numero di punti.", "sinistra"))
    sources = post.get("sources") or []
    findings += source_findings(sources, minimum=1 if official else 3)
    areas = {item.get("area") for item in sources if item.get("url")}
    if not areas & {"istituzionale", "agenzia"}:
        findings.append(Finding("error", "fonte_istituzionale", "Serve almeno una fonte istituzionale o di agenzia.", "fonti"))
    if not official and ("centrodestra" not in areas or "centrosinistra" not in areas):
        findings.append(Finding("error", "fonti_varie", "Servono almeno una testata di centrodestra e una di centrosinistra.", "fonti"))
    return findings


def _points(text: str) -> int:
    lines = [line for line in text.splitlines() if line.strip()]
    bullets = [line for line in lines if line.lstrip().startswith(("-", "•", "*"))]
    return len(bullets) or len(lines)


def profile_findings(kind: str, data: dict) -> list[Finding]:
    """Checks for the blocks of the "Modello Politico"."""

    findings: list[Finding] = []
    if kind == "biography":
        findings += text_findings(data.get("body"), field="testo")
        count = words(data.get("body"))
        if count and not 40 <= count <= 100:
            findings.append(Finding("warning", "lunghezza", f"«Chi è»: {count} parole, indicazione 50–80 (3–5 righe di fatti).", "testo"))
    elif kind == "career_entry":
        findings += text_findings(f"{data.get('role','')} {data.get('institution','')}", field="ruolo")
        if not data.get("start_date"):
            findings.append(Finding("error", "data_mancante", "Ogni incarico ha una data di inizio.", "inizio"))
    elif kind == "position":
        findings += text_findings(data.get("position_statement"), field="posizione")
        findings += text_findings(data.get("verifiable_statement"), field="dichiarazione")
        if not data.get("statement_date"):
            findings.append(Finding("error", "data_mancante", "Ogni posizione si basa su una dichiarazione o un voto con data.", "data"))
    elif kind == "proceeding":
        findings += text_findings(data.get("summary"), field="sintesi")
        findings += text_findings(data.get("outcome_summary"), field="esito")
    findings += source_findings(data.get("sources") or [])
    return findings


def promise_findings(data: dict) -> list[Finding]:
    findings = text_findings(data.get("title"), field="promessa")
    findings += text_findings(data.get("exact_statement"), field="dichiarazione")
    if not data.get("introduced_at"):
        findings.append(Finding("error", "data_mancante", "Una promessa si traccia solo se ha data e fonte.", "data"))
    findings += source_findings([data.get("source") or {}])
    return findings


def verdict_findings(data: dict) -> list[Finding]:
    findings = text_findings(data.get("rationale"), field="aggiornamento")
    findings += source_findings([data.get("source") or {}])
    return findings


def has_errors(findings: Iterable[Finding | dict]) -> bool:
    return any((item.level if isinstance(item, Finding) else item.get("level")) == "error" for item in findings)
