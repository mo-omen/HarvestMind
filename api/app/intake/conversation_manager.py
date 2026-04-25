from app.intake.missing_field_detector import MissingFieldDetector
from app.schemas.intake import (
    IntakeFieldName,
    IntakeFieldUpdate,
    IntakeQuestion,
    IntakeState,
    IntakeTurnRequest,
    IntakeTurnResponse,
)


class ConversationManager:
    question_prompts: dict[IntakeFieldName, str] = {
        "location": "What is the farm location in Malaysia? Share the district, town, or state.",
        "crop": "What crop are you currently growing?",
        "expected_harvest_days": "How many days remain until the expected harvest?",
        "farm_size_hectares": "What is the farm size in hectares?",
        "labor_flexibility_pct": "What percentage of your labor can be redirected if needed?",
        "candidate_crops": "Which candidate crops would you consider as alternatives?",
    }

    def __init__(self, detector: MissingFieldDetector | None = None) -> None:
        self.detector = detector or MissingFieldDetector()

    def advance(self, request: IntakeTurnRequest) -> IntakeTurnResponse:
        merged_state = self._merge_state(
            current_state=request.state,
            extracted_fields=request.extracted_fields,
        )
        hydrated_state = self.detector.hydrate_state(merged_state)

        if hydrated_state.is_complete:
            return IntakeTurnResponse(
                status="complete",
                state=hydrated_state,
                analysis_request=self.detector.build_analysis_request(hydrated_state),
            )

        next_field = hydrated_state.missing_fields[0]
        return IntakeTurnResponse(
            status="needs_input",
            state=hydrated_state,
            next_question=IntakeQuestion(
                field_name=next_field,
                prompt=self.question_prompts[next_field],
            ),
        )

    def _merge_state(
        self,
        current_state: IntakeState | None,
        extracted_fields: IntakeFieldUpdate,
    ) -> IntakeState:
        base_state = current_state or IntakeState()
        updates: dict[str, object] = {}

        for field_name in IntakeFieldUpdate.model_fields:
            if field_name not in extracted_fields.model_fields_set:
                continue

            value = getattr(extracted_fields, field_name)
            if field_name == "candidate_crops":
                updates[field_name] = value or []
                continue

            updates[field_name] = value

        return base_state.model_copy(update=updates)
