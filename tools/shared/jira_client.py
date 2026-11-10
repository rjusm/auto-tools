#!/usr/bin/env python3
"""Реальный клиент Jira REST API (Server/Data Center, Personal Access Token).

Это НЕ то же самое, что mocks/jira_mock.py — тот всегда dry-run и ничего не
создаёт. Этот скрипт делает настоящий POST в Jira и создаёт настоящий тикет.
Используй его только когда пользователь явно попросил создать реальную задачу.

Конфиг — tools/shared/.env.local (тот же файл, что для Telegram-бота):
    JIRA_URL=https://jira.example.com      # без /rest/... в конце
    JIRA_PAT=...                           # Personal Access Token (Profile -> Personal Access Tokens)
    JIRA_TLS_INSECURE=1                    # (опционально) отключить проверку TLS для self-signed
    JIRA_CA_FILE=...                       # (опционально) путь к CA-сертификату

Использование:
    python3 -I jira_client.py create --project EOC --type Task \
        --summary "Коротко" --description "Подробности" [--labels a,b]

Печатает URL и ключ созданного тикета. Код выхода 2 при ошибке конфигурации/сети/API.
"""
import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.environ.get("JIRA_ENV_FILE") or os.path.join(HERE, ".env.local")

KNOWN_VARS = ("JIRA_URL", "JIRA_PAT", "JIRA_TLS_INSECURE", "JIRA_CA_FILE")


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
    if not cfg.get("JIRA_URL") or not cfg.get("JIRA_PAT"):
        sys.stderr.write(
            "jira_client: нужны JIRA_URL и JIRA_PAT (ни в %s, ни в окружении)\n" % ENV_FILE)
        sys.exit(2)
    return cfg


def build_ssl_context(cfg):
    if cfg.get("JIRA_CA_FILE"):
        return ssl.create_default_context(cafile=cfg["JIRA_CA_FILE"])
    if str(cfg.get("JIRA_TLS_INSECURE", "")).strip().lower() in ("1", "true", "yes"):
        sys.stderr.write(
            "jira_client: ВНИМАНИЕ — проверка TLS-сертификата отключена "
            "(JIRA_TLS_INSECURE=1), соединение уязвимо к MITM\n")
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    return None


def create_issue(cfg, project, issuetype, summary, description, labels=None, epic_key=None,
                  assignee=None, story_points=None, parent_key=None, timeout=20):
    url = cfg["JIRA_URL"].rstrip("/") + "/rest/api/2/issue"
    payload = {"fields": {
        "project": {"key": project},
        "issuetype": {"name": issuetype},
        "summary": summary,
        "description": description,
    }}
    if labels:
        payload["fields"]["labels"] = labels
    if epic_key:
        # Jira Server/DC: поле Epic Link обычно customfield_10107, но варьируется по инстансу.
        payload["fields"]["customfield_10107"] = epic_key
    if assignee:
        payload["fields"]["assignee"] = {"name": assignee}
    if story_points is not None:
        # Jira Server/DC: поле Story Points обычно customfield_10110, варьируется по инстансу.
        payload["fields"]["customfield_10110"] = story_points
    if parent_key:
        payload["fields"]["parent"] = {"key": parent_key}

    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer %s" % cfg["JIRA_PAT"]})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=build_ssl_context(cfg)) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        sys.stderr.write("jira_client: HTTP %d: %s\n" % (e.code, body[:1000]))
        sys.exit(2)
    except (urllib.error.URLError, OSError) as ex:
        sys.stderr.write("jira_client: ошибка запроса (%s)\n" % type(ex).__name__)
        sys.exit(2)


def add_comment(cfg, issue_key, body, timeout=20):
    url = cfg["JIRA_URL"].rstrip("/") + "/rest/api/2/issue/%s/comment" % issue_key
    req = urllib.request.Request(
        url, data=json.dumps({"body": body}).encode(), method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer %s" % cfg["JIRA_PAT"]})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=build_ssl_context(cfg)) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        sys.stderr.write("jira_client: HTTP %d: %s\n" % (e.code, body_text[:1000]))
        sys.exit(2)
    except (urllib.error.URLError, OSError) as ex:
        sys.stderr.write("jira_client: ошибка запроса (%s)\n" % type(ex).__name__)
        sys.exit(2)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("--project", required=True)
    c.add_argument("--type", required=True, dest="issuetype")
    c.add_argument("--summary", required=True)
    c.add_argument("--description", required=True)
    c.add_argument("--labels", help="через запятую")
    c.add_argument("--epic", help="ключ эпика для Epic Link, например EOC-11")
    c.add_argument("--assignee", help="username исполнителя, например usmonov.r@eskhata.com")
    c.add_argument("--story-points", type=float, dest="story_points")
    c.add_argument("--parent", help="ключ родительской задачи — для создания подзадачи")
    m = sub.add_parser("comment")
    m.add_argument("--issue", required=True)
    m.add_argument("--body", required=True)
    a = ap.parse_args()
    cfg = load_cfg()

    if a.cmd == "create":
        labels = [x.strip() for x in a.labels.split(",")] if a.labels else None
        res = create_issue(cfg, a.project, a.issuetype, a.summary, a.description, labels, a.epic,
                            a.assignee, a.story_points, a.parent)
        key = res.get("key")
        base = cfg["JIRA_URL"].rstrip("/")
        print("%s/browse/%s" % (base, key))

    if a.cmd == "comment":
        add_comment(cfg, a.issue, a.body)
        base = cfg["JIRA_URL"].rstrip("/")
        print("%s/browse/%s" % (base, a.issue))


if __name__ == "__main__":
    main()
