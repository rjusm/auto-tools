#!/usr/bin/env python3
"""Мок Telegram Bot API для тестов tg_gate.py. Только stdlib, ничего не создаёт во внешнем мире.

Эмулирует: sendMessage, getUpdates, answerCallbackQuery.
Управление (то, что в реальности делает человек в Telegram):
    POST /_mock/press   {"data": "go|skip|stop", "user_id": 1}   нажать inline-кнопку
    POST /_mock/say     {"text": "/stop", "user_id": 1}          написать сообщение боту
    GET  /_mock/messages                                         что бот отправил
    POST /_mock/reset                                            сбросить состояние
Запуск отдельно: python mock_telegram.py [port]   (по умолчанию 8081)
"""
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        self.updates = []   # [{update_id, ...}]
        self.sent = []      # отправленные ботом сообщения
        self.answered = []
        self.next_id = 1


STATE = State()


def _push(update):
    with STATE.lock:
        update["update_id"] = STATE.next_id
        STATE.next_id += 1
        STATE.updates.append(update)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # тишина
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n).decode() if n else ""

    def do_GET(self):
        if self.path == "/_mock/messages":
            with STATE.lock:
                return self._json(STATE.sent)
        self._json({"ok": False, "description": "not found"}, 404)

    def do_POST(self):
        raw = self._body()
        path = self.path.split("?")[0]

        if path.startswith("/_mock/"):
            data = json.loads(raw or "{}")
            if path == "/_mock/reset":
                with STATE.lock:
                    STATE.reset()
            elif path == "/_mock/press":
                uid = data.get("user_id", 1)
                _push({"callback_query": {"id": "cb%d" % STATE.next_id, "from": {"id": uid},
                                          "data": data["data"]}})
            elif path == "/_mock/say":
                uid = data.get("user_id", 1)
                _push({"message": {"from": {"id": uid}, "chat": {"id": uid}, "text": data["text"]}})
            return self._json({"ok": True})

        # /bot<token>/<method>
        parts = path.strip("/").split("/")
        if len(parts) != 2 or not parts[0].startswith("bot"):
            return self._json({"ok": False, "description": "bad path"}, 404)
        method = parts[1]
        p = {k: v[0] for k, v in parse_qs(raw).items()}

        if method == "sendMessage":
            with STATE.lock:
                msg = {"message_id": len(STATE.sent) + 1, "chat_id": p.get("chat_id"),
                       "text": p.get("text", ""),
                       "reply_markup": json.loads(p["reply_markup"]) if "reply_markup" in p else None}
                STATE.sent.append(msg)
            return self._json({"ok": True, "result": {"message_id": msg["message_id"]}})

        if method == "answerCallbackQuery":
            with STATE.lock:
                STATE.answered.append(p.get("callback_query_id"))
            return self._json({"ok": True, "result": True})

        if method == "getUpdates":
            offset = int(p.get("offset", 0))
            wait = min(int(p.get("timeout", 0)), 1)  # long-poll ограничен 1 с, чтобы тесты были быстрыми
            deadline = time.time() + wait
            while True:
                with STATE.lock:
                    STATE.updates = [u for u in STATE.updates if u["update_id"] >= offset]
                    out = list(STATE.updates)
                if out or time.time() >= deadline:
                    return self._json({"ok": True, "result": out})
                time.sleep(0.05)

        self._json({"ok": False, "description": "unknown method"}, 404)


def serve(port=0, host="127.0.0.1"):
    """Запустить в фоновом потоке. Возвращает (server, port)."""
    srv = ThreadingHTTPServer((host, port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8081
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print("mock telegram on :%d" % port, flush=True)
    srv.serve_forever()
