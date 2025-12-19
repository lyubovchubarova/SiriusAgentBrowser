import logging
import json
from typing import Optional

from src.browser.browser_controller import BrowserController, BrowserOptions
from src.browser.debug_wrapper import DebugWrapper
from src.planner.planner import Planner
from src.planner.models import Plan
from src.vlm.vlm import VisionAgent

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(
        self,
        headless: bool = False,
        debug_mode: bool = False,
        llm_provider: str = "yandex",
        llm_model: str = "gpt-4o",
    ):
        self.planner = Planner(provider=llm_provider, model=llm_model)
        self.vision_agent = VisionAgent()
        self.browser_controller = BrowserController(BrowserOptions(headless=headless))
        self._is_browser_started = False
        self.debug_mode = debug_mode

    def start_browser(self):
        if not self._is_browser_started:
            self.browser_controller.start()
            self._is_browser_started = True
            logger.info("Browser started.")

    def close_browser(self):
        if self._is_browser_started:
            self.browser_controller.close()
            self._is_browser_started = False
            logger.info("Browser closed.")

    def process_request(self, user_request: str) -> str:
        """
        Обрабатывает пользовательский запрос.

        1. Генерирует план действий с помощью Planner.
        2. Запускает браузер.
        3. Выполняет каждый шаг плана с помощью VisionAgent.
        4. Возвращает результат.
        """
        logger.info(f"Processing request: {user_request}")

        try:
            # 1. Планирование
            logger.info("Creating plan...")
            plan: Plan = self.planner.create_plan(user_request)
            logger.info(f"Plan created: {plan.task} ({len(plan.steps)} steps)")

            # 2. Запуск браузера
            self.start_browser()
            page = self.browser_controller.page

            if self.debug_mode:
                page = DebugWrapper(page)

            # 3. Выполнение шагов
            results = []

            # Dynamic execution loop
            max_steps = 20  # Safety limit
            step_count = 0

            # Memory of executed steps for cycle detection
            execution_history = []

            while plan.steps and step_count < max_steps:
                step = plan.steps[0]  # Always take the first step of the current plan
                step_count += 1

                logger.info(f"Step {step.step_id}: {step.description}")

                # Execute
                result = self.vision_agent.execute_step(step, page)
                results.append(f"Step {step.step_id}: {result}")
                logger.info(f"Step {step.step_id} result: {result}")

                # Add to history
                execution_history.append(
                    {
                        "description": step.description,
                        "action": step.action,
                        "result": result,
                        "url": page.url if hasattr(page, "url") else "unknown",
                    }
                )

                # Check for critical browser error
                if "Target page, context or browser has been closed" in result:
                    logger.warning("Browser closed unexpectedly. Restarting...")
                    self.close_browser()
                    self.start_browser()
                    page = self.browser_controller.page
                    if self.debug_mode:
                        page = DebugWrapper(page)
                    # Retry the same step? Or replan?
                    # Let's replan.

                if self.debug_mode:
                    print(f"\n--- [DEBUG] Step {step.step_id} Completed ---")
                    print(f"Action: {step.action}")
                    print(f"Result: {result}")
                    user_input = input(
                        "Press Enter to continue (replan), or 'q' to quit: "
                    )
                    if user_input.lower() == "q":
                        logger.info("Execution stopped by user (debug mode).")
                        break

                # Capture State
                try:
                    screenshot_path = "screenshots/current_state.png"
                    dom_data = self.browser_controller.screenshot_with_bboxes(
                        screenshot_path
                    )
                    elements = dom_data.get("elements", [])

                    # Format elements for LLM
                    # Limit to top 100 elements to save context
                    formatted_elements = []
                    for el in elements[:100]:
                        formatted_elements.append(
                            f"[{el['id']}] {el['type']} \"{el['text']}\""
                        )
                    dom_str = "\n".join(formatted_elements)

                    # Add Accessibility Tree for better context
                    ax_tree = self.browser_controller.get_accessibility_tree()
                    # Limit tree size roughly
                    if len(ax_tree) > 8000:
                        ax_tree = ax_tree[:8000] + "...(truncated)"

                    dom_str += f"\n\nAccessibility Tree (Semantic View):\n{ax_tree}"

                    current_url = page.url
                except Exception as e:
                    logger.error(f"Failed to capture state: {e}")
                    dom_str = "Error capturing DOM"
                    current_url = "unknown"

                # Prepare history string for planner
                # Take last 20 steps to provide better context and avoid loops
                history_str = ""
                recent_history = execution_history[-20:]
                start_idx = max(1, len(execution_history) - 19)
                for i, h in enumerate(recent_history):
                    history_str += f"- Step {start_idx + i}: {h['description']} (Action: {h['action']}) -> Result: {h['result']}\n"

                # Simple cycle detection
                # If the exact same action description and result happened in the last 3 steps (excluding current), warn
                cycle_warning = ""
                if len(execution_history) > 1:
                    last_entry = execution_history[-1]

                    # Check for repeated failures
                    if "Failed" in last_entry["result"]:
                        fail_count = 0
                        for h in execution_history[-3:]:
                            if (
                                "Failed" in h["result"]
                                and h["description"] == last_entry["description"]
                            ):
                                fail_count += 1

                        if fail_count >= 2:
                            cycle_warning = "CRITICAL: You are repeatedly failing with the same action. You MUST change strategy. Do NOT try the same action again."

                    # Check previous entries for exact duplicates
                    if not cycle_warning:
                        for prev in execution_history[:-1][
                            -3:
                        ]:  # Look at last 3 before current
                            if (
                                prev["description"] == last_entry["description"]
                                and prev["result"] == last_entry["result"]
                            ):
                                cycle_warning = "WARNING: It seems you are repeating the same action with the same result. You MUST try a different approach."
                                break

                if cycle_warning:
                    history_str += f"\n{cycle_warning}"
                    logger.warning(f"Cycle detected: {cycle_warning}")

                # Special handling for "No target found"
                if "No target found" in result:
                    logger.warning(
                        "Action failed: No target found. Triggering full replan strategy."
                    )
                    result += " (CRITICAL FAILURE: The target element was NOT found. The previous plan is invalid. You MUST generate a completely NEW plan using a different strategy, e.g., use a search engine, go to the homepage, or use a different selector.)"

                # Special handling for Search Fallback Loop
                if "You are now on the search results page" in result:
                    result += " (CRITICAL INSTRUCTION: You are on a search results page. The previous 'navigate' action was converted to a search. DO NOT use 'navigate' again. Your next action MUST be 'click' to select a result from the list.)"

                # Replan
                logger.info("Replanning based on new state...")
                try:
                    new_plan = self.planner.update_plan(
                        task=user_request,
                        last_step_desc=step.description,
                        last_step_result=result,
                        current_url=current_url,
                        dom_elements=dom_str,
                        history=history_str,
                    )

                    # Check if task is completed
                    # Heuristic: if plan is empty or has a "finish" step
                    if not new_plan.steps:
                        logger.info(
                            "Planner returned empty plan. Assuming task completed."
                        )
                        break

                    if (
                        len(new_plan.steps) == 1
                        and new_plan.steps[0].action == "extract"
                        and "complete" in new_plan.steps[0].description.lower()
                    ):
                        logger.info("Planner indicates task completion.")
                        break

                    plan = new_plan
                    logger.info(f"New plan: {len(plan.steps)} steps")

                except Exception as e:
                    logger.error(f"Replanning failed: {e}", exc_info=True)
                    break
                    # If replan fails, we are stuck.
                    break

            return "\n".join(results)

        except Exception as e:
            logger.error(f"Error processing request: {e}", exc_info=True)
            return f"Error: {e}"
        finally:
            # self.close_browser()
            pass
            # Обычно агент выполнил задачу и завершил работу.
            # self.close_browser()
            pass
