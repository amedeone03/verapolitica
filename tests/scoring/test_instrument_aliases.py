from datetime import date

from backend.app.scoring.instrument_aliases import (
    ALIAS_POLICY_VERSION,
    INSTRUMENT_ALIASES,
    aliases_for,
)
from backend.app.scoring.official_evidence import (
    OfficialPassage,
    retrieve_official_candidates,
)
from backend.app.scoring.retrieval_profile import (
    RETRIEVAL_POLICY_VERSION,
    build_retrieval_profile,
    extract_instrument_phrases,
)
from backend.app.scoring.types import CommitmentType, PledgeSpecificity
from tests.scoring.test_official_evidence import _passage


def _carceri_profile():
    return build_retrieval_profile(
        proposal_id=103,
        title="Certezza della pena e nuovo piano carceri",
        commitment_text=(
            "rimettendo al centro il principio fondamentale della certezza della pena, "
            "grazie anche a un nuovo piano carceri."
        ),
        actor_names=("Giorgia Meloni",),
        topic_code="12",
        specificity=PledgeSpecificity.HIGH,
        commitment_type=CommitmentType.ACTION,
        announcement_date=date(2022, 10, 25),
        mandate_start=date(2022, 10, 22),
        mandate_end=date(2027, 10, 12),
    )


def _fragili_profile():
    return build_retrieval_profile(
        proposal_id=107,
        title="Mantenere e migliorare il sostegno economico per i soggetti fragili",
        commitment_text=(
            "vogliamo mantenere e, laddove possibile, migliorare il doveroso sostegno "
            "economico per i soggetti effettivamente fragili non in condizioni di lavorare"
        ),
        actor_names=("Giorgia Meloni",),
        topic_code="13",
        specificity=PledgeSpecificity.HIGH,
        commitment_type=CommitmentType.ACTION,
        announcement_date=date(2022, 10, 25),
        mandate_start=date(2022, 10, 22),
        mandate_end=date(2027, 10, 12),
    )


def test_alias_policy_is_explicit_versioned_and_reviewable():
    assert ALIAS_POLICY_VERSION == "instrument-alias/v1"
    assert RETRIEVAL_POLICY_VERSION == "pledge_evidence_retrieval_v2"
    assert INSTRUMENT_ALIASES
    for item in INSTRUMENT_ALIASES:
        assert item.source
        assert item.alias
        assert item.topics
        assert item.reason
        assert item.source.casefold() != item.alias.casefold()


def test_aliases_preserve_original_terms_and_do_not_replace_them():
    profile = _carceri_profile()
    originals = extract_instrument_phrases(profile.title, profile.commitment_text)
    assert "piano carceri" in originals
    assert "piano carceri" in profile.original_instrument_phrases
    assert "piano carceri" in profile.instrument_phrases
    assert "edilizia penitenziaria" in profile.alias_phrases
    assert "strutture penitenziarie" in profile.alias_phrases
    assert "edilizia penitenziaria" not in profile.original_instrument_phrases
    assert "piano carceri" in profile.query
    assert "edilizia penitenziaria" in profile.query
    assert profile.retrieval_policy_version == RETRIEVAL_POLICY_VERSION
    assert profile.alias_policy_version == ALIAS_POLICY_VERSION


def test_aliases_require_source_phrase_and_matching_topic():
    assert aliases_for(("piano carceri",), topic_code="12") == (
        "edilizia penitenziaria",
        "strutture penitenziarie",
    )
    assert aliases_for(("piano carceri",), topic_code="13") == ()
    assert aliases_for(("assegno di inclusione",), topic_code="13") == ()
    assert aliases_for(("soggetti effettivamente fragili",), topic_code="13") == (
        "assegno di inclusione",
    )
    assert aliases_for((), topic_code="12") == ()


def test_alias_only_match_without_enactment_is_rejected():
    profile = _carceri_profile()
    overcrowding = _passage(
        "https://www.giustizia.it/giustizia/it/mg_1_14.page",
        (
            "Relazione sul sovraffollamento delle strutture penitenziarie. "
            "La nota non approva un programma di interventi di edilizia penitenziaria."
        ),
        published=date(2024, 9, 30),
    )
    candidates, reasons = retrieve_official_candidates(profile, [overcrowding])
    assert candidates == []
    assert reasons["alias_without_supporting_context"] == 1


def test_alias_with_topic_actor_and_enactment_recovers_prison_plan():
    profile = _carceri_profile()
    law = _passage(
        "https://www.gazzettaufficiale.it/eli/id/2024/08/09/24G00133/sg",
        (
            "LEGGE 8 agosto 2024, n. 112. Promulga. Istituzione del Commissario "
            "straordinario per l'edilizia penitenziaria e il programma degli "
            "interventi. Ministero della giustizia."
        ),
        published=date(2024, 8, 8),
    )
    candidates, _reasons = retrieve_official_candidates(profile, [law])
    assert len(candidates) == 1
    assert candidates[0].retrieval_reason == "official_alias_with_context"
    assert "edilizia penitenziaria" in candidates[0].instrument_hits
    assert "piano carceri" not in candidates[0].instrument_hits


def test_alias_with_context_recovers_assegno_di_inclusione():
    profile = _fragili_profile()
    assert "soggetti effettivamente fragili" in profile.original_instrument_phrases
    assert "assegno di inclusione" in profile.alias_phrases
    law = _passage(
        "https://www.gazzettaufficiale.it/eli/id/2023/07/03/23G00087/sg",
        (
            "LEGGE 3 luglio 2023, n. 85. Promulga. E' istituito l'Assegno di "
            "inclusione, quale misura nazionale di contrasto alla poverta'."
        ),
        published=date(2023, 7, 3),
    )
    candidates, _reasons = retrieve_official_candidates(profile, [law])
    assert len(candidates) == 1
    assert candidates[0].retrieval_reason == "official_alias_with_context"
    assert "assegno di inclusione" in candidates[0].instrument_hits


def test_hard_negatives_for_alias_families_stay_irrelevant():
    prison = _carceri_profile()
    welfare = _fragili_profile()
    negatives = [
        (
            prison,
            _passage(
                "https://www.giustizia.it/giustizia/it/mg_12.page",
                (
                    "Organigramma: Direzione generale per l'edilizia penitenziaria. "
                    "Non e' una legge e non istituisce nuovi posti detentivi."
                ),
            ),
        ),
        (
            prison,
            _passage(
                "https://www.giustizia.it/giustizia/it/mg_1_8.page",
                (
                    "Concorso per il Corpo di polizia penitenziaria. L'avviso non e' "
                    "un programma di edilizia penitenziaria."
                ),
            ),
        ),
        (
            welfare,
            _passage(
                "https://www.lavoro.gov.it/temi-e-priorita/poverta-ed-esclusione-sociale",
                (
                    "Linee guida per i servizi di inclusione sociale. Il documento "
                    "non disciplina l'Assegno di inclusione."
                ),
            ),
        ),
        (
            welfare,
            _passage(
                "https://www.istat.it/it/archivio/assegno-di-inclusione",
                (
                    "Nota statistica sui nuclei percettori dell'Assegno di inclusione. "
                    "La nota non e' una legge di attuazione."
                ),
            ),
        ),
        (
            welfare,
            _passage(
                "https://www.mef.gov.it/ufficio-stampa/comunicati/2023/assegno-unico/",
                (
                    "Erogazione dell'assegno unico e universale per i figli a carico. "
                    "La misura e' distinta dall'Assegno di inclusione."
                ),
            ),
        ),
    ]
    for profile, passage in negatives:
        candidates, reasons = retrieve_official_candidates(profile, [passage])
        assert candidates == []
        assert (
            reasons.get("alias_without_supporting_context")
            or reasons.get("missing_instrument_overlap")
        )
