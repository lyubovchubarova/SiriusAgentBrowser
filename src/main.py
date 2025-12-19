import logging
import os
import sys

from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.orchestrator import Orchestrator

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


def main():
    # Загружаем переменные окружения (.env)
    load_dotenv()

    # Проверяем наличие ключей (опционально, но полезно для отладки)
    if not os.getenv("YANDEX_CLOUD_API_KEY"):
        print("Warning: YANDEX_CLOUD_API_KEY not found in environment variables.")

    # Инициализируем оркестратор
    # headless=False чтобы видеть браузер
    # Можно выбрать провайдера: "yandex" или "openai"
    # Можно выбрать модель для openai: "gpt-4o", "gpt-3.5-turbo" и т.д.
    provider = os.getenv("LLM_PROVIDER", "yandex")
    model = os.getenv("LLM_MODEL", "gpt-4o")

    print(f"Using LLM Provider: {provider}, Model: {model}")

    orchestrator = Orchestrator(
        headless=False, debug_mode=False, llm_provider=provider, llm_model=model
    )

    # Пример запроса
    user_query = "Найди статью про трансформеры в машинном обучении на хабре и скопируй первый комментарий под ней"

    print(f"User Query: {user_query}")
    print("-" * 50)

    # Запускаем обработку
    result = orchestrator.process_request(user_query)

    print("-" * 50)
    print("Result:")
    print(result)


if __name__ == "__main__":
    main()
