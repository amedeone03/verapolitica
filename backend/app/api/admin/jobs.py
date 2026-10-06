from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import sessionmaker, Session

from backend.app.api.deps import get_api_settings, get_session_factory
from backend.app.core.config import Settings
from backend.app.jobs import IngestionJobService
from backend.app.models import IngestionJobStatus, IngestionJobTrigger
from backend.app.schemas.jobs import IngestionJobRunList, IngestionJobRunResult


router = APIRouter(prefix="/jobs", tags=["admin-jobs"])


def get_job_service(
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    settings: Annotated[Settings, Depends(get_api_settings)],
) -> IngestionJobService:
    return IngestionJobService(session_factory, settings)


@router.get("", response_model=IngestionJobRunList)
def list_job_runs(
    service: Annotated[IngestionJobService, Depends(get_job_service)],
    job_name: str | None = None,
    job_status: Annotated[IngestionJobStatus | None, Query(alias="status")] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> IngestionJobRunList:
    return service.list(
        offset=offset,
        limit=limit,
        job_name=job_name,
        status=job_status,
    )


@router.get("/{job_run_id}", response_model=IngestionJobRunResult)
def get_job_run(
    job_run_id: int,
    service: Annotated[IngestionJobService, Depends(get_job_service)],
) -> IngestionJobRunResult:
    return service.get(job_run_id)


@router.post(
    "/{job_name}/run",
    response_model=IngestionJobRunResult,
    status_code=status.HTTP_200_OK,
)
def run_job(
    job_name: str,
    service: Annotated[IngestionJobService, Depends(get_job_service)],
) -> IngestionJobRunResult:
    return service.execute(job_name, trigger_type=IngestionJobTrigger.ADMIN)
