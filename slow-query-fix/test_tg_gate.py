"""Тесты tg_gate.py против мока Telegram API (ничего реального не создаётся).

Запуск: python -m unittest -v      (мок поднимается сам)
В docker: docker compose up --build --abort-on-container-exit tests   (используется сервис mock-telegram)
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request

import mock_telegram

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, "tg_gate.py")
TOKEN = "123456:SECRET-TEST-TOKEN"
ME = 111
STRANGER = 999

MOCK_URL = os.environ.get("MOCK_URL")
_srv = None


def setUpModule():
    global MOCK_URL, _srv
    if not MOCK_URL:
        _srv, port = mock_telegram.serve(0)
        MOCK_URL = "http://127.0.0.1:%d" % port


def tearDownModule():
    if _srv:
        _srv.shutdown()


def mock(method, path, body=None):
    req = urllib.request.Request(MOCK_URL + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.load(r)


class GateTest(unittest.TestCase):
    def setUp(self):
        mock("POST", "/_mock/reset", {})
        self.tmp = tempfile.TemporaryDirectory()
        self.env = dict(os.environ,
                        SLOWQUERY_TG_TOKEN=TOKEN, SLOWQUERY_TG_CHAT_ID=str(ME),
                        SLOWQUERY_TG_API_BASE=MOCK_URL,
                        SLOWQUERY_ENV_FILE=os.path.join(self.tmp.name, "absent.env"),
                        SLOWQUERY_STATE_FILE=os.path.join(self.tmp.name, "offset.json"))

    def tearDown(self):
        self.tmp.cleanup()

    def run_gate(self, *args, env=None, timeout=20):
        return subprocess.run([sys.executable, "-I", GATE, *args], env=env or self.env,
                              capture_output=True, text=True, timeout=timeout)

    def start_gate(self, *args):
        return subprocess.Popen([sys.executable, "-I", GATE, *args], env=self.env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def wait_prompt(self):
        """Дождаться, пока gate отправит сообщение с кнопками (аналог: человек увидел сообщение)."""
        for _ in range(100):
            if any(m["reply_markup"] for m in mock("GET", "/_mock/messages")):
                return
            time.sleep(0.05)
        self.fail("gate не отправил сообщение с кнопками")

    def answer_gate(self, *args, press=None, say=None, user=ME):
        p = self.start_gate("gate", "Продолжить?", *args)
        self.wait_prompt()
        if press:
            mock("POST", "/_mock/press", {"data": press, "user_id": user})
        if say:
            mock("POST", "/_mock/say", {"text": say, "user_id": user})
        out, err = p.communicate(timeout=20)
        return p.returncode, out, err

    # --- notify ---
    def test_notify_sends_and_exits_0(self):
        r = self.run_gate("notify", "Этап 1 готов")
        self.assertEqual(r.returncode, 0)
        msgs = mock("GET", "/_mock/messages")
        self.assertEqual([m["text"] for m in msgs], ["Этап 1 готов"])
        self.assertEqual(msgs[0]["chat_id"], str(ME))

    def test_notify_picks_up_pending_stop(self):
        mock("POST", "/_mock/say", {"text": "/stop", "user_id": ME})
        self.assertEqual(self.run_gate("notify", "Этап 2").returncode, 10)

    # --- check ---
    def test_check_quiet_returns_0(self):
        self.assertEqual(self.run_gate("check").returncode, 0)

    def test_check_stop_text_variants(self):
        for word in ("/stop", "стоп", "STOP"):
            mock("POST", "/_mock/reset", {})
            self.env["SLOWQUERY_STATE_FILE"] = os.path.join(self.tmp.name, "o_%s.json" % abs(hash(word)))
            mock("POST", "/_mock/say", {"text": word, "user_id": ME})
            self.assertEqual(self.run_gate("check").returncode, 10, word)

    def test_check_stop_button(self):
        mock("POST", "/_mock/press", {"data": "stop", "user_id": ME})
        self.assertEqual(self.run_gate("check").returncode, 10)

    def test_check_consumes_update(self):
        mock("POST", "/_mock/say", {"text": "/stop", "user_id": ME})
        self.assertEqual(self.run_gate("check").returncode, 10)
        self.assertEqual(self.run_gate("check").returncode, 0)  # повторно уже не срабатывает

    # --- gate ---
    def test_gate_continue(self):
        rc, _, _ = self.answer_gate(press="go")
        self.assertEqual(rc, 0)

    def test_gate_skip(self):
        rc, _, _ = self.answer_gate(press="skip")
        self.assertEqual(rc, 12)

    def test_gate_stop_button(self):
        rc, _, _ = self.answer_gate(press="stop")
        self.assertEqual(rc, 10)

    def test_gate_stop_text(self):
        rc, _, _ = self.answer_gate(say="/stop")
        self.assertEqual(rc, 10)

    def test_gate_has_three_buttons(self):
        self.answer_gate(press="go")
        kb = mock("GET", "/_mock/messages")[0]["reply_markup"]["inline_keyboard"][0]
        self.assertEqual([b["callback_data"] for b in kb], ["go", "skip", "stop"])

    def test_gate_timeout_exits_11(self):
        r = self.run_gate("gate", "ждём", "--timeout", "2")
        self.assertEqual(r.returncode, 11)
        self.assertIn("остановлен", mock("GET", "/_mock/messages")[-1]["text"])

    def test_gate_ignores_stranger(self):
        p = self.start_gate("gate", "--timeout", "4", "кто нажал?")
        self.wait_prompt()
        mock("POST", "/_mock/press", {"data": "go", "user_id": STRANGER})
        mock("POST", "/_mock/say", {"text": "/stop", "user_id": STRANGER})
        time.sleep(1.5)
        self.assertIsNone(p.poll(), "чужое нажатие не должно завершать gate")
        mock("POST", "/_mock/press", {"data": "go", "user_id": ME})
        p.communicate(timeout=20)
        self.assertEqual(p.returncode, 0)

    def test_gate_ignores_stale_press_from_before(self):
        mock("POST", "/_mock/press", {"data": "go", "user_id": ME})  # старое нажатие до gate
        r = self.run_gate("gate", "новый этап", "--timeout", "2")
        self.assertEqual(r.returncode, 11)

    # --- ошибки ---
    def test_missing_config_exits_2(self):
        env = {k: v for k, v in self.env.items() if not k.startswith("SLOWQUERY_TG_TOKEN")}
        self.assertEqual(self.run_gate("notify", "x", env=env).returncode, 2)

    def test_unreachable_api_exits_2_without_leaking_token(self):
        env = dict(self.env, SLOWQUERY_TG_API_BASE="http://127.0.0.1:1")
        r = self.run_gate("notify", "x", env=env)
        self.assertEqual(r.returncode, 2)
        self.assertNotIn(TOKEN, r.stdout + r.stderr)

    def test_env_file_is_read(self):
        path = os.path.join(self.tmp.name, "cfg.env")
        with open(path, "w") as f:
            f.write('# c\nSLOWQUERY_TG_TOKEN="%s"\nSLOWQUERY_TG_CHAT_ID=%d\n' % (TOKEN, ME))
        env = {k: v for k, v in self.env.items() if k not in ("SLOWQUERY_TG_TOKEN", "SLOWQUERY_TG_CHAT_ID")}
        env["SLOWQUERY_ENV_FILE"] = path
        self.assertEqual(self.run_gate("notify", "из файла", env=env).returncode, 0)


if __name__ == "__main__":
    unittest.main()
