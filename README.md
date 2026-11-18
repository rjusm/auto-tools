# auto-tools

Claude Code skills for this project.

- [`skills/slow-query-fix`](skills/slow-query-fix/SKILL.md) — slow SQL query from Grafana (MySQL process list) → find source in code → fix → reproduce at prod-like volume in local docker → MR.
- [`skills/incident-triage`](skills/incident-triage/SKILL.md) — anomaly/alert from monitoring (Grafana + Prometheus/VictoriaMetrics + Loki/VictoriaLogs via Grafana MCP) → correlate metrics/logs/alerts → root cause → (if it's a code bug) fix → MR → optional postmortem, saved to the user's Obsidian vault (`~/Documents/SecondBrain/04 Archive/Postmortems/`), not committed to this repo.
- [`skills/promql`](skills/promql/SKILL.md), [`skills/loki`](skills/loki/SKILL.md) — PromQL/LogQL query reference, vendored from [`grafana/skills`](https://github.com/grafana/skills) (Apache-2.0); used by `incident-triage` step 2 when building metric/log queries.
- [`tools/shared`](tools/shared) — shared infrastructure used by both skills: the Telegram notify/gate bot (`tg_gate.py`, rules in `tools/shared/TELEGRAM_GATE.md`) and dry-run git/Jira mocks (`tools/shared/mocks`) used by their test suites.
- [`.mcp.json`](.mcp.json) — Grafana MCP server config for `incident-triage` (read-only; needs `GRAFANA_URL`/`GRAFANA_SERVICE_ACCOUNT_TOKEN` in your environment).