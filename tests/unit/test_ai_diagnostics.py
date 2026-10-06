import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.ai.provider import AIResponse
from app.ai.runner import AIRunner
from app.api.auth import create_user
from app.contracts.facts_v1 import FactsOutputV1
from app.core.editorial import EditorialError
from app.infrastructure.db.models import AiRun, Fact, JobRun
from app.infrastructure.db.session import get_db
from app.main import create_app
from app.orchestration.editorial import EditorialService
from app.orchestration.editorial_jobs import EditorialJobRequest, process_editorial_jobs, queue_job
from tests.unit.test_phase3 import seed, settings

REJECTED_TEXT = "sk-private-do-not-log"


class InvalidProvider:
    def __init__(self, fault):
        self.fault = fault

    def generate(self, **kwargs):
        if self.fault == "provider":
            raise EditorialError("AI_REFUSAL")
        if self.fault == "unknown_code":
            raise EditorialError(REJECTED_TEXT)
        if self.fault == "value_error":
            raise ValueError(REJECTED_TEXT)
        if self.fault == "schema":
            output = {"facts": [{"subject": REJECTED_TEXT, REJECTED_TEXT: REJECTED_TEXT}]}
        else:
            output = {
                "facts": [
                    {
                        "fact_type": "price",
                        "subject": "発表内容",
                        "predicate": "price",
                        "value": "19,800円",
                        "evidence_text": "本文にない価格19,800円",
                        "evidence_start": 0,
                        "evidence_end": 7,
                        "confidence": 1,
                    }
                ]
            }
        return AIResponse(output, "response-test", 10, 5, 1)


@pytest.mark.parametrize(
    "fault,code",
    [
        ("schema", "AI_SCHEMA_INVALID"),
        ("evidence", "FACT_EVIDENCE_MISMATCH"),
        ("provider", "AI_REFUSAL"),
        ("unknown_code", "AI_VALIDATION_ERROR"),
        ("value_error", "AI_VALIDATION_ERROR"),
    ],
)
def test_failed_attempts_persist_sanitized_conditions_and_logs(
    acquisition_session, capsys, fault, code
):
    session = acquisition_session
    item = seed(session)
    config = settings()
    runner = AIRunner(session, config, InvalidProvider(fault))
    service = EditorialService(session, config, runner)
    assert service.facts(item.id, "ai") is None
    session.commit()
    runs = [session.get(AiRun, run_id) for run_id in runner.run_ids]
    assert len(runs) == 2
    for attempt, run in enumerate(runs, 1):
        assert run.output_json is None
        assert run.validation_status == "invalid"
        assert run.validation_errors_json
        assert all(error["code"] == code for error in run.validation_errors_json)
        assert all(error["attempt"] == attempt for error in run.validation_errors_json)
        if fault == "schema":
            assert any(error["condition"] == "missing" for error in run.validation_errors_json)
            assert any(
                error["path"] == ["facts", 0, "value"] for error in run.validation_errors_json
            )
            assert any(error["path"] == ["facts", 0, "*"] for error in run.validation_errors_json)
        elif fault == "evidence":
            assert run.validation_errors_json[0]["path"] == ["facts", 0, "evidence_text"]
    assert session.scalars(select(Fact)).first() is None
    persisted = json.dumps([run.validation_errors_json for run in runs], ensure_ascii=False)
    logs = capsys.readouterr()
    assert REJECTED_TEXT not in persisted + logs.out + logs.err
    assert "ai_validation_failed" in logs.out + logs.err


def test_diagnostics_are_scoped_to_job_and_visible_in_authenticated_item_detail(
    acquisition_session,
    monkeypatch,
):
    session = acquisition_session
    item = seed(session)
    user, token = create_user(session, "diagnostic-reader", ["editor"])
    # An unrelated old attempt must not be attached to this job.
    old = AiRun(
        item_id=item.id,
        task_type="facts",
        execution_role="facts",
        provider="openai",
        model="old-model",
        model_profile_key="facts-default",
        prompt_version="facts-v1",
        input_hash="old-input",
        validation_status="invalid",
    )
    session.add(old)
    job = queue_job(
        session,
        item.id,
        "pipeline",
        EditorialJobRequest(expected_version=item.workflow_version, mode="ai"),
        user.id,
    )
    session.commit()
    config = settings()
    monkeypatch.setattr(
        "app.orchestration.editorial_jobs.EditorialService",
        lambda db, cfg, actor_id: EditorialService(
            db, cfg, AIRunner(db, cfg, InvalidProvider("evidence")), actor_id
        ),
    )
    assert process_editorial_jobs(session, config) == 1
    session.commit()
    app = create_app()
    app.dependency_overrides[get_db] = lambda: session
    headers = {"Authorization": "Bearer " + token}
    with TestClient(app) as client:
        assert client.get(f"/api/v1/items/{item.id}").status_code == 401
        assert client.get(f"/api/v1/jobs/{job.id}").status_code == 401
        result = client.get(f"/api/v1/jobs/{job.id}", headers=headers).json()
        assert result["status"] == "success"
        assert result["result"]["status"] == "review_required"
        assert len(result["ai_runs"]) == 2
        assert str(old.id) not in {run["id"] for run in result["ai_runs"]}
        assert all(
            run["validation_errors"][0]["code"] == "FACT_EVIDENCE_MISMATCH"
            for run in result["ai_runs"]
        )
        detail = client.get(f"/api/v1/items/{item.id}", headers=headers).json()
        assert len(detail["ai_runs"]) == 3
        assert (
            next(run for run in detail["ai_runs"] if run["id"] == str(old.id))["validation_errors"]
            is None
        )
        assert all("output_json" not in run for run in detail["ai_runs"])
        assert "token_hash" not in json.dumps(result) + json.dumps(detail)
        assert detail["drafts"] == []


def test_successful_run_has_no_validation_errors(acquisition_session):
    session = acquisition_session
    item = seed(session)

    class Provider:
        def generate(self, **kwargs):
            return AIResponse({"facts": []})

    runner = AIRunner(session, settings(), Provider())
    result, run_id = runner.run("facts", item.id, {}, FactsOutputV1)
    session.commit()
    assert result is not None
    assert session.get(AiRun, run_id).validation_errors_json == []


def test_ai_run_ids_survive_a_later_job_failure(acquisition_session, monkeypatch):
    session = acquisition_session
    item = seed(session)
    user, _ = create_user(session, "operator", ["editor"])
    job = queue_job(
        session,
        item.id,
        "facts",
        EditorialJobRequest(expected_version=item.workflow_version, mode="ai"),
        user.id,
    )
    session.commit()

    class Provider:
        def generate(self, **kwargs):
            return AIResponse({"facts": []})

    def fail_after_ai(service, operation, item_id, request):
        service.runner.run("facts", item_id, {}, FactsOutputV1)
        raise EditorialError("CURRENT_FACTS_REQUIRED")

    monkeypatch.setattr("app.orchestration.editorial_jobs.execute_job", fail_after_ai)
    monkeypatch.setattr(
        "app.orchestration.editorial_jobs.EditorialService",
        lambda db, cfg, actor_id: EditorialService(
            db, cfg, AIRunner(db, cfg, Provider()), actor_id
        ),
    )
    process_editorial_jobs(session, settings())
    session.commit()
    assert session.get(JobRun, job.id).status == "failed"
    assert len(job.stats_json["ai_run_ids"]) == 1


def test_partial_fact_rejections_are_persisted_and_not_passed_to_evidence(acquisition_session):
    session = acquisition_session
    item = seed(session)

    class Provider:
        def generate(self, **kwargs):
            def candidate(value):
                return {
                    "fact_type": "price",
                    "subject": "発表内容",
                    "predicate": "price",
                    "value": value,
                    "evidence_text": value,
                    "evidence_start": 0,
                    "evidence_end": len(value),
                    "confidence": 1,
                }

            return AIResponse({"facts": [candidate("19,800円"), candidate("99999円")]})

    config = settings()
    service = EditorialService(session, config, AIRunner(session, config, Provider()))
    evidence = service.facts(item.id, "ai")
    session.commit()
    assert [f["value"] for f in evidence.payload_json["verified_facts"]] == ["19,800円"]
    run = session.scalars(select(AiRun)).one()
    assert run.validation_status == "valid_with_rejections"
    assert run.validation_errors_json[0]["path"] == ["facts", 1, "evidence_text"]
    assert "99999" not in json.dumps(run.output_json) + json.dumps(run.validation_errors_json)
