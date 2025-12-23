import json
import os
import shlex
import sqlite3
import subprocess

import dotenv
import openai

dotenv.load_dotenv()
YANDEX_CLOUD_FOLDER = os.getenv("YANDEX_CLOUD_FOLDER")
YANDEX_CLOUD_API_KEY = os.getenv("YANDEX_CLOUD_API_KEY")
YANDEX_CLOUD_MODEL = os.getenv("YANDEX_CLOUD_MODEL_PATH")


def request(prompt):
    subprocess.run(shlex.split(f'venv/Scripts/python src/main.py "{prompt}"'))
    db = "logs.db"
    q1 = "SELECT session_id FROM action_logs ORDER BY id DESC LIMIT 1"
    q2 = "SELECT component, action_type, message, details FROM action_logs WHERE session_id = ?"
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    r = cur.execute(q1).fetchone()
    if not r:
        return json.dumps({"request": prompt, "objects": []}, ensure_ascii=False)
    sid = r[0]
    rows = [dict(x) for x in cur.execute(q2, (sid,)).fetchall()]
    return json.dumps(
        {"request": prompt, "objects": rows}, ensure_ascii=False, indent=2
    )


def judge(response):
    system_prompt = (
        "Ты судья для тестов браузерного агента.\n"
        "На вход подаётся JSON с шагами агента.\n"
        "Оцени, выполнен ли запрос пользователя.\n"
        "Ответ строк без MARKDOWN разметки.\n"
        "Ответ строго в JSON:\n"
        '{"result":"OK"} или {"result":"FAIL"}'
    )

    client = openai.OpenAI(
        api_key=YANDEX_CLOUD_API_KEY,
        base_url="https://rest-assistant.api.cloud.yandex.net/v1",
        project=YANDEX_CLOUD_FOLDER,
    )

    response = client.responses.create(
        model=f"gpt://{YANDEX_CLOUD_FOLDER}/yandexgpt/rc",
        temperature=0.3,
        instructions=system_prompt,
        input=response,
    )
    return response.output_text


if __name__ == "__main__":
    from pathlib import Path

    result_path = Path("tests/result.json")
    judge_path = Path("tests/judge_answer.json")

    result_content = request("погода во владивостоке сейчас")
    result_path.write_text(result_content, encoding="utf8")

    judge_input = result_path.read_text(encoding="utf8")
    judge_content = judge(judge_input)
    judge_path.write_text(judge_content, encoding="utf8")
