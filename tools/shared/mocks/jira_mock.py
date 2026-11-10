#!/usr/bin/env python3
"""Мок Jira для dry-run. Сети нет: данные из mocks/fixtures/<KEY>.json, запись — только в журнал.

    jira_mock.py get EW-000
    jira_mock.py comment EW-000 "текст"
    jira_mock.py transition EW-000 "In Review"
Неизвестный ключ -> заглушка с типовыми полями. Журнал: mocks/.calls.jsonl.
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.environ.get("MOCK_CALLS_LOG") or os.path.join(HERE, ".calls.jsonl")


def log(entry):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(dict(entry, ts=time.time(), tool="jira"), ensure_ascii=False) + "\n")


def main():
    a = sys.argv[1:]
    if len(a) < 2 or a[0] not in ("get", "comment", "transition"):
        sys.exit("usage: jira_mock.py get|comment|transition KEY [text]")
    cmd, key = a[0], a[1]
    if cmd == "get":
        path = os.path.join(HERE, "fixtures", key + ".json")
        if os.path.exists(path):
            print(open(path, encoding="utf-8").read())
        else:
            print(json.dumps({"key": key, "summary": "[mock] " + key, "status": "In Progress",
                              "url": "https://jira.example.invalid/browse/" + key}, ensure_ascii=False))
        return
    log({"op": cmd, "key": key, "payload": a[2:]})
    print("[jira-mock] НЕ выполнено (dry-run): %s %s %s" % (cmd, key, " ".join(a[2:])))


if __name__ == "__main__":
    main()
