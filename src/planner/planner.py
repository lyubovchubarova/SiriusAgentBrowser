import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any

from openai import OpenAI
from pydantic import ValidationError

from .models import Plan

SYSTEM_PROMPT = """
You are a planner for browser automation.

Return ONLY valid JSON. No code fences. No commentary.

Hard constraints:
- steps length MUST be <= 10. If task is complex, merge steps.
- step_id must start from 1 and increase by 1 without gaps.
- action must be exactly one of: navigate, click, type, scroll, extract, hover, inspect, wait.
- description: short, clear, imperative.
  - For 'navigate', MUST include the full URL.
  - For 'click' or 'type', YOU MUST USE THE ELEMENT ID if available in the context (e.g., "Click [E12] 'Search'", "Type 'cat' into [E45]").
  - If no ID is visible, use the text description in single quotes.
  - For 'inspect', describe what element or section you want to analyze (e.g., "Inspect the main article content").
  - For 'wait', describe what you are waiting for (e.g., "Wait for the results to load").
- expected_result: concrete visible outcome.
- estimated_time: integer seconds.

TREE OF THOUGHTS (ToT) REASONING:
Before generating the final plan, you MUST perform a mental simulation of 3 possible strategies in the "reasoning" field.
Structure your reasoning like this:
1. Strategy A: [Description] -> Pros/Cons -> Score (1-10)
2. Strategy B: [Description] -> Pros/Cons -> Score (1-10)
3. Strategy C: [Description] -> Pros/Cons -> Score (1-10)
Selected Strategy: [Best Strategy] because [Reason].

Strategies for complex pages:
- If the target is inside a carousel or horizontal list, add a step to click the "Next", "Right Arrow", or ">" button.
- If the page seems stuck or empty, try to "scroll" to trigger lazy loading.
- If a popup/modal blocks the view, add a step to click "Close", "X", or "Not now".
- If a menu is hidden, try to "hover" over the parent element to reveal it.

CRITICAL NAVIGATION RULES:
- If you don't know the exact URL, do NOT guess. Navigate to a search engine (https://google.com) and search.
- If you are on a search results page (Google, Yandex, etc.), DO NOT use 'navigate' to go to the target site. Use 'click' to select the relevant result.
- If the previous step resulted in a "fallback search", your next step MUST be to 'click' on a result.

VISION / SCREENSHOTS:
- You primarily work with the DOM tree.
- If the DOM is insufficient (e.g., complex canvas, missing IDs, confusing layout) and you need to see the page to plan correctly, set "needs_vision": true in the JSON.
- If "needs_vision" is true, return an empty "steps" array. The system will call you again with a screenshot.

Schema:
{
  "reasoning": string, // MANDATORY: Tree of Thoughts analysis (3 strategies + selection).
  "task": string,
  "steps": [
    {
      "step_id": number,
      "action": "navigate" | "click" | "type" | "scroll" | "extract" | "hover" | "inspect" | "wait",
      "description": string,
      "expected_result": string
    }
  ],
  "estimated_time": number,
  "needs_vision": boolean // Optional, default false. Set to true to request a screenshot.
}
""".strip()


@dataclass(frozen=True)
class PlannerError(Exception):
    message: str
    raw_output: str = ""

    def __str__(self) -> str:
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

    def _ask_llm(
        self,
        task: str,
        extra_user_text: str | None = None,
        image_path: str | None = None,
    ) -> str:
        user_content: Any

        if image_path:
            import base64
            from pathlib import Path

            with Path(image_path).open("rb") as img_file:
                b64_image = base64.b64encode(img_file.read()).decode("utf-8")

            text_part = task if not extra_user_text else f"{task}\n\n{extra_user_text}"
            user_content = [
                {"type": "text", "text": text_part},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64_image}"},
                },
            ]
        else:
            user_content = (
                task if not extra_user_text else f"{task}\n\n{extra_user_text}"
            )

        if self.provider == "yandex":
            # YandexGPT specific call
            # Note: This assumes the OpenAI client is patched or configured for Yandex's specific API structure
            # which seems to use .responses.create instead of .chat.completions.create

            # Yandex currently supports images via specific API or multimodal models.
            # Assuming the client handles list content correctly for multimodal models if configured.
            # If not, we might need to adjust. For now, assuming standard OpenAI-like structure for multimodal.

            # Note: Yandex GPT API structure for images might differ.
            # If using standard OpenAI client with Yandex base_url, it might expect standard format.

            resp = self.client.responses.create(
                model=f"gpt://{self.folder}/{self.model_path}",
                temperature=0.2,
                input=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                max_output_tokens=1000,
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
                max_tokens=1000,
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
        screenshot_path: str | None = None,
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
        if screenshot_path:
            context += "\nA screenshot of the current page is attached. Use it to resolve ambiguity if the DOM is insufficient.\n"

        return self._generate_plan_with_retry(context, image_path=screenshot_path)

    def _generate_plan_with_retry(
        self, user_prompt: str, image_path: str | None = None
    ) -> Plan:
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
                raw_text = self._ask_llm(
                    user_prompt, extra_user_text=extra, image_path=image_path
                )
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

    def critique_plan(self, plan: Plan, context: str) -> tuple[bool, str]:
        """
        Critiques the generated plan. Returns (is_valid, critique_message).
        """
        prompt = f"""
        You are a critical reviewer for browser automation plans.

        Context:
        {context}

        Proposed Plan:
        {plan.model_dump_json(indent=2)}

        Analyze the plan for:
        1. Logical consistency (e.g., clicking a button that doesn't exist in context).
        2. Redundancy (repeating steps).
        3. Safety (avoiding infinite loops).
        4. Completeness (does it address the user task?).

        If the plan is good, return "VALID".
        If the plan has issues, return "INVALID: <reason>".
        """

        try:
            response = self._ask_llm(prompt)
            if "INVALID" in response:
                return False, response
            return True, "Plan looks good."
        except Exception as e:
            return True, f"Critique failed, assuming valid. Error: {e}"

    def generate_summary(self, task: str, history: str) -> str:
        """
        Generates a human-readable summary of the task execution.
        """
        prompt = f"""
        You are a helpful assistant. The user asked: "{task}".

        Here is the execution history of the agent:
        {history}

        Please provide a concise, human-readable answer or summary of the result.
        If the task was to find information, provide that information clearly.
        If the task was an action, confirm it was completed and describe the outcome.
        Do not mention internal steps like "clicked element E12" unless necessary for context.
        """

        try:
            if self.provider == "yandex":
                resp = self.client.responses.create(
                    model=f"gpt://{self.folder}/{self.model_path}",
                    temperature=0.7,
                    input=[
                        {"role": "system", "content": "You are a helpful assistant."},
                        {"role": "user", "content": prompt},
                    ],
                    max_output_tokens=1000,
                )
                return resp.output_text or ""
            else:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.7,
                )
                return response.choices[0].message.content or ""
        except Exception as e:
            return f"Task completed, but failed to generate summary: {e}"
