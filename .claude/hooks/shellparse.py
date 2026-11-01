"""Small POSIX-ish shell lexer shared by the Claude Code PreToolUse guards.

This is not a full shell parser. Its job is to find every simple command a Bash
command line could run, including ones hidden behind wrappers (``sudo``,
``env``, ``xargs``, ``bash -c``, ``eval``, ``find -exec``, ``cmd.exe /c``),
inside ``$(...)``, backticks and ``<(...)`` substitutions, and in heredocs or
echo pipelines fed to a shell. The guards then inspect each command.

Anything it cannot lex raises ``ParseError``; callers must fail closed.

Stdlib only, and compatible with the host ``python3`` (3.10), because Claude
Code runs the hooks on the host.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterator, List, Optional

MAX_DEPTH = 8

SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "mksh", "ash", "fish"})
# Programs whose output, piped into a shell, can't be inspected.
DECODERS = frozenset({"base64", "base32", "xxd", "openssl", "gzip", "gunzip", "zcat", "bzcat", "xzcat", "rev", "tr"})

_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\[[^\]]*\])?\+?=")
_VAR_WORD_RE = re.compile(r"^\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))$")
_REDIR_RE = re.compile(r"&>>|&>|<<<|<<-|<<|<>|>>|>&|<&|>\||>|<")
_CONTROL_OPS = ("&&", "||", ";;&", ";;", ";&", "|&", "&", "|", ";", "(", ")")
_KEYWORDS = frozenset({"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "for", "in",
                       "case", "esac", "select", "function", "!", "{", "}", "[[", "]]", "coproc"})


class ParseError(ValueError):
    """The command line could not be lexed; guards must treat this as blocked."""


@dataclass
class SimpleCommand:
    argv: List[str]
    """Arguments after leading assignments and wrappers (sudo, env, ...) are removed."""
    words: List[str]
    """Every word as written (quotes removed), including wrappers and assignments."""
    redirects: List[str] = field(default_factory=list)
    stdin: List[str] = field(default_factory=list)
    """Heredoc and herestring bodies fed to this command."""
    piped_from: Optional["SimpleCommand"] = None
    nested: List["SimpleCommand"] = field(default_factory=list)
    """Commands found in substitutions, ``-c`` strings, ``eval``, ``find -exec`` and so on."""
    wrappers: List[str] = field(default_factory=list)
    opaque: bool = False
    """True when the command runs code this lexer cannot inspect (encoded or decoded scripts)."""
    depth: int = 0

    @property
    def name(self) -> str:
        return normalize(self.argv[0]) if self.argv else ""


def normalize(word: str) -> str:
    """Reduce a command word to a comparable program name: basename, lower case, no Windows
    extension, no version suffix on python/pip (``/usr/bin/python3.10`` -> ``python``)."""
    base = re.split(r"[/\\]", word)[-1].lower()
    base = re.sub(r"\.(exe|cmd|bat|com|ps1)$", "", base)
    m = re.match(r"^(python|pip|pypy|pydoc)(\d+(\.\d+)*)?$", base)
    return m.group(1) if m else base


def walk(commands: List[SimpleCommand]) -> Iterator[SimpleCommand]:
    """Yield every command, depth first, including nested ones."""
    for cmd in commands:
        yield cmd
        yield from walk(cmd.nested)


def parse(cmdline: str, depth: int = 0) -> List[SimpleCommand]:
    if depth > MAX_DEPTH:
        raise ParseError("command nesting is too deep to inspect")
    raws = _group(_lex(cmdline))
    commands: List[SimpleCommand] = []
    variables: dict = {}
    prev: Optional[SimpleCommand] = None
    for raw in raws:
        cmd = _build(raw, depth, variables)
        if raw.piped:
            cmd.piped_from = prev
        commands.append(cmd)
        prev = cmd
    for cmd in commands:
        _expand(cmd)
    return commands


# --------------------------------------------------------------------------- lexer

@dataclass
class _Tok:
    kind: str  # word | op | redir | heredoc
    text: str
    nested: List[str] = field(default_factory=list)


def _lex(text: str) -> List[_Tok]:
    tokens: List[_Tok] = []
    pending_heredocs: List[tuple] = []  # (token index, delimiter, strip tabs, delimiter quoted)
    buf: List[str] = []
    nested: List[str] = []
    in_word = False
    quoted = False  # any part of the current word was quoted or escaped
    expect_delim: Optional[str] = None
    i, n = 0, len(text)

    def flush() -> None:
        nonlocal buf, nested, in_word, quoted, expect_delim
        if in_word:
            word = "".join(buf)
            if expect_delim is not None:
                tokens.append(_Tok("heredoc", ""))
                pending_heredocs.append((len(tokens) - 1, word, expect_delim == "<<-", quoted))
                expect_delim = None
            else:
                tokens.append(_Tok("word", word, nested))
        buf, nested, in_word, quoted = [], [], False, False

    while i < n:
        c = text[i]
        if c in " \t\r":
            flush()
            i += 1
        elif c == "\\":
            if text.startswith("\\\n", i):
                i += 2
            elif i + 1 < n:
                buf.append(text[i + 1])
                in_word = quoted = True
                i += 2
            else:
                i += 1
        elif c == "\n":
            flush()
            tokens.append(_Tok("op", "\n"))
            i += 1
            if pending_heredocs:
                i = _read_heredocs(text, i, pending_heredocs, tokens)
        elif c == "#" and not in_word:
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif c == "'":
            j = text.find("'", i + 1)
            if j < 0:
                raise ParseError("unterminated single quote")
            buf.append(text[i + 1:j])
            in_word = quoted = True
            i = j + 1
        elif c == '"':
            i = _lex_dquote(text, i + 1, buf, nested)
            in_word = quoted = True
        elif text.startswith("$(", i):
            inner, j = _balanced(text, i + 2)
            buf.append(text[i:j])
            nested.append(inner)
            in_word = True
            i = j
        elif text.startswith("${", i):
            j = _match_brace(text, i + 2)
            buf.append(text[i:j])
            in_word = True
            i = j
        elif c == "`":
            inner, j = _backtick(text, i + 1)
            buf.append(text[i:j])
            nested.append(inner)
            in_word = True
            i = j
        elif c in "<>" and text.startswith("(", i + 1) and not in_word:
            inner, j = _balanced(text, i + 2)
            tokens.append(_Tok("word", text[i:j], [inner]))
            i = j
        elif c in "<>" or text.startswith("&>", i):
            if in_word and "".join(buf).isdigit() and not nested:
                buf, in_word = [], False  # file descriptor number, e.g. 2>&1
            else:
                flush()
            m = _REDIR_RE.match(text, i)
            assert m is not None
            op = m.group(0)
            tokens.append(_Tok("redir", op))
            if op in ("<<", "<<-"):
                expect_delim = op
            i = m.end()
        elif c in ";|&()":
            flush()
            op = next(o for o in _CONTROL_OPS if text.startswith(o, i))
            tokens.append(_Tok("op", op))
            i += len(op)
        else:
            buf.append(c)
            in_word = True
            i += 1
    flush()
    if expect_delim is not None:
        raise ParseError("heredoc operator without a delimiter")
    return tokens


def _lex_dquote(text: str, i: int, buf: List[str], nested: List[str]) -> int:
    """Lex the inside of a double-quoted string starting at ``i``; return the index after the closing quote."""
    n = len(text)
    while i < n:
        c = text[i]
        if c == '"':
            return i + 1
        if c == "\\" and i + 1 < n and text[i + 1] in '$`"\\\n':
            if text[i + 1] != "\n":
                buf.append(text[i + 1])
            i += 2
        elif text.startswith("$(", i):
            inner, j = _balanced(text, i + 2)
            buf.append(text[i:j])
            nested.append(inner)
            i = j
        elif text.startswith("${", i):
            j = _match_brace(text, i + 2)
            buf.append(text[i:j])
            i = j
        elif c == "`":
            inner, j = _backtick(text, i + 1)
            buf.append(text[i:j])
            nested.append(inner)
            i = j
        else:
            buf.append(c)
            i += 1
    raise ParseError("unterminated double quote")


def _balanced(text: str, i: int) -> tuple:
    """Find the ``)`` that closes a ``(`` just before ``i``, skipping quotes. Return (inner, end)."""
    depth, start, n = 1, i, len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "'":
            j = text.find("'", i + 1)
            if j < 0:
                raise ParseError("unterminated single quote")
            i = j + 1
            continue
        if c == '"':
            i = _lex_dquote(text, i + 1, [], [])
            continue
        if c == "`":
            i = _backtick(text, i + 1)[1]
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return text[start:i], i + 1
        i += 1
    raise ParseError("unterminated $( or (")


def _match_brace(text: str, i: int) -> int:
    depth, n = 1, len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ParseError("unterminated ${")


def _backtick(text: str, i: int) -> tuple:
    out: List[str] = []
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n:
            out.append(text[i + 1])
            i += 2
        elif c == "`":
            return "".join(out), i + 1
        else:
            out.append(c)
            i += 1
    raise ParseError("unterminated backtick")


def _read_heredocs(text: str, i: int, pending: List[tuple], tokens: List[_Tok]) -> int:
    n = len(text)
    for idx, delim, strip_tabs, quoted in pending:
        lines: List[str] = []
        while i < n:
            j = text.find("\n", i)
            line = text[i:] if j < 0 else text[i:j]
            i = n if j < 0 else j + 1
            if (line.lstrip("\t") if strip_tabs else line) == delim:
                break
            lines.append(line)
        # A quoted delimiter (<<'EOF', <<"EOF", <<\EOF) makes bash take the body literally: nothing is expanded.
        tokens[idx] = _Tok("heredoc", "\n".join(lines), [] if quoted else _substitutions(lines))
    pending.clear()
    return i


def _substitutions(lines: List[str]) -> List[str]:
    """``$(...)`` and backtick commands inside a heredoc body (bash expands them)."""
    nested: List[str] = []
    try:
        _lex_dquote("\n".join(lines) + '"', 0, [], nested)
    except ParseError:
        pass
    return nested


# ------------------------------------------------------------------------- grouping

@dataclass
class _Raw:
    words: List[_Tok] = field(default_factory=list)
    redirects: List[_Tok] = field(default_factory=list)
    stdin: List[_Tok] = field(default_factory=list)
    piped: bool = False


def _group(tokens: List[_Tok]) -> List[_Raw]:
    raws: List[_Raw] = []
    cur = _Raw()
    redir: Optional[str] = None
    for tok in tokens:
        if tok.kind == "op":
            if redir is not None and redir not in ("<<", "<<-"):
                raise ParseError(f"redirection {redir!r} without a target")
            redir = None
            if cur.words or cur.redirects or cur.stdin:
                raws.append(cur)
            cur = _Raw(piped=tok.text in ("|", "|&"))
        elif tok.kind == "redir":
            redir = tok.text
        elif tok.kind == "heredoc":
            cur.stdin.append(tok)
            redir = None
        elif redir is not None:
            (cur.stdin if redir == "<<<" else cur.redirects).append(tok)
            redir = None
        else:
            cur.words.append(tok)
    if cur.words or cur.redirects or cur.stdin:
        raws.append(cur)
    return raws


# --------------------------------------------------------------------- unwrapping

# wrapper name -> (options that take a value, number of positional args before the command)
_WRAPPERS = {
    "sudo": ({"-u", "-g", "-h", "-p", "-C", "-U", "-r", "-t", "-T", "-D", "-R", "--user", "--group"}, 0),
    "doas": ({"-u", "-C"}, 0),
    "nohup": (set(), 0),
    "builtin": (set(), 0),
    "exec": ({"-a"}, 0),
    "time": ({"-f", "-o"}, 0),
    "nice": ({"-n", "--adjustment"}, 0),
    "ionice": ({"-c", "-n", "-p", "-P", "-u"}, 0),
    "chrt": (set(), 1),
    "taskset": (set(), 1),
    "stdbuf": ({"-i", "-o", "-e"}, 0),
    "timeout": ({"-s", "-k", "--signal", "--kill-after"}, 1),
    "setsid": (set(), 0),
    "unbuffer": (set(), 0),
    "noglob": (set(), 0),
    "nocorrect": (set(), 0),
    "watch": ({"-n", "-d", "--interval", "--differences"}, 0),
    "xargs": ({"-a", "-d", "-E", "-I", "-L", "-n", "-P", "-s", "--arg-file",
               "--delimiter", "--eof", "--replace", "--max-lines", "--max-args", "--max-procs",
               "--max-chars", "--process-slot-var"}, 0),
    "env": ({"-u", "-C", "-S", "--unset", "--chdir", "--split-string"}, 0),
    "command": (set(), 0),
}


def _peel(argv: List[str], wrappers: List[str], extra: List[str]) -> List[str]:
    """Strip assignments, keywords and wrapper programs from the front of ``argv``."""
    while argv:
        if _ASSIGN_RE.match(argv[0]) or argv[0] in _KEYWORDS:
            argv = argv[1:]
            continue
        name = normalize(argv[0])
        spec = _WRAPPERS.get(name)
        if spec is None:
            return argv
        if name == "command" and len(argv) > 1 and argv[1] in ("-v", "-V"):
            return argv  # a lookup, not an execution
        takes_value, positionals = spec
        i = 1
        while i < len(argv):
            a = argv[i]
            if a == "--":
                i += 1
                break
            if name == "env" and _ASSIGN_RE.match(a):
                i += 1
                continue
            if a.startswith("-") and len(a) > 1:
                opt = a.split("=", 1)[0]
                flag = opt if opt.startswith("--") else "-" + opt[-1]
                needs_value = "=" not in a and (opt in takes_value or flag in takes_value)
                if name == "env" and (a.startswith("-S") or opt == "--split-string"):
                    if "=" in a:
                        extra.append(a.split("=", 1)[1])
                    elif len(a) > 2 and not a.startswith("--"):
                        extra.append(a[2:])
                    elif i + 1 < len(argv):
                        extra.append(argv[i + 1])
                i += 2 if needs_value else 1
                continue
            break
        i += positionals
        rest = argv[i:]
        if name == "env":
            while rest and _ASSIGN_RE.match(rest[0]):
                rest = rest[1:]
        if not rest:
            if name == "xargs":
                rest = ["echo"]
            else:
                return argv  # wrapper with nothing to run (e.g. bare `env`) is the command itself
        wrappers.append(name)
        argv = rest
    return argv


def _build(raw: _Raw, depth: int, variables: dict) -> SimpleCommand:
    words = [t.text for t in raw.words]
    argv = list(words)
    # Leading assignments; a command made only of assignments defines variables for later words.
    lead = 0
    while lead < len(argv) and _ASSIGN_RE.match(argv[lead]):
        lead += 1
    if lead == len(argv) or (argv and argv[0] in ("export", "declare", "typeset", "readonly", "local")):
        for w in argv:
            if _ASSIGN_RE.match(w):
                key, _, value = w.partition("=")
                variables[key.rstrip("+")] = value
    argv = argv[lead:]
    if argv:
        m = _VAR_WORD_RE.match(argv[0])
        if m and (m.group(1) or m.group(2)) in variables:
            argv = variables[m.group(1) or m.group(2)].split() + argv[1:]

    wrappers: List[str] = []
    extra: List[str] = []
    argv = _peel(argv, wrappers, extra)
    cmd = SimpleCommand(
        argv=argv,
        words=words,
        redirects=[t.text for t in raw.redirects],
        stdin=[t.text for t in raw.stdin],
        wrappers=wrappers,
        depth=depth,
    )
    for tok in raw.words + raw.redirects + raw.stdin:
        for inner in tok.nested:
            cmd.nested.extend(parse(inner, depth + 1))
    for s in extra:
        cmd.nested.extend(parse(s, depth + 1))
    return cmd


def _expand(cmd: SimpleCommand) -> None:
    """Add the commands a program will itself execute (``bash -c``, ``eval``, ``find -exec``...)."""
    name, args, d = cmd.name, cmd.argv[1:], cmd.depth + 1
    strings: List[str] = []

    if name in SHELLS:
        script = _shell_command_string(args)
        if script is not None:
            strings.append(script)
        elif not any(not a.startswith(("-", "+")) for a in args):
            # The shell reads its program from stdin.
            strings.extend(cmd.stdin)
            src = cmd.piped_from
            if src is not None:
                if src.name in ("echo", "printf"):
                    strings.append(" ".join(src.argv[1:]).replace("\\n", "\n"))
                elif src.name in DECODERS or src.opaque:
                    cmd.opaque = True
    elif name == "eval":
        strings.append(" ".join(args))
    elif name in ("su", "runuser", "script"):
        for i, a in enumerate(args):
            if a in ("-c", "--command") and i + 1 < len(args):
                strings.append(args[i + 1])
    elif name == "cmd":
        for i, a in enumerate(args):
            if a.lower() in ("/c", "/k", "/r"):
                strings.append(" ".join(args[i + 1:]))
                break
    elif name in ("powershell", "pwsh"):
        for i, a in enumerate(args):
            low = a.lower()
            if low in ("-e", "-ec", "-enc") or (len(low) > 2 and "-encodedcommand".startswith(low)):
                cmd.opaque = True
            elif low.startswith("-c") and "-command".startswith(low):
                strings.append(" ".join(args[i + 1:]))
                break
    elif name == "find":
        i = 0
        while i < len(args):
            if args[i] in ("-exec", "-execdir", "-ok", "-okdir"):
                j = i + 1
                while j < len(args) and args[j] not in (";", "+"):
                    j += 1
                if j > i + 1:
                    sub = SimpleCommand(argv=[], words=args[i + 1:j], depth=d)
                    sub.argv = _peel(list(sub.words), sub.wrappers, [])
                    _expand(sub)
                    cmd.nested.append(sub)
                i = j
            i += 1

    for s in strings:
        cmd.nested.extend(parse(s, d))


def _shell_command_string(args: List[str]) -> Optional[str]:
    """Return the ``-c`` program of a shell invocation, or None if there isn't one."""
    has_c = False
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            i += 1
            break
        if a in ("-o", "+o", "-O", "+O", "--rcfile", "--init-file"):
            i += 2
            continue
        if (a.startswith("-") or a.startswith("+")) and not a.startswith("--"):
            if "c" in a[1:]:
                has_c = True
            i += 1
            continue
        if a.startswith("--"):
            i += 1
            continue
        break
    if has_c and i < len(args):
        return args[i]
    return None
