import logging
import uuid
from typing import TYPE_CHECKING, Any

from src.browser.browser_controller import BrowserController, BrowserOptions
from src.browser.debug_wrapper import DebugWrapper
from src.logger_db import log_action
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
        self,
        user_request: str,
        chat_history: list[dict[str, str]] | None = None,
        status_callback: Any = None,
        stream_callback: Any = None,
        user_input_callback: Any = None,
    ) -> str:
        """
        Обрабатывает пользовательский запрос.

        1. Генерирует план действий с помощью Planner.
        2. Запускает браузер.
        3. Выполняет каждый шаг плана с помощью VisionAgent.
        4. Возвращает результат.
        """
        session_id = str(uuid.uuid4())
        logger.info(f"Processing request: {user_request} (Session ID: {session_id})")
        log_action(
            "Orchestrator",
            "REQUEST_START",
            f"Processing request: {user_request}",
            {"request": user_request},
            session_id=session_id,
        )
        self._stop_requested = False

        def report_status(msg: str) -> None:
            if status_callback:
                status_callback(msg)
            print(f"[STATUS] {msg}")

        try:
            # 0. Intent Classification - DISABLED (Always Agent Mode)
            # report_status("Analyzing request...")
            # intent = self.planner.classify_intent(user_request, session_id=session_id)
            # logger.info(f"Intent classified as: {intent}")

            # Always assume agent mode
            # intent = "agent"

            # if intent == "chat":
            #     report_status("Generating answer...")
            #     answer = self.planner.generate_direct_answer(
            #         user_request, stream_callback=None, session_id=session_id
            #     )
            #     return answer

            # 1. Планирование
            logger.info("Creating plan...")
            report_status("Thinking... (Generating Plan)")
            print(f"\n[PLANNER LOG] Requesting plan for: {user_request}")

            # Retrieve memory context
            memory_context = ""

            # Force initial state context
            initial_state_context = "Current State: New Browser Session (Empty Tab). You need to navigate to the target site."

            plan: Plan = self.planner.create_plan(
                user_request,
                chat_history,
                status_callback=stream_callback,
                session_id=session_id,
            )

            # Check if initial plan is empty or just "finish"
            if not plan.steps or (
                len(plan.steps) == 1 and plan.steps[0].action in ["finish", "extract"]
            ):
                logger.warning(
                    "Initial plan was empty or premature finish. Retrying with explicit instruction."
                )
                # Retry with stronger prompt
                plan = self.planner.create_plan(
                    user_request
                    + f"\n\n{initial_state_context}\nCRITICAL: You MUST generate navigation steps.",
                    chat_history,
                    status_callback=stream_callback,
                    session_id=session_id,
                )

            print(f"[PLANNER LOG] Plan received: {plan}")
            logger.info(f"Plan created: {plan.task} ({len(plan.steps)} steps)")
            log_action(
                "Planner",
                "PLAN_CREATED",
                f"Plan created with {len(plan.steps)} steps",
                {"task": plan.task, "steps": [s.description for s in plan.steps]},
                session_id=session_id,
            )
            report_status(f"Plan created: {len(plan.steps)} steps")

            # 2. Запуск браузера
            report_status("Starting browser...")
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

                if step.action == "finish":
                    logger.info(f"Task completed: {step.description}")

                    # Extract content for summary
                    try:
                        final_page_content = page.evaluate("document.body.innerText")
                        if len(final_page_content) > 5000:
                            final_page_content = final_page_content[:5000] + "..."
                    except Exception:
                        final_page_content = "Could not extract content."

                    result = f"Task Completed. Final Page Content Summary: {final_page_content[:500]}"  # Short summary for result
                    results.append(result)

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
                log_action(
                    "Orchestrator",
                    "STEP_START",
                    f"Starting step {step.step_id}: {step.description}",
                    {
                        "step_id": step.step_id,
                        "description": step.description,
                        "action": step.action,
                    },
                    session_id=session_id,
                )

                # Execute
                if step.action == "ask_user":
                    logger.info(f"Asking user: {step.description}")
                    report_status(f"Waiting for user input: {step.description}")

                    if user_input_callback:
                        try:
                            user_answer = user_input_callback(step.description)
                        except Exception as e:
                            logger.error(f"Error getting user input: {e}")
                            user_answer = "Error: Could not get user input."
                    else:
                        # Fallback to console input
                        print(f"\n[AGENT QUESTION] {step.description}")
                        try:
                            user_answer = input("Your answer: ")
                        except EOFError:
                            user_answer = "No answer provided."

                    result = f"User answered: {user_answer}"
                    logger.info(f"User answer received: {user_answer}")

                # Handle 'extract' action specifically
                elif step.action == "extract":
                    logger.info(f"Executing Extraction: {step.description}")
                    try:
                        # Prefer text extraction from DOM over screenshot
                        page_text = page.evaluate("document.body.innerText")
                        # Limit text length to avoid token limits
                        if len(page_text) > 10000:
                            page_text = page_text[:10000] + "...(truncated)"

                        result = f"Extracted Text:\n{page_text}"

                        # If the user asked for this info, we should probably return it or save it
                        # For now, it goes into the execution history which the planner sees
                    except Exception as e:
                        logger.error(f"Text extraction failed: {e}")
                        result = f"Failed to extract text: {e}"

                elif step.action == "search":
                    logger.info(f"Executing Search: {step.description}")

                    # Try Yandex Search API first
                    api_results = yandex_search(step.description)

                    if api_results is not None:
                        logger.info(
                            f"Yandex Search API successful. Found {len(api_results)} results."
                        )

                        # Generate text summary for the agent to analyze directly
                        text_summary = (
                            f"Search Results for '{step.description}' (via API):\n"
                        )

                        for item in api_results:
                            title = item.get("title", "No Title")
                            url = item.get("url", "#")
                            snippet = item.get("snippet", "")
                            text_summary += f"- [Title: {title}] [URL: {url}]\n  Snippet: {snippet}\n"

                        # Explicit instruction to the planner
                        text_summary += "\nNOTE: The browser did NOT navigate to these results. Use the URLs above to 'navigate' to the most relevant page, or 'finish' if the answer is in the snippets."

                        result = text_summary

                    else:
                        logger.warning(
                            "Yandex Search API failed (returned None). Falling back to manual search."
                        )
                        log_action(
                            "Orchestrator",
                            "SEARCH_FALLBACK",
                            "API failed, using manual search",
                            {"query": step.description},
                            session_id=session_id,
                        )

                        # User prefers using the address bar for searching instead of API
                        # This mimics a user typing in the address bar
                        try:
                            # 1. Go to search engine homepage (ya.ru is faster/cleaner)
                            logger.info("Navigating to ya.ru for human-like search...")
                            page.goto("https://ya.ru")

                            # 2. Wait for search input
                            # ya.ru usually has input with name="text" or id="text"
                            search_input = page.locator(
                                "input[name='text'], input#text, input[type='search']"
                            ).first
                            search_input.wait_for(state="visible", timeout=5000)

                            # 3. Type the query with delay to simulate human typing
                            # 50-150ms delay per keystroke
                            logger.info(f"Typing query: {step.description}")
                            search_input.click()
                            search_input.type(step.description, delay=100)

                            # 4. Press Enter
                            page.keyboard.press("Enter")

                            # Handle popups on search result page
                            try:
                                # Give it a moment to start loading
                                page.wait_for_timeout(1000)
                                self.browser_controller.handle_popups()
                            except Exception:
                                pass

                            # Wait for results to load
                            try:
                                page.wait_for_selector(
                                    "ul.serp-list, #search-result, .main__content, .serp-item",
                                    timeout=5000,
                                )
                            except Exception:
                                pass  # Might be different layout, but we are on the page

                            result = f"Typed '{step.description}' into search and navigated to results."
                        except Exception as e:
                            logger.error(f"Human-like search failed: {e}")
                            # Fallback to direct URL navigation if typing fails
                            try:
                                import urllib.parse

                                query = urllib.parse.quote(step.description)
                                search_url = f"https://ya.ru/search/?text={query}"
                                logger.info(
                                    f"Fallback: Navigating directly to {search_url}"
                                )
                                page.goto(search_url)
                                result = f"Navigated to search results for '{step.description}' (Fallback)"
                            # For other actions, use VisionAgent but hint to prefer DOM interaction
                            # For other actions, use VisionAgent but hint to prefer DOM interaction
                            except Exception as fallback_error:
                                result = f"Search failed completely: {fallback_error}"
                else:
                    result = self.vision_agent.execute_step(
                        step,
                        page,
                        check_stop_callback=lambda: self._stop_requested,
                        stream_callback=stream_callback,
                        session_id=session_id,
                    )

                results.append(f"Step {step.step_id}: {result}")
                log_action(
                    "Orchestrator",
                    "STEP_COMPLETE",
                    f"Step {step.step_id} completed",
                    {"result": result},
                    session_id=session_id,
                )
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
                    # user_input = input(
                    #     "Press Enter to continue (replan), or 'q' to quit: "
                    # )
                    # if user_input.lower() == "q":
                    #     logger.info("Execution stopped by user (debug mode).")
                    #     break

                # Attempt to handle popups via script before capturing state
                try:
                    if self.browser_controller.handle_popups():
                        logger.info("Popups handled via script.")
                        # Give a moment for animations to finish
                        page.wait_for_timeout(500)
                except Exception as e:
                    logger.warning(f"Popup handling failed: {e}")

                # Capture State
                try:
                    # Optimization: Skip screenshot generation for text-only planning
                    # We pass "SKIP_SCREENSHOT" to get elements without drawing/saving image
                    screenshot_path = "SKIP_SCREENSHOT"
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
                # Context Management: "Forget" older details to save tokens
                # We keep full details for the last few steps, but summarize older ones.
                history_str = ""
                total_steps = len(execution_history)
                KEEP_FULL_CONTEXT_STEPS = 5

                for i, h in enumerate(execution_history):
                    is_recent = i >= (total_steps - KEEP_FULL_CONTEXT_STEPS)

                    step_desc = (
                        f"- Step {i + 1}: {h['description']} (Action: {h['action']})"
                    )
                    result_text = h["result"]

                    if not is_recent and len(result_text) > 150:
                        # Summarize old results to avoid polluting context with stale data
                        # especially large extracted text or DOM dumps
                        result_text = result_text[:150] + "... (history truncated)"

                    history_str += f"{step_desc} -> Result: {result_text}\n"

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
                            # user_hint = input(
                            #     "Your hint (or press Enter to continue): "
                            # )
                            # if user_hint.strip():
                            #     cycle_warning += f"\nUSER HINT: {user_hint}"
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
                        status_callback=stream_callback,
                        session_id=session_id,
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

                        # Now we actually need the screenshot
                        real_screenshot_path = "screenshots/planning_context.png"
                        # We can use the browser controller to get it with bboxes if needed,
                        # or just raw screenshot. Planner usually expects raw screenshot for VLM.
                        self.browser_controller.screenshot(
                            real_screenshot_path, viewport_only=True
                        )

                        new_plan = self.planner.update_plan(
                            task=user_request,
                            last_step_desc=step.description,
                            last_step_result=result,
                            current_url=current_url,
                            dom_elements=dom_str,
                            history=full_context_str,
                            screenshot_path=real_screenshot_path,
                            status_callback=stream_callback,
                            session_id=session_id,
                        )

                    # 3. Critique Step (Self-Correction)
                    # Only critique if plan is not empty and not just "extract"
                    if new_plan.steps and not (
                        len(new_plan.steps) == 1
                        and new_plan.steps[0].action == "extract"
                    ):
                        is_valid, critique = self.planner.critique_plan(
                            new_plan, full_context_str, session_id=session_id
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
                                session_id=session_id,
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
                        # Double check: Did we actually do anything?
                        if len(execution_history) == 0:
                            logger.warning(
                                "Planner tried to finish without any actions. Forcing replan."
                            )
                            full_context_str += "\nCRITICAL ERROR: You cannot finish the task without performing any actions (navigate, search, etc.). You are in a new browser session. You MUST navigate to the target site first."
                            new_plan = self.planner.update_plan(
                                task=user_request,
                                last_step_desc=step.description,
                                last_step_result=result,
                                current_url=current_url,
                                dom_elements=dom_str,
                                history=full_context_str,
                                status_callback=stream_callback,
                                session_id=session_id,
                            )
                        else:
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

                if not results:
                    final_output = "Не удалось выполнить ни одного действия. Возможно, возникла ошибка при планировании."
                    logger.warning("No results to summarize.")
                else:
                    summary = self.planner.generate_summary(
                        task=user_request,
                        history=history_text,
                        page_content=final_page_content,
                        session_id=session_id,
                    )
                    final_output = summary
                    logger.info(f"Final Summary: {summary}")
            except Exception as e:
                logger.error(f"Failed to generate summary: {e}")
                final_output = "Задача выполнена, но не удалось сгенерировать отчет."

            # Log the final answer
            log_action(
                "Orchestrator",
                "FINAL_ANSWER",
                "Task completed",
                {"answer": final_output},
                session_id=session_id,
            )

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
            error_msg = f"Error: {e}"
            log_action(
                "Orchestrator",
                "FINAL_ANSWER",
                "Task failed with error",
                {"answer": error_msg, "error": str(e)},
                session_id=session_id,
            )
            return error_msg
        finally:
            # self.close_browser()
            pass
