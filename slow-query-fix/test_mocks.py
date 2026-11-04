"""Тесты моков git/Jira: убеждаемся, что запись не выполняется, а чтение работает."""
import json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
GIT, JIRA = (os.path.join(HERE, "mocks", n) for n in ("git_mock.py", "jira_mock.py"))


class MockTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.log = os.path.join(self.d.name, "calls.jsonl")
        self.env = dict(os.environ, MOCK_CALLS_LOG=self.log)
        subprocess.run(["git", "init", "-q", self.d.name], check=True)

    def tearDown(self):
        self.d.cleanup()

    def run_mock(self, script, *args):
        return subprocess.run([sys.executable, "-I", script, *args], env=self.env, cwd=self.d.name,
                              capture_output=True, text=True)

    def calls(self):
        return [json.loads(l) for l in open(self.log)] if os.path.exists(self.log) else []

    def test_git_read_passthrough(self):
        r = self.run_mock(GIT, "status", "--short")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.calls(), [])

    def test_git_writes_are_not_executed(self):
        for args in (["checkout", "-b", "x"], ["switch", "-c", "x"], ["add", "."], ["commit", "-m", "m"],
                     ["push", "origin", "x"], ["branch", "x"], ["reset", "--hard"], ["merge", "dev"]):
            self.assertIn("НЕ выполнено", self.run_mock(GIT, *args).stdout, args)
        self.assertEqual(len(self.calls()), 8)
        branches = subprocess.run(["git", "branch", "--list"], cwd=self.d.name, capture_output=True, text=True).stdout
        self.assertNotIn("x", branches)

    def test_jira_get_fixture_and_default(self):
        self.assertEqual(json.loads(self.run_mock(JIRA, "get", "EW-000").stdout)["key"], "EW-000")
        self.assertIn("[mock]", json.loads(self.run_mock(JIRA, "get", "ZZ-1").stdout)["summary"])
        self.assertEqual(self.calls(), [])

    def test_jira_writes_only_logged(self):
        self.run_mock(JIRA, "comment", "EW-000", "MR готов")
        self.run_mock(JIRA, "transition", "EW-000", "In Review")
        self.assertEqual([c["op"] for c in self.calls()], ["comment", "transition"])


if __name__ == "__main__":
    unittest.main()
