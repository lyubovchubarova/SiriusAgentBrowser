import base64
import os
import re
import time
from pathlib import Path
from typing import Any

import openai

from src.logger_db import log_action, update_session_stats

VERIFY_SYSTEM_PROMPT = """
Ты — визуальный ассистент для проверки выполнения действий в браузере.
Твоя задача — определить, соответствует ли состояние страницы (скриншот) ожидаемому результату.

Формат ответа:
TRUE: <причина>
FALSE: <причина>

Пример:
TRUE: На странице виден заголовок "Википедия".
FALSE: Страница пустая, ожидаемый текст не найден.
"""


class VLMAgent:
    def __init__(self, token: str | None = None, folder_id: str | None = None) -> None:
        self.token = token or os.getenv("YANDEX_CLOUD_API_KEY")
        self.folder_id = folder_id or os.getenv("YANDEX_CLOUD_FOLDER")

        if not self.token:
            # Если ключа нет, агент не сможет работать.
            pass

        if self.folder_id:
            self.model = f"gpt://{self.folder_id}/gemma-3-27b-it/latest"
            self.client = openai.OpenAI(
                api_key=self.token,
                base_url="https://llm.api.cloud.yandex.net/v1",
                project=self.folder_id,
            )
        else:
            # Fallback to OpenAI if configured, or just fail later
            self.client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            self.model = "gpt-4o"

        # Load click prompt
        try:
            prompt_path = Path(__file__).parent / "system_prompt.txt"
            with prompt_path.open(encoding="utf8") as file:
                self.click_system_prompt = file.read()
        except Exception:
            self.click_system_prompt = "You are a clicker agent."

    def _encode_image(self, image_path: str) -> str:
        with Path(image_path).open("rb") as image_file:
            return base64.b64encode(image_file.read()).decode("utf-8")

    def _call_vlm(
        self,
        image_path: str,
        system_prompt: str,
        user_prompt: str,
        stream_callback: Any = None,
        session_id: str = "default",
    ) -> str:
        if not self.client:
            return "Error: VLM client not initialized"

        print("\n[VLM LOG] Sending request to VLM...")
        print(f"[VLM LOG] System Prompt: {system_prompt[:100]}...")
        print(f"[VLM LOG] User Prompt: {user_prompt}")

        for attempt in range(3):
            try:
                base64_image = self._encode_image(image_path)

                # Enable streaming
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": system_prompt,
                        },
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": user_prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/png;base64,{base64_image}"
                                    },
                                },
                            ],
                        },
                    ],
                    temperature=0.1,
                    max_tokens=1000,
                    stream=True,  # Enable streaming
                    stream_options={"include_usage": True},
                )

                full_response = ""
                usage_logged = False

                for chunk in response:
                    if chunk.choices and chunk.choices[0].delta.content:
                        content = chunk.choices[0].delta.content
                        full_response += content
                        if stream_callback:
                            stream_callback(content)

                    if hasattr(chunk, "usage") and chunk.usage and not usage_logged:
                        total_tokens = chunk.usage.total_tokens
                        update_session_stats(session_id, "vlm", total_tokens)
                        log_action(
                            "VLM",
                            "VLM_USAGE",
                            f"VLM request used {total_tokens} tokens",
                            {
                                "tokens": total_tokens,
                                "model": self.model,
                                "system_prompt": system_prompt,
                                "prompt": user_prompt,
                                "response": full_response,
                            },
                            session_id=session_id,
                            tokens_used=total_tokens,
                        )
                        usage_logged = True

                if not usage_logged:
                    # Fallback estimation
                    input_len = (
                        len(system_prompt) + len(user_prompt) + 1000
                    )  # +1000 for image overhead estimate
                    output_len = len(full_response)
                    estimated_tokens = (input_len + output_len) // 3
                    update_session_stats(session_id, "vlm", estimated_tokens)
                    log_action(
                        "VLM",
                        "VLM_USAGE_ESTIMATED",
                        f"VLM request used ~{estimated_tokens} tokens (estimated)",
                        {
                            "tokens": estimated_tokens,
                            "model": self.model,
                            "estimated": True,
                            "system_prompt": system_prompt,
                            "prompt": user_prompt,
                            "response": full_response,
                        },
                        session_id=session_id,
                        tokens_used=estimated_tokens,
                    )

                return full_response

            except Exception as e:
                print(f"VLM call failed (attempt {attempt + 1}/3): {e}")
                time.sleep(2)

        return "Error calling VLM: Max retries exceeded"

    def get_target_id(
        self,
        image_path: str,
        task_description: str,
        stream_callback: Any = None,
        session_id: str = "default",
    ) -> str:
        """
        Returns target ID in format :id:<number>: or :not_found:
        """
        response = self._call_vlm(
            image_path,
            self.click_system_prompt,
            task_description,
            stream_callback=stream_callback,
            session_id=session_id,
        )

        # Basic validation
        if ":id:" in response:
            try:
                # Expected format :id:12:
                match = re.search(r":id:(\d+):", response)
                if match:
                    return response
            except Exception as e:
                return f"Error parsing ID: {e}"

        return response

    def extract_data(
        self,
        image_path: str,
        query: str,
        stream_callback: Any = None,
        session_id: str = "default",
    ) -> str:
        """
        Extracts structured data from the image based on the query.
        """
        system_prompt = (
            "Ты — аналитик данных. Твоя задача — извлечь информацию со скриншота по запросу пользователя.\n"
            "Отвечай только фактами, которые видишь на изображении.\n"
            "Если данных нет, напиши 'Данные не найдены'."
        )
        return self._call_vlm(
            image_path,
            system_prompt,
            query,
            stream_callback=stream_callback,
            session_id=session_id,
        )

    def verify_state(
        self,
        image_path: str,
        expected_result: str,
        stream_callback: Any = None,
        session_id: str = "default",
    ) -> tuple[bool, str]:
        """
        Verifies if the screenshot matches the expected result.
        """
        response = self._call_vlm(
            image_path,
            VERIFY_SYSTEM_PROMPT,
            f"Ожидаемый результат: {expected_result}",
            stream_callback=stream_callback,
            session_id=session_id,
        )

        if "TRUE" in response.upper():
            return True, response
        return False, response
