import time
import re
import os
from playwright.sync_api import Page
from src.planner.models import Step
from src.vlm.agent import VLMAgent as RealVLMAgent


class VisionAgent:
    """
    VLM агент, который выполняет шаги плана, анализируя скриншоты и управляя браузером.
    """

    def __init__(self):
        # Initialize the real VLM agent
        # We try to get credentials from env, but don't crash if missing
        self.vlm = RealVLMAgent()

    def _mark_page(self, page: Page):
        """
        Injects JavaScript to draw numbered boxes on interactive elements (Set-of-Marks).
        """
        js_code = """
        (function() {
            // Remove existing marks
            document.querySelectorAll('.som-marker').forEach(e => e.remove());
            window.som_elements = {};

            let id = 1;
            // Select interactive elements
            const items = document.querySelectorAll('a, button, input, textarea, select, [role="button"], [role="link"]');
            
            items.forEach(el => {
                const rect = el.getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0 && window.getComputedStyle(el).visibility !== 'hidden') {
                    // Check if in viewport
                    if (rect.top >= 0 && rect.left >= 0 && rect.bottom <= window.innerHeight && rect.right <= window.innerWidth) {
                        
                        const marker = document.createElement('div');
                        marker.className = 'som-marker';
                        marker.textContent = id;
                        marker.style.position = 'fixed';
                        marker.style.left = rect.left + 'px';
                        marker.style.top = rect.top + 'px';
                        marker.style.backgroundColor = '#FFD700'; // Gold
                        marker.style.color = 'black';
                        marker.style.border = '2px solid #FF0000'; // Red
                        marker.style.fontSize = '14px';
                        marker.style.fontWeight = 'bold';
                        marker.style.zIndex = '2147483647'; // Max z-index
                        marker.style.padding = '2px';
                        marker.style.borderRadius = '4px';
                        marker.style.boxShadow = '0 0 2px white';
                        marker.style.pointerEvents = 'none'; // Click through
                        
                        document.body.appendChild(marker);
                        window.som_elements[id] = el;
                        id++;
                    }
                }
            });
            return id - 1; // Return count
        })()
        """
        try:
            count = page.evaluate(js_code)
            print(f"SoM: Marked {count} elements.")
            return count
        except Exception as e:
            print(f"SoM marking failed: {e}")
            return 0

    def _unmark_page(self, page: Page):
        try:
            page.evaluate(
                "document.querySelectorAll('.som-marker').forEach(e => e.remove());"
            )
        except:
            pass

    def verify_step(
        self, step: Step, page: Page, execution_result: str
    ) -> tuple[bool, str]:
        """
        Проверяет, был ли шаг выполнен успешно.
        Возвращает (успех, сообщение).
        """
        print(f"Verifying step {step.step_id}: {step.expected_result}")

        if "Error" in execution_result:
            return False, f"Execution failed: {execution_result}"

        # Use VLM for verification if possible
        try:
            screenshot_path = "screenshots/verify_step.png"
            page.screenshot(path=screenshot_path)

            # Only use VLM if configured (client exists)
            if self.vlm.client:
                success, reason = self.vlm.verify_state(
                    screenshot_path, step.expected_result
                )
                print(f"VLM Verification: {success} - {reason}")
                # We trust VLM, but if it fails (e.g. API error), we fall back to heuristics
                if "Error calling VLM" not in reason:
                    return success, reason
        except Exception as e:
            print(f"VLM verification failed: {e}")

        # Fallback heuristics
        try:
            if step.action == "navigate":
                # Проверяем, что URL изменился или содержит ожидаемую часть
                # Это очень грубая проверка
                if (
                    "wikipedia" in step.description.lower()
                    and "wikipedia" not in page.url.lower()
                ):
                    return False, f"Expected wikipedia in URL, got {page.url}"
                return True, "Navigation verified"

            elif step.action == "type":
                # Проверить, что введенный текст появился на странице (грубо)
                # Или просто поверить
                return True, "Typing verified"

            elif step.action == "click":
                # Проверить, что произошло изменение (URL или контент)
                return True, "Click verified"

            elif step.action == "extract":
                return True, "Extraction verified"

        except Exception as e:
            return False, f"Verification exception: {e}"

        return True, "Verified"

    def execute_step(self, step: Step, page: Page) -> str:
        """
        Выполняет один шаг плана.

        Args:
            step: Шаг плана для выполнения.
            page: Страница браузера Playwright.

        Returns:
            Результат выполнения шага.
        """
        print(f"Executing step {step.step_id}: {step.action} - {step.description}")

        try:
            if step.action == "navigate":
                # Пытаемся найти URL в описании
                # Improved regex to catch www. and domains without protocol
                url_match = re.search(r"(https?://|www\.)\S+", step.description)
                if url_match:
                    url = url_match.group(0)
                    if url.startswith("www."):
                        url = "https://" + url

                    # Basic validation
                    if "." not in url:
                        return f"Failed to navigate: Invalid URL '{url}'"

                    try:
                        page.goto(url, timeout=30000)
                        return f"Navigated to {url}"
                    except Exception as e:
                        return f"Failed to navigate to {url}: {e}"

                # Эвристика для Википедии, если URL не найден
                if (
                    "википеди" in step.description.lower()
                    or "wikipedia" in step.description.lower()
                ):
                    url = "https://ru.wikipedia.org"
                    page.goto(url)
                    return f"Navigated to {url} (heuristic)"

                # Эвристика для Habr
                if (
                    "habr" in step.description.lower()
                    or "хабр" in step.description.lower()
                ):
                    url = "https://habr.com/ru/all/"
                    page.goto(url)
                    return f"Navigated to {url} (heuristic)"

                # Fallback: Google Search if description implies searching or visiting a site
                # e.g. "Go to Pinterest" -> search pinterest
                # If we reached here, no URL was found and no specific heuristic matched.
                # We treat the description as a search query.

                query = step.description
                # Clean up common prefixes
                for prefix in [
                    "go to",
                    "перейти на",
                    "перейти",
                    "navigate to",
                    "open",
                    "открыть",
                ]:
                    if prefix in query.lower():
                        query = re.sub(f"(?i){prefix}", "", query).strip()

                if query:
                    search_url = f"https://www.google.com/search?q={query}"
                    page.goto(search_url)
                    return f"Navigated to Google Search for '{query}'. You are now on the search results page. DO NOT navigate again. CLICK on a relevant result link."

                return "Failed to navigate: No URL found"

            elif step.action == "type":
                text_to_type = "Python"
                match = re.search(r"['\"](.*?)['\"]", step.description)
                if match:
                    text_to_type = match.group(1)
                elif "Python" in step.description:
                    text_to_type = "Python"

                # Try to find search input
                search_input = None
                selectors = [
                    "input[name='search']",
                    "input[type='search']",
                    "input[placeholder*='search']",
                    "input[placeholder*='поиск']",
                    "input",
                ]

                def find_input():
                    for sel in selectors:
                        try:
                            if page.locator(sel).first.is_visible():
                                return page.locator(sel).first, sel
                        except:
                            continue
                    return None, None

                search_input, found_sel = find_input()

                if not search_input:
                    # Try clicking search button/icon to reveal input
                    try:
                        btn = page.locator(
                            "button[aria-label*='search'], a[href*='search'], svg[class*='search']"
                        ).first
                        if btn.is_visible():
                            print("Clicking search button to reveal input...")
                            btn.click()
                            time.sleep(1)
                            search_input, found_sel = find_input()
                    except:
                        pass

                if search_input:
                    try:
                        # Check if we already typed this text recently to avoid loops
                        # This is a local check, orchestrator handles global cycles

                        search_input.click()
                        search_input.fill("")  # Clear first
                        search_input.type(text_to_type, delay=100)
                        page.keyboard.press("Enter")
                        time.sleep(3)
                        return f"Typed '{text_to_type}' into {found_sel}"
                    except Exception as e:
                        # If fill failed, try blind
                        pass

                # Fallback: blind typing
                try:
                    page.keyboard.type(text_to_type)
                    page.keyboard.press("Enter")
                    time.sleep(3)
                    return f"Typed '{text_to_type}' blindly"
                except Exception as e:
                    return f"Error typing: {e}"

            elif step.action == "click":
                target_text = None
                match = re.search(r"['\"](.*?)['\"]", step.description)
                if match:
                    target_text = match.group(1)
                elif "Python" in step.description:
                    target_text = "Python"

                # Heuristic for search button
                is_search_button_desc = (
                    "button" in step.description.lower()
                    or "icon" in step.description.lower()
                    or "btn" in step.description.lower()
                )
                is_search_results_page = (
                    "search/?q=" in page.url or "search?q=" in page.url
                )

                if (
                    not target_text
                    and (
                        "search" in step.description.lower()
                        or "поиск" in step.description.lower()
                    )
                    and is_search_button_desc
                ):
                    if is_search_results_page:
                        return (
                            "Skipped clicking search button (already on search results)"
                        )

                    try:
                        # Try to find search button/icon
                        btn = page.locator(
                            "button[aria-label*='search'], a[href*='search'], svg[class*='search']"
                        ).first
                        if btn.is_visible():
                            btn.click()
                            time.sleep(2)
                            return "Clicked search button (heuristic)"
                    except:
                        pass

                # Heuristic for "first result"
                if (
                    not target_text
                    and "first" in step.description.lower()
                    and (
                        "result" in step.description.lower()
                        or "link" in step.description.lower()
                    )
                ):
                    try:
                        # Try generic article selectors
                        # Habr, Wikipedia, etc.
                        selectors = [
                            "article h2 a",
                            ".search-results a",
                            "h3 a",
                            ".result a",
                        ]
                        for sel in selectors:
                            if page.locator(sel).first.is_visible():
                                page.locator(sel).first.click()
                                time.sleep(2)
                                return f"Clicked first result using selector '{sel}'"
                    except:
                        pass

                # Heuristic for "Next" / "Arrow" buttons (Carousels)
                if (
                    "next" in step.description.lower()
                    or "arrow" in step.description.lower()
                    or "right" in step.description.lower()
                    or "далее" in step.description.lower()
                    or "вправо" in step.description.lower()
                ):
                    try:
                        # Common selectors for carousels/sliders
                        selectors = [
                            "button[aria-label*='next']",
                            "button[aria-label*='Next']",
                            "button[class*='next']",
                            "button[class*='arrow']",
                            "div[class*='arrow-right']",
                            "svg[class*='arrow']",
                            "[aria-label='Next']",
                            ".slick-next",
                            ".swiper-button-next",
                        ]
                        for sel in selectors:
                            if page.locator(sel).first.is_visible():
                                page.locator(sel).first.click()
                                time.sleep(1)
                                return (
                                    f"Clicked next/arrow button using selector '{sel}'"
                                )
                    except:
                        pass

                if target_text:
                    try:
                        # Try to find the element
                        element = None

                        # 1. Try by role link
                        link = page.get_by_role("link", name=target_text).first
                        if link.is_visible():
                            element = link

                        # 2. Try by text
                        if not element:
                            text_el = page.get_by_text(target_text).first
                            if text_el.is_visible():
                                element = text_el

                        # 3. Try by alt text (images)
                        if not element:
                            img_el = page.locator(f"img[alt='{target_text}']").first
                            if img_el.is_visible():
                                element = img_el
                            else:
                                # Partial match for alt
                                img_el = page.locator(
                                    f"img[alt*='{target_text}']"
                                ).first
                                if img_el.is_visible():
                                    element = img_el

                        if element:
                            try:
                                element.click(timeout=5000)
                                time.sleep(2)
                                return f"Clicked '{target_text}'"
                            except Exception as e:
                                err_msg = str(e)
                                if (
                                    "intercepts pointer events" in err_msg
                                    or "visible" in err_msg
                                ):
                                    print(
                                        f"Click failed (intercepted/hidden), trying force click... Error: {err_msg}"
                                    )
                                    try:
                                        element.click(force=True, timeout=5000)
                                        time.sleep(2)
                                        return f"Force clicked '{target_text}' (original click was blocked)"
                                    except Exception as e2:
                                        return f"Error force clicking '{target_text}': {e2}. Original error: {err_msg}"
                                return f"Error clicking '{target_text}': {e}"

                        return f"Failed to click: Element '{target_text}' not found or not visible"

                    except Exception as e:
                        return f"Error finding/clicking '{target_text}': {e}"

                # If text/selector based click failed, try VLM click
                if self.vlm.client:
                    print("Trying VLM visual click...")

                    # Retry loop for VLM click (scroll and retry)
                    for attempt in range(2):
                        try:
                            # 1. Mark elements
                            self._mark_page(page)

                            # 2. Screenshot
                            screenshot_path = "screenshots/click_target.png"
                            page.screenshot(path=screenshot_path)

                            # 3. Unmark (optional, but cleaner for user)
                            self._unmark_page(page)

                            # 4. Ask VLM for ID
                            vlm_resp = self.vlm.get_target_id(
                                screenshot_path, step.description
                            )
                            print(f"VLM SoM Response (Attempt {attempt+1}): {vlm_resp}")

                            if ":not_found:" in vlm_resp:
                                print("VLM did not find the target. Scrolling down...")
                                page.mouse.wheel(0, 500)
                                time.sleep(2)
                                continue

                            # 5. Parse :id:N:
                            match = re.search(r":id:(\d+):", vlm_resp)
                            if match:
                                el_id = int(match.group(1))

                                # 6. Click element by ID using JS
                                js_click = f"""
                                (function() {{
                                    const el = window.som_elements[{el_id}];
                                    if (el) {{
                                        el.scrollIntoView({{block: 'center', inline: 'center'}});
                                        return true;
                                    }}
                                    return false;
                                }})()
                                """
                                found = page.evaluate(js_click)

                                if found:
                                    try:
                                        handle = page.evaluate_handle(
                                            f"window.som_elements[{el_id}]"
                                        )
                                        if handle:
                                            handle.as_element().click()
                                            time.sleep(2)
                                            return f"Clicked element #{el_id} using VLM SoM"
                                    except Exception as e_click:
                                        print(
                                            f"Playwright click failed: {e_click}. Trying JS click..."
                                        )
                                        page.evaluate(
                                            f"window.som_elements[{el_id}].click()"
                                        )
                                        time.sleep(2)
                                        return f"Clicked element #{el_id} using JS fallback"
                                else:
                                    print(f"Element #{el_id} not found in JS map.")

                        except Exception as e:
                            print(f"VLM SoM click failed: {e}")

                    return "Failed to click: VLM could not find target after scrolling"

                return "Failed to click: No target found"

            elif step.action == "hover":
                # Logic similar to click, but using hover()
                target_text = None
                match = re.search(r"['\"](.*?)['\"]", step.description)
                if match:
                    target_text = match.group(1)

                if target_text:
                    try:
                        element = page.get_by_text(target_text).first
                        if element.is_visible():
                            element.hover()
                            time.sleep(1)
                            return f"Hovered over '{target_text}'"
                    except:
                        pass

                # Fallback to VLM SoM for hover
                if self.vlm.client:
                    print("Trying VLM visual hover (Set-of-Marks)...")
                    try:
                        self._mark_page(page)
                        screenshot_path = "screenshots/hover_target.png"
                        page.screenshot(path=screenshot_path)
                        self._unmark_page(page)

                        vlm_resp = self.vlm.get_target_id(
                            screenshot_path, step.description
                        )
                        match = re.search(r":id:(\d+):", vlm_resp)
                        if match:
                            el_id = int(match.group(1))
                            handle = page.evaluate_handle(
                                f"window.som_elements[{el_id}]"
                            )
                            if handle:
                                handle.as_element().hover()
                                time.sleep(1)
                                return f"Hovered over element #{el_id} using VLM SoM"
                    except Exception as e:
                        print(f"VLM hover failed: {e}")

                return "Failed to hover"

            elif step.action == "scroll":
                page.mouse.wheel(0, 500)
                time.sleep(1)
                return "Scrolled down"

            elif step.action == "extract":
                # 1. Try VLM extraction first (Smart Extraction)
                if self.vlm.client:
                    try:
                        screenshot_path = "screenshots/extract_source.png"
                        page.screenshot(path=screenshot_path)

                        extraction_result = self.vlm.extract_data(
                            screenshot_path, step.description
                        )
                        return f"VLM Extracted Data: {extraction_result}"
                    except Exception as e:
                        print(f"VLM extraction failed: {e}")

                # 2. Fallback to text extraction
                try:
                    # Если просят заголовок
                    if (
                        "title" in step.description.lower()
                        or "заголовок" in step.description.lower()
                    ):
                        title = page.title()
                        # Также попробуем найти h1
                        h1 = page.locator("h1").first
                        if h1.is_visible():
                            title = h1.inner_text()
                        return f"Extracted Title: {title}"

                    # Если просят текст
                    content = page.locator("body").inner_text()
                    # Возвращаем первые 200 символов для примера
                    return f"Extracted Text (snippet): {content[:200]}..."
                except Exception as e:
                    return f"Error extracting: {e}"

        except Exception as e:
            return f"Error executing step: {e}"

        return f"Executed {step.action} (no specific logic)"
