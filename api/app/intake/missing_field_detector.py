from app.schemas.analysis import DecisionAnalysisRequest
from app.schemas.intake import IntakeFieldName, IntakeState, REQUIRED_INTAKE_FIELDS


class MissingFieldDetector:
    required_fields: tuple[IntakeFieldName, ...] = REQUIRED_INTAKE_FIELDS

    def detect_missing_fields(self, state: IntakeState) -> list[IntakeFieldName]:
        return [
            field_name
            for field_name in self.required_fields
            if not self._field_is_complete(state, field_name)
        ]

    def detect_filled_fields(self, state: IntakeState) -> list[IntakeFieldName]:
        return [
            field_name
            for field_name in self.required_fields
            if self._field_is_complete(state, field_name)
        ]

    def hydrate_state(self, state: IntakeState) -> IntakeState:
        missing_fields = self.detect_missing_fields(state)
        filled_fields = [
            field_name
            for field_name in self.required_fields
            if field_name not in missing_fields
        ]
        return state.model_copy(
            update={
                "filled_fields": filled_fields,
                "missing_fields": missing_fields,
                "is_complete": not missing_fields,
            }
        )

    def build_analysis_request(
        self, state: IntakeState
    ) -> DecisionAnalysisRequest | None:
        hydrated_state = self.hydrate_state(state)
        if not hydrated_state.is_complete:
            return None

        return DecisionAnalysisRequest(
            location=hydrated_state.location,
            crop=hydrated_state.crop,
            candidate_crops=hydrated_state.candidate_crops,
            expected_harvest_days=hydrated_state.expected_harvest_days,
            farm_size_hectares=hydrated_state.farm_size_hectares,
            labor_flexibility_pct=hydrated_state.labor_flexibility_pct,
        )

    def _field_is_complete(
        self, state: IntakeState, field_name: IntakeFieldName
    ) -> bool:
        value = getattr(state, field_name)

        if field_name in {"location", "crop"}:
            return bool(value)
        if field_name == "candidate_crops":
            return len(value) > 0
        return value is not None

