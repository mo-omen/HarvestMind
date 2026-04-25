from fastapi import APIRouter, HTTPException, status

from app.db.runtime import ensure_schema_ready
from app.schemas.advisor import AdvisorMessageRequest, AdvisorMessageResponse
from app.services.advisor import AdvisorProfileNotFoundError, AdvisorService


router = APIRouter(prefix="/advisor", tags=["advisor"])


def _get_advisor_service() -> AdvisorService:
    database = ensure_schema_ready()
    return AdvisorService(database)


@router.post("/message", response_model=AdvisorMessageResponse)
async def process_advisor_message(payload: AdvisorMessageRequest) -> AdvisorMessageResponse:
    service = _get_advisor_service()
    try:
        return await service.answer(payload)
    except AdvisorProfileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process advisor message: {exc}",
        ) from exc
