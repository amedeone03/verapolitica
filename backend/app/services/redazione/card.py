"""The feed card the redazione composes for each post.

A card is stored in ``EditorialPost.blocks["card"]`` and drawn the same way in
the public feed and in the console preview:

    [category band]          e.g. DISEGNO DI LEGGE (navy), REFERENDUM (red)
    [badge · date]   [aside] e.g. "Nuova pubblicazione · 30 ott", "Aperto il …"
    (o) Name   (o) Name      politicians with a profile: round image, name, party
    [PD] [M5S]               parties involved (chosen, plus the people's parties)
    Institution              e.g. "Ministero delle Infrastrutture e dei Trasporti"
    Title / summary          the post title and "sommario"
    [iter strip]             optional: four steps, current step, status text
    Info · Fonti · Chiedi    link to the post, its sources, Ask VeraPolitica
    [link] [save] [share]    optional external link ("Leggi su camera.it")
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import EditorialImage, PoliticalParty, PoliticalPartyAffiliation, Politician
from backend.app.services.reference_profile_audit import is_complete_source_url

CATEGORIES: dict[str, tuple[str, str]] = {
    "notizia": ("Notizia", "navy"),
    "disegno_di_legge": ("Disegno di legge del Governo", "navy"),
    "proposta_di_legge": ("Proposta di legge", "navy"),
    "decreto": ("Decreto-legge", "navy"),
    "votazione": ("Votazione in Aula", "ink"),
    "interrogazione": ("Interrogazione", "navy"),
    "referendum": ("Referendum", "red"),
    "promessa": ("Promessa", "green"),
    "elezioni": ("Elezioni", "ink"),
}
BADGE_TONES = ("plain", "navy", "green", "red")
BADGE_PRESETS = (
    "Nuova pubblicazione", "Nuovo emendamento", "Aggiornamento", "Approvato", "Respinto",
    "In vigore", "Scade oggi", "Si vota", "Correzione",
)
ITER_STEPS = {
    "camera": ("Camera", "Senato", "Navetta", "Gazzetta Ufficiale"),
    "senato": ("Senato", "Camera", "Navetta", "Gazzetta Ufficiale"),
}
ITER_STATES = ("in_corso", "fermo", "concluso")
MAX_PEOPLE = 3
MAX_PARTIES = 6


def current_parties(session: Session, politician_ids: list[int]) -> dict[int, PoliticalParty]:
    """Each politician's current party (affiliation without an end date)."""

    if not politician_ids:
        return {}
    result: dict[int, PoliticalParty] = {}
    for affiliation, party in session.execute(
        select(PoliticalPartyAffiliation, PoliticalParty)
        .join(PoliticalParty, PoliticalParty.id == PoliticalPartyAffiliation.political_party_id)
        .where(
            PoliticalPartyAffiliation.politician_id.in_(politician_ids),
            PoliticalPartyAffiliation.end_date.is_(None),
        )
        .order_by(PoliticalPartyAffiliation.start_date.desc())
    ):
        result.setdefault(affiliation.politician_id, party)
    return result


def party_dict(party: PoliticalParty) -> dict:
    return {"id": party.id, "name": party.canonical_name, "abbreviation": party.abbreviation}


def _text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _date(value: Any) -> str | None:
    try:
        return date.fromisoformat(str(value)).isoformat() if value else None
    except ValueError:
        return None


def sanitize(card: dict | None, session: Session) -> dict | None:
    """Keep only known fields, check references, cap lengths."""

    if not card:
        return None
    category = card.get("category") if card.get("category") in CATEGORIES else "notizia"
    badge = card.get("badge") or {}
    # People are politicians with a profile: name and party come from the profile.
    people = []
    seen: set[int] = set()
    for person in card.get("people") or []:
        politician_id = person.get("politician_id")
        politician_id = int(politician_id) if str(politician_id or "").isdigit() else None
        if politician_id is None or politician_id in seen or session.get(Politician, politician_id) is None:
            continue
        image_id = person.get("image_id")
        image_id = int(image_id) if str(image_id or "").isdigit() else None
        if image_id is not None and session.get(EditorialImage, image_id) is None:
            image_id = None
        seen.add(politician_id)
        people.append(
            {
                "politician_id": politician_id,
                "image_id": image_id,
                "use_portrait": bool(person.get("use_portrait")) and image_id is None,
            }
        )
        if len(people) == MAX_PEOPLE:
            break
    parties = []
    for value in card.get("parties") or []:
        party_id = int(value) if str(value or "").isdigit() else None
        if party_id and party_id not in parties and session.get(PoliticalParty, party_id) is not None:
            parties.append(party_id)
    parties = parties[:MAX_PARTIES]
    iter_data = card.get("iter") or None
    if iter_data and iter_data.get("enabled", True):
        first = iter_data.get("first") if iter_data.get("first") in ITER_STEPS else "camera"
        try:
            current = min(4, max(1, int(iter_data.get("current") or 1)))
        except (TypeError, ValueError):
            current = 1
        state = iter_data.get("state") if iter_data.get("state") in ITER_STATES else "in_corso"
        iter_clean = {
            "first": first,
            "current": current,
            "state": state,
            "status": _text(iter_data.get("status"), 160) or None,
            "since_label": _text(iter_data.get("since_label"), 40) or "Presentato il",
            "since": _date(iter_data.get("since")),
        }
    else:
        iter_clean = None
    link = card.get("link") or {}
    link_url = _text(link.get("url"), 1000)
    return {
        "category": category,
        "badge": {
            "label": _text(badge.get("label"), 60) or "Nuova pubblicazione",
            "tone": badge.get("tone") if badge.get("tone") in BADGE_TONES else "plain",
            "date": _date(badge.get("date")),
        },
        "aside": _text(card.get("aside"), 80) or None,
        "people": people,
        "parties": parties,
        "institution": _text(card.get("institution"), 160) or None,
        "iter": iter_clean,
        "link": (
            {"label": _text(link.get("label"), 60) or "Leggi la fonte", "url": link_url}
            if link_url and is_complete_source_url(link_url)
            else None
        ),
    }


def public(card: dict | None, session: Session, *, portrait_ids: frozenset[int] = frozenset()) -> dict | None:
    """What the reader's app needs to draw the card."""

    if not card:
        return None
    label, tone = CATEGORIES.get(card.get("category"), CATEGORIES["notizia"])
    ids = [p["politician_id"] for p in card.get("people", []) if p.get("politician_id")]
    politicians = {row.id: row for row in session.scalars(select(Politician).where(Politician.id.in_(ids)))} if ids else {}
    party_of = current_parties(session, ids)
    people = []
    for person in card.get("people", []):
        politician = politicians.get(person.get("politician_id"))
        if politician is None:
            continue  # cards only show politicians with a profile
        image_url = None
        if person.get("image_id"):
            image_url = f"/media/{person['image_id']}"
        elif person.get("use_portrait"):
            image_url = f"politician:{politician.id}"
        party = party_of.get(politician.id)
        people.append(
            {
                "name": f"{politician.canonical_given_name} {politician.canonical_family_name}",
                "role": party.canonical_name if party else None,
                "politician_id": politician.id,
                "party_id": party.id if party else None,
                "image_url": image_url,
            }
        )
    # Parties involved: those chosen by the redazione plus the people's own parties.
    party_ids = list(card.get("parties") or [])
    for person in people:
        if person["party_id"] and person["party_id"] not in party_ids:
            party_ids.append(person["party_id"])
    parties_by_id = {row.id: row for row in session.scalars(select(PoliticalParty).where(PoliticalParty.id.in_(party_ids)))} if party_ids else {}
    parties = [party_dict(parties_by_id[pid]) for pid in party_ids if pid in parties_by_id]
    iter_data = card.get("iter")
    if iter_data:
        names_of_steps = ITER_STEPS[iter_data["first"]]
        steps = []
        for index, step_label in enumerate(names_of_steps, start=1):
            if index < iter_data["current"] or (iter_data["state"] == "concluso" and index <= iter_data["current"]):
                state = "done"
            elif index == iter_data["current"]:
                state = "stopped" if iter_data["state"] == "fermo" else "current"
            else:
                state = "todo"
            steps.append({"label": step_label, "state": state})
        iter_public = {**iter_data, "steps": steps}
    else:
        iter_public = None
    return {
        "category": card.get("category"),
        "category_label": label,
        "tone": tone,
        "badge": card.get("badge"),
        "aside": card.get("aside"),
        "people": people,
        "parties": parties,
        "institution": card.get("institution"),
        "iter": iter_public,
        "link": card.get("link"),
    }


def options() -> dict:
    return {
        "categories": [{"key": key, "label": label, "tone": tone} for key, (label, tone) in CATEGORIES.items()],
        "badge_presets": list(BADGE_PRESETS),
        "badge_tones": list(BADGE_TONES),
        "iter_steps": {key: list(value) for key, value in ITER_STEPS.items()},
        "iter_states": list(ITER_STATES),
        "max_people": MAX_PEOPLE,
    }
