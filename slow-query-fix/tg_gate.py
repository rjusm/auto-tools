#!/usr/bin/env python3
"""Telegram-уведомления и "ворота" подтверждения для скилла slow-query-fix.

Только stdlib. Токен и chat id берутся из переменных окружения или из файла
tools/slow-query-fix/.env.local (в .gitignore), формат KEY=VALUE:
    SLOWQUERY_TG_TOKEN=...      # токен ОТДЕЛЬНОГО бота (не боевых ботов проекта)
    SLOWQUERY_TG_CHAT_ID=...    # id личного чата с ботом
    SLOWQUERY_TG_USER_ID=...    # (необязательно) id пользователя; по умолчанию = chat id

Команды:
    notify "текст"                 отправить сообщение, не ждать (exit 0)
    gate "текст" [--timeout 1800]  сообщение с кнопками [Продолжить][Пропустить][Стоп]
                                   и ожидание ответа
    check                          неблокирующая проверка: не нажали ли Стоп / не пришло ли /stop

Коды выхода:
    0   продолжить (gate: нажато "Продолжить"; notify/check: всё ок)
    10  СТОП: остановить процесс, ничего больше не выполнять
    11  таймаут ожидания (трактовать как стоп, ничего не делать дальше)
    12  пропустить текущий этап (gate)
    2   ошибка конфигурации/сети (трактовать как стоп и сообщить пользователю)

Для тестов: SLOWQUERY_TG_API_BASE (адрес мока вместо api.telegram.org),
SLOWQUERY_ENV_FILE и SLOWQUERY_STATE_FILE (изолированные конфиг и offset).
"""
import argparse
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.environ.get("SLOWQUERY_ENV_FILE") or os.path.join(HERE, ".env.local")
STATE_FILE = os.environ.get("SLOWQUERY_STATE_FILE") or os.path.join(
    tempfile.gettempdir(), "slow_query_fix_tg_offset.json")


def load_cfg():
    cfg = {}
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    cfg[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("SLOWQUERY_TG_TOKEN", "SLOWQUERY_TG_CHAT_ID", "SLOWQUERY_TG_USER_ID"):
        if os.environ.get(k):
            cfg[k] = os.environ[k]
    if not cfg.get("SLOWQUERY_TG_TOKEN") or not cfg.get("SLOWQUERY_TG_CHAT_ID"):
        sys.stderr.write("tg_gate: не заданы SLOWQUERY_TG_TOKEN / SLOWQUERY_TG_CHAT_ID\n")
        sys.exit(2)
    cfg.setdefault("SLOWQUERY_TG_USER_ID", cfg["SLOWQUERY_TG_CHAT_ID"])
    return cfg


def api(cfg, method, params=None, timeout=15):
    base = os.environ.get("SLOWQUERY_TG_API_BASE", "https://api.telegram.org").rstrip("/")
    url = "%s/bot%s/%s" % (base, cfg["SLOWQUERY_TG_TOKEN"], method)
    data = urllib.parse.urlencode(params or {}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=timeout) as r:
            return json.load(r)
    except (urllib.error.URLError, OSError, ValueError) as e:
        # не печатаем URL: в нём токен
        sys.stderr.write("tg_gate: ошибка запроса к Telegram (%s)\n" % type(e).__name__)
        sys.exit(2)


def send(cfg, text, markup=None):
    p = {"chat_id": cfg["SLOWQUERY_TG_CHAT_ID"], "text": text[:4000]}
    if markup:
        p["reply_markup"] = json.dumps(markup)
    res = api(cfg, "sendMessage", p)
    if not res.get("ok"):
        sys.stderr.write("tg_gate: Telegram отклонил сообщение\n")
        sys.exit(2)
    return res["result"]["message_id"]


def get_offset():
    try:
        with open(STATE_FILE) as f:
            return json.load(f).get("offset", 0)
    except (OSError, ValueError):
        return 0


def set_offset(v):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump({"offset": v}, f)
    except OSError:
        pass


def poll(cfg, wait):
    """Забрать новые апдейты. Возвращает список (kind, payload) только от разрешённого пользователя."""
    off = get_offset()
    res = api(cfg, "getUpdates", {"offset": off, "timeout": wait,
                                  "allowed_updates": json.dumps(["message", "callback_query"])},
              timeout=wait + 10)
    events = []
    for u in res.get("result", []):
        off = max(off, u["update_id"] + 1)
        cb = u.get("callback_query")
        msg = u.get("message")
        if cb and str(cb["from"]["id"]) == str(cfg["SLOWQUERY_TG_USER_ID"]):
            api(cfg, "answerCallbackQuery", {"callback_query_id": cb["id"]})
            events.append(("button", cb.get("data", "")))
        elif msg and str(msg.get("from", {}).get("id")) == str(cfg["SLOWQUERY_TG_USER_ID"]):
            events.append(("text", (msg.get("text") or "").strip().lower()))
        # всё от других пользователей игнорируется
    set_offset(off)
    return events


def interpret(events):
    for kind, val in events:
        if (kind == "button" and val == "stop") or (kind == "text" and val in ("/stop", "стоп", "stop")):
            return 10
        if kind == "button" and val == "go":
            return 0
        if kind == "button" and val == "skip":
            return 12
    return None


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("notify"); n.add_argument("text")
    g = sub.add_parser("gate"); g.add_argument("text"); g.add_argument("--timeout", type=int, default=1800)
    sub.add_parser("check")
    a = ap.parse_args()
    cfg = load_cfg()

    if a.cmd == "notify":
        send(cfg, a.text)
        # заодно проверим, не просили ли остановиться
        rc = interpret(poll(cfg, 0))
        sys.exit(10 if rc == 10 else 0)

    if a.cmd == "check":
        rc = interpret(poll(cfg, 0))
        if rc == 10:
            send(cfg, "Получен СТОП. Процесс остановлен.")
        sys.exit(10 if rc == 10 else 0)

    if a.cmd == "gate":
        poll(cfg, 0)  # сбросить старые апдейты, чтобы не поймать прошлое нажатие
        send(cfg, a.text, {"inline_keyboard": [[
            {"text": "Продолжить", "callback_data": "go"},
            {"text": "Пропустить этап", "callback_data": "skip"},
            {"text": "Стоп", "callback_data": "stop"}]]})
        deadline = time.time() + a.timeout
        while time.time() < deadline:
            rc = interpret(poll(cfg, min(25, max(1, int(deadline - time.time())))))
            if rc is not None:
                send(cfg, {0: "Принято: продолжаю.", 12: "Принято: этап пропущен.",
                           10: "Принято: СТОП. Процесс остановлен."}[rc])
                sys.exit(rc)
        send(cfg, "Нет ответа за %d мин. Процесс остановлен." % (a.timeout // 60))
        sys.exit(11)


if __name__ == "__main__":
    main()
