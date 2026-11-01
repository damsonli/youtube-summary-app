#!/usr/bin/env python3
"""Claude Code PreToolUse hook: keep secrets away from Claude (D-029, D-043).

Secrets are env profiles (``.env`` / ``.env.<profile>``, except the committed ``.env.example``)
and secret files: anything under a ``secrets/`` directory (repo ``secrets/``, containers'
``/run/secrets``). Blocks any tool call that would read, copy, edit or dump them:

* file tools (Read, Edit, Write, MultiEdit, NotebookEdit) by path, and Grep by path / glob
* Bash commands that name such a file (also via globs, quote splitting, substitutions,
  heredocs, ``bash -c``...), dump the environment (``printenv``, bare ``env``/``export``/``set``,
  ``/proc/*/environ``), print interpolated compose env (``docker compose config``,
  ``docker inspect``) or search recursively without excluding ``.env*`` and ``secrets/``

Exit 2 blocks the call and shows stderr to Claude. Any internal error also exits 2.

Known limits: this is a guardrail against accidental access, not a sandbox. Obfuscated
names (``printf '\\x2eenv'``), indirect readers (``find -exec cat``, ``tar .``), a bare
``secrets`` word (``cp -r secrets /tmp``) and globs whose first segment is just ``*``
(``cat */db_password``) are not caught. The settings.json deny rules and the
container-only workflow are the second layer.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import sys
from typing import Iterable, List, Optional

sys.dont_write_bytecode = True  # hooks run on the host; keep __pycache__ off the repo
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from shellparse import SHELLS, ParseError, SimpleCommand, normalize, parse, walk  # noqa: E402

ALLOWED = ".env.example"
# Names a glob is tested against; any match other than the example means "could expand to a secret".
CANDIDATES = (".env", ".env.dev", ".env.paper", ".env.live", ".env.test", ".env.local", ".env.prod")
FILE_TOOLS = {"Read": "file_path", "Edit": "file_path", "Write": "file_path", "MultiEdit": "file_path",
              "NotebookEdit": "notebook_path"}
EXCLUDE_AWARE = frozenset({"grep", "egrep", "fgrep", "rg", "tar", "rsync"})

_REF_RE = re.compile(r"(?<![\w.-])\.env(?:\.[\w.-]+)?(?![\w-])")
_GLOB_CHARS = re.compile(r"[*?\[]")
_PROC_ENVIRON_RE = re.compile(r"/proc/[^/\s]+/environ")
_EXCLUDE_RE = re.compile(r"""--exclude(?:-dir)?[= ]\S+|(?:-g|--i?glob)[= ]['"]?!\S+""")
_COMPOSE_VALUE_OPTS = {"-f", "--file", "-p", "--project-name", "--profile", "--env-file",
                       "--project-directory", "--ansi", "--parallel", "--progress"}

SECRETS_DIR = "secrets"
# `secrets/x`, `./secrets/`, `/run/secrets`, `C:\repo\secrets\x`; not `secrets.py`, `import secrets`, `init-secrets`.
_SECRETS_DIR_RE = re.compile(r"(?:^|[\s/\\'\"=:;|&(<>`])secrets[/\\]|/secrets(?![\w.-])")

ADVICE = ("Env profiles other than .env.example, and files under secrets/ or /run/secrets, hold secrets "
          "and must not be read, copied, edited or dumped by Claude. Use .env.example for key names, "
          "or ask the user to check the value.")


def block_message(what: str) -> str:
    return f"BLOCKED by secret guard (D-029, D-043): {what}. {ADVICE}"


# ----------------------------------------------------------------------- matching

def secret_refs(text: str) -> List[str]:
    """``.env`` / ``.env.<x>`` names mentioned in ``text``, other than ``.env.example``."""
    found = []
    for m in _REF_RE.finditer(text):
        name = m.group(0).rstrip(".")
        if name != ALLOWED:
            found.append(name)
    return found


def secret_dir_ref(text: str) -> Optional[str]:
    """A ``secrets/`` or ``/run/secrets`` reference in ``text``, if any."""
    m = _SECRETS_DIR_RE.search(text)
    return m.group(0).strip(" \t\n'\"=:;|&(<>`") if m else None


def is_secret_path(path: str) -> bool:
    parts = re.split(r"[/\\]", path.rstrip("/\\"))
    if SECRETS_DIR in parts and (len(parts) > 1 or path.endswith(("/", "\\"))):
        return True  # inside a secrets/ dir, or the dir itself as a path (`secrets/`, `./secrets`, `/run/secrets`)
    base = parts[-1]
    return bool(re.fullmatch(r"\.env(\..*)?", base)) and base.rstrip(".") != ALLOWED


def _brace_expand(pattern: str) -> List[str]:
    m = re.search(r"\{([^{}]*,[^{}]*)\}", pattern)
    if not m:
        return [pattern]
    out: List[str] = []
    for alt in m.group(1).split(","):
        out.extend(_brace_expand(pattern[:m.start()] + alt + pattern[m.end():]))
    return out


def glob_could_match_secret(pattern: str) -> bool:
    """True if a shell glob could expand to a secret env file (dotfiles need a literal leading dot) or into a
    ``secrets/`` dir (``secr*/x``). A segment of wildcards only (``*``) is let through, see Known limits."""
    for alt in _brace_expand(pattern):
        segments = re.split(r"[/\\]", alt)
        for seg in segments:
            if (_GLOB_CHARS.search(seg) and _GLOB_CHARS.sub("", seg)
                    and fnmatch.fnmatchcase(SECRETS_DIR, seg)):
                return True
        base = segments[-1]
        if not base.startswith(".") or not _GLOB_CHARS.search(base):
            continue
        if any(fnmatch.fnmatchcase(c, base) for c in CANDIDATES):
            return True
    return False


def _word_parts(word: str) -> Iterable[str]:
    for alt in _brace_expand(word):
        yield alt
        yield from re.split(r"[=:,]", alt)


def _strip_exclusions(text: str) -> str:
    """Drop ``--exclude=.env*`` / ``-g '!.env*'`` style arguments: naming a file to skip it is fine."""
    return _EXCLUDE_RE.sub(" ", text)


def _is_exclusion(cmd: SimpleCommand, i: int) -> bool:
    """Is word ``i`` an exclude pattern of a search/copy tool (``grep --exclude='.env*'``)?"""
    if cmd.name not in EXCLUDE_AWARE:
        return False
    w = cmd.words[i]
    if w.startswith(("--exclude=", "--exclude-dir=", "--glob=!", "--iglob=!")):
        return True
    prev = cmd.words[i - 1] if i > 0 else ""
    return prev in ("--exclude", "--exclude-dir") or (prev in ("-g", "--glob", "--iglob") and w.startswith("!"))


# --------------------------------------------------------------------- bash rules

def _env_dump(cmd: SimpleCommand) -> Optional[str]:
    name, args = cmd.name, cmd.argv[1:]
    if name == "printenv":
        return "`printenv` dumps the environment, which may hold loaded secrets"
    if name == "env" and not any(not a.startswith("-") for a in args):
        return "bare `env` dumps the environment, which may hold loaded secrets"
    if name == "export" and (not args or "-p" in args):
        return "`export -p` dumps the environment, which may hold loaded secrets"
    if name == "set" and not args:
        return "bare `set` dumps all shell variables, which may hold loaded secrets"
    if name in ("declare", "typeset") and (not args or any(a.startswith("-") and ("p" in a or "x" in a) for a in args)):
        return f"`{name} -p/-x` dumps shell variables, which may hold loaded secrets"
    return None


def _docker_rule(cmd: SimpleCommand) -> Optional[str]:
    name, args = cmd.name, cmd.argv[1:]
    if name not in ("docker", "docker-compose"):
        return None
    if name == "docker-compose":
        args = ["compose"] + args
    positionals = _positionals(args)
    # `docker manifest inspect` only reads registry metadata; every other `* inspect` can show env
    if positionals[:1] == ["inspect"] or (len(positionals) > 1 and positionals[1] == "inspect"
                                           and positionals[0] != "manifest"):
        return "`docker inspect` prints container environment variables"
    if positionals[:1] == ["compose"]:
        sub = _positionals(args[args.index("compose") + 1:], _COMPOSE_VALUE_OPTS)
        if sub[:1] == ["config"]:
            return "`docker compose config` prints values interpolated from env files"
    if "printenv" in (normalize(a) for a in args) or (args and normalize(args[-1]) == "env"):
        return "dumping a container's environment exposes secrets loaded from env files"
    return None


def _positionals(args: List[str], value_opts: Iterable[str] = ()) -> List[str]:
    out, skip = [], False
    for a in args:
        if skip:
            skip = False
            continue
        if a.startswith("-"):
            skip = a in value_opts
            continue
        out.append(a)
    return out


def _recursive_search(cmd: SimpleCommand) -> Optional[str]:
    name, args = cmd.name, cmd.argv[1:]
    if name in ("grep", "egrep", "fgrep"):
        recursive = any(a in ("--recursive", "--dereference-recursive") or a == "-d" or
                        (a.startswith("-") and not a.startswith("--") and ("r" in a or "R" in a)) for a in args)
        if not recursive:
            return None
        def values(opt: str) -> List[str]:
            out = [a.split("=", 1)[1] for a in args if a.startswith(opt + "=")]
            return [p.strip("'\"") for p in out + [args[i + 1] for i, a in enumerate(args[:-1]) if a == opt]]

        def matches(name: str, patterns: List[str]) -> bool:
            return any(fnmatch.fnmatchcase(name, p) for p in patterns)

        includes = values("--include")
        if includes and not matches(".env.dev", includes) and not matches("db_password", includes):
            return None  # only named file types are searched (`--include='*.py'`); secret files have none
        if not matches(".env.dev", values("--exclude")):
            return ("recursive grep would read .env files; add --exclude='.env*' --exclude-dir=secrets "
                    "or use rg (it respects .gitignore)")
        if not matches(SECRETS_DIR, values("--exclude-dir")):
            return "recursive grep would read secrets/; add --exclude-dir=secrets or use rg (it respects .gitignore)"
        return None
    if name == "rg":
        joined = " ".join(args)
        no_ignore = "--no-ignore" in joined or bool(re.search(r"(^|\s)-[a-zA-Z]*u", joined))
        hidden = "--hidden" in joined or "-." in args or bool(re.search(r"(^|\s)-[a-zA-Z]*u[a-zA-Z]*u", joined))
        if no_ignore and hidden:
            return "rg with --no-ignore and --hidden would read gitignored .env files"
    return None


def _embedded_shell_strings(cmd: SimpleCommand) -> List[str]:
    """``sh -c '...'`` programs passed to a container (``docker compose run svc bash -c ...``)."""
    out = []
    args = cmd.argv
    for i, a in enumerate(args):
        if normalize(a) in SHELLS:
            for j in range(i + 1, len(args) - 1):
                if args[j].startswith("-") and "c" in args[j][1:]:
                    out.append(args[j + 1])
                    break
    return out


def check_bash(command: str, depth: int = 0) -> Optional[str]:
    stripped = _strip_exclusions(command)
    refs = secret_refs(stripped)
    if refs:
        return block_message(f"the command references `{refs[0]}`")
    secret_dir = secret_dir_ref(stripped)
    if secret_dir:
        return block_message(f"the command references the secret files in `{secret_dir}`")
    if _PROC_ENVIRON_RE.search(command):
        return block_message("the command reads a process environment (/proc/*/environ)")
    try:
        commands = parse(command)
    except ParseError as exc:
        return block_message(f"the command could not be inspected ({exc}); simplify it")
    for cmd in walk(commands):
        if cmd.opaque:
            return block_message("the command runs encoded or decoded code that cannot be inspected")
        for i, word in enumerate(cmd.words + cmd.redirects):
            if i < len(cmd.words) and _is_exclusion(cmd, i):
                continue
            for part in _word_parts(word):
                if secret_refs(part) or is_secret_path(part):
                    return block_message(f"the command references `{part}`")
                if glob_could_match_secret(part):
                    return block_message(f"the glob `{part}` can expand to a secret file")
            if "dotglob" in word:
                return block_message("`dotglob` makes globs match .env files")
        for body in cmd.stdin:
            ref = (secret_refs(body) or [secret_dir_ref(body)])[0]
            if ref:
                return block_message(f"the heredoc references `{ref}`")
        for rule in (_env_dump, _docker_rule, _recursive_search):
            reason = rule(cmd)
            if reason:
                return block_message(reason)
        if cmd.name in ("docker", "docker-compose") and depth < 4:
            for inner in _embedded_shell_strings(cmd):
                reason = check_bash(inner, depth + 1)
                if reason:
                    return reason
    return None


# ------------------------------------------------------------------------- entry

def check_payload(payload: dict) -> Optional[str]:
    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        raise ValueError("tool_input is not an object")
    if tool == "Bash":
        return check_bash(str(tool_input.get("command", "")))
    if tool in FILE_TOOLS:
        path = str(tool_input.get(FILE_TOOLS[tool], ""))
        if is_secret_path(path):
            return block_message(f"{tool} on `{path}`")
        return None
    if tool == "Grep":
        path = str(tool_input.get("path") or "")
        glob = str(tool_input.get("glob") or "")
        if is_secret_path(path):
            return block_message(f"Grep on `{path}`")
        if glob and (secret_refs(glob) or secret_dir_ref(glob) or glob_could_match_secret(glob)):
            return block_message(f"Grep with glob `{glob}` would search secret files")
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("payload is not an object")
        reason = check_payload(payload)
    except Exception as exc:  # fail closed: any other exit code would let the tool run
        print(f"BLOCKED by secret guard: could not inspect the tool call ({type(exc).__name__}: {exc}).",
              file=sys.stderr)
        return 2
    if reason:
        print(reason, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
