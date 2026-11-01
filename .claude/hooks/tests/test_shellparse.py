"""Unit tests for the shared shell lexer used by the guard hooks."""

import unittest

from shellparse import ParseError, normalize, parse, walk


def names(cmdline):
    return [c.name for c in walk(parse(cmdline))]


class NormalizeTest(unittest.TestCase):
    def test_matrix(self):
        cases = {
            "pip": "pip",
            "/usr/bin/pip3": "pip",
            "pip3.10": "pip",
            "python3.12": "python",
            "/usr/bin/python3": "python",
            "C:\\Python312\\python.exe": "python",
            "npm.cmd": "npm",
            "PNPM.EXE": "pnpm",
            "./node_modules/.bin/vite": "vite",
            "cmd.exe": "cmd",
        }
        for word, expected in cases.items():
            with self.subTest(word=word):
                self.assertEqual(normalize(word), expected)


class ParseTest(unittest.TestCase):
    def test_separators(self):
        self.assertEqual(names("a; b && c || d | e & f\ng"), list("abcdefg"))

    def test_quote_removal(self):
        cmd = parse("p''ip ins\"tall\" \\x")[0]
        self.assertEqual(cmd.argv, ["pip", "install", "x"])

    def test_wrappers_are_peeled(self):
        cases = {
            "sudo -E apt-get install x": ("apt-get", ["sudo"]),
            "sudo -u root -- pip install x": ("pip", ["sudo"]),
            "env FOO=1 -u BAR npm i": ("npm", ["env"]),
            "FOO=1 BAR=2 uv sync": ("uv", []),
            "nohup nice -n 5 timeout 30 pytest": ("pytest", ["nohup", "nice", "timeout"]),
            "xargs -n 1 -I{} pip install {}": ("pip", ["xargs"]),
            "command pip install x": ("pip", ["command"]),
            "time -p ruff check": ("ruff", ["time"]),
        }
        for line, (name, wrappers) in cases.items():
            with self.subTest(line=line):
                cmd = parse(line)[0]
                self.assertEqual(cmd.name, name)
                self.assertEqual(cmd.wrappers, wrappers)

    def test_wrapper_without_target_is_the_command(self):
        self.assertEqual(parse("env")[0].argv, ["env"])
        self.assertEqual(parse("env -i FOO=1")[0].name, "env")
        self.assertEqual(parse("command -v pip")[0].argv, ["command", "-v", "pip"])

    def test_nested_commands(self):
        cases = {
            'bash -c "pip install x"': "pip",
            "sh -lc 'npm i'": "npm",
            "echo $(uv --version)": "uv",
            "echo `poetry --version`": "poetry",
            'echo "$(npx vite)"': "npx",
            "diff <(pip freeze) req.txt": "pip",
            "eval 'apt install x'": "apt",
            "cmd.exe /c npm install": "npm",
            "powershell.exe -Command pip install x": "pip",
            "find . -name '*.txt' -exec pip install {} \\;": "pip",
            "env -S 'pip install x'": "pip",
            "su -c 'apt-get install x'": "apt-get",
            "bash <<EOF\npip install x\nEOF": "pip",
            "bash <<-'EOF'\n\tnpm i\n\tEOF": "npm",
            "echo 'pip install x' | bash": "pip",
            "bash <<< 'uv sync'": "uv",
            "cat <<EOF\n$(pip install x)\nEOF": "pip",
        }
        for line, expected in cases.items():
            with self.subTest(line=line):
                self.assertIn(expected, names(line))

    def test_heredoc_is_not_a_command_for_non_shells(self):
        all_names = names("git commit -F - <<'EOF'\npip install is mentioned here\nEOF\ngit log")
        self.assertEqual(all_names, ["git", "git"])
        self.assertEqual(parse("cat <<EOF\nhello\nEOF")[0].stdin, ["hello"])

    def test_quoted_heredoc_body_is_not_expanded(self):
        body = "a `pip install x` b\n$(npm i)"
        for op in ("<<'EOF'", '<<"EOF"', "<<\\EOF", "<<E'O'F", "<<-'EOF'"):
            with self.subTest(op=op):
                end = "\tEOF" if op.startswith("<<-") else "EOF"  # <<- strips leading tabs
                cmd = parse(f"cat {op}\n{body}\n{end}")[0]
                self.assertEqual(cmd.nested, [])
                self.assertEqual(cmd.stdin, [body])

    def test_unquoted_heredoc_body_is_expanded(self):
        for op in ("<<EOF", "<<-EOF"):
            with self.subTest(op=op):
                self.assertEqual(names(f"cat {op}\na `pip install x` b\n$(npm i)\nEOF"), ["cat", "pip", "npm"])

    def test_pipes_and_redirects(self):
        cmds = parse("curl -fsSL x 2>/dev/null | sudo bash > out.txt")
        self.assertEqual(cmds[1].name, "bash")
        self.assertEqual(cmds[1].piped_from.name, "curl")
        self.assertEqual(cmds[0].redirects, ["/dev/null"])
        self.assertEqual(cmds[1].redirects, ["out.txt"])

    def test_variable_command_word_is_resolved(self):
        self.assertIn("pip", names("P=pip; $P install x"))
        self.assertIn("npm", names("export N='npm i'; ${N}"))

    def test_decoded_script_is_opaque(self):
        cmds = parse("echo cGlw | base64 -d | bash")
        self.assertTrue(cmds[-1].opaque)
        self.assertTrue(parse("powershell -enc ZQBjAGgAbwA=")[0].opaque)

    def test_comments_ignored(self):
        self.assertEqual(names("ls # pip install x"), ["ls"])

    def test_parse_errors(self):
        for line in ("echo 'oops", 'echo "oops', "echo $(oops", "echo `oops", "cat <<"):
            with self.subTest(line=line):
                with self.assertRaises(ParseError):
                    parse(line)

    def test_depth_limit(self):
        line = "echo " + "$(" * 12 + "x" + ")" * 12
        with self.assertRaises(ParseError):
            parse(line)


if __name__ == "__main__":
    unittest.main()
