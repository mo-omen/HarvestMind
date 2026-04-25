from fastapi import APIRouter, HTTPException, status

from app.db.runtime import ensure_schema_ready
from app.repositories.profiles import (
    PostgresFarmerProfileRepository,
    ProfileRepositoryConfigurationError,
    ProfileRepositoryError,
)
from app.schemas.profile import FarmerProfileRequest, FarmerProfileResponse


router = APIRouter(prefix="/profiles", tags=["profiles"])


def _get_profile_repository() -> PostgresFarmerProfileRepository:
    database = ensure_schema_ready()
    return PostgresFarmerProfileRepository(conninfo=database.config.dsn)


@router.post("", response_model=FarmerProfileResponse)
async def upsert_profile(payload: FarmerProfileRequest) -> FarmerProfileResponse:
    repository = _get_profile_repository()

    try:
        saved = repository.upsert_profile(
            {
                "farmer_id": payload.farmer_id,
                "location": payload.location,
                "preferred_crops": payload.preferred_crops,
                "current_crop": payload.current_crop,
                "current_price_rm_per_kg": payload.current_price_rm_per_kg,
                "expected_harvest_date": payload.expected_harvest_date,
                "farm_size_hectares": payload.farm_size_hectares,
                "expected_harvest_days": payload.expected_harvest_days,
                "labor_flexibility_pct": payload.labor_flexibility_pct,
                "candidate_crops": payload.resolved_candidate_crops(),
            }
        )
    except ProfileRepositoryConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except ProfileRepositoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    return FarmerProfileResponse(**saved)


@router.get("/{farmer_id}", response_model=FarmerProfileResponse)
async def get_profile(farmer_id: str) -> FarmerProfileResponse:
    repository = _get_profile_repository()

    try:
        record = repository.get_profile(farmer_id)
    except ProfileRepositoryConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except ProfileRepositoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Profile '{farmer_id}' was not found.",
        )

    return FarmerProfileResponse(**record, saved=True)
