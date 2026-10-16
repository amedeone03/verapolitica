"""Run Ask VeraPolitica gold cases against the service. No live HTTP server."""

from __future__ import annotations

import tempfile
from pathlib import Path

from pydantic import ValidationError

from backend.app.ai.text_completion import FakeTextCompleter, TextCompleter
from backend.app.core.config import AppEnvironment, Settings
from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.evaluation.ask_dataset import (
    AskGoldCase,
    AskGoldDataset,
    is_real_ask_dataset,
    load_ask_gold_dataset,
    resolve_ask_dataset_root,
)
from backend.app.evaluation.ask_fixture import AskEvalCatalog, build_ask_eval_world
from backend.app.evaluation.ask_metrics import (
    AskCaseScore,
    AskEvalReport,
    aggregate_ask_scores,
    score_ask_case,
)
from backend.app.evaluation.ask_real_corpus import (
    build_real_ask_catalog,
    load_real_corpus_spec,
    open_real_ask_session_factory,
)
from backend.app.evaluation.dataset import EvaluationDatasetError
from backend.app.schemas.ask import AskRequest
from backend.app.services.ask_verapolitica_service import (
    AskVeraPoliticaService,
    clear_ask_cache,
)


def _settings(database_url: str, raw_path: Path) -> Settings:
    return Settings(
        env=AppEnvironment.TEST,
        database_url=database_url,
        raw_storage_path=raw_path,
        admin_api_key="eval-ask-admin-secret-not-for-production",
        trusted_hosts="localhost,127.0.0.1,testserver",
        enable_demo_ui=False,
    )


def _safe_fake_completer() -> FakeTextCompleter:
    def _complete(_system: str, user: str) -> str:
        label = "In corso"
        for line in user.splitlines():
            if "label=" in line:
                label = line.split("label=", 1)[1].split(";", 1)[0].strip() or label
                break
        return (
            "VeraPolitica risponde solo con i dati verificati già pubblicati. "
            f"Lo stato pubblico resta '{label}'. "
            "Nessuna fonte esterna viene introdotta e il verdetto pubblicato non cambia."
        )

    return FakeTextCompleter(_complete)


def run_ask_evaluation(
    *,
    dataset: AskGoldDataset | None = None,
    dataset_root: Path | None = None,
    dataset_name: str | Path | None = None,
    category: str | None = None,
    case_id: str | None = None,
    completer: TextCompleter | None | object = None,
    mode: str = "deterministic",
    workspace_root: Path | None = None,
) -> AskEvalReport:
    root = dataset_root
    if root is None and dataset is None:
        root = resolve_ask_dataset_root(dataset_name)
    gold = dataset or load_ask_gold_dataset(root)
    selected = [
        case
        for case in gold.cases
        if (category is None or case.category == category)
        and (case_id is None or case.id == case_id)
    ]
    if not selected:
        raise EvaluationDatasetError("no gold cases matched the filters")
    clear_ask_cache()
    if is_real_ask_dataset(gold):
        spec_root = root or resolve_ask_dataset_root("real-v1")
        scores = _run_real_corpus(
            selected,
            spec_root=spec_root,
            completer=completer,
            workspace_root=workspace_root,
        )
    else:
        scores = _run_synthetic(selected, completer=completer)
    return aggregate_ask_scores(gold.dataset_version, scores, mode=mode)


def _run_synthetic(
    selected: list[AskGoldCase],
    *,
    completer: TextCompleter | None | object,
) -> tuple[AskCaseScore, ...]:
    with tempfile.TemporaryDirectory(prefix="ask-eval-") as tmp:
        root = Path(tmp)
        url = f"sqlite:///{root / 'ask-eval.db'}"
        engine = create_db_engine(url)
        Base.metadata.create_all(engine)
        factory = create_session_factory(engine)
        try:
            catalog = build_ask_eval_world(factory)
            settings = _settings(url, root / "raw")
            service = AskVeraPoliticaService(factory, settings, completer=completer)
            return tuple(_run_case(case, catalog, service) for case in selected)
        finally:
            engine.dispose()
            clear_ask_cache()


def _run_real_corpus(
    selected: list[AskGoldCase],
    *,
    spec_root: Path,
    completer: TextCompleter | None | object,
    workspace_root: Path | None,
) -> tuple[AskCaseScore, ...]:
    spec = load_real_corpus_spec(spec_root)
    engine, factory, database = open_real_ask_session_factory(workspace_root=workspace_root)
    try:
        with factory() as session:
            catalog = build_real_ask_catalog(session, spec)
        settings = _settings(f"sqlite:///{database}", database.parent / "raw")
        service = AskVeraPoliticaService(factory, settings, completer=completer)
        return tuple(_run_case(case, catalog, service) for case in selected)
    finally:
        engine.dispose()
        clear_ask_cache()


def _run_case(
    case: AskGoldCase,
    catalog: AskEvalCatalog,
    service: AskVeraPoliticaService,
) -> AskCaseScore:
    question = case.resolved_question()
    try:
        AskRequest(question=question or " ")
    except ValidationError:
        if case.expect_invalid:
            return score_ask_case(case, catalog, response=None, invalid=True)
        return AskCaseScore(
            case_id=case.id,
            category=case.category,
            passed=False,
            reasons=("request rejected by public schema",),
        )
    if case.expect_invalid:
        return score_ask_case(case, catalog, response=None, invalid=False)
    response = service.ask(question)
    return score_ask_case(case, catalog, response=response)


def render_ask_report(report: AskEvalReport) -> str:
    lines = [
        f"Ask VeraPolitica evaluation ({report.mode})",
        f"dataset: {report.dataset_version}",
        f"total={report.total} passed={report.passed} failed={report.failed}",
        "These figures are performance on this curated gold set, not a universal accuracy claim.",
        "",
        "Category breakdown:",
    ]
    for name, counts in report.category_totals.items():
        lines.append(
            f"  {name}: {counts['passed']}/{counts['total']} passed "
            f"({counts['failed']} failed)"
        )
    lines.append("")
    lines.append("Metrics:")
    for key, value in report.metrics.items():
        lines.append(f"  {key}: {value:.3f}")
    if report.failures:
        lines.append("")
        lines.append("Failed cases:")
        for case_id, reason in report.failures:
            lines.append(f"  {case_id}: {reason}")
    return "\n".join(lines)
