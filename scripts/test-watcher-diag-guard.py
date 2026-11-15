#!/usr/bin/env python3
"""The session watcher's one-round-at-a-time guard for display diagnostics (oneos_switch.sh).

A diagnostics round still running from the round before keeps its pid in $STAGE/diag.pid, and the
watcher skips the next round while that pid is alive. The guard used to be
`kill -0 "$(cat $STAGE/diag.pid)"`: with no diag.pid (it is removed right before the first round)
busybox's kill -0 '' takes the empty pid as 0, its own process group, and succeeds, so S Ultra X9U
session 3d9814984612c525 skipped every round (fixed in 1921ecc). Only an all-digit pid without a
leading 0 is checked now.

The guard is taken out of the watcher's quoted block, unquoted the way the outer shell does it
($STAGE written in, \\$ and \\" unescaped), and run under busybox sh (when there is one), dash and
sh for files that must not skip the round and for a live pid that must.

Optional argument: another copy of oneos_switch.sh to test instead, for example
`git show d285f7a:switcher/assets/oneos_switch.sh`, the version with the bug.
"""
from pathlib import Path
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
SWITCH = ROOT / 'switcher/assets/oneos_switch.sh'
SKIPPED = 'display diagnostics \\$dname skipped: the previous round is still running'


def guard(src):
    """The lines from the guard's first command through the `fi` that closes its skip."""
    lines = src.split('\n')
    hits = [i for i, l in enumerate(lines) if SKIPPED in l]
    assert len(hits) == 1, 'the diagnostics skip is not where the test expects it'
    first = hits[0] - 1
    assert 'kill -0' in lines[first] and lines[first].lstrip().startswith('if '), lines[first]
    # The commands right above the if (up to the comment that explains them) belong to the guard.
    while first > 0 and lines[first - 1].strip() and not lines[first - 1].lstrip().startswith('#'):
        first -= 1
    last = hits[0] + 1
    while lines[last].strip() != 'fi':
        last += 1
    return '\n'.join(lines[first:last + 1]) + '\n'


def unquote(block, stage):
    block = re.sub(r'(?<!\\)\$STAGE\b', stage, block)
    left = re.findall(r'(?<!\\)\$[A-Za-z_{(]', block)
    assert not left, left
    return re.sub(r'\\([$"\\`])', r'\1', block)


def busybox():
    for p in [shutil.which('busybox')] + sorted(glob.glob('/nix/store/*busybox*/bin/busybox')):
        if p and os.access(p, os.X_OK):
            return p
    return None


def shells():
    out = []
    bb = busybox()
    if bb:
        out.append(('busybox sh', [bb, 'sh']))
    else:
        print('busybox not found (PATH or /nix/store): busybox sh is not tested', file=sys.stderr)
    for name in ('dash', 'sh'):
        p = shutil.which(name)
        if p:
            out.append((name, [p]))
    return out


class DiagGuard(unittest.TestCase):
    def run_guard(self, shell, content):
        """True when the guard skips the round. content None: no diag.pid."""
        with tempfile.TemporaryDirectory() as stage:
            if content is not None:
                Path(stage, 'diag.pid').write_text(content)
            script = 'dname=diag_1\n' + unquote(guard(SOURCE), stage) + 'echo "round:$dname"\n'
            r = subprocess.run(shell + ['-c', script], capture_output=True, text=True, timeout=30)
            self.assertIn('round:', r.stdout, (r.stdout, r.stderr))
            return r.stdout.strip().endswith('round:')

    def test_no_live_round_runs(self):
        dead = subprocess.Popen(['true'])
        dead.wait()
        cases = {'no file': None, 'empty': '', 'empty line': '\n', 'garbage': 'abc\n', 'zero': '0\n',
                 'minus one': '-1\n', 'leading zero': '007\n', 'dead pid': '%d\n' % dead.pid}
        for sname, shell in shells():
            for cname, content in cases.items():
                with self.subTest(shell=sname, case=cname):
                    self.assertFalse(self.run_guard(shell, content), 'round skipped for %s' % cname)

    def test_live_round_skips(self):
        live = subprocess.Popen(['sleep', '60'])
        try:
            for sname, shell in shells():
                with self.subTest(shell=sname):
                    self.assertTrue(self.run_guard(shell, '%d\n' % live.pid))
        finally:
            live.kill()
            live.wait()

    def test_no_kill_of_an_unchecked_cat(self):
        # The original bug's shape: whatever cat gives (nothing, too) goes straight to kill -0.
        bad = [n for n, l in enumerate(SOURCE.split('\n'), 1) if 'kill -0 \\"\\$(cat' in l]
        self.assertEqual(bad, [], 'kill -0 of an unchecked $(cat ...) at lines %s' % bad)


if __name__ == '__main__':
    if len(sys.argv) > 1 and not sys.argv[1].startswith('-'):
        SWITCH = Path(sys.argv.pop(1))
    SOURCE = SWITCH.read_text()
    unittest.main()
