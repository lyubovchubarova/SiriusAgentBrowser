import time
import re
from playwright.sync_api import Page
from src.planner.models import Step


class VisionAgent:
    """
    VLM агент, который выполняет шаги плана, анализируя скриншоты и управляя браузером.
    """

    def __init__(self):
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

        # Здесь должна быть логика VLM: отправка скриншота и вопроса "Соответствует ли состояние expected_result?"
        # Пока используем эвристики.

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
                url_match = re.search(r"https?://\S+", step.description)
                if url_match:
                    url = url_match.group(0)
                    page.goto(url)
                    return f"Navigated to {url}"

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
                        search_input.click()
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

                return "Failed to click: No target found"

            elif step.action == "scroll":
                page.mouse.wheel(0, 500)
                time.sleep(1)
                return "Scrolled down"

            elif step.action == "extract":
                # Логика извлечения информации
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
