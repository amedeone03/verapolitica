from datetime import date, datetime, timezone

from backend.app.scoring.conservative_evidence_judge import ConservativeOfficialActJudge
from backend.app.scoring.evidence_matching import EvidenceJudgment, Passage
from backend.app.scoring.llm_evidence_judge import parse_judge_output
from backend.app.scoring.instrument_aliases import ALIAS_POLICY_VERSION
from backend.app.scoring.official_evidence import (
    MATCHER_VERSION,
    OfficialPassage,
    retrieve_official_candidates,
    validate_official_judgment,
)
from backend.app.scoring.official_sources import classify_source_url, is_official_source_url
from backend.app.scoring.retrieval_profile import (
    RETRIEVAL_POLICY_VERSION,
    build_retrieval_profile,
)
from backend.app.scoring.types import (
    CommitmentType,
    EvidenceLabel,
    FulfillmentVerdict,
    PledgeSpecificity,
)


def _profile(**overrides):
    values = dict(
        proposal_id=106,
        title="Autonomia differenziata",
        commitment_text="intendiamo dare seguito al processo virtuoso di autonomia differenziata",
        actor_names=("Giorgia Meloni",),
        topic_code="20",
        specificity=PledgeSpecificity.HIGH,
        commitment_type=CommitmentType.ACTION,
        announcement_date=date(2022, 10, 25),
        mandate_start=date(2022, 10, 22),
        mandate_end=date(2027, 10, 12),
        origin_urls=("https://www.governo.it/it/articolo/le-dichiarazioni-programmatiche-del-governo-meloni/20770",),
    )
    values.update(overrides)
    return build_retrieval_profile(**values)


def _passage(url, text, *, passage_id=1, raw_id=10, published=date(2024, 6, 26)):
    return OfficialPassage(
        passage=Passage(passage_id, raw_id, text, url),
        source_id=1,
        source_key="gazzetta",
        source_name="Gazzetta Ufficiale",
        retrieved_at=datetime(2026, 10, 9, tzinfo=timezone.utc),
        published_at=published,
    )


def test_official_source_allowlist_rejects_news_and_http():
    assert is_official_source_url("https://www.gazzettaufficiale.it/eli/id/2024/06/28/24G00105/sg")
    assert is_official_source_url("https://www.governo.it/it/articolo/x")
    assert classify_source_url("https://www.corriere.it/politica/autonomia").reason == "blocked_non_official_host"
    assert classify_source_url("http://www.governo.it/it/x").reason == "source_not_https"
    assert classify_source_url("https://blog.example/autonomia").reason == "unofficial_host"


def test_no_candidate_when_corpus_empty_or_only_origin():
    profile = _profile()
    origin = _passage(
        "https://www.governo.it/it/articolo/le-dichiarazioni-programmatiche-del-governo-meloni/20770",
        "intendiamo dare seguito al processo virtuoso di autonomia differenziata",
    )
    candidates, reasons = retrieve_official_candidates(profile, [origin])
    assert candidates == []
    assert reasons["origin_document"] == 1
    none, empty_reasons = retrieve_official_candidates(profile, [])
    assert none == [] and empty_reasons == {}


def test_same_topic_and_title_only_documents_do_not_retrieve_without_instrument():
    justice = build_retrieval_profile(
        proposal_id=103,
        title="Certezza della pena e nuovo piano carceri",
        commitment_text="rimettendo al centro il principio fondamentale della certezza della pena, grazie anche a un nuovo piano carceri.",
        actor_names=("Giorgia Meloni",),
        topic_code="12",
        specificity=PledgeSpecificity.HIGH,
        commitment_type=CommitmentType.ACTION,
        announcement_date=date(2022, 10, 25),
        mandate_start=date(2022, 10, 22),
        mandate_end=date(2027, 10, 12),
    )
    title_only = _passage(
        "https://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:legge:2024-08-09;114",
        "LEGGE 9 agosto 2024, n. 114. Modifiche all'ordinamento giudiziario e tabelle infradistrettuali.",
    )
    candidates, reasons = retrieve_official_candidates(justice, [title_only])
    assert candidates == []
    assert reasons["missing_instrument_overlap"] == 1


def test_procedural_calendar_is_not_a_candidate():
    profile = build_retrieval_profile(
        proposal_id=104,
        title="Riforma dell'ordinamento giudiziario",
        commitment_text="rivedremo anche la riforma dell'ordinamento giudiziario per le logiche correntizie",
        actor_names=("Giorgia Meloni",),
        topic_code="12",
        specificity=PledgeSpecificity.HIGH,
        commitment_type=CommitmentType.ACTION,
        announcement_date=date(2022, 10, 25),
        mandate_start=date(2022, 10, 22),
        mandate_end=date(2027, 10, 12),
    )
    calendar = _passage(
        "https://www.giustizia.it/giustizia/it/mg_2_4.page",
        "Il Ministero della giustizia pubblica il calendario delle commissioni per marzo.",
        published=date(2024, 3, 1),
    )
    candidates, reasons = retrieve_official_candidates(profile, [calendar])
    assert candidates == []
    assert reasons["missing_instrument_overlap"] == 1


def test_same_topic_without_instrument_abstains():
    profile = _profile()
    justice = _passage(
        "https://www.giustizia.it/calendario",
        "Il Ministero della giustizia pubblica il calendario delle commissioni.",
        published=date(2024, 3, 1),
    )
    candidates, reasons = retrieve_official_candidates(profile, [justice])
    assert candidates == []
    assert reasons["missing_instrument_overlap"] == 1


def test_other_official_law_without_instrument_phrase_is_rejected():
    justice = build_retrieval_profile(
        proposal_id=104,
        title="Riforma dell'ordinamento giudiziario",
        commitment_text="rivedremo anche la riforma dell'ordinamento giudiziario per le logiche correntizie",
        actor_names=("Giorgia Meloni",),
        topic_code="12",
        specificity=PledgeSpecificity.HIGH,
        commitment_type=CommitmentType.ACTION,
        announcement_date=date(2022, 10, 25),
        mandate_start=date(2022, 10, 22),
        mandate_end=date(2027, 10, 12),
    )
    law = _passage(
        "https://www.gazzettaufficiale.it/eli/id/2024/06/28/24G00105/sg",
        "LEGGE 26 giugno 2024, n. 86. Disposizioni per l'attuazione dell'autonomia differenziata delle Regioni a statuto ordinario.",
    )
    candidates, reasons = retrieve_official_candidates(justice, [law])
    assert candidates == []
    assert reasons["missing_instrument_overlap"] == 1


def test_retrieval_policy_versions_are_deterministic():
    profile = _profile()
    assert MATCHER_VERSION == "pledge-evidence/v3"
    assert profile.retrieval_policy_version == RETRIEVAL_POLICY_VERSION
    assert profile.alias_policy_version == ALIAS_POLICY_VERSION
    assert RETRIEVAL_POLICY_VERSION == "pledge_evidence_retrieval_v2"
    assert ALIAS_POLICY_VERSION == "instrument-alias/v1"


def test_official_law_with_instrument_becomes_candidate():
    profile = _profile()
    law = _passage(
        "https://www.gazzettaufficiale.it/eli/id/2024/06/28/24G00105/sg",
        "LEGGE 26 giugno 2024, n. 86. Disposizioni per l'attuazione dell'autonomia differenziata delle Regioni.",
    )
    candidates, _reasons = retrieve_official_candidates(profile, [law])
    assert len(candidates) == 1
    assert "autonomia differenziata" in candidates[0].instrument_hits
    assert candidates[0].source_url.startswith("https://www.gazzettaufficiale.it")


def test_pre_announcement_document_is_outside_window():
    profile = _profile()
    old = _passage(
        "https://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:legge:2021;1",
        "Disposizioni per l'attuazione dell'autonomia differenziata",
        published=date(2021, 1, 1),
    )
    _candidates, reasons = retrieve_official_candidates(profile, [old])
    assert reasons["outside_date_window"] == 1


def test_validate_official_judgment_is_fail_closed():
    profile = _profile()
    text = "LEGGE 26 giugno 2024, n. 86. Disposizioni per l'attuazione dell'autonomia differenziata delle Regioni."
    ok = EvidenceJudgment(
        EvidenceLabel.SUPPORTS,
        FulfillmentVerdict.IN_PROGRESS,
        "attuazione dell'autonomia differenziata delle Regioni",
        "La legge attua il processo promesso.",
    )
    assert (
        validate_official_judgment(
            ok,
            text,
            source_url="https://www.gazzettaufficiale.it/eli/x",
            profile=profile,
            published_at=date(2024, 6, 26),
            is_origin=False,
        )
        is None
    )
    invented = EvidenceJudgment(
        EvidenceLabel.SUPPORTS,
        FulfillmentVerdict.IN_PROGRESS,
        "il governo ha mantenuto interamente la promessa",
        "ok",
    )
    assert (
        validate_official_judgment(
            invented,
            text,
            source_url="https://www.gazzettaufficiale.it/eli/x",
            profile=profile,
            published_at=date(2024, 6, 26),
            is_origin=False,
        )
        == "excerpt_not_found_in_source"
    )
    news = validate_official_judgment(
        ok,
        text,
        source_url="https://www.corriere.it/politica",
        profile=profile,
        published_at=date(2024, 6, 26),
        is_origin=False,
    )
    assert news == "blocked_non_official_host"
    kept_from_intent = EvidenceJudgment(
        EvidenceLabel.SUPPORTS,
        FulfillmentVerdict.KEPT,
        "intendiamo dare seguito al processo virtuoso di autonomia differenziata",
        "annuncio",
    )
    assert (
        validate_official_judgment(
            kept_from_intent,
            "intendiamo dare seguito al processo virtuoso di autonomia differenziata",
            source_url="https://www.governo.it/it/x",
            profile=profile,
            published_at=date(2023, 1, 1),
            is_origin=False,
        )
        == "announcement_is_not_fulfilment"
    )


def test_conservative_judge_never_proposes_closed_verdicts():
    judge = ConservativeOfficialActJudge()
    text = "LEGGE 26 giugno 2024, n. 86. Disposizioni per l'attuazione dell'autonomia differenziata delle Regioni. Promulga la seguente legge."
    judgment = judge.judge(
        pledge_text="dare seguito al processo di autonomia differenziata",
        commitment_type=CommitmentType.ACTION,
        passage_text=text,
    )
    assert judgment.label is EvidenceLabel.SUPPORTS
    assert judgment.proposed_verdict is FulfillmentVerdict.IN_PROGRESS
    unrelated = judge.judge(
        pledge_text="dare seguito al processo di autonomia differenziata",
        commitment_type=CommitmentType.ACTION,
        passage_text="Calendario dei lavori della commissione agricoltura.",
    )
    assert unrelated.label is EvidenceLabel.NOT_ENOUGH_INFO
    title_only = judge.judge(
        pledge_text=(
            "rivedremo anche la riforma dell'ordinamento giudiziario, "
            "per mettere fine alle logiche correntizie"
        ),
        commitment_type=CommitmentType.ACTION,
        passage_text=(
            "LEGGE 9 agosto 2024, n. 114. Promulga. Modifiche all'ordinamento "
            "giudiziario: tabelle infradistrettuali e collegio per la custodia cautelare."
        ),
    )
    assert title_only.label is EvidenceLabel.NOT_ENOUGH_INFO


def test_invalid_llm_json_is_not_rewritten():
    garbage = parse_judge_output({"foo": "bar"})
    assert garbage.label is EvidenceLabel.NOT_ENOUGH_INFO
    assert garbage.proposed_verdict is None
    incompatible = parse_judge_output(
        {
            "evidence_label": "supports",
            "proposed_verdict": "broken",
            "quoted_excerpt": "attuazione dell'autonomia differenziata",
            "rationale": "errato",
        }
    )
    assert incompatible.label is EvidenceLabel.SUPPORTS
    assert incompatible.proposed_verdict is FulfillmentVerdict.BROKEN
    profile = _profile()
    assert (
        validate_official_judgment(
            incompatible,
            "LEGGE 26 giugno 2024, n. 86. Disposizioni per l'attuazione dell'autonomia differenziata.",
            source_url="https://www.gazzettaufficiale.it/eli/x",
            profile=profile,
            published_at=date(2024, 6, 26),
            is_origin=False,
        )
        == "verdict_incompatible_with_label"
    )
