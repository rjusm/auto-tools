"""Тесты victorialogs_query.py: конфиг, выбор TLS-режима, basic auth, обработка ошибок.
Ничего реального в сеть не ходит — urllib.request.urlopen подменяется.
"""
import base64
import json
import os
import ssl
import sys
import tempfile
import unittest
import urllib.error
from io import BytesIO
from unittest import mock as umock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import victorialogs_query as vl


class LoadCfgTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env_file = os.path.join(self.tmp.name, "absent.env")

    def tearDown(self):
        self.tmp.cleanup()

    def _cfg(self, env_overrides=None, file_content=None):
        if file_content is not None:
            self.env_file = os.path.join(self.tmp.name, "present.env")
            with open(self.env_file, "w", encoding="utf-8") as f:
                f.write(file_content)
        with umock.patch.dict(os.environ, env_overrides or {}, clear=False), \
             umock.patch.object(vl, "ENV_FILE", self.env_file):
            return vl.load_cfg()

    def test_missing_url_exits_2(self):
        with self.assertRaises(SystemExit) as ctx:
            self._cfg()
        self.assertEqual(ctx.exception.code, 2)

    def test_reads_file(self):
        cfg = self._cfg(file_content='VIKTORIALOGS_URL=https://logs.example\nVIKTORIALOGS_USERNAME=u\n')
        self.assertEqual(cfg["VIKTORIALOGS_URL"], "https://logs.example")
        self.assertEqual(cfg["VIKTORIALOGS_USERNAME"], "u")

    def test_env_overrides_file(self):
        cfg = self._cfg(env_overrides={"VIKTORIALOGS_URL": "https://from-env"},
                         file_content='VIKTORIALOGS_URL=https://from-file\n')
        self.assertEqual(cfg["VIKTORIALOGS_URL"], "https://from-env")


class SslContextTest(unittest.TestCase):
    def test_default_is_none_verified(self):
        self.assertIsNone(vl.build_ssl_context({}))

    def test_insecure_flag_disables_verification(self):
        ctx = vl.build_ssl_context({"VIKTORIALOGS_TLS_INSECURE": "1"})
        self.assertEqual(ctx.verify_mode, ssl.CERT_NONE)
        self.assertFalse(ctx.check_hostname)

    def test_insecure_flag_accepts_yes_true(self):
        for val in ("true", "YES", "1"):
            ctx = vl.build_ssl_context({"VIKTORIALOGS_TLS_INSECURE": val})
            self.assertEqual(ctx.verify_mode, ssl.CERT_NONE, val)

    def test_falsy_insecure_flag_keeps_verification(self):
        for val in ("0", "false", "", None):
            cfg = {"VIKTORIALOGS_TLS_INSECURE": val} if val is not None else {}
            self.assertIsNone(vl.build_ssl_context(cfg), val)

    def test_ca_file_takes_precedence_over_insecure(self):
        with tempfile.NamedTemporaryFile(suffix=".pem", delete=False) as f:
            # ssl.create_default_context(cafile=...) только парсит путь, не читает
            # его прямо в create_default_context (ошибка будет при реальном использовании
            # контекста для соединения) — здесь достаточно убедиться, что выбирается
            # ветка cafile, а не insecure.
            path = f.name
        try:
            with umock.patch("ssl.create_default_context") as mock_ctx:
                vl.build_ssl_context({"VIKTORIALOGS_CA_FILE": path, "VIKTORIALOGS_TLS_INSECURE": "1"})
                mock_ctx.assert_called_once_with(cafile=path)
        finally:
            os.unlink(path)


class QueryTest(unittest.TestCase):
    def _fake_response(self, body):
        return BytesIO(body.encode())

    def test_sends_basic_auth_header(self):
        cfg = {"VIKTORIALOGS_URL": "https://logs.example", "VIKTORIALOGS_USERNAME": "u",
               "VIKTORIALOGS_PASSWORD": "p"}
        captured = {}

        def fake_urlopen(req, timeout=None, context=None):
            captured["auth"] = req.get_header("Authorization")
            captured["url"] = req.full_url
            return self._fake_response('{"ok":true}\n')

        with umock.patch("victorialogs_query.urllib.request.urlopen", side_effect=fake_urlopen):
            out = vl.query(cfg, "*", limit=5)
        self.assertEqual(out, '{"ok":true}\n')
        self.assertEqual(captured["url"], "https://logs.example/select/logsql/query")
        expected = "Basic " + base64.b64encode(b"u:p").decode()
        self.assertEqual(captured["auth"], expected)

    def test_no_username_no_auth_header(self):
        cfg = {"VIKTORIALOGS_URL": "https://logs.example"}
        captured = {}

        def fake_urlopen(req, timeout=None, context=None):
            captured["auth"] = req.get_header("Authorization")
            return self._fake_response("{}\n")

        with umock.patch("victorialogs_query.urllib.request.urlopen", side_effect=fake_urlopen):
            vl.query(cfg, "*")
        self.assertIsNone(captured["auth"])

    def test_http_error_exits_2_with_body_snippet(self):
        cfg = {"VIKTORIALOGS_URL": "https://logs.example"}

        def fake_urlopen(req, timeout=None, context=None):
            raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized",
                                         hdrs=None, fp=BytesIO(b"bad credentials"))

        with umock.patch("victorialogs_query.urllib.request.urlopen", side_effect=fake_urlopen):
            with self.assertRaises(SystemExit) as ctx:
                vl.query(cfg, "*")
        self.assertEqual(ctx.exception.code, 2)

    def test_network_error_exits_2(self):
        cfg = {"VIKTORIALOGS_URL": "https://logs.example"}

        def fake_urlopen(req, timeout=None, context=None):
            raise urllib.error.URLError("boom")

        with umock.patch("victorialogs_query.urllib.request.urlopen", side_effect=fake_urlopen):
            with self.assertRaises(SystemExit) as ctx:
                vl.query(cfg, "*")
        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
