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
from urllib.parse import urlsplit

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

# CEO process: every news proposal needs these three before Friday assignment.
PROPOSAL_TRIAD = (
    ("fatto", "Cosa è successo o succederà"),
    ("perche", "Interesse per il pubblico"),
    ("fonti", "Fonti verificabili"),
)

NEWS_BLOCKS: tuple[tuple[str, str, int, int], ...] = (
    ("perche", "Perché interessa il pubblico", 40, 60),
    ("fatto", "Il fatto (cosa è successo o succederà)", 80, 120),
    ("cosa_cambia", "Cosa cambia per te", 80, 120),
    ("maggioranza", "Cosa dice la maggioranza", 60, 90),
    ("opposizione", "Cosa dice l'opposizione", 60, 90),
    ("altri", "Cosa dicono gli altri", 40, 70),
    ("numeri", "I numeri e l'impatto economico", 60, 100),
    ("cosa_succede", "Cosa succede adesso", 30, 60),
)
# Required for every news analysis; the rest (and «perché è stato deciso») are optional.
# Regional/local pieces often are the numbers themselves, or have no decision rationale.
NEWS_REQUIRED_BLOCKS = frozenset({"perche", "fatto", "maggioranza", "opposizione"})
NEWS_OPTIONAL_BLOCKS = frozenset({"cosa_cambia", "altri", "numeri", "cosa_succede"})
TERRITORIAL_SCOPES = frozenset({"region", "province", "municipality"})
# Legacy keys kept readable so older posts and fixtures still check out.
_NEWS_SIDE_ALIASES = {"maggioranza": "destra", "opposizione": "sinistra"}
NEWS_TOTAL_WORDS = (450, 700)
# Trial cadence shown in redazione (soft warning, not a hard block).
DAILY_NEWS_TRIAL = {
    "active": True,
    "target_per_day": 1,
    "note": "Prova di due settimane: una notizia al giorno (avviso, non blocco).",
}

# N3: «cosa cambia» is scoped to the editorial level of the piece.
COSA_CAMBIA_BY_SCOPE: dict[str, tuple[str, str]] = {
    "national": (
        "Cosa cambia a livello nazionale",
        "Effetti per chi vive in Italia: chi paga, chi riceve, cosa NON cambia a Roma/Governo/Parlamento.",
    ),
    "region": (
        "Cosa cambia in regione",
        "Effetti per chi vive in quella regione: sanità, trasporti, tasse regionali, cosa NON cambia.",
    ),
    "province": (
        "Cosa cambia in provincia",
        "Effetti per chi vive in quella provincia: viabilità, scuole di competenza, servizi provinciali.",
    ),
    "municipality": (
        "Cosa cambia nel comune",
        "Effetti per chi vive in quel comune: tariffe, scuola, rifiuti, casa, cosa NON cambia.",
    ),
}

SOURCE_AREAS = {
    "istituzionale": "Istituzionale",
    "agenzia": "Agenzia",
    "centrodestra": "Stampa di centrodestra",
    "centrosinistra": "Stampa di centrosinistra",
    "stampa_locale": "Stampa locale",
    "tecnica": "Tecnica",
    "altro": "Altro",
}

# N4: these hosts cannot back a published claim (home pages already fail elsewhere).
WEAK_SOURCE_HOST_SUFFIXES = (
    "wikipedia.org",
    "facebook.com",
    "fb.com",
    "twitter.com",
    "x.com",
    "instagram.com",
    "tiktok.com",
    "reddit.com",
    "tuttitalia.it",
    "blogspot.com",
    "wordpress.com",
)


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


def is_weak_source_host(url: str | None) -> bool:
    """Wikipedia, social and blog hosts cannot prove a claim on VeraPolitica."""

    if not url:
        return False
    host = urlsplit(str(url).strip()).netloc.casefold()
    if host.startswith("www."):
        host = host[4:]
    return any(host == suffix or host.endswith("." + suffix) for suffix in WEAK_SOURCE_HOST_SUFFIXES)


def cosa_cambia_label(scope: str | None) -> str:
    return COSA_CAMBIA_BY_SCOPE.get(scope or "national", COSA_CAMBIA_BY_SCOPE["national"])[0]


def cosa_cambia_hint(scope: str | None) -> str:
    return COSA_CAMBIA_BY_SCOPE.get(scope or "national", COSA_CAMBIA_BY_SCOPE["national"])[1]


def is_territorial_scope(scope: str | None) -> bool:
    return (scope or "national") in TERRITORIAL_SCOPES


def required_news_block_keys(*, official: bool = False, scope: str | None = None) -> frozenset[str]:
    """Blocks that block approval when empty (same set for national and territorial)."""

    _ = scope
    if official:
        return frozenset({"fatto", "cosa_cambia"})
    return NEWS_REQUIRED_BLOCKS


def requires_press_side_variety(*, official: bool = False, scope: str | None = None) -> bool:
    """National news needs centrodestra + centrosinistra; local press often has no side."""

    if official:
        return False
    return not is_territorial_scope(scope)


def source_findings(
    sources: list[dict],
    *,
    field: str = "fonti",
    minimum: int = 1,
    require_date: bool = False,
    require_name: bool = False,
) -> list[Finding]:
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
    seen_urls: set[str] = set()
    for item in sources:
        name = (item.get("name") or "").strip()
        url = item.get("url")
        if not url:
            continue
        url_text = str(url).strip()
        if require_name and not name:
            findings.append(
                Finding("error", "fonte_senza_nome", "Ogni fonte ha il nome della testata o dell'ente.", field)
            )
        if not is_complete_source_url(url_text):
            findings.append(
                Finding(
                    "error",
                    "fonte_generica",
                    f"«{name or url_text}» punta a una home o a una sezione: serve la pagina precisa.",
                    field,
                )
            )
        if is_weak_source_host(url_text):
            findings.append(
                Finding(
                    "error",
                    "fonte_inattendibile",
                    f"«{name or url_text}» non è una fonte verificabile (Wikipedia, social o blog).",
                    field,
                )
            )
        if require_date and not (item.get("date") or "").strip():
            findings.append(
                Finding(
                    "error",
                    "fonte_senza_data",
                    f"«{name or url_text}» non ha la data della pagina o dell'articolo.",
                    field,
                )
            )
        marker = url_text.casefold()
        if marker in seen_urls:
            findings.append(
                Finding("warning", "fonte_duplicata", f"La fonte «{name or url_text}» è ripetuta.", field)
            )
        seen_urls.add(marker)
    return findings


def is_official_publication(post: dict) -> bool:
    """A feed card that only announces an official list, not a political news analysis."""

    card = post.get("card") or {}
    return card.get("category") == "pubblicazione"


def normalize_news_side_blocks(blocks: dict) -> dict:
    """Map legacy destra/sinistra onto maggioranza/opposizione without dropping old keys."""

    out = dict(blocks or {})
    for new_key, old_key in _NEWS_SIDE_ALIASES.items():
        if not (out.get(new_key) or "").strip() and (out.get(old_key) or "").strip():
            out[new_key] = out[old_key]
    return out


def news_block_text(blocks: dict, key: str) -> str:
    blocks = normalize_news_side_blocks(blocks)
    text = blocks.get(key) or ""
    if key in _NEWS_SIDE_ALIASES and not text.strip():
        text = blocks.get(_NEWS_SIDE_ALIASES[key]) or ""
    return text


def news_findings(post: dict) -> list[Finding]:
    """Checks for the "Modello Notizia" (nine blocks)."""

    blocks = normalize_news_side_blocks(post.get("blocks") or {})
    scope = post.get("scope") or "national"
    official = is_official_publication(post)
    findings = text_findings(post.get("title"), field="titolo", title=True)
    if len(post.get("title") or "") > 90:
        findings.append(Finding("warning", "titolo_lungo", "Il titolo supera i 90 caratteri.", "titolo"))
    findings += text_findings(blocks.get("sommario"), field="sommario")
    if not (blocks.get("sommario") or "").strip():
        findings.append(Finding("error", "blocco_vuoto", "Manca il sommario: chi ha deciso cosa, quando.", "sommario"))
    # N2 triad (fatto + interesse + fonti) applies to news analyses. A
    # «pubblicazione ufficiale» only announces an institutional list.
    # Optional blocks (cosa_cambia, altri, numeri, cosa_succede) and
    # «perché è stato deciso» stay empty without blocking — useful for
    # regional pieces where those sections would feel forced.
    required_empty = required_news_block_keys(official=official, scope=scope)
    total = 0
    for key, label, low, high in NEWS_BLOCKS:
        if key == "cosa_cambia":
            label = cosa_cambia_label(scope)
        text = news_block_text(blocks, key)
        # Subsection 2.2 («perché è stato deciso») is optional and never
        # substitutes for the fatto body when checking emptiness.
        checked = text
        if key == "fatto":
            deciso = (blocks.get("perche_deciso") or "").strip()
            if deciso:
                checked = f"{text}\n{deciso}"
        count = words(checked)
        total += count
        findings += text_findings(checked, field=key)
        if not text.strip():
            if key not in required_empty:
                continue
            if key == "perche":
                message = "Manca l'interesse per il pubblico: perché questa notizia riguarda i lettori."
            elif key == "fatto":
                message = "Manca il fatto: cosa è successo o succederà."
            elif key == "cosa_cambia":
                message = f"Blocco vuoto: «{label}»."
            else:
                message = f"Blocco vuoto: «{label}». Se uno schieramento non si è espresso, lo si scrive."
            findings.append(Finding("error", "blocco_vuoto", message, key))
        elif count < low * 0.75 or count > high * 1.25:
            findings.append(Finding("warning", "lunghezza", f"«{label}»: {count} parole, indicazione {low}–{high}.", key))
        if key in {"maggioranza", "opposizione"} and text.strip():
            findings.extend(_side_attribution_findings(text, field=key, label=label))
    if total and not NEWS_TOTAL_WORDS[0] <= total <= NEWS_TOTAL_WORDS[1]:
        findings.append(Finding("warning", "lunghezza_totale", f"Lunghezza totale {total} parole, indicazione 450–700.", None))
    majority, opposition = news_block_text(blocks, "maggioranza"), news_block_text(blocks, "opposizione")
    if majority.strip() and opposition.strip():
        right_words, left_words = words(majority), words(opposition)
        ratio = max(right_words, left_words) / max(1, min(right_words, left_words))
        if ratio > 1.3:
            findings.append(
                Finding(
                    "warning",
                    "equilibrio",
                    f"Maggioranza {right_words} parole, opposizione {left_words}: stesso spazio per tutti.",
                    "opposizione",
                )
            )
        right_points, left_points = _points(majority), _points(opposition)
        if right_points != left_points:
            findings.append(
                Finding(
                    "warning",
                    "equilibrio_punti",
                    f"Maggioranza {right_points} punti, opposizione {left_points}: stesso numero di punti.",
                    "opposizione",
                )
            )
    sources = post.get("sources") or []
    findings += source_findings(
        sources,
        minimum=1 if official else 3,
        require_date=True,
        require_name=True,
    )
    areas = {item.get("area") for item in sources if item.get("url")}
    if not areas & {"istituzionale", "agenzia"}:
        findings.append(
            Finding(
                "error",
                "fonte_istituzionale",
                "Serve almeno una fonte istituzionale o di agenzia. Per dati oggettivi (Camera, ISTAT, elenco ufficiale) basta quella pagina; per notizie e controversie no.",
                "fonti",
            )
        )
    # Local/regional press is often independent: no left/right gate there.
    if requires_press_side_variety(official=official, scope=scope) and (
        "centrodestra" not in areas or "centrosinistra" not in areas
    ):
        findings.append(
            Finding(
                "error",
                "fonti_varie",
                "Per le notizie nazionali servono almeno una testata di centrodestra e una di centrosinistra, oltre alla fonte istituzionale o di agenzia. Una sola fonte istituzionale non basta per una controversia. Per notizie regionali/locali basta istituzionale o agenzia più stampa locale o altre fonti (senza classificare destra/sinistra).",
                "fonti",
            )
        )
    return findings


def _points(text: str) -> int:
    lines = [line for line in text.splitlines() if line.strip()]
    bullets = [line for line in lines if line.lstrip().startswith(("-", "•", "*"))]
    return len(bullets) or len(lines)


# «- Nome Cognome (Partito): …» — person plus party/role in parentheses.
_ATTRIBUTED_POINT = re.compile(
    r"[A-ZÀÈÉÌÒÓÙ][\w'’àèéìòóù.-]*(?:\s+[A-ZÀÈÉÌÒÓÙ][\w'’àèéìòóù.-]*)*"
    r"\s*\([^)]{2,}\)"
    r"\s*[:—,-]",
    re.UNICODE,
)


def _side_attribution_findings(text: str, *, field: str, label: str) -> list[Finding]:
    """Each majority/opposition point should name a person and a party/role."""

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    points = [line.lstrip("-•* ").strip() for line in lines if line.lstrip().startswith(("-", "•", "*"))]
    if not points:
        points = lines
    missing = [point for point in points if not _ATTRIBUTED_POINT.search(point)]
    if missing:
        return [
            Finding(
                "warning",
                "esponente_mancante",
                f"«{label}»: ogni punto indica esponente e partito (es. «- Mario Rossi (PD): …»). Manca in {len(missing)} "
                f"{'punto' if len(missing) == 1 else 'punti'}.",
                field,
            )
        ]
    return []


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
