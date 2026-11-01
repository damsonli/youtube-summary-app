"""Unit matrix for the secret guard (block_env.py)."""

import unittest

from block_env import check_payload, glob_could_match_secret, is_secret_path


def bash(command):
    return check_payload({"tool_name": "Bash", "tool_input": {"command": command}})


def tool(name, **tool_input):
    return check_payload({"tool_name": name, "tool_input": tool_input})


BASH_BLOCKED = [
    # direct references
    "cat .env",
    "cat .env.dev",
    "cat ./.env.live",
    'cat "backend/.env.paper"',
    "less /repo/web/.env.local",
    "source .env.dev",
    ". .env.dev",
    "set -a; . ./.env.live; set +a",
    "cp .env.dev /tmp/x",
    "cp .env.example .env.dev",
    "grep KEY .env.dev",
    "head -n1 .env.example.bak",
    "base64 < .env.dev",
    "docker compose --env-file .env.live up",
    "docker compose run --rm -e X --env-file=.env.dev api true",
    "echo ok && cat .env",
    "ls; cat .env.paper | head",
    # bypass attempts
    "cat .en''v.dev",
    'cat ".e"nv.live',
    "cat .\\env.dev",
    "cat .env*",
    "cat .e?v.dev",
    "cat ./.[e]nv.live",
    "cat .e{n,x}v.dev",
    "cat backend/.e*",
    "head .*",
    "bash -c 'cat .env.dev'",
    "sh -c \"$(echo cat) .env.live\"",
    "echo $(cat .env.dev)",
    "f=.env; cat ${f}.dev",
    "shopt -s dotglob; cat *",
    "bash <<EOF\ncat .env.dev\nEOF",
    "echo Y2F0IC5lbnY= | base64 -d | sh",
    "cat -- --exclude .env.dev",
    "cat --exclude=.env.dev",
    "docker compose run --rm backend-dev bash -c 'cat /app/.env.dev'",
    # environment dumps
    "printenv",
    "printenv ALPACA_SECRET",
    "env",
    "env -0",
    "export -p",
    "export",
    "set",
    "declare -px",
    "cat /proc/self/environ",
    "xargs -0 -L1 < /proc/1/environ",
    "docker compose config",
    "docker-compose -f compose.yml config",
    "docker compose -f compose.dev.yml --profile x config --services",
    "docker inspect star-api-1",
    "docker container inspect api",
    "docker image inspect python:3.12-slim",
    "docker compose exec api printenv",
    "docker compose exec api env",
    "docker compose run --rm api sh -c 'env'",
    # recursive search that would read .env files or secrets/
    "grep -r KEY .",
    "grep -Rn SECRET ./",
    "grep --recursive token",
    "grep -r --exclude='.env*' KEY .",
    "grep -r --exclude-dir=secrets KEY .",
    "rg --no-ignore --hidden KEY",
    "rg -uu KEY",
    # secret files (D-043): repo secrets/ and containers' /run/secrets
    "cat secrets/db_password",
    "cat ./secrets/redis_password",
    "less /repo/secrets/db_password",
    "cat C:\\repo\\secrets\\db_password",
    "ls secrets/",
    "ls -la ./secrets",
    "cp -r /repo/secrets /tmp",
    "base64 < secrets/db_password",
    "cat secr*/db_password",
    "cat secret?/x",
    "cat s{ecrets,x}/db_password",
    "cat sec''rets/db_password",
    "docker compose exec api cat /run/secrets/star_db_password",
    "docker compose exec -T postgres sh -c 'cat /run/secrets/star_db_password'",
    "docker compose exec api ls /run/secrets",
    "bash <<EOF\ncat secrets/db_password\nEOF",
    "echo $(cat secrets/db_password)",
]

BASH_ALLOWED = [
    "cat .env.example",
    "cp .env.example /tmp/example",
    "diff .env.example docs/x",
    "ls -la",
    "cat *",
    "cat README.md",
    "git status",
    "git commit -m 'add .env.example placeholders'",
    "git add .gitignore .env.example",
    "cat .envrc",
    "cat backend/src/star/core/env.py",
    "env FOO=1 make test-unit",
    "env -u FOO make test-unit",
    "export FOO=1",
    "set -euo pipefail",
    "declare -a arr",
    "grep -r --exclude='.env*' --exclude-dir=secrets KEY .",
    "grep -rn --include='*.py' KEY backend",
    "grep -r --exclude '.env*' --exclude-dir secrets KEY .",
    # secrets as a word, module or make target is fine; only the secrets/ directory is protected
    "make init-secrets",
    "python3 -c 'import secrets; print(secrets.token_hex(1))'",
    "cat backend/src/star/core/secrets.py",
    "git grep -n secrets Makefile",
    "git commit -m 'docs: secrets handling'",
    "ls *.py",
    "rg -g '!.env*' KEY",
    "tar --exclude='.env*' -czf /tmp/src.tgz backend",
    "grep KEY docs/decisions.md",
    "rg KEY",
    "rg --hidden KEY",
    "docker compose up -d",
    "docker compose -f compose.dev.yml run --rm backend-dev uv sync",
    "docker compose ps",
    "docker manifest inspect python:3.12-slim-bookworm",
    "docker compose run --rm api env FOO=1 python -V",
    "make test-unit",
    "echo hi > out.txt 2>&1",
    "python3 -c 'print(1)'",
]


class BashMatrixTest(unittest.TestCase):
    def test_blocked(self):
        for command in BASH_BLOCKED:
            with self.subTest(command=command):
                reason = bash(command)
                self.assertIsNotNone(reason, f"should block: {command}")
                self.assertIn("BLOCKED by secret guard", reason)

    def test_allowed(self):
        for command in BASH_ALLOWED:
            with self.subTest(command=command):
                self.assertIsNone(bash(command), f"should allow: {command}")

    def test_unparseable_command_fails_closed(self):
        self.assertIsNotNone(bash("echo 'unterminated"))


class FileToolMatrixTest(unittest.TestCase):
    def test_file_tools(self):
        blocked = [".env", ".env.dev", "/repo/.env.live", "C:\\repo\\backend\\.env.paper", "web/.env.local",
                   ".env.example.bak", ".env.", "secrets/db_password", "/repo/secrets/redis_password",
                   "C:\\repo\\secrets\\db_password", "/run/secrets/star_db_password", "./secrets"]
        allowed = [".env.example", "/repo/.env.example", "README.md", ".envrc", "backend/env.py", "",
                   "backend/src/star/core/secrets.py", "docs/secrets.md", "secrets"]
        for name in ("Read", "Edit", "Write", "MultiEdit"):
            for path in blocked:
                with self.subTest(tool=name, path=path):
                    self.assertIsNotNone(tool(name, file_path=path))
            for path in allowed:
                with self.subTest(tool=name, path=path):
                    self.assertIsNone(tool(name, file_path=path))
        self.assertIsNotNone(tool("NotebookEdit", notebook_path="/repo/.env.dev"))
        self.assertIsNone(tool("NotebookEdit", notebook_path="/repo/nb.ipynb"))

    def test_grep(self):
        self.assertIsNotNone(tool("Grep", pattern="KEY", path=".env.dev"))
        self.assertIsNotNone(tool("Grep", pattern="KEY", glob=".env*"))
        self.assertIsNotNone(tool("Grep", pattern="KEY", glob="**/.env.live"))
        self.assertIsNone(tool("Grep", pattern="KEY", path="docs"))
        self.assertIsNone(tool("Grep", pattern="KEY", glob="*.py"))
        self.assertIsNone(tool("Grep", pattern="KEY", path=".env.example"))
        self.assertIsNotNone(tool("Grep", pattern="KEY", path="secrets/"))
        self.assertIsNotNone(tool("Grep", pattern="KEY", path="/repo/secrets"))
        self.assertIsNotNone(tool("Grep", pattern="KEY", glob="secrets/*"))
        self.assertIsNotNone(tool("Grep", pattern="KEY", glob="secr*/**"))
        self.assertIsNone(tool("Grep", pattern="secrets", glob="*.md"))

    def test_other_tools_pass_through(self):
        self.assertIsNone(tool("Glob", pattern="**/.env*"))
        self.assertIsNone(tool("WebFetch", url="https://example.com/.env"))


class HelperTest(unittest.TestCase):
    def test_is_secret_path(self):
        self.assertTrue(is_secret_path(".env.dev/"))
        self.assertFalse(is_secret_path(".env.example"))

    def test_glob_needs_literal_leading_dot(self):
        self.assertFalse(glob_could_match_secret("*"))
        self.assertFalse(glob_could_match_secret("*.env"))
        self.assertTrue(glob_could_match_secret(".*"))
        self.assertFalse(glob_could_match_secret(".env.exam*"))

    def test_glob_into_secrets_dir(self):
        self.assertTrue(glob_could_match_secret("secr*/x"))
        self.assertTrue(glob_could_match_secret("/repo/s*s/db_password"))
        self.assertFalse(glob_could_match_secret("*/x"))  # wildcard-only segment: documented limit
        self.assertFalse(glob_could_match_secret("*.py"))


if __name__ == "__main__":
    unittest.main()
