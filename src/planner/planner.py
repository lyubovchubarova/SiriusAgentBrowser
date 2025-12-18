import json
import os
import re
from dataclasses import dataclass

from pydantic import ValidationError
from openai import OpenAI

from models import Plan


SYSTEM_PROMPT = """
You are a planner for browser automation.

Return ONLY valid JSON. No code fences. No commentary.

Hard constraints:
- steps length MUST be <= 10. If task is complex, merge steps.
- step_id must start from 1 and increase by 1 without gaps.
- action must be exactly one of: navigate, click, type, scroll.
- description: short, clear, imperative, one action.
- expected_result: concrete visible outcome.
- estimated_time: integer seconds.

Schema:
{
  "task": string,
  "steps": [
    {
      "step_id": number,
      "action": "navigate" | "click" | "type" | "scroll",
      "description": string,
      "expected_result": string
    }
  ],
  "estimated_time": number
}
""".strip()


@dataclass(frozen=True)
class PlannerError(Exception):
    message: str
    raw_output: str = ""


def extract_json(text: str) -> str:
    """
    Tries:
    1) ```json ... ```
    2) first {...} block
    """
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1)

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise PlannerError("LLM returned no JSON object", raw_output=text)
    return match.group(0)


class Planner:
    def __init__(self):
        self.folder = os.environ["YANDEX_CLOUD_FOLDER"]
        self.model_path = os.environ["YANDEX_CLOUD_MODEL_PATH"]

        self.client = OpenAI(
            api_key=os.environ["YANDEX_CLOUD_API_KEY"],
            base_url=os.environ["YANDEX_CLOUD_BASE_URL"],
            project=self.folder,
        )

    def _ask_llm(self, task: str, extra_user_text: str | None = None) -> str:
        user_content = task if not extra_user_text else f"{task}\n\n{extra_user_text}"
        resp = self.client.responses.create(
            model=f"gpt://{self.folder}/{self.model_path}",
            temperature=0.2,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            max_output_tokens=700,
        )
        return resp.output_text or ""

    def create_plan(self, task: str) -> Plan:
        last_raw = ""
        last_err = ""

        for attempt in range(1, 3):  # 1 + 1 ретрай
            extra = None
            if attempt > 1:
                extra = (
                    "Fix the previous output.\n"
                    "Return ONLY corrected JSON.\n"
                    f"Validation/parsing error:\n{last_err}\n"
                    f"Previous raw output:\n{last_raw}\n"
                )

            raw_text = self._ask_llm(task, extra_user_text=extra)
            last_raw = raw_text

            try:
                json_text = extract_json(raw_text)

                try:
                    data = json.loads(json_text)
                except json.JSONDecodeError as e:
                    last_err = f"JSONDecodeError: {e}"
                    continue

                try:
                    return Plan.model_validate(data)
                except ValidationError as e:
                    last_err = f"Pydantic ValidationError: {e}"
                    continue

            except PlannerError as e:
                last_err = e.message
                continue

        raise PlannerError(
            message=f"Failed to build a valid plan after 2 attempts. Last error: {last_err}",
            raw_output=last_raw,
        )
