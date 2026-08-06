"""Dictation endpoints.

Recording is started and stopped by separate requests rather than held open for the length of
an utterance, because the user is speaking in between and the interface must stay responsive.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.dependencies import ServicesDep
from app.api.schemas import (
    DictationResultResponse,
    DictationStateResponse,
    StopDictationRequest,
)
from app.pipeline.dictation import DictationConflictError, DictationResult

router = APIRouter(prefix="/dictation", tags=["dictation"])


def _to_response(result: DictationResult) -> DictationResultResponse:
    return DictationResultResponse(
        text=result.text,
        raw_text=result.raw_text,
        was_enhanced=result.was_enhanced,
        enhancement_error=result.enhancement_error,
        language=result.language,
        model=result.model,
        audio_seconds=result.audio_seconds,
        speech_seconds=result.speech_seconds,
        transcribe_seconds=result.transcribe_seconds,
        enhance_seconds=result.enhance_seconds,
        stopped_because=result.stopped_because.value,
    )


@router.get("/state", summary="Report whether a recording is in progress")
async def read_state(services: ServicesDep) -> DictationStateResponse:
    return DictationStateResponse(state=services.dictation.state)


@router.post("/start", summary="Begin recording", status_code=status.HTTP_202_ACCEPTED)
async def start(services: ServicesDep) -> DictationStateResponse:
    """Open the microphone and start capturing."""
    try:
        await services.dictation.start()
    except DictationConflictError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error

    return DictationStateResponse(state=services.dictation.state)


@router.post("/stop", summary="Finish recording and return the text")
async def stop(services: ServicesDep, request: StopDictationRequest) -> DictationResultResponse:
    """Stop capturing, transcribe, and clean up.

    This is the slow call: it takes about as long as transcription needs.
    """
    try:
        result = await services.dictation.stop(request.profile)
    except DictationConflictError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error

    return _to_response(result)


@router.post(
    "/cancel",
    summary="Discard the recording in progress",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def cancel(services: ServicesDep) -> None:
    """Throw away what has been captured without transcribing it."""
    try:
        await services.dictation.cancel()
    except DictationConflictError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
