#!/usr/bin/env python3
"""Запускает mcp-grafana (Docker, stdio) с конфигом из skills/incident-triage/.env.local.

Нужен, потому что .mcp.json сам по себе подставляет ${VAR} только из реального
окружения процесса, который запускает Claude Code — файл .env.local он не читает.
Этот скрипт читает файл (как tools/shared/tg_gate.py читает свой), кладёт значения
в окружение и запускает docker run с теми же флагами, что описаны в SKILL.md.

Формат .env.local (KEY=VALUE, в .gitignore):
    GRAFANA_URL=...
    GRAFANA_SERVICE_ACCOUNT_TOKEN=...      # или
    GRAFANA_USERNAME=...                   # + GRAFANA_PASSWORD (basic auth)
    GRAFANA_PASSWORD=...
    GRAFANA_ORG_ID=...                     # опционально

Переменные окружения, заданные в реальном shell, имеют приоритет над файлом
(та же логика, что в tg_gate.py).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.environ.get("GRAFANA_ENV_FILE") or os.path.join(HERE, ".env.local")

KNOWN_VARS = (
    "GRAFANA_URL",
    "GRAFANA_SERVICE_ACCOUNT_TOKEN",
    "GRAFANA_USERNAME",
    "GRAFANA_PASSWORD",
    "GRAFANA_ORG_ID",
)


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
    return cfg


def main():
    cfg = load_cfg()
    if not cfg.get("GRAFANA_URL"):
        sys.stderr.write(
            "run_mcp_grafana: не задан GRAFANA_URL (ни в %s, ни в окружении)\n" % ENV_FILE)
        sys.exit(2)
    has_token = bool(cfg.get("GRAFANA_SERVICE_ACCOUNT_TOKEN"))
    has_basic = bool(cfg.get("GRAFANA_USERNAME")) and bool(cfg.get("GRAFANA_PASSWORD"))
    if not has_token and not has_basic:
        sys.stderr.write(
            "run_mcp_grafana: нужен либо GRAFANA_SERVICE_ACCOUNT_TOKEN, "
            "либо пара GRAFANA_USERNAME+GRAFANA_PASSWORD\n")
        sys.exit(2)

    env = dict(os.environ)
    env.update(cfg)

    docker_args = ["docker", "run", "--rm", "-i"]
    for k in KNOWN_VARS:
        if cfg.get(k):
            docker_args += ["-e", k]
    docker_args += [
        "grafana/mcp-grafana",
        "-t", "stdio",
        "--disable-write",
        "--usage-stats=disabled",
    ]
    os.execvpe("docker", docker_args, env)


if __name__ == "__main__":
    main()
