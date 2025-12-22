import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, cast

from openai import OpenAI
from pydantic import ValidationError

from .models import Plan

SYSTEM_PROMPT = """
You are a planner for browser automation.

Return ONLY valid JSON. No code fences. No commentary.
Format the JSON with indentation (2 or 4 spaces) for readability.

Hard constraints:
- steps length MUST be <= 10. If task is complex, merge steps.
- step_id must start from 1 and increase by 1 without gaps.
- action must be exactly one of: navigate, click, type, scroll, extract, hover, inspect, wait, finish, search, solve_captcha, ask_user.
- description: short, clear, imperative.
  - For 'search', provide ONLY the optimal search keywords (e.g., "python documentation"). Do NOT include system words like "search for", "find", "look up".
  - For 'navigate', MUST include the full URL.
  - For 'click' or 'type', YOU MUST USE THE ELEMENT ID if available in the context (e.g., "Click [E12] 'Search'", "Type 'cat' into [E45]").
  - If no ID is visible, use the text description in single quotes.
  - For 'inspect', describe what element or section you want to analyze (e.g., "Inspect the main article content").
  - For 'wait', describe what you are waiting for (e.g., "Wait for the results to load").
  - For 'solve_captcha', describe what kind of captcha you see (e.g., "Solve the Cloudflare challenge").
  - For 'ask_user', describe the question you want to ask the user (e.g., "Please enter the 2FA code sent to your phone", "What is your login username?").
  - For 'finish', describe why the task is complete. If the task was just to find/open a page, use this action as soon as the page is loaded.
- expected_result: concrete visible outcome.
- estimated_time: integer seconds.

REASONING:
Provide a concise chain-of-thought reasoning for your plan IN RUSSIAN. Explain why you chose the specific actions and elements.
If the task is complex, briefly consider alternatives, but prioritize speed and directness.

Strategies for complex pages:
- If the target is inside a carousel or horizontal list, add a step to click the "Next", "Right Arrow", or ">" button.
- If the page seems stuck or empty, try to "scroll" to trigger lazy loading.
- If a popup/modal blocks the view, add a step to click "Close", "X", or "Not now".
- If a menu is hidden, try to "hover" over the parent element to reveal it.
- If you see a CAPTCHA or "I am not a robot" checkbox, use the 'solve_captcha' action.

CRITICAL NAVIGATION RULES:
- DIRECT NAVIGATION: If you know the URL (e.g., 'https://youtube.com', 'https://github.com'), use 'navigate' directly. Do not search for it.
- SEARCHING: If you need to find something, use the 'search' action. This will type the query into the browser's address bar/search engine.
- DO NOT navigate to a search engine (like ya.ru) manually to type a query. Just use the 'search' action.
- AFTER SEARCHING: You will be on a search results page. Use 'click' to select the relevant result.
- ADDRESS BAR: The 'search' action is equivalent to typing in the address bar.

QUALITY CONTROL & COMPLETION:
- When selecting a search result, CHECK THE HREF/URL in the context if available. Ensure it matches the target domain (e.g., 'genius.com' for lyrics, not 'yandex.ru/ads').
- Avoid clicking 'Sponsored', 'Ad', or 'Реклама' links unless explicitly asked.
- In your reasoning, explicitly state WHY you chose a specific ID (e.g., "I chose [E15] because it links to genius.com and has the correct title").
- CHECK IF THE TASK IS ALREADY COMPLETED. If the current page content matches the user's request (e.g., the article is open), use the 'finish' action immediately. DO NOT continue clicking or opening more pages.
- NEW SESSION RULE: If you are starting a new task and the current URL is unknown or 'about:blank', you MUST generate at least one 'navigate' or 'search' step. Do NOT assume the page is already open.
- SINGLE TAB POLICY: PREFER working in the current tab. Only open a new tab if the user EXPLICITLY requested it (e.g., "open in a new tab"). If the user did not ask for a new tab, assume all links should open in the current tab.

VISION / SCREENSHOTS:
- You primarily work with the DOM tree.
- If the DOM is insufficient (e.g., complex canvas, missing IDs, confusing layout) and you need to see the page to plan correctly, set "needs_vision": true in the JSON.
- If "needs_vision" is true, return an empty "steps" array. The system will call you again with a screenshot.

Schema:
{
  "reasoning": string, // Concise reasoning for the plan.
  "task": string,
  "steps": [
    {
      "step_id": number,
      "action": "navigate" | "click" | "type" | "scroll" | "extract" | "hover" | "inspect" | "wait" | "finish",
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

    def classify_intent(self, user_prompt: str) -> str:
        """
        Determines if the user prompt requires browser automation ('agent')
        or can be answered directly by the LLM ('chat').
        """
        prompt = f"""
You are a classifier. Determine if the user's request requires using a web browser to perform actions (searching, navigating, clicking) OR if it can be answered directly by a language model (general knowledge, recipes, explanations).

User Request: "{user_prompt}"

Return ONLY one word: "agent" or "chat".
""".strip()

        try:
            model_to_use = self.model
            if self.provider == "yandex":
                # Construct proper YandexGPT model URI
                if self.model_path.startswith("gpt://"):
                    model_to_use = self.model_path
                else:
                    model_to_use = f"gpt://{self.folder}/{self.model_path}"

            response = self.client.chat.completions.create(
                model=model_to_use,
                messages=cast("Any", [{"role": "user", "content": prompt}]),
                temperature=0.0,
            )
            content = response.choices[0].message.content
            result = content.strip().lower() if content else "agent"
            return "agent" if "agent" in result else "chat"
        except Exception as e:
            print(f"Classification error: {e}")
            return "agent"  # Default to agent if unsure

    def generate_direct_answer(
        self, user_prompt: str, stream_callback: Any = None
    ) -> str:
        """
        Generates a direct answer for the user without using the browser.
        """
        messages = [
            {
                "role": "system",
                "content": "You are a helpful AI assistant. Answer the user's question directly and concisely.",
            },
            {"role": "user", "content": user_prompt},
        ]

        # Determine model to use
        model_to_use = self.model
        if self.provider == "yandex":
             if self.model_path.startswith("gpt://"):
                model_to_use = self.model_path
             else:
                model_to_use = f"gpt://{self.folder}/{self.model_path}"

        try:
            if stream_callback:
                stream = cast(
                    "Any",
                    self.client.chat.completions.create(
                        model=model_to_use,
                        messages=cast("Any", messages),
                        stream=True,
                    ),
                )
                full_response = ""
                for chunk in stream:
                    if chunk.choices[0].delta.content:
                        content = chunk.choices[0].delta.content
                        full_response += content
                        stream_callback(content)
                return full_response
            else:
                response = self.client.chat.completions.create(
                    model=model_to_use,
                    messages=cast("Any", messages),
                )
                return response.choices[0].message.content or ""
        except Exception as e:
            return f"Error generating answer: {e}"

    def _ask_llm(
        self,
        task: str,
        extra_user_text: str | None = None,
        image_path: str | None = None,
        system_prompt: str | None = None,
        use_reasoning: bool = False,
        stream_callback: Any = None,
    ) -> str:
        user_content: Any

        # Default to global SYSTEM_PROMPT if not provided
        sys_prompt = system_prompt if system_prompt is not None else SYSTEM_PROMPT

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
            # Use standard OpenAI-compatible API for Yandex
            print("\n[PLANNER LOG] Sending request to LLM (Streamed)...")

            model_to_use = self.model_path
            if not model_to_use.startswith("gpt://"):
                model_to_use = f"gpt://{self.folder}/{self.model_path}"

            kwargs = {
                "model": model_to_use,
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_content},
                ],
                "temperature": 0.2,
                "max_tokens": 2000,
                "stream": True,
            }

            if use_reasoning:
                kwargs["extra_body"] = {"reasoningOptions": {"mode": "ENABLED_HIDDEN"}}
                print("[PLANNER LOG] Reasoning enabled.")

            try:
                response = self.client.chat.completions.create(**cast("Any", kwargs))

                full_response = ""
                print("[PLANNER STREAM] ", end="", flush=True)

                for chunk in response:
                    if not chunk.choices:
                        continue
                    content = chunk.choices[0].delta.content
                    if content:
                        print(content, end="", flush=True)
                        full_response += content
                        if stream_callback:
                            stream_callback(content)

                print("\n")  # Newline after stream
                return full_response

            except Exception as e:
                print(f"\n[PLANNER ERROR] Streaming failed: {e}")
                # Fallback or re-raise?
                raise e

        elif self.provider == "openai":
            # Standard OpenAI API call with streaming
            print("\n[PLANNER LOG] Sending request to OpenAI (Streamed)...")
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.2,
                max_tokens=1000,
                stream=True,
            )

            full_response = ""
            print("[PLANNER STREAM] ", end="", flush=True)

            for chunk in response:
                if not chunk.choices:
                    continue
                content = chunk.choices[0].delta.content
                if content:
                    print(content, end="", flush=True)
                    full_response += content
                    if stream_callback:
                        stream_callback(content)

            print("\n")
            return full_response

        return ""

    def create_plan(
        self,
        task: str,
        chat_history: list[dict[str, str]] | None = None,
        status_callback: Any = None,
    ) -> Plan:
        prompt = f"Task: {task}\n\nCurrent State: New Browser Session (Empty Tab). You need to navigate to the target site."
        if chat_history:
            # Format chat history for the model
            history_str = ""
            for msg in chat_history:
                role = msg.get("role", "unknown").upper()
                content = msg.get("content", "")
                history_str += f"{role}: {content}\n"

            prompt += f"\n\nCONTEXT FROM CHAT HISTORY:\n{history_str}\n\nUse this history to understand the user's intent better (e.g. if they refer to previous results), but focus on executing the current Task."

        return self._generate_plan_with_retry(prompt, stream_callback=status_callback)

    def update_plan(
        self,
        task: str,
        last_step_desc: str,
        last_step_result: str,
        current_url: str,
        dom_elements: str,
        history: str = "",
        screenshot_path: str | None = None,
        status_callback: Any = None,
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

        return self._generate_plan_with_retry(
            context, image_path=screenshot_path, stream_callback=status_callback
        )

    def _generate_plan_with_retry(
        self,
        user_prompt: str,
        image_path: str | None = None,
        stream_callback: Any = None,
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
                    user_prompt,
                    extra_user_text=extra,
                    image_path=image_path,
                    use_reasoning=True,  # Enable reasoning for planning
                    stream_callback=stream_callback,
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
                    return cast("Plan", Plan.model_validate(data))
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
            response = self._ask_llm(
                task=prompt,
                system_prompt="You are a critical reviewer.",
                use_reasoning=True,  # Reasoning helps critique
            )
            if "INVALID" in response:
                return False, response
            return True, "Plan looks good."
        except Exception as e:
            return True, f"Critique failed, assuming valid. Error: {e}"

    def generate_summary(self, task: str, history: str, page_content: str = "") -> str:
        """
        Generates a human-readable summary of the task execution.
        """
        prompt = f"""
        You are a helpful assistant. The user asked: "{task}".

        Here is the execution history of the agent:
        {history}

        Here is the text content of the final page (truncated):
        {page_content[:5000]}

        Please provide a concise, human-readable answer or summary of the result.

        IMPORTANT RULES FOR SUMMARY:
        1. If the user asked to "find", "open", "read", or "navigate to" a page/article, and the agent successfully opened it:
           - Just confirm that the page is open.
           - Briefly mention the title or topic of the page to confirm it's the right one.
           - DO NOT copy the full text of the article into the chat unless explicitly asked (e.g. "summarize", "copy text").
        2. If the user asked a specific question (e.g., "what is the price?", "who is the CEO?"):
           - Extract the specific answer from the page content.
        3. Keep it short and natural.
        4. Do not mention internal steps like "clicked element E12" unless necessary for context.
        """

        try:
            # Use _ask_llm but with a custom system prompt for summary
            return self._ask_llm(
                task=prompt,
                system_prompt="You are a helpful assistant.",
                use_reasoning=False,  # No reasoning needed for summary
            )
        except Exception as e:
            return f"Task completed, but failed to generate summary: {e}"
