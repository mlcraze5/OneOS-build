#!/usr/bin/env python3
"""The IMS / SMS registration gate's no-SIM skip (oneos_switch.sh).

Before the pivot the gate waits up to 45 x 2 s for `dumpsys telephony.registry` to show
mVoiceRegState=0. With no SIM in any slot the voice state is only ever OUT_OF_SERVICE or POWER_OFF,
so S25 Ultra session 25b4785c4206828f (no SIM, ColorOS 17 guest) lost the full 90 s on every switch.
The wait is skipped now only when One UI's gsm.sim.state names every slot ABSENT; an empty, unknown
or not-yet-ready state still waits as before.

The gate is taken out of oneos_switch.sh as it stands (from its `ims_i=0` through the
`preflight: ims gate done` line) and run under busybox sh (when there is one), dash and sh, with
getprop, dumpsys, sleep, pidof and setprop stubbed as shell functions (functions win over busybox
applets, so the stubs hold under busybox sh too).

Optional argument: another copy of oneos_switch.sh to test instead.
"""
from pathlib import Path
import glob
import os
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
SWITCH = ROOT / 'switcher/assets/oneos_switch.sh'
HEADER = '# --- IMS / SMS REGISTRATION GATE'
DONE = 'echo "preflight: ims gate done $(date +%T)"'


def gate(src):
    """The gate's lines from `ims_i=0` through the `preflight: ims gate done` echo."""
    lines = src.split('\n')
    hits = [i for i, l in enumerate(lines) if l.startswith(HEADER)]
    assert len(hits) == 1, 'the IMS gate is not where the test expects it'
    first = next(i for i in range(hits[0], len(lines)) if lines[i] == 'ims_i=0')
    last = next(i for i in range(first, len(lines)) if lines[i] == DONE)
    block = '\n'.join(lines[first:last + 1]) + '\n'
    # Plain top-level script, not part of a generated quoted string: no escaped $ in it.
    assert '\\$' not in block and '\\"' not in block, 'the gate looks generated (escaped quoting)'
    return block


def stubs(sim, reg):
    return (
        'getprop() { [ "$1" = gsm.sim.state ] && printf "%%s\\n" \'%s\'; }\n'
        'dumpsys() { echo "mVoiceRegState=%s(STUB)"; }\n'
        'sleep() { echo SLEPT >&2; }\n'
        'pidof() { echo 4242; }\n'
        'setprop() { :; }\n'
        'ims_pid=\n'
    ) % (sim, reg)


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


SKIP = {'two absent': 'ABSENT,ABSENT', 'one absent': 'ABSENT', 'spaced': ' ABSENT , ABSENT '}
WAIT = {'loaded first': 'LOADED,ABSENT', 'loaded second': 'ABSENT,LOADED', 'empty': '',
        'not ready': 'NOT_READY', 'unknown first': 'UNKNOWN,ABSENT', 'empty slot': 'ABSENT,',
        'prefix only': 'ABSENTX', 'lower case': 'absent', 'pin': 'PIN_REQUIRED,ABSENT',
        'commas only': ','}


class ImsGateNoSim(unittest.TestCase):
    def run_gate(self, shell, sim, reg=1):
        script = stubs(sim, reg) + gate(SOURCE) + 'echo "vars:$ims_st:$ims_i"\n'
        r = subprocess.run(shell + ['-c', script], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, (r.stdout, r.stderr))
        self.assertIn('preflight: ims gate done', r.stdout, (r.stdout, r.stderr))
        return r.stdout, r.stderr.count('SLEPT')

    def test_no_sim_skips(self):
        for sname, shell in shells():
            for cname, sim in SKIP.items():
                with self.subTest(shell=sname, case=cname):
                    out, slept = self.run_gate(shell, sim)
                    self.assertEqual(slept, 0, out)
                    self.assertIn('IMS gate: skipped, no SIM (gsm.sim.state=%s), imsd=4242' % sim, out)
                    self.assertNotIn('voiceRegState=', out)
                    self.assertIn('vars:1:0', out)

    def test_anything_else_waits(self):
        for sname, shell in shells():
            for cname, sim in WAIT.items():
                with self.subTest(shell=sname, case=cname):
                    out, slept = self.run_gate(shell, sim)
                    self.assertEqual(slept, 45, out)
                    self.assertIn('IMS gate: voiceRegState=1 after 90s, imsd=4242', out)
                    self.assertNotIn('skipped', out)
                    self.assertIn('vars:1:45', out)

    def test_registered_sim_passes_at_once(self):
        for sname, shell in shells():
            with self.subTest(shell=sname):
                out, slept = self.run_gate(shell, 'LOADED,ABSENT', reg=0)
                self.assertEqual(slept, 0, out)
                self.assertIn('IMS gate: voiceRegState=0 after 0s, imsd=4242', out)
                self.assertIn('vars:0:0', out)

    def test_switch_script_syntax(self):
        for sname, shell in shells():
            with self.subTest(shell=sname):
                r = subprocess.run(shell + ['-n', str(SWITCH)], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == '__main__':
    if len(sys.argv) > 1 and not sys.argv[1].startswith('-'):
        SWITCH = Path(sys.argv.pop(1))
    SOURCE = SWITCH.read_text()
    unittest.main()
