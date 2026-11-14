"""N1–N4: news week, proposal triad, scoped cosa_cambia, source gate."""

from __future__ import annotations

from datetime import date, datetime

from backend.app.services.redazione.news_week import news_week, week_bounds
from backend.app.services.redazione.style import (
    cosa_cambia_label,
    has_errors,
    is_weak_source_host,
    news_findings,
)


def _base_blocks(**extra):
    blocks = {
        "sommario": "Il Consiglio dei ministri ha approvato il 16 settembre 2026 un decreto-legge sul bollo auto.",
        "perche": "Il bollo riguarda la gran parte degli automobilisti e il decreto va convertito entro il 16 novembre.",
        "fatto": "Il Consiglio dei ministri ha approvato un decreto-legge che azzera il bollo 2027 per una sola auto fino a 80 kW.",
        "cosa_cambia": "- Una sola auto fino a 80 kW: non paghi il bollo nel 2027.\n- Auto sopra i 185 kW: continui a pagare.",
        "destra": "- Fratelli d'Italia: misura pensata per essere strutturale.\n- Lega: valuta anche il superbollo.",
        "sinistra": "- Partito Democratico: misura limitata al 2027.\n- Movimento 5 Stelle: il risparmio medio è basso.",
    }
    blocks.update(extra)
    return blocks


def _good_sources():
    return [
        {"name": "ANSA", "url": "https://www.ansa.it/sito/notizie/economia/2026/09/16/bollo-auto.html", "date": "2026-09-16", "area": "agenzia"},
        {"name": "Il Giornale", "url": "https://www.ilgiornale.it/news/politica/bollo-auto-2027.html", "date": "2026-09-16", "area": "centrodestra"},
        {"name": "Domani", "url": "https://www.editorialedomani.it/politica/bollo-auto-2027-esenzione", "date": "2026-09-16", "area": "centrosinistra"},
    ]


def test_news_week_runs_tuesday_to_monday():
    # Thursday 12 Nov 2026 → week Tue 10 → Mon 16
    week = news_week(now=datetime(2026, 11, 12, 10, 0, 0))
    assert week.week_start == "2026-11-10"
    assert week.week_end == "2026-11-16"
    assert week.proposals_on == "2026-11-13"
    assert week.assignments_on == "2026-11-16"
    assert week.phase == "scrittura"

    friday = news_week(now=datetime(2026, 11, 13, 15, 0, 0))
    assert friday.phase == "proposte"
    monday = news_week(now=datetime(2026, 11, 16, 9, 0, 0))
    assert monday.phase == "assegnazioni"
    assert week_bounds(date.fromisoformat(monday.today)) == (date(2026, 11, 10), date(2026, 11, 16))


def test_proposal_triad_requires_public_interest():
    findings = news_findings(
        {
            "title": "Bollo auto 2027: esenzione per una sola auto fino a 80 kW",
            "scope": "national",
            "blocks": _base_blocks(perche=""),
            "sources": _good_sources(),
        }
    )
    assert any(f.code == "blocco_vuoto" and f.field == "perche" for f in findings)
    assert has_errors(findings)


def test_cosa_cambia_label_follows_scope():
    assert "nazionale" in cosa_cambia_label("national").casefold()
    assert "regione" in cosa_cambia_label("region").casefold()
    assert "provincia" in cosa_cambia_label("province").casefold()
    assert "comune" in cosa_cambia_label("municipality").casefold()


def test_weak_or_undated_sources_block_approval():
    assert is_weak_source_host("https://it.wikipedia.org/wiki/Bollo_auto")
    assert is_weak_source_host("https://www.facebook.com/posts/123")
    assert not is_weak_source_host("https://www.ansa.it/sito/notizie/economia/2026/09/16/bollo-auto.html")

    wiki = news_findings(
        {
            "title": "Bollo auto 2027: esenzione per una sola auto fino a 80 kW",
            "scope": "region",
            "blocks": _base_blocks(),
            "sources": [
                {"name": "Wikipedia", "url": "https://it.wikipedia.org/wiki/Bollo_auto", "date": "2026-09-16", "area": "altro"},
                {"name": "Il Giornale", "url": "https://www.ilgiornale.it/news/politica/bollo-auto-2027.html", "date": "2026-09-16", "area": "centrodestra"},
                {"name": "Domani", "url": "https://www.editorialedomani.it/politica/bollo-auto-2027-esenzione", "date": "2026-09-16", "area": "centrosinistra"},
            ],
        }
    )
    assert any(f.code == "fonte_inattendibile" for f in wiki)

    undated = news_findings(
        {
            "title": "Bollo auto 2027: esenzione per una sola auto fino a 80 kW",
            "scope": "national",
            "blocks": _base_blocks(),
            "sources": [
                {**item, "date": None} for item in _good_sources()
            ],
        }
    )
    assert any(f.code == "fonte_senza_data" for f in undated)
    assert has_errors(undated)

    ok = news_findings(
        {
            "title": "Bollo auto 2027: esenzione per una sola auto fino a 80 kW",
            "scope": "national",
            "blocks": _base_blocks(),
            "sources": _good_sources(),
        }
    )
    assert not has_errors(ok)
