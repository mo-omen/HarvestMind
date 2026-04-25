from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, HTTPException, status

from app.db.runtime import ensure_schema_ready
from app.intake.conversation_manager import ConversationManager
from app.intake.field_extractor import FieldExtractorError, extract_field_updates_result
from app.repositories.intake_sessions import IntakeSessionCreate, IntakeSessionRepository
from app.schemas.intake import IntakeFieldUpdate, IntakeState, IntakeTurnRequest, IntakeTurnResponse
from app.schemas.intake_session import (
    IntakeSessionCreateRequest,
    IntakeSessionMessageRequest,
    IntakeSessionResponse,
    IntakeSessionTurnResponse,
    IntakeTranscriptEntry,
)


router = APIRouter(prefix="/intake", tags=["intake"])
conversation_manager = ConversationManager()

_CLARIFICATION_PROMPTS = {
    "location": "I need a Malaysian district, town, or state. Try “Muar, Johor” or “Kota Bharu, Kelantan”.",
    "crop": "I need the crop you are currently growing. For example, “chili”, “ginger”, or “paddy”.",
    "expected_harvest_days": "I need the harvest window as a number of days. For example, “21 days” or “about 6 weeks”.",
    "farm_size_hectares": "I need the farm size in hectares. For example, “2 hectares” or “5 acres”.",
    "labor_flexibility_pct": "I need the percentage of labor that can be redirected. For example, “30%” or “about half”.",
    "candidate_crops": "I need at least one alternative crop you would consider. For example, “ginger and cucumber”.",
}


def _get_session_repository() -> IntakeSessionRepository:
    database = ensure_schema_ready()
    return IntakeSessionRepository(database)


def _merge_extracted_fields(
    current_fields: IntakeFieldUpdate,
    new_fields: IntakeFieldUpdate,
) -> IntakeFieldUpdate:
    payload = current_fields.model_dump(exclude_none=True)
    payload.update(new_fields.model_dump(exclude_none=True))
    return IntakeFieldUpdate(**payload)


def _reprompt_for_field(state: IntakeState, field_name: str) -> IntakeTurnResponse:
    hydrated_state = conversation_manager.detector.hydrate_state(state)
    return IntakeTurnResponse(
        status="needs_input",
        state=hydrated_state,
        next_question={
            "field_name": field_name,
            "prompt": _CLARIFICATION_PROMPTS.get(
                field_name,
                conversation_manager.question_prompts[field_name],
            ),
        },
    )


@router.post("/message", response_model=IntakeTurnResponse)
async def process_intake_message(payload: IntakeTurnRequest) -> IntakeTurnResponse:
    state = conversation_manager.detector.hydrate_state(payload.state or IntakeState())
    extracted_fields = payload.extracted_fields

    try:
        if payload.message:
            asked_field = state.missing_fields[0] if state.missing_fields else "location"
            extraction_result = await extract_field_updates_result(
                asked_field=asked_field,
                intake_state=state,
                farmer_answer=payload.message,
            )
            if asked_field not in extraction_result.updates.model_fields_set:
                return _reprompt_for_field(state, asked_field)
            extracted_fields = _merge_extracted_fields(
                extracted_fields,
                extraction_result.updates,
            )
    except FieldExtractorError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    return conversation_manager.advance(
        IntakeTurnRequest(
            message=payload.message,
            state=state,
            extracted_fields=extracted_fields,
        )
    )


@router.post("/sessions", response_model=IntakeSessionResponse)
async def create_session(payload: IntakeSessionCreateRequest) -> IntakeSessionResponse:
    repository = _get_session_repository()
    now = datetime.now(UTC)
    record = repository.save(
        IntakeSessionCreate(
            session_id=str(uuid4()),
            farmer_id=payload.farmer_id,
            state=IntakeState().model_dump(mode="json"),
            analysis_request=None,
            transcript=[],
            status="needs_input",
        )
    )
    return _to_session_response(record)


@router.get("/sessions/{session_id}", response_model=IntakeSessionResponse)
async def get_session(session_id: str) -> IntakeSessionResponse:
    repository = _get_session_repository()
    record = repository.get(session_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Intake session '{session_id}' was not found.",
        )
    return _to_session_response(record)


@router.post("/sessions/{session_id}/message", response_model=IntakeSessionTurnResponse)
async def process_session_message(
    session_id: str,
    payload: IntakeSessionMessageRequest,
) -> IntakeSessionTurnResponse:
    repository = _get_session_repository()
    record = repository.get(session_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Intake session '{session_id}' was not found.",
        )

    turn = await process_intake_message(
        IntakeTurnRequest(
            message=payload.message,
            state=IntakeState.model_validate(record.state),
        )
    )
    now = datetime.now(UTC)
    transcript = [
        *record.transcript,
        {"role": "farmer", "text": payload.message, "created_at": now.isoformat()},
    ]
    if turn.next_question is not None:
        transcript.append(
            {"role": "assistant", "text": turn.next_question.prompt, "created_at": now.isoformat()}
        )

    updated = repository.save(
        IntakeSessionCreate(
            session_id=session_id,
            farmer_id=record.farmer_id,
            state=turn.state.model_dump(mode="json"),
            analysis_request=turn.analysis_request.model_dump(mode="json") if turn.analysis_request is not None else None,
            transcript=transcript,
            status=turn.status,
        )
    )
    return IntakeSessionTurnResponse(
        session=_to_session_response(updated),
        turn=turn,
    )


def _to_session_response(record) -> IntakeSessionResponse:
    return IntakeSessionResponse(
        session_id=record.session_id,
        farmer_id=record.farmer_id,
        state=IntakeState.model_validate(record.state),
        analysis_request=record.analysis_request,
        transcript=[
            IntakeTranscriptEntry.model_validate(item)
            for item in record.transcript
        ],
        status=record.status,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )
