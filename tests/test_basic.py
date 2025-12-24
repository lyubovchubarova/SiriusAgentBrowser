import json
import os
import pathlib
import shlex
import sqlite3
import subprocess
import time
from typing import Any

import dotenv
import openai
import tqdm


dotenv.load_dotenv()
YANDEX_CLOUD_FOLDER = os.getenv("YANDEX_CLOUD_FOLDER")
YANDEX_CLOUD_API_KEY = os.getenv("YANDEX_CLOUD_API_KEY")
YANDEX_CLOUD_MODEL = "qwen3-235b-a22b-fp8/latest"

TESTS_PROMPTS_PATH = pathlib.Path("tests/test_requests.json")

TEMP_RESULT_PATH = pathlib.Path("tests/result.json")
TEMP_JUDGE_PATH = pathlib.Path("tests/judge_answer.json")
LOGS_PATH = pathlib.Path("tests/logs/" + time.strftime("%Y%m%d_%H%M%S") + ".log")


def request(prompt: str) -> str:
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


def judge(response: str) -> str:
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

    return client.responses.create(
        model=f"gpt://{YANDEX_CLOUD_FOLDER}/{YANDEX_CLOUD_MODEL}",
        temperature=0.3,
        instructions=system_prompt,
        input=response,
    ).output_text

def test_prompts() -> None:
    with TESTS_PROMPTS_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)

    succes = 0
    summary_tokens = 0
    total = len(data)

    bar = tqdm.tqdm(total=total, desc="Tests", unit="req")
    unsucces = []
    for idx, obj in enumerate(data, 1):
        TEMP_RESULT_PATH.open("w", encoding="utf8").write(
            request(obj["query"])
        )
        TEMP_JUDGE_PATH.open("w", encoding="utf8").write(
            judge(TEMP_RESULT_PATH.open("r", encoding="utf8").read())
        )
        with TEMP_JUDGE_PATH.open("r", encoding="utf-8") as f:
            answer = json.load(f)

        if answer.get("result") == "OK":
            succes += 1
        else:
            unsucces.append(obj["id"])

        con = sqlite3.connect("logs.db")
        cur = con.cursor()
        res = cur.execute("SELECT total_tokens FROM session_stats ORDER BY start_time DESC LIMIT 1").fetchone()
        con.close()
        summary_tokens += res[0]
        pct_succes = succes / idx * 100
        bar.set_postfix({
            "success_pct": f"{pct_succes:.2f}%",
            "avg_tokens": f"{summary_tokens / idx:.2f}"
        })
        bar.update(1)

    bar.close()
    print(f"Итог: {succes}/{total} успешных ({succes / total * 100:.2f}%)")
    print(f"Затрачено токенов: {summary_tokens}. Среднее количество токенов: {summary_tokens / total:.2f}")
    with LOGS_PATH.open("w", encoding="utf8") as f:
        print(f"Итог: {succes}/{total} успешных ({succes / total * 100:.2f}%)", file=f)
        print(f"Затрачено токенов: {summary_tokens}. Среднее количество токенов: {summary_tokens / total:.2f}", file=f)
        print(unsucces, file=f)


if __name__ == "__main__":
    test_prompts()
