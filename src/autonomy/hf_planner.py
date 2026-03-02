from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from .errors import AdapterExecutionError
from .models import Action, ActionType, MissionPlan


_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


class HuggingFacePlanner:
    """Calls a Hugging Face hosted LLM over HTTPS.

    Designed to avoid loading model weights in-process (keeps this workspace fast).

    Environment variables:
      - HF_TOKEN: Hugging Face access token
      - HF_MODEL_ID: e.g. meta-llama/Llama-3.1-8B-Instruct
      - HF_ENDPOINT_URL: optional fully-qualified URL for a dedicated endpoint
      - HF_TIMEOUT_S: optional request timeout (default 20)
    """

    def __init__(
        self,
        model_id: str | None = None,
        token: str | None = None,
        endpoint_url: str | None = None,
        timeout_s: float | None = None,
    ) -> None:
        self.model_id = model_id or os.getenv("HF_MODEL_ID", "").strip()
        self.token = token or os.getenv("HF_TOKEN", "").strip()
        self.endpoint_url = endpoint_url or os.getenv("HF_ENDPOINT_URL", "").strip()
        self.timeout_s = float(timeout_s or os.getenv("HF_TIMEOUT_S", "20"))

        if not self.token:
            raise AdapterExecutionError("HF_TOKEN is required to call Hugging Face")
        if not (self.endpoint_url or self.model_id):
            raise AdapterExecutionError("HF_MODEL_ID or HF_ENDPOINT_URL is required")

    def build_plan(self, goal: str, vehicle_id: str) -> MissionPlan:
        prompt = self._build_prompt(goal=goal, vehicle_id=vehicle_id)
        raw = self._generate(prompt)
        plan_dict = self._parse_plan_json(raw)
        return self._plan_from_dict(plan_dict)

    def _build_prompt(self, goal: str, vehicle_id: str) -> str:
        # Keep this extremely constrained: we only want JSON that matches the plan schema.
        schema = {
            "goal": "string",
            "vehicle_id": "string",
            "actions": [
                {
                    "type": "arm|move_to|hold|return_to_home|disarm",
                    "x": "number|null",
                    "y": "number|null",
                    "speed_mps": "number|null",
                }
            ],
        }
        return (
            "You are a mission planner. Output ONLY valid JSON (no markdown, no prose).\n"
            "The JSON MUST match this schema exactly:\n"
            f"{json.dumps(schema, separators=(',', ':'), sort_keys=True)}\n"
            "Constraints:\n"
            "- Prefer short plans (<= 10 actions).\n"
            "- Always include arm at start and disarm at end.\n"
            "- Use return_to_home before disarm.\n"
            "\n"
            f"goal={goal!r}\n"
            f"vehicle_id={vehicle_id!r}\n"
        )

    def _generate(self, prompt: str) -> str:
        url = self.endpoint_url or f"https://api-inference.huggingface.co/models/{self.model_id}"
        try:
            body = self._post_text_generation(url=url, prompt=prompt)
            return self._extract_generated_text(json.loads(body))
        except urllib.error.HTTPError as exc:
            # Some dedicated HF endpoints expose OpenAI-compatible routes only.
            if self.endpoint_url and exc.code in {404, 405}:
                return self._post_openai_chat_completion(prompt=prompt)
            detail = exc.read().decode("utf-8", errors="replace")
            raise AdapterExecutionError(f"HF inference HTTP {exc.code}: {detail}") from exc
        except (json.JSONDecodeError, AdapterExecutionError):
            if self.endpoint_url:
                return self._post_openai_chat_completion(prompt=prompt)
            raise
        except urllib.error.URLError as exc:
            raise AdapterExecutionError(f"HF inference error: {exc}") from exc

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _post_text_generation(self, url: str, prompt: str) -> str:
        payload = {
            "inputs": prompt,
            "parameters": {
                "max_new_tokens": 300,
                "temperature": 0.1,
                "return_full_text": False,
            },
        }
        request = urllib.request.Request(
            url=url,
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
            return response.read().decode("utf-8")

    def _post_openai_chat_completion(self, prompt: str) -> str:
        if not self.endpoint_url:
            raise AdapterExecutionError("OpenAI-compatible fallback requires HF_ENDPOINT_URL")

        parsed = urllib.parse.urlparse(self.endpoint_url)
        if parsed.path.rstrip("/").endswith("/v1/chat/completions"):
            chat_url = self.endpoint_url
        else:
            chat_url = self.endpoint_url.rstrip("/") + "/v1/chat/completions"

        model = self.model_id or os.getenv("HF_CHAT_MODEL", "").strip()
        if not model:
            raise AdapterExecutionError(
                "endpoint appears OpenAI-compatible; set HF_MODEL_ID (or HF_CHAT_MODEL)"
            )

        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 300,
        }
        request = urllib.request.Request(
            url=chat_url,
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise AdapterExecutionError(f"HF chat completion HTTP {exc.code}: {detail}") from exc

        try:
            parsed_body = json.loads(body)
        except json.JSONDecodeError as exc:
            raise AdapterExecutionError("HF chat completion returned non-JSON response") from exc

        if isinstance(parsed_body, dict):
            choices = parsed_body.get("choices")
            if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                message = choices[0].get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str):
                        return content
                text = choices[0].get("text")
                if isinstance(text, str):
                    return text

        raise AdapterExecutionError("HF chat completion returned an unsupported response shape")

    def _extract_generated_text(self, parsed: object) -> str:
        if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict) and "generated_text" in parsed[0]:
            return str(parsed[0].get("generated_text", ""))
        if isinstance(parsed, dict) and "generated_text" in parsed:
            return str(parsed.get("generated_text", ""))

        # Typical response shapes:
        # - [{"generated_text": "..."}]
        # - {"generated_text": "..."}
        # - endpoint-specific JSON
        # Some endpoints return {"choices": [{"text": ...}]} or similar.
        if isinstance(parsed, dict):
            choices = parsed.get("choices")
            if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                text = choices[0].get("text") or choices[0].get("message", {}).get("content")
                if isinstance(text, str):
                    return text

        raise AdapterExecutionError("HF inference returned an unsupported response shape")

    def _parse_plan_json(self, raw: str) -> dict[str, object]:
        raw = raw.strip()
        if raw.startswith("{") and raw.endswith("}"):
            candidate = raw
        else:
            match = _JSON_BLOCK_RE.search(raw)
            if not match:
                raise AdapterExecutionError("LLM did not return JSON")
            candidate = match.group(0)

        try:
            plan = json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise AdapterExecutionError("LLM returned invalid JSON") from exc

        if not isinstance(plan, dict):
            raise AdapterExecutionError("LLM plan must be a JSON object")
        return plan

    def _plan_from_dict(self, plan: dict[str, object]) -> MissionPlan:
        goal = plan.get("goal")
        vehicle_id = plan.get("vehicle_id")
        actions_raw = plan.get("actions")
        if not isinstance(goal, str) or not isinstance(vehicle_id, str) or not isinstance(actions_raw, list):
            raise AdapterExecutionError("LLM plan missing required fields")

        actions: list[Action] = []
        for entry in actions_raw:
            if not isinstance(entry, dict):
                continue
            type_raw = entry.get("type")
            if not isinstance(type_raw, str):
                continue
            try:
                action_type = ActionType(type_raw)
            except ValueError:
                raise AdapterExecutionError(f"LLM produced unknown action type: {type_raw}")

            action = Action(
                type=action_type,
                x=float(entry["x"]) if "x" in entry and entry["x"] is not None else None,
                y=float(entry["y"]) if "y" in entry and entry["y"] is not None else None,
                speed_mps=float(entry["speed_mps"]) if "speed_mps" in entry and entry["speed_mps"] is not None else None,
            )
            if action.type == ActionType.MOVE_TO and (action.speed_mps is None or action.speed_mps <= 0):
                action.speed_mps = 3.0
            actions.append(action)

        if not actions:
            raise AdapterExecutionError("LLM plan contained no actions")

        # Light sanity: ensure expected start/end actions exist.
        if actions[0].type != ActionType.ARM:
            actions.insert(0, Action(type=ActionType.ARM))
        if actions[-1].type != ActionType.DISARM:
            if actions[-1].type != ActionType.RETURN_TO_HOME:
                actions.append(Action(type=ActionType.RETURN_TO_HOME))
            actions.append(Action(type=ActionType.DISARM))

        return MissionPlan(goal=goal, vehicle_id=vehicle_id, actions=actions)


def dump_prompt_example(goal: str = "patrol sector alpha", vehicle_id: str = "veh-001") -> str:
    # Helper for debugging prompts without calling the network.
    planner = HuggingFacePlanner(model_id="dummy", token="dummy", endpoint_url="https://example.invalid")
    return planner._build_prompt(goal=goal, vehicle_id=vehicle_id)
