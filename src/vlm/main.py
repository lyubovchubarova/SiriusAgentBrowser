import base64
import dotenv
import os
import openai


class VLMAgent:
    def __init__(self, token: str, folder_id: str) -> None:
        if token is None or folder_id is None:
            raise ValueError("Невалидные данные в .env")
        self.model = f"gpt://{folder_id}/gemma-3-27b-it/latest"
        self.client = openai.OpenAI(
            api_key=token,
            base_url="https://llm.api.cloud.yandex.net/v1",
            project=folder_id,
        )

    def request(self, filename: str, prompt: str) -> str | None:
        with open(filename, "rb") as f:
            image_base64 = base64.b64encode(f.read()).decode("utf-8")
        image_payload = (
            f"data:image/{filename[filename.rfind('.') + 1 :]};base64,{image_base64}"
        )
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_payload}},
                    ],
                }
            ],
            temperature=0.3,
            max_tokens=200,
        )

        return response.choices[0].message.content


if __name__ == "__main__":
    dotenv.load_dotenv()
    if (
        os.getenv("YANDEX_GPT_API_TOKEN", None) is None
        or os.getenv("YANDEX_CLOUD_FOLDER_ID", None) is None
    ):
        raise ValueError("Невалидные данные в .env")
    vision_agent: VLMAgent = VLMAgent(
        token=os.getenv("YANDEX_GPT_API_TOKEN", ""),
        folder_id=os.getenv("YANDEX_CLOUD_FOLDER_ID", ""),
    )
    print(vision_agent.request("cat.jpg", "привет кто на картинке"))
