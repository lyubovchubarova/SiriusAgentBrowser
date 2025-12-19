from playwright.sync_api import Page
from src.planner.models import Step


class VisionAgent:
    """
    VLM агент, который выполняет шаги плана, анализируя скриншоты и управляя браузером.
    """

    def __init__(self):
        pass

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

        # Здесь должна быть логика VLM:
        # 1. Сделать скриншот
        # 2. Отправить скриншот и описание шага в VLM
        # 3. Получить координаты или код действия
        # 4. Выполнить действие через page

        # Пока реализуем простую заглушку, которая пытается выполнить действие напрямую,
        # если это навигация, или просто логирует.

        if step.action == "navigate":
            # Для навигации ожидаем, что в description или expected_result есть URL,
            # но по схеме Planner action просто "navigate".
            # Обычно Planner должен давать URL.
            # Предположим, что VLM сам разберется или Planner вернет URL в description.
            # Для простоты, если в description есть http, переходим.
            if "http" in step.description:
                url = step.description.split(" ")[-1]  # Очень грубо
                if url.startswith("http"):
                    page.goto(url)
                    return f"Navigated to {url}"

        # TODO: Реализовать полноценную логику с VLM

        return f"Executed {step.action}"
