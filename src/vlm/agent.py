import base64
import os
import time
import re
from pathlib import Path
from typing import Optional

import openai
from PIL import Image

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
    def __init__(self, token: str = None, folder_id: str = None) -> None:
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
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode("utf-8")

    def _call_vlm(self, image_path: str, system_prompt: str, user_prompt: str) -> str:
        if not self.client:
            return "Error: VLM client not initialized"

        for attempt in range(3):
            try:
                base64_image = self._encode_image(image_path)
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
                )
                return response.choices[0].message.content or ""
            except Exception as e:
                print(f"VLM call failed (attempt {attempt+1}/3): {e}")
                time.sleep(2)

        return "Error calling VLM: Max retries exceeded"

    def get_target_id(self, image_path: str, task_description: str) -> str:
        """
        Returns target ID in format :id:<number>: or :not_found:
        """
        response = self._call_vlm(
            image_path, self.click_system_prompt, task_description
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

    def extract_data(self, image_path: str, query: str) -> str:
        """
        Extracts structured data from the image based on the query.
        """
        system_prompt = (
            "Ты — аналитик данных. Твоя задача — извлечь информацию со скриншота по запросу пользователя.\n"
            "Отвечай только фактами, которые видишь на изображении.\n"
            "Если данных нет, напиши 'Данные не найдены'."
        )
        return self._call_vlm(image_path, system_prompt, query)

    def verify_state(self, image_path: str, expected_result: str) -> tuple[bool, str]:
        """
        Verifies if the screenshot matches the expected result.
        """
        response = self._call_vlm(
            image_path, VERIFY_SYSTEM_PROMPT, f"Ожидаемый результат: {expected_result}"
        )

        if "TRUE" in response.upper():
            return True, response
        return False, response
