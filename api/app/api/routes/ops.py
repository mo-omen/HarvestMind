from fastapi import APIRouter, HTTPException, status

from app.db.runtime import ensure_schema_ready
from app.schemas.ops import SyncJobListResponse, SyncJobRequest, SyncJobResponse
from app.services.ops import OperationsService


router = APIRouter(prefix="/ops", tags=["ops"])


def _get_operations_service() -> OperationsService:
    database = ensure_schema_ready()
    return OperationsService(database)


@router.post("/sync", response_model=SyncJobResponse)
async def run_sync_job(payload: SyncJobRequest) -> SyncJobResponse:
    service = _get_operations_service()
    try:
        record = await service.run_sync(payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to run sync job: {exc}",
        ) from exc
    return SyncJobResponse.model_validate(record.__dict__)


@router.get("/sync/jobs", response_model=SyncJobListResponse)
async def list_sync_jobs(limit: int = 20) -> SyncJobListResponse:
    service = _get_operations_service()
    records = service.list_jobs(limit=limit)
    return SyncJobListResponse(
        items=[SyncJobResponse.model_validate(record.__dict__) for record in records]
    )
