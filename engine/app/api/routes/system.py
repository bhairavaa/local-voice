"""System-level endpoints used by the desktop shell to supervise the engine."""

from __future__ import annotations

from fastapi import APIRouter

from app.adapters.enhancement.profiles import EnhancementProfile
from app.api.dependencies import ContextDep, ServicesDep
from app.api.schemas import AudioDeviceResponse, CapabilitiesResponse, HealthResponse

router = APIRouter(tags=["system"])


@router.get("/health", summary="Report engine liveness")
async def health(context: ContextDep) -> HealthResponse:
    """Confirm the engine is running and report basic process facts."""
    return HealthResponse(
        status="ok",
        version=context.version,
        process_id=context.process_id,
        uptime_seconds=context.uptime_seconds(),
    )


@router.get("/capabilities", summary="Report what the engine can currently do")
async def capabilities(context: ContextDep, services: ServicesDep) -> CapabilitiesResponse:
    """Describe the available models and microphones.

    Enhancement availability is probed live, because Ollama can be started or stopped while
    the engine is running.
    """
    settings = context.settings
    enhancement_available = (
        await services.enhancer.is_available() if settings.enhancement.enabled else False
    )

    return CapabilitiesResponse(
        speech_model=str(settings.speech.model),
        speech_model_loaded=services.transcriber.is_loaded,
        enhancement_enabled=settings.enhancement.enabled,
        enhancement_available=enhancement_available,
        enhancement_model=settings.enhancement.model,
        profiles=list(EnhancementProfile),
        input_devices=[
            AudioDeviceResponse(
                index=device.index,
                name=device.name,
                max_input_channels=device.max_input_channels,
                is_default=device.is_default,
            )
            for device in services.devices.input_devices()
        ],
    )
