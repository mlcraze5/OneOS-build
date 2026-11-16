#!/usr/bin/env python3
"""Run the generated ColorOS compile script (SystemUI, then the launcher) against stub pm and cmd.

The launcher, com.android.launcher (OplusLauncher.apk), ran with only its vdex in session
25b4785c4206828f (S25 Ultra, X9U IN guest, set x9u-in-1105-sultra), so guest_prepare.sh's
oneos_sysui_compile.sh compiles it with speed once per APK after SystemUI's step. The test takes
both heredocs out of guest_prepare.sh, points /data/ and /system/system_ext/ at a temporary
directory and runs the result with sh, with pm, cmd, getprop, sleep and timeout stubbed on PATH.
"""
import os, re, subprocess, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GEN = (ROOT / 'switcher/assets/guest_prepare.sh').read_text()


def heredoc(tag):
    m = re.search(r"<<'%s'\n(.*?)\n%s\n" % (tag, tag), GEN, re.S)
    assert m, tag
    return m.group(1) + '\n'


SCRIPT = heredoc('SYSUI') + heredoc('LAUNCHER')

STUBS = {
    # pm art dump PKG: status from $STATE/PKG; pm path PKG: the launcher's APK.
    'pm': '''#!/bin/sh
if [ "$1" = art ] && [ "$2" = dump ]; then
    s=$(cat "$STATE/$3" 2>/dev/null)
    echo "Dexopt state:"; echo "  [$3]"; echo "    path: /x/base.apk"; echo "      arm64: [status=$s] [reason=unknown]"
elif [ "$1" = path ] && [ "$2" = com.android.launcher ]; then
    [ -n "$LAUNCHER_APK" ] && echo "package:$LAUNCHER_APK"
fi
exit 0
''',
    # cmd package compile -m F -f PKG: logged; $FAIL_PKG fails, others turn to the filter.
    'cmd': '''#!/bin/sh
echo "$*" >> "$STATE/cmd.log"
eval "p=\\${$#}"
if [ "$p" = "$FAIL_PKG" ]; then echo "Failure: dex2oat crashed"; exit 1; fi
echo "$4" > "$STATE/$p"
echo Success
''',
    'getprop': '#!/bin/sh\n[ "$1" = sys.boot_completed ] && echo 1\nexit 0\n',
    'sleep': '#!/bin/sh\nexit 0\n',
    'timeout': '#!/bin/sh\nshift\nexec "$@"\n',
}


class LauncherCompileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.t = t
        self.state = t / 'state'
        self.state.mkdir()
        bin_ = t / 'bin'
        bin_.mkdir()
        for name, body in STUBS.items():
            (bin_ / name).write_text(body)
            (bin_ / name).chmod(0o755)
        self.bin = bin_
        self.data = t / 'data'
        (self.data / 'dalvik-cache/arm64').mkdir(parents=True)
        boot = self.data / 'misc/apexdata/com.android.art/dalvik-cache/arm64/boot.oat'
        boot.parent.mkdir(parents=True)
        boot.write_bytes(b'boot')
        sysui = t / 'system/system_ext/priv-app/SystemUI/SystemUI.apk'
        sysui.parent.mkdir(parents=True)
        sysui.write_bytes(b'sysui')
        self.lapk = t / 'system/system_ext/priv-app/OplusLauncher/OplusLauncher.apk'
        self.lapk.parent.mkdir(parents=True)
        self.lapk.write_bytes(b'launcher')
        self.script = t / 'oneos_sysui_compile.sh'
        self.script.write_text(SCRIPT.replace('/data/', str(self.data) + '/')
                               .replace('/system/system_ext/', str(t) + '/system/system_ext/'))
        self.set_status('com.android.systemui', 'speed')
        self.set_status('com.android.launcher', 'verify')

    def tearDown(self):
        self.tmp.cleanup()

    def set_status(self, pkg, s):
        (self.state / pkg).write_text(s + '\n')

    def run_script(self, fail=''):
        cmdlog = self.state / 'cmd.log'
        if cmdlog.exists():
            cmdlog.unlink()
        env = dict(os.environ, PATH=str(self.bin) + ':' + os.environ['PATH'], STATE=str(self.state),
                   LAUNCHER_APK=str(self.lapk), FAIL_PKG=fail)
        r = subprocess.run(['sh', str(self.script)], env=env, capture_output=True, text=True)
        self.assertEqual(0, r.returncode, r.stderr)
        return cmdlog.read_text().splitlines() if cmdlog.exists() else []

    def log(self):
        return (self.data / 'oneos_sysui_compile.log').read_text()

    def lmark(self):
        return self.data / 'oneos_launcher_compiled'

    def odex(self, name):
        p = self.data / 'dalvik-cache/arm64' / ('system@system_ext@priv-app@%s@%s.apk@classes.dex' % (name, name))
        p.write_bytes(b'odex')

    def test_scripts_parse(self):
        self.assertEqual(0, subprocess.run(['sh', '-n', str(self.script)]).returncode)
        self.assertEqual(0, subprocess.run(['sh', '-n', str(ROOT / 'switcher/assets/guest_prepare.sh')]).returncode)

    def test_sysui_compiled_launcher_verify_compiles_with_speed(self):
        calls = self.run_script()
        self.assertEqual(['package compile -m speed -f com.android.launcher'], calls)
        self.assertTrue(self.lmark().is_file())
        self.assertRegex(self.lmark().read_text(), r'^apk=[0-9a-f]{64} boot=4:\d+\n$')
        # SystemUI's own marker and log lines as before.
        self.assertTrue((self.data / 'oneos_sysui_compiled').is_file())
        self.assertIn('SystemUI arm64 is speed already: nothing to compile', self.log())
        self.assertIn('launcher marker saved', self.log())

    def test_marker_and_odex_skip_launcher(self):
        self.run_script()
        self.odex('OplusLauncher')
        self.set_status('com.android.launcher', 'verify')
        self.assertEqual([], self.run_script())
        self.assertIn('launcher compiled on an earlier session for this APK', self.log())

    def test_marker_without_odex_checks_again(self):
        self.run_script()
        self.set_status('com.android.launcher', 'verify')
        self.assertEqual(['package compile -m speed -f com.android.launcher'], self.run_script())

    def test_changed_apk_compiles_again(self):
        self.run_script()
        self.odex('OplusLauncher')
        self.lapk.write_bytes(b'launcher v2')
        self.set_status('com.android.launcher', 'verify')
        self.assertEqual(['package compile -m speed -f com.android.launcher'], self.run_script())

    def test_symlinked_marker_is_not_trusted(self):
        self.run_script()
        self.odex('OplusLauncher')
        real = self.t / 'elsewhere'
        real.write_text(self.lmark().read_text())
        self.lmark().unlink()
        self.lmark().symlink_to(real)
        self.set_status('com.android.launcher', 'verify')
        self.assertEqual(['package compile -m speed -f com.android.launcher'], self.run_script())
        self.assertFalse(self.lmark().is_symlink())
        self.assertEqual(real.read_text(), self.lmark().read_text())

    def test_sysui_early_return_still_runs_launcher(self):
        # SystemUI compiled now (run-from-apk), then skipped by its marker on the next run.
        self.set_status('com.android.systemui', 'run-from-apk')
        self.set_status('com.android.launcher', 'speed')
        self.assertEqual(['package compile -m speed -f com.android.systemui'], self.run_script())
        self.odex('SystemUI')
        self.lmark().unlink()
        self.set_status('com.android.launcher', 'run-from-apk')
        self.assertEqual(['package compile -m speed -f com.android.launcher'], self.run_script())
        self.assertIn('SystemUI compiled on an earlier session for this APK', self.log())
        self.assertTrue(self.lmark().is_file())

    def test_sysui_failure_still_runs_launcher(self):
        self.set_status('com.android.systemui', 'verify')
        calls = self.run_script(fail='com.android.systemui')
        self.assertEqual(['package compile -m speed -f com.android.systemui',
                          'package compile -m speed -f com.android.launcher'], calls)
        self.assertFalse((self.data / 'oneos_sysui_compiled').exists())
        self.assertTrue(self.lmark().is_file())

    def test_launcher_compile_failure_leaves_no_marker(self):
        calls = self.run_script(fail='com.android.launcher')
        self.assertEqual(['package compile -m speed -f com.android.launcher'], calls)
        self.assertFalse(self.lmark().exists())
        self.assertIn('launcher: no marker: tried again next session', self.log())

    def test_already_speed_saves_marker_without_compile(self):
        self.set_status('com.android.launcher', 'speed-profile')
        self.assertEqual([], self.run_script())
        self.assertTrue(self.lmark().is_file())

    def test_unknown_status_not_compiled(self):
        self.set_status('com.android.launcher', 'unknown')
        self.assertEqual([], self.run_script())
        self.assertFalse(self.lmark().exists())

    def test_no_launcher_package_is_skipped(self):
        self.lapk = self.t / 'missing.apk'
        self.assertEqual([], self.run_script())
        self.assertIn('launcher: no APK from pm path', self.log())

    def test_launcher_step_behind_its_switch(self):
        i = GEN.index("<<'LAUNCHER'")
        gate = GEN.rindex('if [ "${ONEOS_GUEST_LAUNCHER_COMPILE:-1}" = 1 ]; then', 0, i)
        self.assertNotIn('\nSYSUI\n', GEN[gate:i])
        self.assertLess(GEN.index("\nSYSUI\n"), gate)


if __name__ == '__main__':
    unittest.main()
