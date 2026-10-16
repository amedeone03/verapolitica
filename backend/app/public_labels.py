"""Citizen-facing Italian labels for public presentation.

Internal enum values and API field names stay unchanged. These maps are
display-only and must not be used by scoring, review, or evidence matching.
"""

from __future__ import annotations

PROPOSAL_TYPE_LABELS: dict[str, str] = {
    "proposal": "Proposta",
    "legislative_proposal": "Proposta di legge",
    "government_initiative": "Iniziativa governativa",
    "explicit_promise": "Promessa esplicita",
}

PROPOSAL_STATUS_LABELS: dict[str, str] = {
    "announced": "Annunciata",
    "introduced": "Presentata",
    "assigned": "Assegnata",
    "under_review": "In esame",
    "approved": "Approvata",
    "rejected": "Respinta",
    "withdrawn": "Ritirata",
    "enacted": "Promulgata",
    "completed": "Conclusa",
    "superseded": "Superata",
    "lapsed": "Decaduta",
    "returned": "Rinviata",
}

PROPOSAL_ACTOR_ROLE_LABELS: dict[str, str] = {
    "proposer": "Proponente",
    "sponsor": "Firmatario",
    "co_sponsor": "Cofirmatario",
    "government": "Governo",
    "commitment_owner": "Titolare della promessa",
}

REFERENDUM_TYPE_LABELS: dict[str, str] = {
    "national_abrogative": "abrogativo nazionale",
    "constitutional": "costituzionale",
    "regional": "regionale",
    "municipal": "comunale",
    "consultative": "consultivo",
    "other": "altro",
}

REFERENDUM_STATUS_LABELS: dict[str, str] = {
    "scheduled": "in programma",
    "open": "aperto",
    "closed": "chiuso",
    "cancelled": "annullato",
    "completed": "concluso",
}

SCOPE_TYPE_LABELS: dict[str, str] = {
    "national": "nazionale",
    "region": "regionale",
    "municipality": "comunale",
}


def _lookup(mapping: dict[str, str], value: object | None, fallback: str) -> str:
    if value is None:
        return fallback
    key = value.value if hasattr(value, "value") else str(value)
    return mapping.get(key, key.replace("_", " "))


def public_proposal_type_label(value: object | None) -> str:
    return _lookup(PROPOSAL_TYPE_LABELS, value, "Proposta")


def public_proposal_status_label(value: object | None) -> str:
    return _lookup(PROPOSAL_STATUS_LABELS, value, "Pubblicata")


def public_proposal_actor_role_label(value: object | None) -> str:
    return _lookup(PROPOSAL_ACTOR_ROLE_LABELS, value, "Ruolo")


def public_referendum_type_label(value: object | None) -> str:
    return _lookup(REFERENDUM_TYPE_LABELS, value, "referendum")


def public_referendum_status_label(value: object | None) -> str:
    return _lookup(REFERENDUM_STATUS_LABELS, value, "stato")


def public_scope_type_label(value: object | None) -> str:
    return _lookup(SCOPE_TYPE_LABELS, value, "ambito")
