#!/usr/bin/env python3
"""Мок git для dry-run: чтение — настоящий git, запись — только в журнал.

Использование: python mocks/git_mock.py <обычные аргументы git>
Журнал: mocks/.calls.jsonl (в .gitignore), путь можно сменить через MOCK_CALLS_LOG.
Ничего не меняет в репозитории: ни веток, ни коммитов, ни push, ни индекса.
"""
import json
import os
import subprocess
import sys
import time

READ_ONLY = {"status", "log", "diff", "show", "rev-parse", "ls-files", "blame", "grep",
             "describe", "remote", "config", "cat-file", "merge-base", "shortlog"}
LOG = os.environ.get("MOCK_CALLS_LOG") or os.path.join(os.path.dirname(os.path.abspath(__file__)), ".calls.jsonl")


def is_read_only(args):
    if not args:
        return True
    cmd, rest = args[0], args[1:]
    if cmd == "branch":  # `git branch` / --show-current / --list — чтение; `git branch NAME` — запись
        return all(a.startswith("-") and a in ("--show-current", "--list", "-a", "-r", "-v", "-vv") for a in rest)
    if cmd == "remote":
        return not any(a in ("add", "remove", "rm", "set-url", "rename") for a in rest)
    if cmd == "config":
        return any(a in ("--get", "--list", "-l", "--get-all") for a in rest)
    return cmd in READ_ONLY


def main():
    args = sys.argv[1:]
    if is_read_only(args):
        sys.exit(subprocess.call(["git", *args]))
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.time(), "tool": "git", "args": args}, ensure_ascii=False) + "\n")
    print("[git-mock] НЕ выполнено (dry-run): git " + " ".join(args))


if __name__ == "__main__":
    main()
