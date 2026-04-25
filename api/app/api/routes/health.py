from fastapi import APIRouter

from app.db.runtime import ensure_schema_ready
from app.services.ops import OperationsService


router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness() -> dict:
    database = ensure_schema_ready()
    service = OperationsService(database)
    return service.readiness().model_dump(mode="json")
