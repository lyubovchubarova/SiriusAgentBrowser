import logging
from typing import Optional

from src.browser.browser_controller import BrowserController, BrowserOptions
from src.planner.planner import Planner
from src.planner.models import Plan
from src.vlm.vlm import VisionAgent

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, headless: bool = False):
        self.planner = Planner()
        self.vision_agent = VisionAgent()
        self.browser_controller = BrowserController(BrowserOptions(headless=headless))
        self._is_browser_started = False

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

            # 3. Выполнение шагов
            results = []
            for step in plan.steps:
                logger.info(f"Step {step.step_id}: {step.description}")
                result = self.vision_agent.execute_step(step, page)
                results.append(f"Step {step.step_id}: {result}")
                logger.info(f"Step {step.step_id} result: {result}")

            return "\n".join(results)

        except Exception as e:
            logger.error(f"Error processing request: {e}", exc_info=True)
            return f"Error: {e}"
        finally:
            # Не закрываем браузер сразу, чтобы пользователь мог увидеть результат?
            # Или закрываем? Для "простого оркестратора" лучше закрыть или оставить управление пользователю.
            # В данном случае закроем для чистоты, или сделаем это опциональным.
            # Пусть вызывающий код решает, когда закрыть, или закроем здесь.
            # Обычно агент выполнил задачу и завершил работу.
            self.close_browser()
