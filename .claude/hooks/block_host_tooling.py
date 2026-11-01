#!/usr/bin/env python3
"""Claude Code PreToolUse hook (Bash): nothing is installed or run on the host (D-038).

Every simple command a Bash call could run (after unwrapping ``sudo``, ``env``, ``xargs``,
``bash -c``, ``eval``, ``find -exec``, ``cmd.exe /c``, substitutions and heredocs; see
shellparse.py) is checked against:

* Python installers and envs (pip, uv, poetry, conda, venv, ...)
* Node installers and runners (npm, npx, pnpm, yarn, corepack, node, bun, ...)
* system package managers (apt, dpkg -i, snap, brew, winget, ...) and ``curl | sh`` installers
* project tools run directly (pytest, ruff, mypy, alembic, vite, playwright, ...)
* any ``python``/``python3``/``pypy``/``pydoc`` run, ``--version`` and ``-c`` one-liners included
  (``python -m <tool>`` gets that tool's hint)
* the other script interpreters (``perl``, ``ruby``, ``php``) and archive tools (``unzip``, ``zipinfo``)

Looking a program up (``which python3``) or naming it in an argument is fine.

Commands run through ``docker`` / ``docker compose`` or ``make`` are allowed with everything
inside them, because they execute in containers. Exit 2 blocks the call and shows stderr to
Claude. Any internal error also exits 2.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Optional

sys.dont_write_bytecode = True  # hooks run on the host; keep __pycache__ off the repo
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from shellparse import SHELLS, DECODERS, ParseError, SimpleCommand, normalize, parse, walk  # noqa: E402

CONTAINER_ENTRYPOINTS = frozenset({"docker", "docker-compose", "make"})
INTERPRETERS = SHELLS | {"python", "pypy", "node", "perl", "ruby", "php"}
DOWNLOADERS = frozenset({"curl", "wget"})
LOOKUPS = frozenset({"which", "command", "type", "whereis", "echo", "printf"})
PYTHONS = frozenset({"python", "pypy", "pydoc"})
HOST_INTERPRETERS = frozenset({"perl", "ruby", "php"})

HINT_PY_DEPS = ("manage Python deps inside the backend-dev container: `make py-add PKG=<name>[==<version>] [DEV=1]` "
                "or `make py-lock`; for anything else `make shell-backend` (then `uv ...`), "
                "or `docker compose -f compose.dev.yml run --rm backend-dev uv ...`")
HINT_NODE = ("run Node tooling inside the web-dev container: `make shell-web`, "
             "or `docker compose -f compose.dev.yml run --rm web-dev pnpm ...`")
HINT_SYSTEM = "add system packages to the image (infra/docker/*.Dockerfile) and rebuild it"
HINT_PY_RUN = ("run Python inside the backend-dev container: `make shell-backend`, or "
               "`docker compose -f compose.dev.yml run --rm backend-dev python ...`; for JSON use `gh --jq`")
HINT_INTERPRETER = ("run scripts inside a container (`make shell-backend`); for text edits use the "
                    "Edit tool, sed or awk")
HINT_ARCHIVE = ("inspect archives inside the backend-dev container: "
                "`docker compose -f compose.dev.yml run --rm backend-dev python -m zipfile -l <zip>`")

BLOCKED = {
    **{n: HINT_PY_DEPS for n in ("pip", "pipx", "uv", "uvx", "poetry", "conda", "mamba", "micromamba",
                                 "virtualenv", "pyenv", "pipenv", "pdm", "hatch")},
    **{n: HINT_NODE for n in ("npm", "npx", "pnpm", "pnpx", "yarn", "corepack", "nvm", "fnm", "volta",
                              "bun", "bunx", "node", "deno")},
    **{n: HINT_SYSTEM for n in ("apt", "apt-get", "aptitude", "snap", "brew", "winget", "choco", "scoop",
                                "yum", "dnf", "pacman", "apk", "flatpak")},
    "pytest": "use `make test-unit` / `make test-feature` / `make test`",
    "py.test": "use `make test-unit` / `make test`",
    "ruff": "use `make lint`",
    "black": "use `make lint`",
    "mypy": "use `make typecheck`",
    "tsc": "use `make typecheck`",
    "eslint": "use `make lint`",
    "prettier": "use `make lint`",
    "vitest": "use `make test-unit`",
    "playwright": "use `make test-e2e`",
    "alembic": "run alembic inside the backend-dev container (`make shell-backend`)",
    "uvicorn": "use `make up`",
    "vite": "use `make up` or `make shell-web`",
    "prefect": "use `make up` / `make shell-backend`",
    "mlflow": "use `make up` / `make shell-backend`",
    "pre-commit": "just `git commit`; the .githooks hook runs pre-commit inside backend-dev",
    "pip-audit": "use `make audit`",
    "unzip": HINT_ARCHIVE,
    "zipinfo": HINT_ARCHIVE,
}
SUBCOMMAND_INSTALLS = {"gem": {"install", "update"}, "cargo": {"install"}, "go": {"install", "get"}}

def block_message(tool: str, hint: str) -> str:
    return (f"BLOCKED by host-tooling guard (D-038): `{tool}` must not run on the host; nothing is "
            f"installed or run outside containers. Instead, {hint}.")


def _hint_for(name: str) -> Optional[str]:
    if name in BLOCKED:
        return BLOCKED[name]
    if name in PYTHONS:
        return HINT_PY_RUN
    if name in HOST_INTERPRETERS:
        return HINT_INTERPRETER
    return None


def _python_module(args: list) -> Optional[str]:
    """The module of ``python ... -m <module>``, if the command line has one before a script or ``-c``."""
    i = 0
    while i < len(args):
        a = args[i]
        if not a.startswith("-") or a == "-":
            return None
        if not a.startswith("--"):
            flags = a[1:]
            for k, f in enumerate(flags):
                if f == "c":
                    return None
                if f == "m":
                    return flags[k + 1:] or (args[i + 1] if i + 1 < len(args) else None)
                if f in "WXQ":
                    i += 0 if flags[k + 1:] else 1
                    break
        i += 1
    return None


def _check_python(cmd: SimpleCommand) -> str:
    mod = _python_module(cmd.argv[1:])
    if mod is None:
        return block_message(" ".join(cmd.argv[:2]), HINT_PY_RUN)
    hint = HINT_PY_DEPS if mod in ("pip", "venv", "ensurepip", "virtualenv") else BLOCKED.get(mod, HINT_PY_RUN)
    return block_message(f"python -m {mod}", hint)


def _check_command(cmd: SimpleCommand) -> Optional[str]:
    name = cmd.name
    if not name or name in CONTAINER_ENTRYPOINTS:
        return None
    if cmd.opaque:
        return block_message(name, "run commands in plain text so they can be checked; encoded or "
                                   "decoded scripts cannot be inspected")
    first = cmd.argv[0]
    if first.startswith(("$(", "`")):
        for inner in walk(cmd.nested):
            if inner.name in DOWNLOADERS or inner.name in DECODERS:
                return block_message(f"{first}", "don't execute downloaded or decoded commands")
            candidates = inner.argv[1:] if inner.name in LOOKUPS else inner.argv[:1]
            for c in candidates:
                hint = _hint_for(normalize(c))
                if hint:
                    return block_message(normalize(c), hint)
        return None
    if name in BLOCKED:
        return block_message(name, BLOCKED[name])
    if name in SUBCOMMAND_INSTALLS and len(cmd.argv) > 1 and cmd.argv[1] in SUBCOMMAND_INSTALLS[name]:
        return block_message(f"{name} {cmd.argv[1]}", HINT_SYSTEM)
    if name == "dpkg" and any(a in ("-i", "--install", "--unpack") for a in cmd.argv[1:]):
        return block_message("dpkg -i", HINT_SYSTEM)
    if name in INTERPRETERS:
        src = cmd.piped_from
        if src is not None and src.name in DOWNLOADERS:
            return block_message(f"{src.name} | {name}", HINT_SYSTEM)
        if any(n.name in DOWNLOADERS for n in walk(cmd.nested)):
            return block_message(f"{name} running a downloaded script", HINT_SYSTEM)
    if name in PYTHONS:
        return _check_python(cmd)
    if name in HOST_INTERPRETERS:
        return block_message(name, HINT_INTERPRETER)
    return None


def check_bash(command: str) -> Optional[str]:
    try:
        commands = parse(command)
    except ParseError as exc:
        return (f"BLOCKED by host-tooling guard (D-038): the command could not be inspected ({exc}). "
                f"Simplify it or run it through `make` / `docker compose`.")
    for cmd in walk(commands):
        # Whatever docker/make runs is inside a container; skip it, but still check host-side
        # substitutions in its words (they are in cmd.nested and visited by walk).
        if cmd.name in CONTAINER_ENTRYPOINTS:
            continue
        reason = _check_command(cmd)
        if reason:
            return reason
    return None


def check_payload(payload: dict) -> Optional[str]:
    if payload.get("tool_name") != "Bash":
        return None
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        raise ValueError("tool_input is not an object")
    return check_bash(str(tool_input.get("command", "")))


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("payload is not an object")
        reason = check_payload(payload)
    except Exception as exc:  # fail closed: any other exit code would let the tool run
        print(f"BLOCKED by host-tooling guard: could not inspect the tool call ({type(exc).__name__}: {exc}).",
              file=sys.stderr)
        return 2
    if reason:
        print(reason, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
