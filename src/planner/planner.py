import json
import os
import re

from models import Plan
from openai import OpenAI

SYSTEM_PROMPT = """
You are a planner for browser automation.

Return ONLY valid JSON.
Do NOT add any text before or after JSON.

Schema:
{
  "task": string,
  "steps": [
    {
      "step_id": number,
      "action": "navigate" | "click" | "type" | "scroll",
      "description": string,
      "expected_result": string
    }
  ],
  "estimated_time": number
}
"""

def extract_json(text: str) -> str:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"LLM returned non-JSON:\n{text}")
    return match.group(0)

class Planner:
    def __init__(self):
        self.folder = os.environ["YANDEX_CLOUD_FOLDER"]
        self.model_path = os.environ["YANDEX_CLOUD_MODEL_PATH"]

        self.client = OpenAI(
            api_key=os.environ["YANDEX_CLOUD_API_KEY"],
            base_url=os.environ["YANDEX_CLOUD_BASE_URL"],
            project=self.folder,
        )

    def create_plan(self, task: str) -> Plan:
        response = self.client.responses.create(
            model=f"gpt://{self.folder}/{self.model_path}",
            temperature=0.2,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": task},
            ],
            max_output_tokens=600,
        )

        raw_text = response.output_text or ""
        #print("RAW MODEL OUTPUT:\n", raw_text)

        json_text = extract_json(raw_text)
        data = json.loads(json_text)

        return Plan.model_validate(data)
