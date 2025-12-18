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
            base_url="https://rest-assistant.api.cloud.yandex.net/v1",
            project=folder_id,
        )

    def request(self, filename: str, prompt: str) -> str:
        with open(filename, "rb") as f:
            image_base64 = base64.b64encode(f.read()).decode("utf-8")
        response = self.client.responses.create(
            model=self.model, temperature=0.3, input=prompt, max_output_tokens=100
        )
        return response.output_text


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
    print(vision_agent.request("image.jpg", "привет кто на картинке"))
