"""Functional tests: the hooks as Claude Code runs them, wired through .claude/settings.json.

Each hook is started with the exact ``command`` string from settings.json (via the shell,
with CLAUDE_PROJECT_DIR set) and fed real PreToolUse JSON payloads on stdin.
"""

import json
import os
import re
import subprocess
import unittest

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DIR = os.path.dirname(os.path.dirname(HOOKS_DIR))
SETTINGS = os.path.join(PROJECT_DIR, ".claude", "settings.json")


def load_settings():
    with open(SETTINGS, encoding="utf-8") as fh:
        return json.load(fh)


def hooks_for(tool_name):
    """Commands of every PreToolUse hook whose matcher selects ``tool_name``."""
    out = []
    for entry in load_settings()["hooks"]["PreToolUse"]:
        if re.fullmatch(entry["matcher"], tool_name):
            out.extend(h["command"] for h in entry["hooks"] if h["type"] == "command")
    return out


def payload(tool_name, tool_input):
    return {
        "session_id": "test-session",
        "transcript_path": "/tmp/transcript.jsonl",
        "cwd": PROJECT_DIR,
        "permission_mode": "default",
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": tool_input,
    }


def run_hook(command, stdin_text):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=PROJECT_DIR)
    return subprocess.run(command, shell=True, input=stdin_text, capture_output=True, text=True,
                          env=env, cwd=PROJECT_DIR, timeout=10)


def run_all(tool_name, tool_input):
    """Run every matching hook like Claude Code does; return the results."""
    stdin_text = json.dumps(payload(tool_name, tool_input))
    return [run_hook(cmd, stdin_text) for cmd in hooks_for(tool_name)]


class SettingsWiringTest(unittest.TestCase):
    def test_hook_scripts_exist(self):
        for entry in load_settings()["hooks"]["PreToolUse"]:
            for hook in entry["hooks"]:
                script = hook["command"].split('"')[1].replace("$CLAUDE_PROJECT_DIR", PROJECT_DIR)
                with self.subTest(script=script):
                    self.assertTrue(os.path.isfile(script))

    def test_matchers_cover_tools(self):
        for tool in ("Bash", "Read", "Edit", "Write", "MultiEdit", "NotebookEdit", "Grep"):
            with self.subTest(tool=tool):
                self.assertTrue(any("block_env.py" in c for c in hooks_for(tool)))
        self.assertTrue(any("block_host_tooling.py" in c for c in hooks_for("Bash")))
        self.assertFalse(any("block_host_tooling.py" in c for c in hooks_for("Read")))

    def test_deny_rules_cover_profiles_but_not_example(self):
        deny = load_settings()["permissions"]["deny"]
        # Edit rules cover every file-writing tool; Claude Code flags Write(...) rules as never matching.
        for tool in ("Read", "Edit"):
            for name in (".env", ".env.dev", ".env.paper", ".env.live"):
                with self.subTest(rule=f"{tool}({name})"):
                    self.assertIn(f"{tool}(**/{name})", deny)
            self.assertIn(f"{tool}(**/secrets/**)", deny)  # D-043 secret files
        self.assertFalse(any(rule.startswith("Write(") for rule in deny))
        self.assertFalse(any("example" in rule for rule in deny))
        self.assertFalse(any(rule.endswith(".env*)") for rule in deny), "a wildcard would also deny .env.example")


class HookProtocolTest(unittest.TestCase):
    def assertBlocked(self, results, text):
        self.assertTrue(any(r.returncode == 2 for r in results), results)
        self.assertTrue(any(text in r.stderr for r in results), [r.stderr for r in results])

    def assertAllowed(self, results):
        for r in results:
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_secret_file_reads_blocked(self):
        self.assertBlocked(run_all("Read", {"file_path": f"{PROJECT_DIR}/.env.dev"}), "secret guard")
        self.assertBlocked(run_all("Bash", {"command": "cat .env.dev", "description": "x"}), "secret guard")
        self.assertBlocked(run_all("Grep", {"pattern": "KEY", "glob": ".env*"}), "secret guard")
        self.assertBlocked(run_all("Read", {"file_path": f"{PROJECT_DIR}/secrets/db_password"}), "secret guard")
        self.assertBlocked(run_all("Bash", {"command": "docker compose exec api cat /run/secrets/x"}), "secret guard")

    def test_example_allowed(self):
        self.assertAllowed(run_all("Read", {"file_path": f"{PROJECT_DIR}/.env.example"}))
        self.assertAllowed(run_all("Bash", {"command": "cat .env.example"}))

    def test_host_install_blocked(self):
        self.assertBlocked(run_all("Bash", {"command": "pip install requests"}), "host-tooling guard")
        self.assertBlocked(run_all("Bash", {"command": 'bash -c "npm i"'}), "host-tooling guard")

    def test_make_and_docker_allowed(self):
        self.assertAllowed(run_all("Bash", {"command": "make test-unit"}))
        self.assertAllowed(run_all("Bash", {"command": "docker compose run --rm backend-dev uv sync"}))

    def test_fail_closed(self):
        for command in hooks_for("Bash"):
            for bad in ("not json", "[]", '{"tool_name": "Bash", "tool_input": "oops"}'):
                with self.subTest(command=command, stdin=bad):
                    result = run_hook(command, bad)
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("could not inspect", result.stderr)


if __name__ == "__main__":
    unittest.main()
