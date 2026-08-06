"""Text cleanup using a language model served locally by Ollama.

Ollama runs as a native service on the same machine, listening on loopback. It is not a cloud
API and not a container: the configuration validator refuses any non-loopback address, so a
transcript cannot be sent off the device by editing a setting.

Every failure here is recoverable. If the service is not running, the model is missing, or the
response looks wrong, the caller keeps the raw transcript. Dictation must never break because
an optional cleanup step was unavailable.
"""

from __future__ import annotations

import re

import httpx

from app.adapters.enhancement.profiles import ProfileTemplate, template_for
from app.config.settings import EnhancementSettings
from app.observability.logging import get_logger
from app.observability.redaction import Sensitive

logger = get_logger(__name__)

# A faithful rewrite is roughly the same length as its input. Anything far outside this band
# means the model invented, summarised, or answered the text instead of correcting it.
MIN_FAITHFUL_RATIO = 0.5
MAX_FAITHFUL_RATIO = 2.0

# Short inputs vary wildly in relative length, so the ratio check only applies above this.
RATIO_CHECK_MIN_CHARACTERS = 40

_CODE_FENCE = re.compile(r"^\s*```[a-zA-Z]*\n(?P<body>.*?)\n?```\s*$", re.DOTALL)
_WRAPPING_QUOTES = re.compile(r'^\s*["“\'](?P<body>.*)["”\']\s*$', re.DOTALL)


class EnhancementUnavailableError(RuntimeError):
    """Raised when the local model cannot be reached or returns nothing usable."""


class OllamaEnhancer:
    """Cleans up transcripts with a model served by a local Ollama instance."""

    def __init__(
        self,
        settings: EnhancementSettings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._client = (
            client
            if client is not None
            else httpx.AsyncClient(
                base_url=settings.base_url,
                timeout=settings.timeout_seconds,
            )
        )
        self._owns_client = client is None

    async def aclose(self) -> None:
        """Release the HTTP connection pool if this instance created it."""
        if self._owns_client:
            await self._client.aclose()

    async def is_available(self) -> bool:
        """Whether the Ollama service is running and has the configured model."""
        try:
            response = await self._client.get("/api/tags")
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            logger.info("text model unavailable", extra={"reason": str(error)})
            return False

        installed = {
            str(entry.get("name", ""))
            for entry in payload.get("models", [])
            if isinstance(entry, dict)
        }
        if self._settings.model in installed:
            return True

        logger.warning(
            "configured text model is not installed",
            extra={"model": self._settings.model, "installed": sorted(installed)},
        )
        return False

    async def enhance(self, text: str, profile: str) -> str:
        """Rewrite a transcript according to a profile.

        Returns the original text unchanged when the result fails the faithfulness check.
        """
        stripped = text.strip()
        if not stripped:
            return stripped

        template = template_for(profile)
        truncated = stripped[: self._settings.max_input_characters]

        raw = await self._chat(template, truncated)
        cleaned = _unwrap(raw)

        if not cleaned:
            raise EnhancementUnavailableError("the text model returned an empty response")

        if template.faithful and not _plausibly_faithful(truncated, cleaned):
            logger.warning(
                "discarding an implausible rewrite",
                extra={
                    "profile": profile,
                    "input_characters": len(truncated),
                    "output_characters": len(cleaned),
                },
            )
            return truncated

        logger.debug(
            "text enhanced",
            extra={"profile": profile, "enhanced": Sensitive(cleaned)},
        )
        return cleaned

    async def _chat(self, template: ProfileTemplate, text: str) -> str:
        request = {
            "model": self._settings.model,
            "stream": False,
            "options": {"temperature": self._settings.temperature},
            "messages": [
                {"role": "system", "content": template.system_prompt},
                {"role": "user", "content": template.render(text)},
            ],
        }

        try:
            response = await self._client.post("/api/chat", json=request)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as error:
            raise EnhancementUnavailableError(
                f"could not reach the local text model at {self._settings.base_url}: {error}"
            ) from error
        except ValueError as error:
            raise EnhancementUnavailableError("the text model returned malformed JSON") from error

        message = payload.get("message")
        if not isinstance(message, dict):
            raise EnhancementUnavailableError("the text model response had no message")

        return str(message.get("content", ""))


def _unwrap(text: str) -> str:
    """Strip the wrappers instruction-tuned models habitually add."""
    candidate = text.strip()

    fenced = _CODE_FENCE.match(candidate)
    if fenced:
        candidate = fenced.group("body").strip()

    quoted = _WRAPPING_QUOTES.match(candidate)
    if quoted:
        candidate = quoted.group("body").strip()

    return candidate


def _plausibly_faithful(original: str, rewritten: str) -> bool:
    """Reject rewrites whose length shows the model did something other than correct the text.

    This is a blunt check, and deliberately so. It cannot detect a subtle substitution, but it
    reliably catches the failure that actually happens: the model answering the dictation, or
    replacing it with a summary or an apology.
    """
    if len(original) < RATIO_CHECK_MIN_CHARACTERS:
        return True

    ratio = len(rewritten) / len(original)
    return MIN_FAITHFUL_RATIO <= ratio <= MAX_FAITHFUL_RATIO


class PassthroughEnhancer:
    """Returns transcripts unchanged.

    Used when enhancement is disabled, so the pipeline has no conditional branch and the
    disabled path is exercised by the same tests as the enabled one.
    """

    async def enhance(self, text: str, profile: str) -> str:
        return text.strip()

    async def is_available(self) -> bool:
        return True
