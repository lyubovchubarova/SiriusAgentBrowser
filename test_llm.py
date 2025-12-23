import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

folder = os.environ["YANDEX_CLOUD_FOLDER"]
model_path = os.environ["YANDEX_CLOUD_MODEL_PATH"]
api_key = os.environ["YANDEX_CLOUD_API_KEY"]
base_url = os.environ["YANDEX_CLOUD_BASE_URL"]

print(f"Folder: {folder}")
print(f"Model: {model_path}")
print(f"Base URL: {base_url}")

client = OpenAI(
    api_key=api_key,
    base_url=base_url,
)

model_uri = f"gpt://{folder}/{model_path}"
print(f"Model URI: {model_uri}")

try:
    response = client.chat.completions.create(
        model=model_uri,
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello, are you working?"},
        ],
        temperature=0.1,
        extra_body={"reasoningOptions": {"mode": "ENABLED_HIDDEN"}}
    )
    print("Response:", response.choices[0].message.content)
except Exception as e:
    print("Error:", e)
