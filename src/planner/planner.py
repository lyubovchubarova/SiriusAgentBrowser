import json
import os
import re
import time
from dataclasses import dataclass

from pydantic import ValidationError
from openai import OpenAI

from .models import Plan


SYSTEM_PROMPT = """
You are a planner for browser automation.

Return ONLY valid JSON. No code fences. No commentary.

Hard constraints:
- steps length MUST be <= 10. If task is complex, merge steps.
- step_id must start from 1 and increase by 1 without gaps.
- action must be exactly one of: navigate, click, type, scroll, extract, hover.
- description: short, clear, imperative, one action. For 'navigate', MUST include the full URL (e.g., https://wikipedia.org).
- expected_result: concrete visible outcome.
- estimated_time: integer seconds.

Strategies for complex pages:
- If the target is inside a carousel or horizontal list, add a step to click the "Next", "Right Arrow", or ">" button.
- If the page seems stuck or empty, try to "scroll" to trigger lazy loading.
- If a popup/modal blocks the view, add a step to click "Close", "X", or "Not now".
- If a menu is hidden, try to "hover" over the parent element to reveal it.

CRITICAL NAVIGATION RULES:
- If you don't know the exact URL, do NOT guess. Navigate to a search engine (https://google.com) and search.
- If you are on a search results page (Google, Yandex, etc.), DO NOT use 'navigate' to go to the target site. Use 'click' to select the relevant result.
- If the previous step resulted in a "fallback search", your next step MUST be to 'click' on a result.

Schema:
{
  "reasoning": string, // Explain your thought process here. Why did you choose these steps? What is the strategy?
  "task": string,
  "steps": [
    {
      "step_id": number,
      "action": "navigate" | "click" | "type" | "scroll" | "extract",
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

    def __str__(self):
        return f"{self.message} (Raw: {self.raw_output[:200]}...)"


def extract_json(text: str) -> str:
    """
    Tries:
    1) ```json ... ```
    2) first {...} block
    """
    fenced = re.search(
        r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE
    )
    if fenced:
        return fenced.group(1)

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise PlannerError("LLM returned no JSON object", raw_output=text)
    return match.group(0)


class Planner:
    def __init__(self, provider: str = "yandex", model: str = "gpt-4o"):
        self.provider = provider
        self.model = model

        if self.provider == "yandex":
            self.folder = os.environ["YANDEX_CLOUD_FOLDER"]
            self.model_path = os.environ["YANDEX_CLOUD_MODEL_PATH"]
            self.client = OpenAI(
                api_key=os.environ["YANDEX_CLOUD_API_KEY"],
                base_url=os.environ["YANDEX_CLOUD_BASE_URL"],
                project=self.folder,
            )
        elif self.provider == "openai":
            self.client = OpenAI(
                api_key=os.environ.get("OPENAI_API_KEY"),
            )
        else:
            raise ValueError(f"Unknown provider: {provider}")

    def _ask_llm(self, task: str, extra_user_text: str | None = None) -> str:
        user_content = task if not extra_user_text else f"{task}\n\n{extra_user_text}"

        if self.provider == "yandex":
            # YandexGPT specific call
            # Note: This assumes the OpenAI client is patched or configured for Yandex's specific API structure
            # which seems to use .responses.create instead of .chat.completions.create
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

        elif self.provider == "openai":
            # Standard OpenAI API call
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.2,
                max_tokens=700,
            )
            return response.choices[0].message.content or ""

        return ""

    def create_plan(self, task: str) -> Plan:
        return self._generate_plan_with_retry(task)

    def update_plan(
        self,
        task: str,
        last_step_desc: str,
        last_step_result: str,
        current_url: str,
        dom_elements: str,
        history: str = "",
    ) -> Plan:
        """
        Generates a new plan (remaining steps) based on the current state.
        """
        context = (
            f"Original Task: {task}\n"
            f"History of recent steps:\n{history}\n"
            f"Just executed step: {last_step_desc}\n"
            f"Result: {last_step_result}\n"
            f"Current URL: {current_url}\n"
            f"Visible Interactive Elements (JSON): {dom_elements}\n\n"
            "CRITICAL: Check if the Original Task is FULLY completed based on the Result and Current URL.\n"
            "For example, if the task asks to 'extract' or 'print' something, ensure that information is ALREADY in the 'Result' of the previous step.\n"
            "If the task is NOT fully completed, generate the next steps.\n"
            "If the task IS fully completed, return a plan with exactly ONE step:\n"
            "  - action: 'extract'\n"
            "  - description: 'Task completed successfully'\n"
            "  - expected_result: 'Done'\n"
            "Otherwise, provide the REMAINING steps to complete the task.\n"
            "Do NOT repeat steps that have already been successfully completed.\n"
            "If the history shows repeated ineffective actions, you MUST choose a DIFFERENT strategy or element.\n"
            "If the previous step failed with 'No target found', you MUST abandon the current approach and try something else (e.g. search, navigation, different element).\n"
            "If the previous step failed due to 'intercepts pointer events' or 'overlay', it means a popup/modal is blocking the view. You MUST add a step to close the modal (look for 'close', 'x', 'not now', 'sign up later') or reload the page."
        )
        return self._generate_plan_with_retry(context)

    def _generate_plan_with_retry(self, user_prompt: str) -> Plan:
        last_raw = ""
        last_err = ""

        for attempt in range(1, 4):  # Increased to 3 attempts
            if attempt > 1:
                time.sleep(2)  # Wait a bit before retry
                extra = (
                    "Fix the previous output.\n"
                    "Return ONLY corrected JSON.\n"
                    f"Validation/parsing error:\n{last_err}\n"
                    f"Previous raw output:\n{last_raw}\n"
                )
            else:
                extra = None

            try:
                raw_text = self._ask_llm(user_prompt, extra_user_text=extra)
                last_raw = raw_text
            except Exception as e:
                last_err = f"LLM API Error: {e}"
                continue

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
            message=f"Failed to build a valid plan after 3 attempts. Last error: {last_err}. Raw output: {last_raw}",
            raw_output=last_raw,
        )
