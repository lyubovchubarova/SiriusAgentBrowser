import logging
from typing import TYPE_CHECKING, Any

from src.browser.browser_controller import BrowserController, BrowserOptions
from src.browser.debug_wrapper import DebugWrapper
from src.memory.long_term_memory import LongTermMemory
from src.planner.planner import Planner
from src.tools.search import yandex_search
from src.vlm.vlm import VisionAgent

if TYPE_CHECKING:
    from src.planner.models import Plan

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(
        self,
        headless: bool = False,
        debug_mode: bool = False,
        llm_provider: str = "yandex",
        llm_model: str = "gpt-4o",
        cdp_url: str | None = None,
    ):
        self.planner = Planner(provider=llm_provider, model=llm_model)
        self.vision_agent = VisionAgent()
        self.browser_controller = BrowserController(
            BrowserOptions(headless=headless, cdp_url=cdp_url)
        )
        self.memory = LongTermMemory()
        self._is_browser_started = False
        self.debug_mode = debug_mode
        self._stop_requested = False

    def stop(self) -> None:
        """Signals the orchestrator to stop execution."""
        self._stop_requested = True
        logger.info("Stop requested.")

    def start_browser(self) -> None:
        if not self._is_browser_started:
            self.browser_controller.start()
            self._is_browser_started = True
            logger.info("Browser started.")

    def close_browser(self) -> None:
        if self._is_browser_started:
            self.browser_controller.close()
            self._is_browser_started = False
            logger.info("Browser closed.")

    def process_request(
        self, user_request: str, chat_history: list[dict[str, str]] | None = None
    ) -> str:
        """
        Обрабатывает пользовательский запрос.

        1. Генерирует план действий с помощью Planner.
        2. Запускает браузер.
        3. Выполняет каждый шаг плана с помощью VisionAgent.
        4. Возвращает результат.
        """
        logger.info(f"Processing request: {user_request}")
        self._stop_requested = False

        try:
            # 1. Планирование
            logger.info("Creating plan...")
            print(f"\n[PLANNER LOG] Requesting plan for: {user_request}")

            # Retrieve memory context
            memory_context = ""
            # We don't have a URL yet, so we can't fetch domain-specific memory easily
            # But we can try if the user request contains a URL
            # For now, let's skip initial memory or try to guess domain from request?
            # Better: Pass empty memory first, and update plan with memory later when we have a URL.

            plan: Plan = self.planner.create_plan(user_request, chat_history)
            print(f"[PLANNER LOG] Plan received: {plan}")
            logger.info(f"Plan created: {plan.task} ({len(plan.steps)} steps)")

            # 2. Запуск браузера
            self.start_browser()
            page: Any = self.browser_controller.page

            if self.debug_mode:
                page = DebugWrapper(page)

            # 3. Выполнение шагов
            results = []

            # Dynamic execution loop
            max_steps = 20  # Safety limit
            step_count = 0

            # Memory of executed steps for cycle detection
            execution_history = []
            final_page_content = ""

            while plan.steps and step_count < max_steps:
                if self._stop_requested:
                    logger.info("Execution stopped by user request.")
                    results.append("Execution stopped by user.")
                    break

                step = plan.steps[0]  # Always take the first step of the current plan

                # Handle 'finish' action
                if step.action == "finish":
                    logger.info(f"Task completed: {step.description}")
                    results.append(f"Task completed: {step.description}")

                    # Extract content for summary
                    try:
                        final_page_content = page.evaluate("document.body.innerText")
                    except Exception:
                        final_page_content = "Could not extract content."

                    # Add to history so memory saver knows we finished
                    execution_history.append(
                        {
                            "description": step.description,
                            "action": "finish",
                            "result": "Task Completed Successfully",
                            "url": page.url,
                        }
                    )
                    break

                step_count += 1

                logger.info(f"Step {step.step_id}: {step.description}")

                # Execute
                if step.action == "search":
                    logger.info(f"Executing Search API: {step.description}")
                    try:
                        search_results = yandex_search(step.description)
                        if not search_results:
                            result = "Search returned no results."
                        else:
                            # Format top 5 results for the planner
                            formatted_results = []
                            for i, res in enumerate(search_results[:5]):
                                formatted_results.append(
                                    f"{i+1}. [{res['title']}]({res['url']}) - {res['snippet']}"
                                )
                            result = "Search Results:\n" + "\n".join(formatted_results)
                    except Exception as e:
                        result = f"Search API failed: {e}"
                else:
                    result = self.vision_agent.execute_step(
                        step, page, check_stop_callback=lambda: self._stop_requested
                    )

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
                        extra_info = ""
                        attrs = el.get("attributes", {})
                        if attrs.get("href"):
                            extra_info = f" (href: {attrs['href']})"
                        elif attrs.get("placeholder"):
                            extra_info = f" (placeholder: {attrs['placeholder']})"

                        formatted_elements.append(
                            f'[{el["id"]}] {el["type"]} "{el["text"]}"{extra_info}'
                        )
                    dom_str = "\n".join(formatted_elements)

                    # Add Accessibility Tree for better context
                    # Only fetch if DOM is complex or small
                    if len(elements) < 5 or len(elements) > 50:
                         ax_tree = self.browser_controller.get_accessibility_tree()
                         # Limit tree size roughly
                         if len(ax_tree) > 5000:
                             ax_tree = ax_tree[:5000] + "...(truncated)"
                         dom_str += f"\n\nAccessibility Tree (Semantic View):\n{ax_tree}"
                    else:
                         dom_str += "\n\n(Accessibility Tree skipped for performance)"

                    current_url = page.url

                    # Retrieve Memory Context
                    memory_context = self.memory.retrieve_relevant(
                        current_url, user_request
                    )
                    if memory_context:
                        logger.info("Memory context retrieved.")

                except Exception as e:
                    logger.error(f"Failed to capture state: {e}")
                    dom_str = "Error capturing DOM"
                    current_url = "unknown"
                    memory_context = ""

                # Prepare history string for planner
                # Pass FULL history to provide maximum context for the planner
                history_str = ""
                for i, h in enumerate(execution_history):
                    history_str += f"- Step {i + 1}: {h['description']} (Action: {h['action']}) -> Result: {h['result']}\n"

                print(
                    f"\n[PLANNER LOG] Updating plan based on history ({len(execution_history)} steps):\n{history_str}"
                )

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
                            # Human-in-the-loop: Ask user for help if stuck
                            print("\n" + "!" * 50)
                            print("AGENT IS STUCK. Please provide a hint or strategy.")
                            print(f"Last error: {last_entry['result']}")
                            user_hint = input(
                                "Your hint (or press Enter to continue): "
                            )
                            if user_hint.strip():
                                cycle_warning += f"\nUSER HINT: {user_hint}"
                            print("!" * 50 + "\n")

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
                    print(
                        f"[PLANNER LOG] Cycle warning added to context: {cycle_warning}"
                    )

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
                print(
                    f"[PLANNER LOG] Replanning... Context: URL={current_url}, Last Result={result[:100]}..."
                )
                try:
                    # Inject memory into history or a new field?
                    # Planner.update_plan takes specific args. Let's append memory to history for now or modify Planner.
                    # Let's append to history_str as it's the easiest way to pass context without changing signature too much

                    full_context_str = history_str
                    if memory_context:
                        full_context_str += f"\n\n{memory_context}"

                    # 1. Try planning with DOM only (Priority to DOM)
                    new_plan = self.planner.update_plan(
                        task=user_request,
                        last_step_desc=step.description,
                        last_step_result=result,
                        current_url=current_url,
                        dom_elements=dom_str,
                        history=full_context_str,
                    )
                    print(f"[PLANNER LOG] Updated Plan: {new_plan}")

                    # 2. Check if Planner requested vision
                    if new_plan.needs_vision:
                        logger.info(
                            "Planner requested vision (screenshot). Waiting for full load and retrying..."
                        )
                        # Force wait for full load before taking screenshot for VLM
                        try:
                            page.wait_for_load_state("load", timeout=15000)
                        except Exception:
                            logger.warning(
                                "Timeout waiting for full load (vision fallback)."
                            )

                        screenshot_path = "screenshots/planning_context.png"
                        self.browser_controller.screenshot(
                            screenshot_path, viewport_only=True
                        )

                        new_plan = self.planner.update_plan(
                            task=user_request,
                            last_step_desc=step.description,
                            last_step_result=result,
                            current_url=current_url,
                            dom_elements=dom_str,
                            history=full_context_str,
                            screenshot_path=screenshot_path,
                        )

                    # 3. Critique Step (Self-Correction)
                    # Only critique if plan is not empty and not just "extract"
                    if new_plan.steps and not (
                        len(new_plan.steps) == 1
                        and new_plan.steps[0].action == "extract"
                    ):
                        is_valid, critique = self.planner.critique_plan(
                            new_plan, full_context_str
                        )
                        if not is_valid:
                            logger.warning(
                                f"Plan critique failed: {critique}. Requesting fix..."
                            )
                            # Add critique to history and replan
                            full_context_str += (
                                f"\nCRITIQUE: {critique}\nPlease fix the plan."
                            )

                            # Re-run update_plan with critique
                            new_plan = self.planner.update_plan(
                                task=user_request,
                                last_step_desc=step.description,
                                last_step_result=result,
                                current_url=current_url,
                                dom_elements=dom_str,
                                history=full_context_str,
                                screenshot_path=(
                                    screenshot_path if new_plan.needs_vision else None
                                ),
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

            # Generate human-readable summary
            final_output = ""
            try:
                history_text = "\n".join(results)
                summary = self.planner.generate_summary(
                    user_request, history_text, final_page_content
                )
                final_output = summary
                logger.info(f"Final Summary: {summary}")
            except Exception as e:
                logger.error(f"Failed to generate summary: {e}")
                final_output = "Задача выполнена, но не удалось сгенерировать отчет."

            # Save successful experience to memory
            if execution_history and "Failed" not in execution_history[-1]["result"]:
                # Only save if the last step wasn't a failure (heuristic)
                # Ideally we need a "Task Completed" signal
                last_url = execution_history[-1]["url"]
                self.memory.add_experience(last_url, user_request, execution_history)
                logger.info("Experience saved to long-term memory.")

            return final_output

        except Exception as e:
            logger.error(f"Error processing request: {e}", exc_info=True)
            return f"Error: {e}"
        finally:
            # self.close_browser()
            pass
