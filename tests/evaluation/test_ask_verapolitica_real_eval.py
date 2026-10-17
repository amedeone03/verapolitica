from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from backend.app.evaluation.ask_dataset import (
    default_real_ask_gold_root,
    load_ask_gold_dataset,
    resolve_ask_dataset_root,
)
from backend.app.evaluation.ask_real_corpus import (
    RealAskCorpusSpec,
    build_real_ask_catalog,
    fingerprint_published_records,
    load_real_corpus_spec,
    published_ask_records,
    unified_demo_database,
)
from backend.app.evaluation.ask_runner import run_ask_evaluation
from backend.app.evaluation.dataset import EvaluationDatasetError
from backend.app.models import (
    Politician,
    PoliticianVersion,
    Proposal,
    ProposalType,
)
from backend.app.schemas.pledge import PledgeClassificationRequest
from backend.app.scoring.types import CommitmentType, HolderRole, PledgeSpecificity
from backend.app.services.pledge_service import PledgeService
from evaluation.eval_ask_verapolitica import build_parser, main


REAL_ROOT = Path(__file__).resolve().parents[2] / "evaluation" / "ask_verapolitica" / "real_v1"
UNIFIED_DB = Path(__file__).resolve().parents[2] / "data" / "unified_demo" / "verapolitica.db"
NOW = datetime(2026, 10, 7, 9, tzinfo=timezone.utc)


def test_real_dataset_loads():
    dataset = load_ask_gold_dataset(default_real_ask_gold_root())
    spec = load_real_corpus_spec(REAL_ROOT)
    assert dataset.dataset_version == "ask-verapolitica-gold/real-v1"
    assert 30 <= len(dataset.cases) <= 50
    assert spec.published_fingerprint
    assert "rdc" in spec.pledges
    assert any(case.expect_zero_results for case in dataset.cases)
    assert not any(case.should_require_clarification for case in dataset.cases)
    assert resolve_ask_dataset_root("real-v1") == REAL_ROOT


def test_unavailable_real_corpus_fails_clearly(tmp_path):
    with pytest.raises(EvaluationDatasetError, match="unavailable"):
        unified_demo_database(tmp_path)


def test_resolves_stable_title_prefixes(session_factory: sessionmaker[Session]):
    with session_factory() as session:
        politician = Politician(
            canonical_given_name="Giorgia",
            canonical_family_name="Meloni",
            normalized_name="giorgia meloni",
            birth_date=date(1977, 1, 15),
        )
        session.add(politician)
        session.flush()
        version = PoliticianVersion(
            politician_id=politician.id,
            version_number=1,
            profile_schema_version=1,
            profile_data={"given_name": "Giorgia", "family_name": "Meloni"},
            published_at=NOW,
        )
        session.add(version)
        session.flush()
        politician.current_version = version
        pledge = Proposal(
            canonical_title="Dare seguito al processo virtuoso di autonomia differenziata già avviato",
            exact_statement="Dare seguito al processo virtuoso di autonomia differenziata.",
            proposal_type=ProposalType.EXPLICIT_PROMISE,
            published_at=NOW,
        )
        session.add(pledge)
        session.commit()
        pledge_id = pledge.id
        politician_id = politician.id

    PledgeService(session_factory).classify(
        pledge_id,
        PledgeClassificationRequest(
            specificity=PledgeSpecificity.HIGH,
            commitment_type=CommitmentType.ACTION,
            holder_role=HolderRole.GOVERNMENT_COALITION,
            cap_topic_code="20",
            mandate_start=date(2022, 10, 13),
            mandate_end=date(2027, 10, 13),
        ),
        classified_by="eval",
    )
    with session_factory() as session:
        fingerprint = fingerprint_published_records(published_ask_records(session))
        spec = RealAskCorpusSpec(
            corpus_name="test",
            corpus_date="2026-10-16",
            database_relpath="tmp",
            published_fingerprint=fingerprint,
            politicians={"giorgia-meloni": {"given_name": "Giorgia", "family_name": "Meloni"}},
            pledges={
                "autonomia": {
                    "title_prefix": "Dare seguito al processo virtuoso di autonomia differenziata"
                }
            },
        )
        catalog = build_real_ask_catalog(session, spec)
    assert catalog.pledge_ids["autonomia"] == pledge_id
    assert catalog.politician_ids["giorgia-meloni"] == politician_id


def test_fingerprint_mismatch_is_explicit(session_factory: sessionmaker[Session]):
    spec = RealAskCorpusSpec(
        corpus_name="test",
        corpus_date="2026-10-16",
        database_relpath="tmp",
        published_fingerprint="0" * 64,
        politicians={},
        pledges={},
    )
    with session_factory() as session, pytest.raises(EvaluationDatasetError, match="fingerprint"):
        build_real_ask_catalog(session, spec)


def test_cli_rejects_unknown_dataset(capsys):
    assert build_parser().parse_args(["--dataset", "real-v1"]).dataset == "real-v1"
    exit_code = main(["--dataset", "does-not-exist"])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Ask evaluation failed" in captured.err


@pytest.mark.skipif(not UNIFIED_DB.is_file(), reason="unified demo corpus is not present")
def test_real_corpus_eval_does_not_write():
    before = (UNIFIED_DB.stat().st_mtime_ns, UNIFIED_DB.stat().st_size)
    report = run_ask_evaluation(dataset_name="real-v1", case_id="unsupported-miglior")
    after = (UNIFIED_DB.stat().st_mtime_ns, UNIFIED_DB.stat().st_size)
    assert before == after
    assert report.total == 1
    assert report.passed == 1
