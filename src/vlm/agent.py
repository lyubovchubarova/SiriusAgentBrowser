import base64
import pathlib

import openai


class VLMAgent:
    def __init__(self, token: str, folder_id: str, system_prompt: str) -> None:
        if token is None or folder_id is None:
            raise ValueError("Невалидные данные в .env")
        self.model = f"gpt://{folder_id}/gemma-3-27b-it/latest"
        self.client = openai.OpenAI(
            api_key=token,
            base_url="https://llm.api.cloud.yandex.net/v1",
            project=folder_id,
        )
        with pathlib.Path(system_prompt).open(encoding="utf8") as file:
            self.system_prompt = file.read()

    def request(self, filename: str, prompt: str) -> str | None:
        with pathlib.Path(filename).open("rb") as f:
            image_base64 = base64.b64encode(f.read()).decode("utf-8")
        image_payload = (
            f"data:image/{filename[filename.rfind('.') + 1 :]};base64,{image_base64}"
        )
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": [
                        {"type": "text", "text": self.system_prompt},
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_payload}},
                    ],
                },
            ],
            temperature=0.3,
            max_tokens=10000,
        )

        return response.choices[0].message.content

