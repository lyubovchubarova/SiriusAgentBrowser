import datetime
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, cast

from openai import OpenAI
from pydantic import ValidationError

from src.logger_db import log_action, update_session_stats

from .models import Plan

SYSTEM_PROMPT = """
Ты — планировщик автоматизации браузера. У тебя есть полный доступ к веб-браузеру, и ты можешь взаимодействовать с любым веб-сайтом через playwright-подобный интерфейс.
Ты НЕ чат-бот. Ты — агент автоматизации.
Твоя цель — выполнить запрос пользователя, сгенерировав последовательность действий в браузере.

Возвращай ТОЛЬКО валидный JSON. Никаких блоков кода. Никаких комментариев.
Форматируй JSON с отступами (2 или 4 пробела) для читаемости.

Жесткие ограничения:
- step_id должен начинаться с 1 и увеличиваться на 1 без пропусков.
- action должен быть ровно одним из: navigate, click, type, scroll, extract, hover, inspect, wait, finish, search, solve_captcha, ask_user, call_tool, send_keys.
- description: краткое, четкое, в повелительном наклонении.
  - Для 'search': указывай ТОЛЬКО оптимальные ключевые слова для поиска (например, "документация python"). НЕ включай системные слова, такие как "поиск", "найти".
  - Для 'navigate': ОБЯЗАТЕЛЬНО указывай полный URL.
  - Для 'click' или 'type': ТЫ ОБЯЗАН ИСПОЛЬЗОВАТЬ ID ЭЛЕМЕНТА, если он доступен в контексте (например, "Click [E12] 'Search'", "Type 'cat' into [E45]").
  - Если ID не виден, используй текстовое описание в одинарных кавычках.
  - Для 'send_keys': используй для отправки специальных клавиш или сочетаний (например, "Press 'Enter'", "Press 'Tab'", "Press 'Control+a'"). Полезно для навигации, если клик не работает.
  - Для 'inspect': опиши, какой элемент или раздел ты хочешь проанализировать (например, "Inspect the main article content").
  - Для 'wait': опиши, чего ты ждешь (например, "Wait for the results to load").
  - Для 'solve_captcha': опиши, какую капчу ты видишь (например, "Solve the Cloudflare challenge").
  - Для 'ask_user': опиши вопрос, который ты хочешь задать пользователю (например, "Please enter the 2FA code sent to your phone", "What is your login username?").
  - Для 'call_tool': описание ДОЛЖНО быть валидной JSON-строкой с полями "tool", "method" и "args".
    - ВАЖНО: Ты должен экранировать двойные кавычки внутри JSON-строки.
    - Пример для create_event: "{\"tool\": \"google_calendar\", \"method\": \"create_event\", \"args\": {\"summary\": \"Meeting\", \"start_time\": \"2023-10-27T10:00:00\", \"end_time\": \"2023-10-27T11:00:00\"}}"
    - Доступные инструменты:
      - google_calendar:
        - create_event(summary: str, start_time: iso_datetime_str, end_time: iso_datetime_str, description: str="", guests: list[str]=None)
          Пример: {\"summary\": \"Встреча\", \"start_time\": \"2025-12-26T06:00:00\", \"end_time\": \"2025-12-26T07:00:00\"}
        - delete_event(event_id: str)
          Пример: {\"event_id\": \"abc123def456\"}
        - list_events_for_date(date: iso_date_str=None)
          Пример: {\"date\": \"2025-12-26\"} или {}, чтобы получить список на текущую дату
        - set_date(date: iso_date_str)
          Пример: {\"date\": \"2025-12-26\"} - переключает на конкретную дату
        - get_current_date()
          Возвращает текущую дату и события на эту дату
        - update_event(event_id: str, summary: str=None, start_time: iso_datetime_str=None, end_time: iso_datetime_str=None, description: str=None)
          Пример: {\"event_id\": \"abc123\", \"summary\": \"Updated Meeting\"}
        - open_calendar(date: iso_date_str=None)
          Открывает Google Calendar в браузере на указанной дате (или текущей, если не указана)
          Пример: {\"date\": \"2025-12-26\"} или {}, чтобы открыть на текущей дате
  - Для 'finish': опиши, почему задача завершена. Если задача состояла только в том, чтобы найти/открыть страницу, используй это действие, как только страница загрузится.
- expected_result: конкретный видимый результат.
- estimated_time: целое число секунд.

РАССУЖДЕНИЕ (REASONING):
Предоставь краткое рассуждение (chain-of-thought) для твоего плана НА РУССКОМ ЯЗЫКЕ. Объясни, почему ты выбрал конкретные действия и элементы.
Будь КОНКРЕТЕН. Избегай общих фраз. Называй действия прямо (например, "Использую действие click для...").
Если задача сложная, кратко рассмотри альтернативы, но отдавай приоритет скорости и прямолинейности.

Стратегии для сложных страниц и восстановления после ошибок:
- Если клик не работает (баг или перекрытие), используй КЛАВИАТУРНУЮ НАВИГАЦИЮ: действие 'send_keys' с "Tab", "Enter", "ArrowDown".
- Если цель находится внутри карусели или горизонтального списка, добавь шаг для клика по кнопке "Next", "Right Arrow" или ">".
- Если страница кажется зависшей или пустой, попробуй "scroll", чтобы запустить ленивую загрузку (lazy loading).
- Если попап/модальное окно перекрывает обзор, добавь шаг для клика по "Close", "X" или "Not now".
- Если меню скрыто, попробуй "hover" над родительским элементом, чтобы раскрыть его.
- Если ты видишь CAPTCHA или чекбокс "I am not a robot", используй действие 'solve_captcha'.
- Если навигация не удалась (таймаут или защита от ботов), используй 'search' (Google/Yandex) вместо прямой навигации.

КРИТИЧЕСКИЕ ПРАВИЛА НАВИГАЦИИ:
- ПРЯМАЯ НАВИГАЦИЯ: Если ты знаешь URL (например, 'https://youtube.com', 'https://github.com'), используй 'navigate' напрямую. Не ищи его через поиск.
- ЯРЛЫКИ (SHORTCUTS):
  - "Calendar" / "Календарь" -> navigate на 'https://calendar.google.com'
  - "Notion" / "Ноушн" -> navigate на 'https://www.notion.so'
  - "Gmail" / "Почта" -> navigate на 'https://mail.google.com'
- ПОИСК: Если тебе нужно что-то найти, используй действие 'search'. Это введет запрос в адресную строку браузера/поисковую систему.
- НЕ переходи в поисковую систему (например, ya.ru) вручную, чтобы ввести запрос. Просто используй действие 'search'.
- ПОСЛЕ ПОИСКА: Ты окажешься на странице результатов поиска. Используй 'click', чтобы выбрать релевантный результат.
- АДРЕСНАЯ СТРОКА: Действие 'search' эквивалентно вводу текста в адресную строку.

ВЗАИМОДЕЙСТВИЕ С КАЛЕНДАРЯМИ:
- **ВСЕГДА ИСПОЛЬЗУЙ ДЕЙСТВИЕ 'call_tool' ДЛЯ ЗАДАЧ GOOGLE CALENDAR.**
- НЕ пытайся переходить на calendar.google.com или кликать кнопки для создания/удаления событий. Используй GoogleCalendarController.
- Используй инструмент 'google_calendar' для ВСЕХ операций с календарем:
  - Чтобы создать встречу: используй create_event с summary, start_time (формат ISO), end_time (формат ISO), опционально description и guests.
  - Чтобы проверить расписание на конкретный день: используй list_events_for_date с date (формат ISO).
  - Чтобы переключиться на другой день: используй set_date с date (формат ISO).
  - Чтобы получить текущую дату и события: используй get_current_date.
  - Чтобы удалить встречу: используй delete_event с event_id.
  - Чтобы обновить существующую встречу: используй update_event с event_id и опциональными полями для обновления.
- При парсинге дат из запросов пользователя преобразуй их в формат ISO (YYYY-MM-DD для дат, YYYY-MM-DDTHH:MM:SS для времени).
- Если пользователь говорит "сегодня", используй текущую дату. Если "завтра", добавь 1 день.

КОНТРОЛЬ КАЧЕСТВА И ЗАВЕРШЕНИЕ:
- При выборе результата поиска ПРОВЕРЯЙ HREF/URL в контексте, если он доступен. Убедись, что он соответствует целевому домену (например, 'genius.com' для текстов песен, а не 'yandex.ru/ads').
- Избегай кликов по ссылкам 'Sponsored', 'Ad' или 'Реклама', если об этом явно не просили.
- В своем рассуждении явно укажи, ПОЧЕМУ ты выбрал конкретный ID (например, "Я выбрал [E15], потому что он ведет на genius.com и имеет правильный заголовок").
- ПРОВЕРЬ, НЕ ЗАВЕРШЕНА ЛИ УЖЕ ЗАДАЧА. Если содержимое текущей страницы соответствует запросу пользователя (например, статья открыта), используй действие 'finish' немедленно. НЕ продолжай кликать или открывать новые страницы. Однако важно проверять действительно на странице есть все о чем просил пользователь в запросе.
- ПРАВИЛО НОВОЙ СЕССИИ: Если ты начинаешь новую задачу и текущий URL неизвестен или 'about:blank', ты ОБЯЗАН сгенерировать хотя бы один шаг 'navigate' или 'search'. НЕ предполагай, что страница уже открыта.
- ПОЛИТИКА ОДНОЙ ВКЛАДКИ: ПРЕДПОЧИТАЙ работать в текущей вкладке. Открывай новую вкладку только если пользователь ЯВНО попросил об этом (например, "открой в новой вкладке"). Если пользователь не просил новую вкладку, считай, что все ссылки должны открываться в текущей.

ЗРЕНИЕ / СКРИНШОТЫ:
- Ты в основном работаешь с DOM-деревом, но ЗРЕНИЕ (VLM) — твой мощный инструмент.
- ЧАЩЕ ЗАПРАШИВАЙ КОНСУЛЬТАЦИЮ VLM ("needs_vision": true).
- Используй "needs_vision": true, если:
  - DOM выглядит сложным, запутанным или содержит мало полезной информации (например, много div без id).
  - Ты не уверен, какой элемент выбрать, и хочешь "увидеть" страницу как человек.
  - Ты столкнулся с динамическим контентом, canvas, или сложными интерфейсами.
  - Ты хочешь проверить визуальное состояние страницы перед важным действием.
- Если "needs_vision" равно true, верни пустой массив "steps". Система вызовет тебя снова со скриншотом.


Схема ответа:
{
  "reasoning": "Ваше рассуждение на русском языке",
  "task": "Описание задачи",
  "steps": [
    {
      "step_id": 1,
      "action": "navigate",
      "description": "Navigate to https://example.com",
      "expected_result": "Page loaded"
    }
  ],
  "estimated_time": 5,
  "needs_vision": false
}
""".strip()
VERIFICATION_SYSTEM_PROMPT = """
Ты — строгий судья по контролю качества (QA Judge) для ИИ-агента браузера.
Твоя работа — оценить, успешно ли агент выполнил запрос пользователя, основываясь на истории выполнения и содержимом финальной страницы.

Проанализируй ситуацию.
1. Выполнил ли агент запрошенные действия?
2. Виден ли финальный результат или достигнут ли он?
3. Если задача "найти информацию", найдена ли информация?
4. Если задача "перейти", загружена ли правильная страница?

Верни JSON-объект:
{
  "reasoning": "Объяснение твоего вердикта на русском языке",
  "success": true,
  "feedback": "Если false, предоставь конкретные инструкции, что делать дальше, чтобы исправить это. Если true, оставь пустым."
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

    # Try to find the outermost JSON object
    # This regex looks for the first { and the last }
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise PlannerError("LLM returned no JSON object", raw_output=text)

    json_str = match.group(0)
    return json_str


class Planner:
    def __init__(self, provider: str = "yandex", model: str = "gpt-4o"):
        self.provider = provider
        self.model = model

        # Provide current date/time hint to the planner so it knows "today"
        today = datetime.date.today()
        now = datetime.datetime.now()
        self.system_prompt = (
            SYSTEM_PROMPT
            + f"\n\nTODAY (system): {today.isoformat()}"
            + f"\nNOW (system, local): {now.isoformat()}"
        )

        if self.provider == "yandex":
            self.folder = os.environ["YANDEX_CLOUD_FOLDER"]
            self.model_path = os.environ["YANDEX_CLOUD_MODEL_PATH"]

            # Construct full model URI for Yandex
            # If model is just "gpt-4o" (default), replace it with Yandex model path
            if self.model == "gpt-4o":
                self.model = f"gpt://{self.folder}/{self.model_path}"
            elif not self.model.startswith("gpt://"):
                # Assume it's a model alias like "yandexgpt/rc"
                self.model = f"gpt://{self.folder}/{self.model}"

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

    def classify_intent(self, user_prompt: str, session_id: str = "default") -> str:
        """
        Determines if the user prompt requires browser automation ('agent')
        or can be answered directly by the LLM ('chat').
        """
        prompt = f"""
You are a helpful assistant that classifies user requests.
Determine if the user's request requires using a web browser to perform actions (searching, navigating, clicking) OR if it can be answered directly by a language model.

Guidelines:
- Choose "agent" if the user asks to:
  - Search for something online.
  - Find information on a specific website.
  - Get up-to-date news, weather, or prices.
  - Perform an action on a website (login, click, buy).
  - Interact with external tools like Calendar, Email, Notion, Docs.
  - "Open" any website or service.
- Choose "chat" if the user asks for:
  - General knowledge or explanations.
  - Creative writing or coding help.
  - Simple recipes or advice that doesn't require a specific source.

User Request: "{user_prompt}"

Please respond with only one word: "agent" or "chat".
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

            # Log usage
            if response.usage:
                total_tokens = response.usage.total_tokens
                update_session_stats(session_id, "llm", total_tokens)
                log_action(
                    "Planner",
                    "LLM_USAGE",
                    f"Intent classification used {total_tokens} tokens",
                    {"tokens": total_tokens, "model": model_to_use},
                    session_id=session_id,
                    tokens_used=total_tokens,
                )

            content = response.choices[0].message.content
            result = content.strip().lower() if content else "agent"
            return "agent" if "agent" in result else "chat"
        except Exception as e:
            print(f"Classification error: {e}")
            return "agent"  # Default to agent if unsure

    def generate_direct_answer(
        self, user_prompt: str, stream_callback: Any = None, session_id: str = "default"
    ) -> str:
        """
        Generates a direct answer for the user without using the browser.
        """
        messages = [
            {
                "role": "system",
                "content": "You are a helpful AI assistant. Answer the user's question directly using your internal knowledge. If the user needs real-time info or specific website actions, suggest they ask to 'search' or 'open' the site.",
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
                        stream_options=(
                            {"include_usage": True}
                            if self.provider == "openai"
                            else None
                        ),
                    ),
                )
                full_response = ""
                usage_logged = False
                for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta.content:
                        content = chunk.choices[0].delta.content
                        full_response += content
                        stream_callback(content)

                    # Try to capture usage from stream if available (OpenAI specific)
                    if hasattr(chunk, "usage") and chunk.usage and not usage_logged:
                        total_tokens = chunk.usage.total_tokens
                        update_session_stats(session_id, "llm", total_tokens)
                        log_action(
                            "Planner",
                            "LLM_USAGE",
                            f"Direct answer used {total_tokens} tokens",
                            {"tokens": total_tokens, "model": model_to_use},
                            session_id=session_id,
                            tokens_used=total_tokens,
                        )
                        usage_logged = True

                # If usage wasn't in stream (e.g. Yandex or older OpenAI), we might miss it.
                # For now, we just log the request count if usage is missing.
                if not usage_logged:
                    update_session_stats(session_id, "llm", 0)

                return full_response
            else:
                response = self.client.chat.completions.create(
                    model=model_to_use,
                    messages=cast("Any", messages),
                )

                if response.usage:
                    total_tokens = response.usage.total_tokens
                    update_session_stats(session_id, "llm", total_tokens)
                    log_action(
                        "Planner",
                        "LLM_USAGE",
                        f"Direct answer used {total_tokens} tokens",
                        {"tokens": total_tokens, "model": model_to_use},
                        session_id=session_id,
                        tokens_used=total_tokens,
                    )
                else:
                    update_session_stats(session_id, "llm", 0)

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
        session_id: str = "default",
    ) -> str:
        user_content: Any

        # Default to global SYSTEM_PROMPT (with current date/time) if not provided
        sys_prompt = system_prompt if system_prompt is not None else self.system_prompt

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
                "stream_options": {"include_usage": True},
            }

            if use_reasoning:
                # For Yandex, we use reasoningOptions.
                # However, if the user wants to SEE the reasoning in the stream,
                # we might need to handle it differently if the API doesn't stream the reasoning block.
                # Current Yandex API (via OpenAI client) might not stream the hidden reasoning.
                # So we will ask the model to output reasoning in the text instead.
                # kwargs["extra_body"] = {"reasoningOptions": {"mode": "ENABLED_HIDDEN"}}
                # print("[PLANNER LOG] Reasoning enabled (Hidden).")
                pass  # Disable hidden reasoning, let prompt handle it.

            try:
                response = self.client.chat.completions.create(**cast("Any", kwargs))

                full_response = ""
                print("[PLANNER STREAM] ", end="", flush=True)

                usage_logged = False

                for chunk in response:
                    if chunk.choices and chunk.choices[0].delta.content:
                        content = chunk.choices[0].delta.content
                        print(content, end="", flush=True)
                        full_response += content
                        if stream_callback:
                            stream_callback(content)

                    if hasattr(chunk, "usage") and chunk.usage and not usage_logged:
                        total_tokens = chunk.usage.total_tokens
                        update_session_stats(session_id, "llm", total_tokens)
                        log_action(
                            "Planner",
                            "LLM_USAGE",
                            f"Plan generation used {total_tokens} tokens",
                            {
                                "tokens": total_tokens,
                                "model": self.model,
                                "system_prompt": sys_prompt,
                                "prompt": str(user_content),
                                "response": full_response,
                            },
                            session_id=session_id,
                            tokens_used=total_tokens,
                        )
                        usage_logged = True

                print("\n")  # Newline after stream

                if not usage_logged:
                    # Fallback estimation
                    # Estimate: 1 token ~ 3-4 chars. Let's use 3 to be safe/conservative.
                    input_len = len(sys_prompt) + len(str(user_content))
                    output_len = len(full_response)
                    estimated_tokens = (input_len + output_len) // 3
                    update_session_stats(session_id, "llm", estimated_tokens)
                    log_action(
                        "Planner",
                        "LLM_USAGE_ESTIMATED",
                        f"Plan generation used ~{estimated_tokens} tokens (estimated)",
                        {
                            "tokens": estimated_tokens,
                            "model": self.model,
                            "estimated": True,
                            "system_prompt": sys_prompt,
                            "prompt": str(user_content),
                            "response": full_response,
                        },
                        session_id=session_id,
                        tokens_used=estimated_tokens,
                    )

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
                stream_options={"include_usage": True},
            )

            full_response = ""
            print("[PLANNER STREAM] ", end="", flush=True)
            usage_logged = False

            for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    print(content, end="", flush=True)
                    full_response += content
                    if stream_callback:
                        stream_callback(content)

                if hasattr(chunk, "usage") and chunk.usage and not usage_logged:
                    total_tokens = chunk.usage.total_tokens
                    update_session_stats(session_id, "llm", total_tokens)
                    log_action(
                        "Planner",
                        "LLM_USAGE",
                        f"Plan generation used {total_tokens} tokens",
                        {
                            "tokens": total_tokens,
                            "model": self.model,
                            "system_prompt": sys_prompt,
                            "prompt": str(user_content),
                            "response": full_response,
                        },
                        session_id=session_id,
                        tokens_used=total_tokens,
                    )
                    usage_logged = True

            if not usage_logged:
                # Fallback estimation for OpenAI if usage is missing
                input_len = len(sys_prompt) + len(str(user_content))
                output_len = len(full_response)
                estimated_tokens = (input_len + output_len) // 3
                update_session_stats(session_id, "llm", estimated_tokens)
                log_action(
                    "Planner",
                    "LLM_USAGE_ESTIMATED",
                    f"Plan generation used ~{estimated_tokens} tokens (estimated)",
                    {
                        "tokens": estimated_tokens,
                        "model": self.model,
                        "estimated": True,
                        "system_prompt": sys_prompt,
                        "prompt": str(user_content),
                        "response": full_response,
                    },
                    session_id=session_id,
                    tokens_used=estimated_tokens,
                )

            print("\n")
            return full_response

        return ""

    def create_plan(
        self,
        task: str,
        chat_history: list[dict[str, str]] | None = None,
        status_callback: Any = None,
        session_id: str = "default",
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

        return self._generate_plan_with_retry(
            prompt, stream_callback=status_callback, session_id=session_id
        )

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
        session_id: str = "default",
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
            "STATE VERIFICATION PROTOCOL:\n"
            "1. DID THE LAST STEP SUCCEED?\n"
            "   - Look at 'Result'. If it says 'Failed', 'Error', or 'No target found', the last step FAILED.\n"
            "   - If it failed, do NOT proceed to the next logical step. You MUST retry with a DIFFERENT selector, or use a fallback strategy (e.g. search instead of click).\n"
            "2. WHERE AM I?\n"
            "   - Look at 'Current URL'. Does it match the expected destination?\n"
            "   - If you expected to be on a specific page but are still on 'google.com' or 'yandex.ru', the navigation FAILED. You must try clicking again or searching.\n"
            "3. WHAT DO I SEE?\n"
            "   - Look at 'Visible Interactive Elements'.\n"
            "   - Do NOT hallucinate elements. If you want to click 'Search', make sure an element with text 'Search' or a search icon is in the list.\n"
            "   - If the list is empty or doesn't contain what you need, use 'needs_vision': true to get a screenshot.\n\n"
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
            context,
            image_path=screenshot_path,
            stream_callback=status_callback,
            session_id=session_id,
        )

    def _generate_plan_with_retry(
        self,
        user_prompt: str,
        image_path: str | None = None,
        stream_callback: Any = None,
        session_id: str = "default",
    ) -> Plan:
        last_raw = ""
        last_err = ""

        # Add specific instruction to avoid JSONDecodeError for tool calls
        user_prompt += "\n\nIMPORTANT: When using 'call_tool', ensure the 'description' field is a valid JSON string with ESCAPED double quotes. Do NOT use single quotes for the JSON string."

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
                    use_reasoning=True,  # Enable reasoning to show thought process
                    stream_callback=stream_callback,
                    session_id=session_id,
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

    def critique_plan(
        self, plan: Plan, context: str, session_id: str | None = None
    ) -> tuple[bool, str]:
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
                use_reasoning=False,  # Disable reasoning for faster critique
                session_id=session_id or "default",
            )
            if "INVALID" in response:
                return False, response
            return True, "Plan looks good."
        except Exception as e:
            return True, f"Critique failed, assuming valid. Error: {e}"

    def verify_task_completion(
        self,
        user_request: str,
        execution_history: list[dict[str, Any]],
        final_page_content: str,
        session_id: str = "default",
    ) -> dict[str, Any]:
        """
        Verifies if the task was completed successfully.
        """
        history_str = json.dumps(execution_history, indent=2, ensure_ascii=False)

        prompt = f"""
        User Request: {user_request}

        Execution History:
        {history_str}

        Final Page Content (Summary):
        {final_page_content[:2000]}
        """

        try:
            response = self._ask_llm(
                task=prompt,
                system_prompt=VERIFICATION_SYSTEM_PROMPT,
                use_reasoning=False,
                session_id=session_id,
            )

            json_res = extract_json(response)
            return cast("dict[str, Any]", json.loads(json_res))
        except Exception as e:
            # Fallback if verification fails
            return {
                "success": True,
                "reasoning": f"Verification failed due to error: {e}. Assuming success.",
                "feedback": "",
            }

    def generate_summary(
        self,
        task: str,
        history: str,
        page_content: str = "",
        session_id: str = "default",
    ) -> str:
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

        Guidelines for the summary:
        1. If the user asked to "find", "open", "read", or "navigate to" a page/article, and the agent successfully opened it:
           - Confirm that the page is open.
           - Briefly mention the title or topic of the page to confirm it's the right one.
           - Avoid copying the full text of the article into the chat unless explicitly asked.
        2. If the user asked a specific question:
           - Extract the specific answer from the page content.
        3. Keep it short and natural.
        4. Avoid mentioning internal steps like "clicked element E12" unless necessary for context.
        """

        try:
            # Use _ask_llm but with a custom system prompt for summary
            return self._ask_llm(
                task=prompt,
                system_prompt="You are a helpful assistant.",
                use_reasoning=False,  # No reasoning needed for summary
                session_id=session_id,
            )
        except Exception as e:
            return f"Task completed, but failed to generate summary: {e}"
