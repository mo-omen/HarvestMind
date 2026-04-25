from datetime import date

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from app.core.malaysia import normalize_malaysia_location


def _normalize_crop_list(value: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in value:
        normalized = item.strip()
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result


class FarmerProfileRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    farmer_id: str | None = None
    location: str
    preferred_crops: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("preferred_crops", "candidate_crops"),
    )
    current_crop: str | None = None
    current_price_rm_per_kg: float | None = Field(default=None, ge=0)
    expected_harvest_date: date | None = None
    farm_size_hectares: float | None = None
    expected_harvest_days: int | None = Field(default=None, ge=1, le=365)
    labor_flexibility_pct: int | None = Field(default=None, ge=0, le=100)
    candidate_crops: list[str] = Field(default_factory=list)

    @field_validator("preferred_crops", "candidate_crops")
    @classmethod
    def validate_crop_lists(cls, value: list[str]) -> list[str]:
        return _normalize_crop_list(value)

    @field_validator("location", "current_crop")
    @classmethod
    def validate_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty")
        return normalized

    @field_validator("location")
    @classmethod
    def validate_location(cls, value: str) -> str:
        return normalize_malaysia_location(value)

    def resolved_candidate_crops(self) -> list[str]:
        if self.candidate_crops:
            return self.candidate_crops
        return self.preferred_crops


class FarmerProfileResponse(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    farmer_id: str
    location: str
    preferred_crops: list[str]
    current_crop: str | None = None
    current_price_rm_per_kg: float | None = None
    expected_harvest_date: date | None = None
    farm_size_hectares: float | None = None
    expected_harvest_days: int | None = None
    labor_flexibility_pct: int | None = None
    candidate_crops: list[str] = Field(default_factory=list)
    saved: bool
