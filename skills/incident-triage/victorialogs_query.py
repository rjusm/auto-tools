#!/usr/bin/env python3
"""Прямой HTTP-клиент VictoriaLogs (LogsQL), в обход Grafana MCP.

Нужен, потому что VictoriaLogs в этом проекте не зарегистрирован как datasource
в Grafana (list_datasources его не показывает) — значит, инструмент Grafana MCP
query_loki_logs до него не достаёт. Конфиг — отдельные переменные в том же
skills/incident-triage/.env.local (как в tg_gate.py/run_mcp_grafana.py), basic auth
через HTTP-прокси перед VictoriaLogs:
    VIKTORIALOGS_URL=https://...
    VIKTORIALOGS_USERNAME=...
    VIKTORIALOGS_PASSWORD=...
    VIKTORIALOGS_CA_FILE=...           # (опционально) путь к CA-сертификату для верификации
    VIKTORIALOGS_TLS_INSECURE=1        # (опционально, только если нет CA) отключить проверку TLS —
                                        # для self-signed сертификата на внутреннем адресе; по
                                        # умолчанию выключено (проверка TLS включена), печатает
                                        # предупреждение в stderr при каждом использовании.

Использование:
    python3 -I victorialogs_query.py query '<LogsQL>' [--start ...] [--end ...] [--limit N]

API: POST {VIKTORIALOGS_URL}/select/logsql/query (см. docs.victoriametrics.com/victorialogs/querying/).
Ответ — построчный JSON (JSON lines), выводится как есть, по одной записи на строку.
"""
import argparse
import base64
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.environ.get("VIKTORIALOGS_ENV_FILE") or os.path.join(HERE, ".env.local")

KNOWN_VARS = ("VIKTORIALOGS_URL", "VIKTORIALOGS_USERNAME", "VIKTORIALOGS_PASSWORD",
              "VIKTORIALOGS_TLS_INSECURE", "VIKTORIALOGS_CA_FILE")


def load_cfg():
    cfg = {}
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    cfg[k.strip()] = v.strip().strip('"').strip("'")
    for k in KNOWN_VARS:
        if os.environ.get(k):
            cfg[k] = os.environ[k]
    if not cfg.get("VIKTORIALOGS_URL"):
        sys.stderr.write(
            "victorialogs_query: не задан VIKTORIALOGS_URL (ни в %s, ни в окружении)\n" % ENV_FILE)
        sys.exit(2)
    return cfg


def build_ssl_context(cfg):
    if cfg.get("VIKTORIALOGS_CA_FILE"):
        return ssl.create_default_context(cafile=cfg["VIKTORIALOGS_CA_FILE"])
    if str(cfg.get("VIKTORIALOGS_TLS_INSECURE", "")).strip().lower() in ("1", "true", "yes"):
        sys.stderr.write(
            "victorialogs_query: ВНИМАНИЕ — проверка TLS-сертификата отключена "
            "(VIKTORIALOGS_TLS_INSECURE=1), соединение уязвимо к MITM\n")
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    return None  # обычная проверка через системные CA


def query(cfg, logsql, start=None, end=None, limit=None, timeout=20):
    url = cfg["VIKTORIALOGS_URL"].rstrip("/") + "/select/logsql/query"
    params = {"query": logsql}
    if start:
        params["start"] = start
    if end:
        params["end"] = end
    if limit:
        params["limit"] = str(limit)
    data = urllib.parse.urlencode(params).encode()

    req = urllib.request.Request(url, data=data, method="POST")
    if cfg.get("VIKTORIALOGS_USERNAME"):
        token = base64.b64encode(
            ("%s:%s" % (cfg["VIKTORIALOGS_USERNAME"], cfg.get("VIKTORIALOGS_PASSWORD", ""))).encode()
        ).decode()
        req.add_header("Authorization", "Basic %s" % token)

    try:
        with urllib.request.urlopen(req, timeout=timeout, context=build_ssl_context(cfg)) as r:
            return r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        sys.stderr.write("victorialogs_query: HTTP %d: %s\n" % (e.code, body[:500]))
        sys.exit(2)
    except (urllib.error.URLError, OSError) as ex:
        sys.stderr.write("victorialogs_query: ошибка запроса (%s)\n" % type(ex).__name__)
        sys.exit(2)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("query")
    q.add_argument("logsql")
    q.add_argument("--start")
    q.add_argument("--end")
    q.add_argument("--limit", type=int)
    a = ap.parse_args()
    cfg = load_cfg()

    if a.cmd == "query":
        out = query(cfg, a.logsql, start=a.start, end=a.end, limit=a.limit)
        sys.stdout.write(out)


if __name__ == "__main__":
    main()
