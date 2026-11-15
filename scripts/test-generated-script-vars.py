#!/usr/bin/env python3
"""Every runtime variable a generated script reads is set inside that script (oneos_switch.sh, guest_start.sh).

Both scripts write further scripts as double-quoted strings (`$BB sh -c "..."`) and unquoted
heredocs. Inside those, `\\$NAME` is left for the generated script to expand when it runs, while a
bare `$NAME` is the generator's own value written in. Escaping a variable that only the generator
has reads an unset variable at run time: the UI Activator's `if [ \\$GUEST_MIUI = 1 ]` ran as
`[ = 1 ]` ("sh: 1: unknown operand" in ui_activator.log, ColorOS session 3d9814984612c525, fixed in
67c8e95), and HyperOS's low-brightness repair never ran.

The test finds each top-level double-quoted string and unquoted heredoc, unquotes it the way the
outer shell does, and checks that every escaped variable is assigned in the same block (NAME=,
for NAME, read ... NAME, export/local/readonly, getopts). `$NF` and the like inside single-quoted
awk programs of the generated script are awk's, not the shell's, and are left out.

Optional arguments: other copies of the scripts to check instead (for example an older version from
`git show`); without arguments the two scripts of the tree are checked.
"""
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = [ROOT / 'switcher/assets/oneos_switch.sh', ROOT / 'switcher/assets/guest_start.sh']

# Variables the shell itself sets.
SPECIAL = {'PATH', 'HOME', 'RANDOM', 'PWD', 'IFS', 'OPTARG', 'OPTIND', 'PPID', 'LINENO', 'SECONDS'}

# Escaped variables a generated block may read without assigning them, each with the reason.
# Empty today: add an entry only for a real runtime environment variable the block inherits.
ALLOWED = {
    # ('oneos_switch.sh', 'NAME'): 'why the generated script has it at run time',
}

# Stands in for an escaped `\$` in the unquoted text, so the generated script's own `$` can be told
# apart from the generator's.
MARK = '\x00'


def blocks(src):
    """(start, end, kind) of the top-level double-quoted strings and unquoted heredoc bodies."""
    n = len(src)
    out = []

    def skip_dq(i):
        # i is just after the opening quote; returns the offset of the closing one.
        while i < n:
            c = src[i]
            if c == '\\':
                i += 2
                continue
            if c == '"':
                return i
            if src.startswith('$((', i):
                i = skip_cs(i + 3, arith=True)
                continue
            if src.startswith('$(', i):
                i = skip_cs(i + 2)
                continue
            if c == '`':
                j = i + 1
                while j < n and src[j] != '`':
                    j += 2 if src[j] == '\\' else 1
                i = j + 1
                continue
            i += 1
        return n

    def skip_cs(i, arith=False):
        depth = 1
        while i < n:
            c = src[i]
            if c == '\\':
                i += 2
                continue
            if c == "'" and not arith:
                i = src.find("'", i + 1) + 1
                continue
            if c == '"':
                i = skip_dq(i + 1) + 1
                continue
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
                if depth == 0:
                    return i + (2 if arith else 1)
            i += 1
        return n

    i = 0
    heredocs = []
    while i < n:
        c = src[i]
        if c == '\n' and heredocs:
            i += 1
            for word, quoted, strip in heredocs:
                start = i
                while i < n:
                    e = src.find('\n', i)
                    e = n if e < 0 else e
                    line = src[i:e]
                    if (line.lstrip('\t') if strip else line) == word:
                        if not quoted:
                            out.append((start, i, 'heredoc'))
                        i = e + 1
                        break
                    i = e + 1
            heredocs = []
            continue
        if c == '\\':
            i += 2
            continue
        if c == '#' and (i == 0 or src[i - 1] in ' \t\n;&|('):
            e = src.find('\n', i)
            i = n if e < 0 else e
            continue
        if c == "'":
            i = src.find("'", i + 1) + 1
            continue
        if c == '"':
            e = skip_dq(i + 1)
            out.append((i + 1, e, 'dq'))
            i = e + 1
            continue
        if src.startswith('$(', i) and not src.startswith('$((', i):
            i += 2
            continue
        m = re.match(r'<<(-?)\s*([\'"]?)([A-Za-z_][A-Za-z_0-9]*)\2', src[i:i + 80])
        if m:
            heredocs.append((m.group(3), bool(m.group(2)), m.group(1) == '-'))
            i += m.end()
            continue
        i += 1
    return out


def generated(body, kind):
    """The block as the generated script sees it, with MARK where an escaped `$` was."""
    text = body.replace('\\$', MARK)
    if kind == 'dq':
        text = text.replace('\\"', '"').replace('\\`', '`')
    return text.replace('\\\\', '\\')


def runtime_refs(text):
    """Names of the escaped variables read outside single quotes and comments of the generated text."""
    names = set()
    i, n = 0, len(text)
    in_dq = False
    while i < n:
        c = text[i]
        if c == '\\':
            i += 2
            continue
        if not in_dq and c == "'":
            # Single-quoted in the generated script: an awk program's $NF is awk's.
            j = text.find("'", i + 1)
            i = n if j < 0 else j + 1
            continue
        if not in_dq and c == '#' and (i == 0 or text[i - 1] in ' \t\n;&|('):
            j = text.find('\n', i)
            i = n if j < 0 else j
            continue
        if c == '"':
            in_dq = not in_dq
        elif c == MARK:
            m = re.match(r'\{?([A-Za-z_]\w*)', text[i + 1:])
            if m:
                names.add(m.group(1))
        i += 1
    return names


def assigned(name, text):
    code = re.sub(r'(?m)^\s*#.*$', '', text)
    pat = (r'(^|[\s;&|({`])(?:export\s+|local\s+|readonly\s+|eval\s+)?' + name + r'='
           r'|\bfor\s+' + name + r'\b'
           r'|\bread\b[^;\n|&]*\b' + name + r'\b'
           r'|\bgetopts\s+\S+\s+' + name + r'\b'
           r'|\b(?:export|local|readonly)\s+(?:\w+\s+)*' + name + r'\b')
    return re.search(pat, code, re.M) is not None


def unassigned(path, src):
    """Lines describing each escaped variable of a generated block that the block never assigns."""
    problems = []
    for start, end, kind in blocks(src):
        body = src[start:end]
        if '\\$' not in body:
            continue
        text = generated(body, kind)
        for name in sorted(runtime_refs(text)):
            if name in SPECIAL or (Path(path).name, name) in ALLOWED or assigned(name, text):
                continue
            first = src.count('\n', 0, start) + 1
            uses = [src.count('\n', 0, start + m.start()) + 1
                    for m in re.finditer(r'\\\$\{?' + name + r'\b', body)]
            problems.append('%s: generated %s at lines %d-%d reads \\$%s (lines %s) but never sets it'
                            % (path, kind, first, src.count('\n', 0, end) + 1, name, uses))
    return problems


class GeneratedScriptVars(unittest.TestCase):
    def test_every_escaped_variable_is_set_in_its_block(self):
        problems = []
        for path in SCRIPTS:
            problems += unassigned(path, Path(path).read_text())
        self.assertEqual(problems, [], '\n' + '\n'.join(problems))

    def test_catches_the_activator_bug(self):
        # The 67c8e95 bug put back into the current activator must be found.
        src = SCRIPTS[0].read_text()
        good = '            if [ $GUEST_MIUI = 1 ]; then\n                bm=\\$('
        self.assertEqual(src.count(good), 1, 'the activator GUEST_MIUI test is not where the test expects it')
        bad = src.replace(good, good.replace('[ $GUEST_MIUI', '[ \\$GUEST_MIUI'))
        problems = unassigned(SCRIPTS[0], bad)
        self.assertTrue(any('\\$GUEST_MIUI' in p for p in problems), problems)

    def test_awk_fields_are_not_runtime_variables(self):
        self.assertEqual(runtime_refs(generated("ls | awk '{print \\$NF}'; echo \\\"\\$x\\\"", 'dq')), {'x'})


if __name__ == '__main__':
    if len(sys.argv) > 1 and not sys.argv[1].startswith('-'):
        SCRIPTS = [Path(p) for p in sys.argv[1:]]
        found = []
        for p in SCRIPTS:
            found += unassigned(p, p.read_text())
        print('\n'.join(found) if found else 'no unassigned escaped variables')
        sys.exit(1 if found else 0)
    unittest.main()
