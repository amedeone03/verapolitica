from datetime import date

import pytest

from backend.app.scoring import (
    AlphaMetric,
    BiasObservation,
    CommitmentType,
    FulfillmentVerdict,
    HolderRole,
    MandateProgress,
    PledgeOutcome,
    PledgeSpecificity,
    ScoringMethodology,
    compute_scorecard,
    design_based_mean,
    draw_audit_sample,
    krippendorff_alpha,
    partisan_skew_audit,
)
from backend.app.scoring.beta import beta_quantile, regularized_incomplete_beta
from backend.app.scoring.evidence_matching import (
    EvidenceJudgment,
    Passage,
    analyze,
    excerpt_is_verbatim,
    reciprocal_rank_fusion,
    retrieve,
    validate_judgment,
)
from backend.app.scoring.types import EvidenceLabel

K, P, B = FulfillmentVerdict.KEPT, FulfillmentVerdict.PARTIALLY_KEPT, FulfillmentVerdict.BROKEN
OPEN = FulfillmentVerdict.IN_PROGRESS
GOV, OPP = HolderRole.GOVERNMENT_COALITION, HolderRole.OPPOSITION


def outcome(pledge_id, verdict, role=GOV, specificity=PledgeSpecificity.HIGH, topic=None):
    return PledgeOutcome(
        pledge_id=pledge_id,
        verdict=verdict,
        role=role,
        specificity=specificity,
        commitment_type=CommitmentType.ACTION,
        topic_code=topic,
    )


# --------------------------------------------------------------------- beta
def test_beta_cdf_and_quantile_match_reference_values():
    assert regularized_incomplete_beta(0.5, 2, 2) == pytest.approx(0.5)
    assert regularized_incomplete_beta(0.3, 2, 5) == pytest.approx(0.579825, abs=1e-6)
    assert beta_quantile(0.05, 2, 3) == pytest.approx(0.097611, abs=1e-5)
    assert beta_quantile(0.5, 0.5, 0.5) == pytest.approx(0.5, abs=1e-9)


# ----------------------------------------------------------------- scorecard
def test_scorecard_uses_closed_denominator_and_half_weight_for_partial():
    outcomes = [outcome(i, K) for i in range(6)] + [
        outcome(10, P), outcome(11, P), outcome(12, B), outcome(13, B),
        outcome(20, OPEN), outcome(21, FulfillmentVerdict.NOT_YET_RATED),
    ]
    card = compute_scorecard(outcomes)
    stratum = card.stratum(GOV)
    assert stratum.closed_pledges == 10
    assert stratum.open_pledges == 2
    assert stratum.kept_equivalent == 7.0
    assert stratum.rate == 0.7
    low, high = stratum.credible_interval
    assert low < 0.7 < high
    assert stratum.rate_withheld_reason is None
    assert dict(stratum.composition)[OPEN] == 1


def test_scorecard_never_mixes_roles():
    outcomes = [outcome(i, K, GOV) for i in range(8)] + [outcome(100 + i, B, OPP) for i in range(8)]
    card = compute_scorecard(outcomes)
    assert [s.role for s in card.strata] == [GOV, OPP]
    assert card.stratum(GOV).rate == 1.0
    assert card.stratum(OPP).rate == 0.0
    assert not hasattr(card, "rate")


def test_scorecard_withholds_rate_for_small_numbers_but_keeps_interval():
    card = compute_scorecard([outcome(1, K), outcome(2, K), outcome(3, K)])
    stratum = card.stratum(GOV)
    assert stratum.rate is None
    assert stratum.rate_withheld_reason == "below_minimum_closed_pledges"
    low, high = stratum.credible_interval
    # 3/3 kept is far from "100%": the interval stays wide.
    assert low < 0.6 and high > 0.99


def test_scorecard_excludes_vague_pledges_and_handles_no_closed():
    card = compute_scorecard(
        [outcome(1, K, specificity=PledgeSpecificity.VAGUE), outcome(2, OPEN)]
    )
    assert card.tracked_pledges == 2
    assert card.excluded_vague_pledges == 1
    stratum = card.stratum(GOV)
    assert stratum.scored_pledges == 1
    assert stratum.rate is None and stratum.credible_interval is None
    assert stratum.rate_withheld_reason == "no_closed_pledges"


def test_scorecard_rejects_duplicates_and_reports_methodology():
    with pytest.raises(ValueError):
        compute_scorecard([outcome(1, K), outcome(1, B)])
    custom = ScoringMethodology(min_closed_for_rate=1)
    card = compute_scorecard([outcome(1, K)], methodology=custom)
    assert card.methodology_version == "pledge-score/v1"
    assert card.stratum(GOV).rate == 1.0


def test_mandate_progress_is_clamped():
    progress = MandateProgress(date(2022, 10, 1), date(2027, 10, 1), date(2025, 4, 1))
    assert 0.49 < progress.elapsed_fraction < 0.51
    assert MandateProgress(date(2022, 1, 1), date(2023, 1, 1), date(2030, 1, 1)).elapsed_fraction == 1.0


# -------------------------------------------------------------- agreement
KRIPPENDORFF_2011 = list(
    zip(
        [1, 2, 3, 3, 2, 1, 4, 1, 2, None, None, None],
        [1, 2, 3, 3, 2, 2, 4, 1, 2, 5, None, 3],
        [None, 3, 3, 3, 2, 3, 4, 2, 2, 5, 1, None],
        [1, 2, 3, 3, 2, 4, 4, 1, 2, 5, 1, None],
    )
)


def test_krippendorff_alpha_matches_published_example():
    assert krippendorff_alpha(KRIPPENDORFF_2011).alpha == pytest.approx(0.743, abs=1e-3)
    ordinal = krippendorff_alpha(
        KRIPPENDORFF_2011, metric=AlphaMetric.ORDINAL, order=[1, 2, 3, 4, 5]
    )
    assert ordinal.alpha == pytest.approx(0.815, abs=1e-3)
    interval = krippendorff_alpha(KRIPPENDORFF_2011, metric=AlphaMetric.INTERVAL)
    assert interval.alpha == pytest.approx(0.849, abs=1e-3)
    # The unit coded by a single coder is not pairable.
    assert ordinal.pairable_units == 11


def test_krippendorff_alpha_edge_cases():
    assert krippendorff_alpha([[K, K], [B, B]]).alpha == 1.0
    assert krippendorff_alpha([[K, None]]).alpha is None
    with pytest.raises(ValueError):
        krippendorff_alpha([[K, B]], metric=AlphaMetric.ORDINAL)


# ---------------------------------------------------------- audit correction
def test_audit_sample_is_reproducible():
    first = draw_audit_sample(range(1, 101), size=10, seed=7, sample_key="q1")
    second = draw_audit_sample(range(100, 0, -1), size=10, seed=7, sample_key="q1")
    assert first.selected_ids == second.selected_ids
    assert first.inclusion_probability == 0.1
    assert draw_audit_sample([1, 2], size=5, seed=1, sample_key="x").selected_ids == (1, 2)


def test_design_based_mean_corrects_systematic_overrating():
    # First-pass labels say everything was kept; truth: half were broken.
    population = {i: 1.0 for i in range(1, 201)}
    truth = {i: (1.0 if i % 2 else 0.0) for i in population}
    sample = draw_audit_sample(list(population), size=50, seed=3, sample_key="s")
    audited = {i: truth[i] for i in sample.selected_ids}
    estimate = design_based_mean(
        population, audited, inclusion_probability=sample.inclusion_probability
    )
    assert estimate.naive_estimate == 1.0
    assert estimate.corrected_estimate == pytest.approx(
        sum(audited.values()) / len(audited), abs=1e-9
    )
    low, high = estimate.confidence_interval
    assert high < 1.0  # the corrected interval rules out the naive 100%
    assert low < 0.5 < high
    assert estimate.disagreement_rate == pytest.approx(
        sum(1 for v in audited.values() if v == 0.0) / 50
    )


def test_design_based_mean_is_exact_with_perfect_labels():
    population = {1: 1.0, 2: 0.0, 3: 0.5, 4: 1.0}
    estimate = design_based_mean(population, {1: 1.0, 2: 0.0}, inclusion_probability=0.5)
    assert estimate.corrected_estimate == estimate.naive_estimate == 0.625
    with pytest.raises(ValueError):
        design_based_mean(population, {9: 1.0}, inclusion_probability=0.5)


# --------------------------------------------------------------- bias audit
def test_bias_audit_flags_skew_within_equal_role_and_period():
    observations = []
    for i in range(20):
        observations.append(BiasObservation("party:A", "government_coalition", "2022", 1.0 if i < 18 else 0.0))
        observations.append(BiasObservation("party:B", "government_coalition", "2022", 1.0 if i < 6 else 0.0))
    report = partisan_skew_audit(observations)
    flagged = {item.bloc for item in report.flagged}
    assert flagged == {"party:A", "party:B"}
    a = next(item for item in report.comparisons if item.bloc == "party:A")
    assert a.weighted_difference == pytest.approx(0.6)


def test_bias_audit_does_not_compare_across_roles():
    observations = [BiasObservation("party:A", "government_coalition", "2022", 1.0)] * 10 + [
        BiasObservation("party:B", "opposition", "2022", 0.0)
    ] * 10
    report = partisan_skew_audit(observations)
    assert report.comparisons == ()
    assert report.skipped_strata == 2


# ----------------------------------------------------------- evidence matching
def test_analyzer_normalises_accents_and_stems():
    assert analyze("Riforma delle pensioni") == analyze("riforme  della PENSIONE")
    tokens = analyze("La riforma della città entro il 2025")
    assert "riform" in tokens and "citta" in tokens and "2025" in tokens
    assert "della" not in tokens


def test_hybrid_retrieval_ranks_relevant_passage_first():
    passages = [
        Passage(1, 10, "Approvato il decreto sul turismo montano.", "https://x/1"),
        Passage(2, 11, "La Camera ha approvato la riforma delle pensioni minime.", "https://x/2"),
        Passage(3, 12, "Calendario dei lavori della commissione bilancio.", "https://x/3"),
    ]
    ranked = retrieve("aumenteremo le pensioni minime con una riforma", passages, limit=2)
    assert ranked[0].passage.passage_id == 2

    class Embedder:
        def embed(self, texts):
            return [[1.0, 0.0] if "turismo" in t or t.startswith("vacanze") else [0.0, 1.0] for t in texts]

    ranked = retrieve("vacanze in montagna", passages, limit=1, embedder=Embedder())
    assert ranked[0].passage.passage_id == 1
    assert ranked[0].semantic_rank == 1


def test_reciprocal_rank_fusion_rewards_agreement():
    fused = reciprocal_rank_fusion([[1, 2, 3], [2, 1, 3]])
    assert fused[1] == fused[2] > fused[3]


def test_validate_judgment_enforces_fever_rules_and_verbatim_citations():
    text = "Il Senato ha approvato in via definitiva la legge sul salario minimo."
    ok = EvidenceJudgment(
        EvidenceLabel.SUPPORTS, K, "approvato in via definitiva la legge", "Legge approvata."
    )
    assert validate_judgment(ok, text) is None
    assert excerpt_is_verbatim(text, "approvato   in via\ndefinitiva la legge")
    nei = EvidenceJudgment(EvidenceLabel.NOT_ENOUGH_INFO, None, "", "")
    assert validate_judgment(nei, text) == "not_enough_info"
    wrong_label = EvidenceJudgment(EvidenceLabel.REFUTES, K, "approvato in via definitiva", "x")
    assert validate_judgment(wrong_label, text) == "verdict_incompatible_with_label"
    invented = EvidenceJudgment(EvidenceLabel.SUPPORTS, K, "approvato all'unanimità ieri", "x")
    assert validate_judgment(invented, text) == "excerpt_not_found_in_source"
