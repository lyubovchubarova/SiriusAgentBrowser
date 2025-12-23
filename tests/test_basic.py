import json
import shlex
import sqlite3
import subprocess


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
        print(json.dumps({"request": prompt, "objects": []}, ensure_ascii=False))
        return
    sid = r[0]
    rows = [dict(x) for x in cur.execute(q2, (sid,)).fetchall()]
    print(json.dumps({"request": prompt, "objects": rows}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    request("кто сейчас президент сша")
