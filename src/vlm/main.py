import os
import re

import dotenv
import pydantic
from agent import VLMAgent


class ClickModel(pydantic.BaseModel):
    value: str

    @pydantic.field_validator("value")
    @classmethod
    def validate_format(cls, v: str) -> str:
        pattern = r"^:click:(-?\d+):(-?\d+):$"
        if not re.match(pattern, v):
            raise ValueError("Строка должна быть в формате :<click>:<x>:<y>:")
        return v


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
    image_url = "C:\\Users\\maxim\\PycharmProjects\\SiriusAgentBrowser\\screenshots\\wiki.png"
    prompt = "кликни скачать на андроид"
    response = vision_agent.request(image_url, prompt)
    print(response)
    ClickModel.validate_format(response)
