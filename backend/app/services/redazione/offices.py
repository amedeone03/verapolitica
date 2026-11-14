"""Catalog of political offices the redazione can attach when adding a person.

Camera/Senato/Governo imports cover many profiles automatically. Everyone else
(PdR, europarlamento, regioni, comuni, …) still needs a selectable carica so
the scheda and the first mandate are not limited to the cabinet.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PoliticalOffice:
    label: str
    institution: str
    mandate_type: str
    legislature: str


# Keys stay stable (stored on the mandate ``office`` field). Labels are what
# the verifier and the citizen see in queue previews.
POLITICAL_OFFICES: dict[str, PoliticalOffice] = {
    # Istituzioni nazionali
    "presidente della repubblica": PoliticalOffice(
        "Presidente della Repubblica",
        "Presidenza della Repubblica",
        "quirinale",
        "Quirinale",
    ),
    "presidente del consiglio": PoliticalOffice(
        "Presidente del Consiglio dei ministri",
        "Governo della Repubblica",
        "government",
        "Governo",
    ),
    "vice presidente del consiglio": PoliticalOffice(
        "Vicepresidente del Consiglio dei ministri",
        "Governo della Repubblica",
        "government",
        "Governo",
    ),
    "ministro": PoliticalOffice(
        "Ministro",
        "Governo della Repubblica",
        "government",
        "Governo",
    ),
    "ministro senza portafoglio": PoliticalOffice(
        "Ministro senza portafoglio",
        "Governo della Repubblica",
        "government",
        "Governo",
    ),
    "sottosegretario": PoliticalOffice(
        "Sottosegretario",
        "Governo della Repubblica",
        "government",
        "Governo",
    ),
    "deputato": PoliticalOffice(
        "Deputato",
        "Camera dei deputati",
        "parliament",
        "Parlamento",
    ),
    "senatore": PoliticalOffice(
        "Senatore",
        "Senato della Repubblica",
        "parliament",
        "Parlamento",
    ),
    "europarlamentare": PoliticalOffice(
        "Europarlamentare",
        "Parlamento europeo",
        "european",
        "Parlamento europeo",
    ),
    # Regioni
    "presidente della regione": PoliticalOffice(
        "Presidente della Regione",
        "Regione",
        "regional",
        "Regione",
    ),
    "vicepresidente della regione": PoliticalOffice(
        "Vicepresidente della Regione",
        "Regione",
        "regional",
        "Regione",
    ),
    "assessore regionale": PoliticalOffice(
        "Assessore regionale",
        "Regione",
        "regional",
        "Regione",
    ),
    "consigliere regionale": PoliticalOffice(
        "Consigliere regionale",
        "Consiglio regionale",
        "regional",
        "Regione",
    ),
    # Province / città metropolitane
    "presidente della provincia": PoliticalOffice(
        "Presidente della Provincia",
        "Provincia",
        "provincial",
        "Provincia",
    ),
    "consigliere provinciale": PoliticalOffice(
        "Consigliere provinciale",
        "Consiglio provinciale",
        "provincial",
        "Provincia",
    ),
    # Comuni
    "sindaco": PoliticalOffice(
        "Sindaco",
        "Comune",
        "municipal",
        "Comune",
    ),
    "vicesindaco": PoliticalOffice(
        "Vicesindaco",
        "Comune",
        "municipal",
        "Comune",
    ),
    "assessore comunale": PoliticalOffice(
        "Assessore comunale",
        "Comune",
        "municipal",
        "Comune",
    ),
    "consigliere comunale": PoliticalOffice(
        "Consigliere comunale",
        "Consiglio comunale",
        "municipal",
        "Comune",
    ),
}

# Kept for callers that still expect the old cabinet-only map of label strings.
GOVERNMENT_OFFICES: dict[str, str] = {
    key: office.label
    for key, office in POLITICAL_OFFICES.items()
    if office.mandate_type == "government"
}


def office_label(key: str | None) -> str | None:
    if not key:
        return None
    office = POLITICAL_OFFICES.get(key)
    return office.label if office else None


def office_defaults(key: str) -> PoliticalOffice:
    return POLITICAL_OFFICES[key]
