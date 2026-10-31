"""UCSD TritonAI OpenAI-compatible HTTP adapter; no implicit retries."""

import json
import os

import httpx

from mas_recovery.core.schemas import Payload, Stage, Usage

INSTRUCTIONS = {
    "researcher": "Read the catalog unit_price and return it as value.",
    "planner": "Multiply the supplied value (unit price) by quantity; return the total as value.",
    "executor": "Use the supplied planned total unchanged; return it as value.",
}


class TritonAIBackend:
    def __init__(self, client: httpx.Client, model: str):
        self.client = client
        self.model = model

    def generate(self, stage: Stage, inputs: dict[str, int]) -> tuple[Payload, Usage]:
        response = self.client.post(
            "chat/completions",
            json={
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": INSTRUCTIONS[stage]
                        + ' Return only a JSON object: {"value": <nonnegative integer>}.',
                    },
                    {"role": "user", "content": json.dumps(inputs, sort_keys=True)},
                ],
            },
        )
        response.raise_for_status()
        body = response.json()
        usage = body.get("usage") or {}
        # No JSON repair or hidden extra calls: malformed model output is a failed attempt.
        return (
            Payload.model_validate_json(body["choices"][0]["message"]["content"]),
            Usage(
                model_calls=1,
                input_tokens=usage.get("prompt_tokens"),
                output_tokens=usage.get("completion_tokens"),
            ),
        )


def make_client() -> httpx.Client:
    key = os.environ.get("TRITONAI_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise ValueError("Set TRITONAI_API_KEY or OPENAI_API_KEY for the TritonAI backend.")
    base_url = (
        os.environ.get("TRITONAI_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or "https://tritonai-api.ucsd.edu/v1"
    )
    return httpx.Client(
        base_url=base_url.rstrip("/") + "/",
        headers={"Authorization": f"Bearer {key}"},
        timeout=60.0,
        follow_redirects=False,
    )
