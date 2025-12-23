import json
import shlex
import sqlite3
import subprocess
import openai
import dotenv
import os
from tqdm import tqdm

dotenv.load_dotenv()
YANDEX_CLOUD_FOLDER = os.getenv("YANDEX_CLOUD_FOLDER")
YANDEX_CLOUD_API_KEY = os.getenv("YANDEX_CLOUD_API_KEY")
YANDEX_CLOUD_MODEL = "qwen3-235b-a22b-fp8/latest"


def request(prompt):
    subprocess.run(
        shlex.split(f'venv/Scripts/python src/main.py "{prompt}"'),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
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
    return json.dumps({"request": prompt, "objects": rows}, ensure_ascii=False, indent=2)


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
        project=YANDEX_CLOUD_FOLDER
    )

    response = client.responses.create(
        model=f"gpt://{YANDEX_CLOUD_FOLDER}/{YANDEX_CLOUD_MODEL}",
        temperature=0.3,
        instructions=system_prompt,
        input=response,
    )
    return response.output_text


from tqdm import tqdm
import json


def test_prompts():
    with open("tests/test_requests.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    succes = 0
    total = len(data)

    bar = tqdm(total=total, desc="Tests", unit="req")

    for idx, obj in enumerate(data, 1):
        open("tests/result.json", "w", encoding="utf8").write(
            request(obj["query"])
        )
        open("tests/judge_answer.json", "w", encoding="utf8").write(
            judge(open("tests/result.json", "r", encoding="utf8").read())
        )
        with open("tests/judge_answer.json", "r", encoding="utf-8") as f:
            answer = json.load(f)

        if answer.get("result") == "OK":
            succes += 1

        # обновляем прогресс бар
        pct_succes = succes / idx * 100
        bar.set_postfix({"success_pct": f"{pct_succes:.2f}%"})
        bar.update(1)

    bar.close()
    print(f"Итог: {succes}/{total} успешных ({succes / total * 100:.2f}%)")


if __name__ == "__main__":
    test_prompts()
