"""Optional model component for the pinned Apache-2.0 NVIDIA NeMo Gym API.

No import from this module is required by HealthCraft's default installation.
Use direct construction in an isolated Gym environment; there is no installer,
model download, hosted fallback, or service startup on import.
"""

from __future__ import annotations

import asyncio
import ipaddress
import subprocess
from pathlib import Path

import nemo_gym
from fastapi import HTTPException, Request
from nemo_gym.base_responses_api_model import (
    BaseResponsesAPIModelConfig,
    SimpleResponsesAPIModel,
)
from nemo_gym.openai_utils import (
    NeMoGymChatCompletion,
    NeMoGymChatCompletionCreateParamsNonStreaming,
    NeMoGymResponse,
    NeMoGymResponseCreateParamsNonStreaming,
)
from pydantic import Field, model_validator

from healthcraft.integrations.nemo_native import GYM_REVISION, NativeOllamaBridge


def validate_gym_revision() -> None:
    """Require the reviewed, unmodified Gym source checkout (wheel installs fail closed)."""
    root = Path(nemo_gym.__file__).resolve().parent.parent
    try:
        revision = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        clean = (
            subprocess.run(
                ["git", "-C", str(root), "diff", "--quiet", "HEAD"],
                check=False,
                capture_output=True,
                timeout=5,
            ).returncode
            == 0
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("Native adapter requires the pinned Gym source checkout") from exc
    if revision != GYM_REVISION or not clean:
        raise ValueError(f"Native adapter requires unmodified Gym {GYM_REVISION}")


class NativeOllamaModelConfig(BaseResponsesAPIModelConfig):
    model: str
    expected_digest: str
    expected_runtime: str = "0.34.4"
    base_url: str = "http://127.0.0.1:11434"
    capture_dir: Path
    output_budget: int = Field(gt=0, strict=True)
    timeout: float = Field(default=300, gt=0)

    @model_validator(mode="after")
    def validate_local_profile(self):
        if not ipaddress.ip_address(self.host).is_loopback:
            raise ValueError("Native model server must bind an explicit loopback address")
        NativeOllamaBridge(**self.bridge_options())
        return self

    def bridge_options(self) -> dict:
        return {
            key: getattr(self, key)
            for key in (
                "model",
                "expected_digest",
                "expected_runtime",
                "base_url",
                "capture_dir",
                "output_budget",
                "timeout",
            )
        }


class NativeOllamaModel(SimpleResponsesAPIModel):
    """Text and function tools only; streaming and training-token capture are unsupported."""

    ray_enabled = False
    config: NativeOllamaModelConfig

    def model_post_init(self, __context) -> None:
        super().model_post_init(__context)
        validate_gym_revision()

    async def responses(self, body: NeMoGymResponseCreateParamsNonStreaming) -> NeMoGymResponse:
        bridge = NativeOllamaBridge(**self.config.bridge_options())
        result = await asyncio.to_thread(
            bridge.responses, body.model_dump(mode="json", exclude_unset=True, exclude_none=True)
        )
        return NeMoGymResponse.model_validate(result)

    async def chat_completions(
        self, body: NeMoGymChatCompletionCreateParamsNonStreaming
    ) -> NeMoGymChatCompletion:
        bridge = NativeOllamaBridge(**self.config.bridge_options())
        result = await asyncio.to_thread(
            bridge.chat_completions,
            body.model_dump(mode="json", exclude_unset=True, exclude_none=True),
        )
        return NeMoGymChatCompletion.model_validate(result)

    # The base class otherwise synthesizes streaming after stripping request
    # options. Reject that wider API surface before it can hide unsupported input.
    async def responses_dispatch(self, request: Request, body: dict):
        self._validate_raw(body, "responses")
        return await super().responses_dispatch(request, body)

    async def chat_completions_dispatch(self, request: Request, body: dict):
        self._validate_raw(body, "chat")
        return await super().chat_completions_dispatch(request, body)

    async def messages(self, request: Request, body: dict):
        raise HTTPException(422, "Native profile does not support the Messages API")

    def _validate_raw(self, body: dict, dialect: str) -> None:
        try:
            NativeOllamaBridge(**self.config.bridge_options()).validate_request(body, dialect)
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
