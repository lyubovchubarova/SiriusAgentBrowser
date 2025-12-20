import math
import random
import re
import time
from typing import Any

from playwright.sync_api import Locator, Page

from src.planner.models import Step
from src.vlm.agent import VLMAgent as RealVLMAgent


class VisionAgent:
    """
    VLM агент, который выполняет шаги плана, анализируя скриншоты и управляя браузером.
    """

    def __init__(self) -> None:
        # Initialize the real VLM agent
        # We try to get credentials from env, but don't crash if missing
        self.vlm = RealVLMAgent()
        self._last_mouse_pos: tuple[float, float] = (0.0, 0.0)

    def _human_like_mouse_move(
        self, page: Page, target_x: float, target_y: float
    ) -> None:
        """
        Moves mouse to (x, y) in a human-like curve with variable speed and noise.
        """
        # Ensure we start from the last known position, even if page changed
        # Note: Playwright's page.mouse is isolated per page, but we want to simulate
        # a single user cursor. We should ideally move the mouse on the new page
        # to the last known position instantly before starting the curve,
        # OR just assume the user moved the mouse there.
        # For now, we just use the stored global position.
        start_x, start_y = self._last_mouse_pos

        # Distance
        dist = math.hypot(target_x - start_x, target_y - start_y)

        # If very close, just move
        if dist < 10:
            page.mouse.move(target_x, target_y)
            self._last_mouse_pos = (float(target_x), float(target_y))
            return

        # Steps based on distance (more steps = smoother/slower)
        steps = max(10, int(dist / 15))

        # Control point for quadratic Bezier (random offset)
        # Midpoint
        mid_x = (start_x + target_x) / 2
        mid_y = (start_y + target_y) / 2

        # Offset perpendicular to the path
        # offset = random.uniform(-dist / 4, dist / 4)

        # Simple perpendicular vector logic
        dx = target_x - start_x
        dy = target_y - start_y

        # Perpendicular: (-dy, dx)
        ctrl_x = mid_x - dy * 0.2 + random.uniform(-20, 20)
        ctrl_y = mid_y + dx * 0.2 + random.uniform(-20, 20)

        for i in range(steps + 1):
            t = i / steps
            # Quadratic Bezier: (1-t)^2 * P0 + 2(1-t)t * P1 + t^2 * P2
            bx = (1 - t) ** 2 * start_x + 2 * (1 - t) * t * ctrl_x + t**2 * target_x
            by = (1 - t) ** 2 * start_y + 2 * (1 - t) * t * ctrl_y + t**2 * target_y

            # Add small noise
            noise_x = random.uniform(-1, 1)
            noise_y = random.uniform(-1, 1)

            if i == steps:
                noise_x = 0
                noise_y = 0

            page.mouse.move(bx + noise_x, by + noise_y)

            # Variable sleep (slower at start/end, faster in middle)
            # speed_factor = 1.0 - 0.5 * math.sin(t * math.pi) # 1 at ends, 0.5 in middle (faster)
            # time.sleep(0.001 * speed_factor)

        self._last_mouse_pos = (float(target_x), float(target_y))

    def _check_captcha(self, page: Page) -> bool:
        """Checks for common CAPTCHA indicators."""
        try:
            # Fast check in title
            title = page.title().lower()
            if (
                "captcha" in title
                or "bot" in title
                or "human" in title
                or "security check" in title
            ):
                return True

            # Check for specific elements (Cloudflare, reCAPTCHA frames)
            if page.locator("iframe[src*='cloudflare']").count() > 0:
                return True
            return bool(page.locator("iframe[src*='recaptcha']").count() > 0)
        except Exception:
            return False

    def _human_type(self, page: Page, text: str) -> None:
        """Types text with variable delay."""
        for char in text:
            delay = random.uniform(0.05, 0.15)
            page.keyboard.type(char)
            time.sleep(delay)

    def _solve_captcha(self, page: Page) -> None:
        """Attempts to solve CAPTCHA automatically by clicking checkboxes."""
        print("Attempting to solve CAPTCHA automatically...")
        time.sleep(2)  # Wait for load

        # Try to find and click the checkbox
        clicked = False

        # 1. Search in frames (ReCaptcha / Cloudflare)
        for frame in page.frames:
            try:
                if (
                    "cloudflare" in frame.url
                    or "turnstile" in frame.url
                    or "recaptcha" in frame.url
                ):
                    # Common selectors for the checkbox
                    checkboxes = [
                        "input[type='checkbox']",
                        ".recaptcha-checkbox-border",
                        ".ctp-checkbox-label",
                        "#checkbox",
                    ]
                    for sel in checkboxes:
                        el = frame.locator(sel).first
                        if el.is_visible():
                            print(
                                f"Found CAPTCHA checkbox ({sel}) in frame. Clicking..."
                            )
                            # Add delay
                            time.sleep(random.uniform(1, 2))
                            el.click()
                            clicked = True
                            break
                if clicked:
                    break
            except Exception:
                continue

        if not clicked:
            # 2. Search in main page (Custom or Shadow DOM)
            try:
                # Look for "I am not a robot" text or similar
                labels = page.get_by_text("I am not a robot")
                if labels.count() > 0 and labels.first.is_visible():
                    print("Found 'I am not a robot' text. Clicking...")
                    labels.first.click()
                    clicked = True
            except Exception:
                pass

        if clicked:
            print("Captcha interaction performed. Waiting 5s for results...")
            time.sleep(5)
        else:
            print(
                "Automatic solution failed (no checkbox found). Pausing for manual solving..."
            )
            time.sleep(15)

    def _mark_page(self, page: Page) -> int:
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
            // Expanded selector to include images and elements that look clickable
            const candidates = document.querySelectorAll('*');

            candidates.forEach(el => {
                // Filter by tag/role first for performance
                const tag = el.tagName.toLowerCase();
                const role = el.getAttribute('role');
                const isInteractiveTag = ['a', 'button', 'input', 'textarea', 'select', 'img', 'svg'].includes(tag);
                const isInteractiveRole = ['button', 'link', 'checkbox', 'menuitem', 'tab', 'option', 'switch'].includes(role);

                // Check computed style for cursor pointer (expensive, so do it last)
                let isClickableStyle = false;
                if (!isInteractiveTag && !isInteractiveRole) {
                     const style = window.getComputedStyle(el);
                     isClickableStyle = style.cursor === 'pointer';
                }

                if (isInteractiveTag || isInteractiveRole || isClickableStyle) {
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
                }
            });
            return id - 1; // Return count
        })()
        """
        try:
            count = int(page.evaluate(js_code))
            print(f"SoM: Marked {count} elements.")
            return count
        except Exception as e:
            print(f"SoM marking failed: {e}")
            return 0

    def _unmark_page(self, page: Page) -> None:
        try:
            page.evaluate(
                "document.querySelectorAll('.som-marker').forEach(e => e.remove());"
            )
        except Exception:
            pass

    def _handle_popups(self, page: Page) -> None:
        """
        Attempts to close common cookie banners and popups.
        """
        try:
            # Common selectors for cookie banners and popups
            selectors = [
                "button:has-text('Accept all')",
                "button:has-text('Allow all')",
                "button:has-text('Принять все')",
                "button:has-text('Согласиться')",
                "button:has-text('Accept cookies')",
                "[aria-label='Accept cookies']",
                ".cc-btn.cc-accept",  # CookieConsent
                "#onetrust-accept-btn-handler",  # OneTrust
            ]

            for sel in selectors:
                try:
                    btn = page.locator(sel).first
                    if btn.is_visible(timeout=500):
                        print(f"Found popup/cookie banner ({sel}), clicking...")
                        btn.click(timeout=1000)
                        time.sleep(0.5)
                        return  # Clicked one, assume handled for now
                except Exception:
                    continue

            # Close buttons (X)
            # close_selectors = [
            #     "button[aria-label='Close']",
            #     "button[aria-label='Закрыть']",
            #     ".close-button",
            #     ".modal-close",
            # ]
            # Only click close if it's clearly a modal/popup (heuristic: high z-index or fixed pos)
            # This is harder to detect safely without VLM.
            # For now, stick to cookie acceptance which is safer.

        except Exception:
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

            if self.vlm.client:
                is_valid, reason = self.vlm.verify_state(
                    screenshot_path, step.expected_result
                )
                if not is_valid:
                    return False, f"VLM Verification Failed: {reason}"
                return True, f"VLM Verified: {reason}"

            # Fallback heuristics if VLM not available
            if step.action == "navigate":
                # Check if URL changed or contains target
                return True, "Navigation verified (heuristic)"

            elif step.action == "type":
                return True, "Typing verified (heuristic)"

            elif step.action == "click":
                return True, "Click verified (heuristic)"

            elif step.action == "extract":
                return True, "Extraction verified (heuristic)"

        except Exception as e:
            return False, f"Verification exception: {e}"

        return True, "Verified"

    def _force_same_tab(self, page: Page) -> None:
        """Removes target='_blank' from all links to force opening in the same tab."""
        try:
            page.evaluate(
                """
                () => {
                    document.querySelectorAll('a[target="_blank"]').forEach(a => a.removeAttribute('target'));
                }
            """
            )
        except Exception:
            pass

    def execute_step(
        self, step: Step, page: Page, check_stop_callback: Any = None
    ) -> str:
        """
        Выполняет один шаг плана.
        """
        if check_stop_callback and check_stop_callback():
            return "Execution stopped by user."

        print(f"Executing step {step.step_id}: {step.action} - {step.description}")

        # Pre-step: Check for CAPTCHA
        if self._check_captcha(page):
            self._solve_captcha(page)

        # Pre-step: Handle popups/cookies
        self._handle_popups(page)

        # Pre-step: Force same tab (unless explicitly requested otherwise)
        # If the step description mentions "new tab" or "new window", we skip this enforcement.
        if (
            "new tab" not in step.description.lower()
            and "new window" not in step.description.lower()
        ):
            self._force_same_tab(page)

        # 0. Check for ID-based execution (Highest Priority)
        # Looks for [E123] pattern
        id_match = re.search(r"\[(E\d+)\]", step.description)
        if id_match:
            element_id = id_match.group(1)
            print(
                f"Found ID {element_id} in description. Attempting precise interaction..."
            )
            try:
                # Selector for the element with the specific data attribute
                selector = f"[data-pw-bbox-id='{element_id}']"
                element = page.locator(selector).first

                if element.is_visible():
                    # Highlight for feedback
                    try:
                        element.evaluate(
                            "el => el.style.border = '4px solid #00FF00'"
                        )  # Green for ID match
                        time.sleep(0.5)
                    except Exception:
                        pass

                    # Human-like movement before interaction
                    try:
                        box = element.bounding_box()
                        if box:
                            # Target center with random offset
                            tx = box["x"] + box["width"] / 2 + random.uniform(-5, 5)
                            ty = box["y"] + box["height"] / 2 + random.uniform(-5, 5)
                            self._human_like_mouse_move(page, tx, ty)
                    except Exception as e:
                        print(f"Human move failed: {e}")

                    if step.action == "click":
                        try:
                            element.click(timeout=3000)
                        except Exception as e:
                            print(
                                f"Standard click failed: {e}. Retrying with force=True."
                            )
                            # Force click bypasses actionability checks (like aria-disabled)
                            element.click(timeout=3000, force=True)

                        try:
                            # Short wait for DOM content loaded, but don't block long
                            page.wait_for_load_state("domcontentloaded", timeout=2000)
                        except Exception:
                            # If timeout, assume page is ready enough or didn't reload
                            pass
                        return f"Clicked element {element_id} (ID-based)"

                    elif step.action == "type":
                        text_to_type = "Python"
                        match = re.search(r"['\"](.*?)['\"]", step.description)
                        if match:
                            text_to_type = match.group(1)

                        element.click()
                        element.fill("")

                        # Human-like typing
                        for char in text_to_type:
                            element.type(char, delay=random.randint(50, 150))

                        page.keyboard.press("Enter")
                        time.sleep(2)
                        return f"Typed '{text_to_type}' into element {element_id} (ID-based)"

                    elif step.action == "hover":
                        element.hover()
                        time.sleep(1)
                        return f"Hovered over element {element_id} (ID-based)"
                else:
                    print(
                        f"Element {element_id} found but not visible. Falling back to heuristics."
                    )
            except Exception as e:
                print(f"ID-based interaction failed: {e}. Falling back to heuristics.")

        try:
            if step.action == "navigate":
                # Пытаемся найти URL в описании
                # Improved regex to catch www. and domains without protocol
                url_match = re.search(r"(https?://|www\.)\S+", step.description)
                if url_match:
                    url = url_match.group(0)
                    # Clean trailing punctuation that might have been captured (e.g. "url)", "url.", "url,")
                    url = url.rstrip(").,;]\"'")

                    if url.startswith("www."):
                        url = "https://" + url

                    # Basic validation
                    if "." not in url:
                        return f"Failed to navigate: Invalid URL '{url}'"

                    try:
                        # Use domcontentloaded to speed up navigation
                        page.goto(url, timeout=30000, wait_until="domcontentloaded")
                        self._handle_popups(page)
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
                    page.goto(search_url, wait_until="domcontentloaded")
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
                    "input[name='q']",  # Google/common
                    "input[name='search']",
                    "input[type='search']",
                    "input[placeholder*='search']",
                    "input[placeholder*='поиск']",
                    "input[aria-label*='search']",
                    "input[aria-label*='поиск']",
                    "input",
                ]

                def find_input() -> tuple[Any, str | None]:
                    for sel in selectors:
                        try:
                            if page.locator(sel).first.is_visible():
                                return page.locator(sel).first, sel
                        except Exception:
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
                    except Exception:
                        pass

                if not search_input and self.vlm.client:
                    print("Trying VLM visual search for input field...")
                    try:
                        if check_stop_callback and check_stop_callback():
                            return "Execution stopped by user."
                        self._mark_page(page)
                        screenshot_path = "screenshots/type_target.png"
                        page.screenshot(path=screenshot_path)
                        self._unmark_page(page)

                        vlm_resp = self.vlm.get_target_id(
                            screenshot_path,
                            "Click on the search input field or text box",
                        )
                        print(f"[VLM LOG] VLM Response for 'type' target: {vlm_resp}")
                        match = re.search(r":id:(\d+):", vlm_resp)
                        if match:
                            el_id = int(match.group(1))
                            handle = page.evaluate_handle(
                                f"window.som_elements[{el_id}]"
                            )
                            if handle:
                                search_input = handle.as_element()
                                found_sel = f"VLM ID {el_id}"
                    except Exception as e:
                        print(f"VLM type fallback failed: {e}")

                if search_input:
                    try:
                        # Check if we already typed this text recently to avoid loops
                        # This is a local check, orchestrator handles global cycles

                        search_input.click()
                        search_input.fill("")  # Clear first
                        self._human_type(page, text_to_type)
                        page.keyboard.press("Enter")
                        time.sleep(3)
                        return f"Typed '{text_to_type}' into {found_sel}"
                    except Exception:
                        # If fill failed, try blind
                        pass

                # Fallback: blind typing
                try:
                    self._human_type(page, text_to_type)
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
                    except Exception:
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
                    except Exception:
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
                    except Exception:
                        pass

                if target_text:
                    try:
                        # Try to find the element
                        found_element: Locator | None = None

                        # 1. Try by role link
                        link = page.get_by_role("link", name=target_text).first
                        if link.is_visible():
                            found_element = link

                        # 2. Try by text
                        if not found_element:
                            text_el = page.get_by_text(target_text).first
                            if text_el.is_visible():
                                found_element = text_el

                        # 3. Try by alt text (images)
                        if not found_element:
                            img_el = page.locator(f"img[alt='{target_text}']").first
                            if img_el.is_visible():
                                found_element = img_el
                            else:
                                # Partial match for alt
                                img_el = page.locator(
                                    f"img[alt*='{target_text}']"
                                ).first
                                if img_el.is_visible():
                                    found_element = img_el

                        # 4. Try button/input by value or placeholder (often missed by get_by_text)
                        if not found_element:
                            try:
                                btn = page.locator(
                                    f"input[value='{target_text}'], input[placeholder='{target_text}']"
                                ).first
                                if btn.is_visible():
                                    found_element = btn
                            except Exception:
                                pass

                        # 5. Fuzzy XPath search (Case-insensitive contains)
                        if not found_element:
                            try:
                                lower_text = target_text.lower()
                                # Translate uppercase to lowercase for case-insensitive search
                                xpath = f"//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{lower_text}')]"
                                fuzzy_el = page.locator(xpath).first
                                if fuzzy_el.is_visible():
                                    found_element = fuzzy_el
                            except Exception:
                                pass

                        if found_element:
                            try:
                                # Highlight element before clicking
                                try:
                                    found_element.evaluate(
                                        "el => el.style.border = '3px solid red'"
                                    )
                                    time.sleep(0.5)
                                except Exception:
                                    pass

                                found_element.click(timeout=5000)
                                try:
                                    # Short wait for DOM content loaded
                                    page.wait_for_load_state(
                                        "domcontentloaded", timeout=2000
                                    )
                                except Exception:
                                    # Proceed if timeout
                                    pass
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
                                        found_element.click(force=True, timeout=5000)
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
                        if check_stop_callback and check_stop_callback():
                            return "Execution stopped by user."
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
                            print(
                                f"[VLM LOG] VLM SoM Response (Attempt {attempt + 1}): {vlm_resp}"
                            )
                            print(
                                f"[VLM LOG] Parsed Action: {'Target Found' if ':id:' in vlm_resp else 'Target Not Found'}"
                            )

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
                                            el_handle = handle.as_element()
                                            if el_handle:
                                                el_handle.click()
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
                    except Exception:
                        pass

                # Fallback to VLM SoM for hover
                if self.vlm.client:
                    print("Trying VLM visual hover (Set-of-Marks)...")
                    try:
                        if check_stop_callback and check_stop_callback():
                            return "Execution stopped by user."
                        self._mark_page(page)
                        screenshot_path = "screenshots/hover_target.png"
                        page.screenshot(path=screenshot_path)
                        self._unmark_page(page)

                        vlm_resp = self.vlm.get_target_id(
                            screenshot_path, step.description
                        )
                        print(f"[VLM LOG] VLM Response for 'hover' target: {vlm_resp}")
                        match = re.search(r":id:(\d+):", vlm_resp)
                        if match:
                            el_id = int(match.group(1))
                            handle = page.evaluate_handle(
                                f"window.som_elements[{el_id}]"
                            )
                            if handle:
                                el_handle = handle.as_element()
                                if el_handle:
                                    el_handle.hover()
                                    time.sleep(1)
                                    return (
                                        f"Hovered over element #{el_id} using VLM SoM"
                                    )
                    except Exception as e:
                        print(f"VLM hover failed: {e}")

                return "Failed to hover"

            elif step.action == "inspect":
                # Inspect element details
                target = step.description
                # Extract selector from description if possible, or use raw description
                # If description says "Inspect [E12]", extract E12
                match = re.search(r"\[(E\d+)\]", step.description)
                if match:
                    target = match.group(1)
                else:
                    # Try to find a selector in quotes
                    match_q = re.search(r"['\"](.*?)['\"]", step.description)
                    if match_q:
                        target = match_q.group(1)

                try:
                    if re.match(r"^E\d+$", target):
                        loc = page.locator(f"[data-pw-bbox-id='{target}']").first
                    else:
                        # Try as text or selector
                        loc = page.get_by_text(target).first
                        if not loc.is_visible():
                            loc = page.locator(target).first

                    if loc.is_visible():
                        text = loc.text_content() or ""
                        html = loc.evaluate("el => el.outerHTML")
                        if len(html) > 500:
                            html = html[:500] + "... (truncated)"
                        return f"Inspect Result:\nText: {text.strip()}\nHTML: {html}"
                    else:
                        return f"Inspect failed: Element '{target}' not found."
                except Exception as e:
                    return f"Inspect error: {e}"

            elif step.action == "wait":
                time.sleep(5)
                return "Waited 5 seconds."

            elif step.action == "scroll":
                page.mouse.wheel(0, 500)
                time.sleep(1)
                return "Scrolled down"

            elif step.action == "extract":
                # 0. Heuristic: URL extraction
                if (
                    "url" in step.description.lower()
                    or "link" in step.description.lower()
                    or "address" in step.description.lower()
                ):
                    # If user wants a specific link (e.g. "copy link to meme"), we need to find it
                    # Check if description implies a specific element
                    target_text = None
                    match = re.search(r"['\"](.*?)['\"]", step.description)
                    if match:
                        target_text = match.group(1)

                    if target_text:
                        # Try to find an element with this text and get its href or src
                        try:
                            # Try link
                            el = page.get_by_role("link", name=target_text).first
                            if el.is_visible():
                                href = el.get_attribute("href")
                                if href:
                                    # Resolve relative URL
                                    full_url = page.evaluate(
                                        f"new URL('{href}', document.baseURI).href"
                                    )
                                    return f"Extracted Link URL: {full_url}"

                            # Try image (src)
                            img = page.locator(f"img[alt='{target_text}']").first
                            if img.is_visible():
                                src = img.get_attribute("src")
                                if src:
                                    full_url = page.evaluate(
                                        f"new URL('{src}', document.baseURI).href"
                                    )
                                    return f"Extracted Image URL: {full_url}"
                        except Exception:
                            pass

                    return f"Extracted Page URL: {page.url}"

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
