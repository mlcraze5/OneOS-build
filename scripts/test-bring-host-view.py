#!/usr/bin/env python3
"""bring_host_view (oneos_root.sh): One UI's apps under the session's bridges.

During a session bridges.sh mounts the guest's trees over One UI's /data/app,
/data/data and /data/user_de, so bring-add saw no One UI app ("not an installed
user app", Galaxy S23 HyperOS 0.5.15). bring-add now re-runs itself in a mount
namespace of its own and reads a read-only, non-recursive bind of /data, which
shows the trees under the bridges. Runs the real functions as root in a
throwaway mount namespace, with a fake /data whose app folder is bridged.

The read-only remount names the source and the view: with the view alone
busybox first looks it up in /proc/mounts, and on the S25 Ultra (ColorOS 17,
0.5.16, session 2c804690b9171656) that lookup failed during a session, so every
bring was refused. The view is then checked read only from mountinfo.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / 'app-android/app/src/full/assets/root/oneos_root.sh').read_text()


def function(name):
    start = SCRIPT.index(name + '() {')
    return SCRIPT[start:SCRIPT.index('\n}\n', start) + 3]


DRIVER = r'''
refuse() {
    echo "@@REFUSED $*"
    [ -z "${BV:-}" ] || awk -v p="$BV" '$5 == p { print "left=" $5 " " $6 }' /proc/self/mountinfo
    exit 3
}
die() { echo "@@FAILED $*"; exit 4; }
mine() { return 0; }
mkdir_mine() { mkdir -p "$1"; }
own() { chmod "$2" "$1"; }
find_tools() { BB=$FAKE_BB; }
{fns}
pkg=$2
bring_host_view "$pkg"
echo "pid=$$ ns=${ONEOS_BRING_NS:-}"
echo "host=${BRING_HOST:-}"
echo "opts=$(awk -v p="$BRING_HOST" '$5 == p { o = $6 } END { print o }' /proc/self/mountinfo)"
BRING_LIVE=1
echo "apk=$(bring_apk_path "$pkg")"
bring_sources
echo "ce=$BCE"
ls "$BCE"
touch "$BRING_HOST/app/written" 2>/dev/null && echo WRITABLE || echo READONLY
'''


BB_STANDIN = r'''#!/bin/sh
c=$1; shift
[ "$c" = unshare ] && [ "$3" = /system/bin/sh ] && { a=$1; b=$2; shift 3; set -- "$a" "$b" sh "$@"; }
if [ "$c" = mount ] && [ "$1" = -o ]; then
    case "$2" in
        remount*)
            [ "${FAKE_BB_MODE:-}" = skip-remount ] && exit 0
            if [ "${FAKE_BB_MODE:-}" = one-arg-fails ] && [ $# -eq 3 ]; then
                echo "mount: can't find $3 in /proc/mounts" >&2
                exit 1
            fi ;;
    esac
fi
case "$c" in mount|umount) [ -n "{busybox}" ] && exec "{busybox}" "$c" "$@" ;; esac
exec "$c" "$@"
'''


@unittest.skipUnless(os.geteuid() == 0 and shutil.which('unshare'), 'needs root and unshare')
class BringHostViewTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='oneos-view-')
        r = self.r = Path(self.temp.name)
        data = r / 'data'
        (data / 'system').mkdir(parents=True)
        (data / 'system/packages.list').write_text('com.anthropic.claude 10357 0 /data/user/0/com.anthropic.claude default none 0 1 1 @null\n')
        apk = data / 'app/~~c1==/com.anthropic.claude-R==/base.apk'
        apk.parent.mkdir(parents=True)
        apk.write_text('apk')
        (data / 'data/com.anthropic.claude').mkdir(parents=True)
        (data / 'data/com.anthropic.claude/prefs').write_text('x')
        (data / 'user_de/0/com.anthropic.claude').mkdir(parents=True)
        (r / 'stage/data/app').mkdir(parents=True)
        (r / 'stage/data/data').mkdir(parents=True)
        bb = r / 'bb'
        # The phone's busybox; this container has no /system/bin/sh, so the stand-in
        # runs the re-exec with sh. mount and umount are busybox's own when it is
        # here (the two-argument remount is busybox's code path, not util-linux's).
        # FAKE_BB_MODE=skip-remount makes a remount do nothing (a view left
        # writable); one-arg-fails fails a remount given the view alone, as the
        # phone's busybox did.
        bb.write_text(BB_STANDIN.replace('{busybox}', shutil.which('busybox') or ''))
        os.chmod(bb, 0o755)
        script = r / 'oneos_root.sh'
        fns = ''.join(function(n) for n in ('bring_host_view', 'bring_apk_path', 'bring_sources'))
        script.write_text(DRIVER.replace('{fns}', fns))
        self.script = script

    def tearDown(self):
        self.temp.cleanup()

    def run_bridged(self, mode=''):
        r = self.r
        outer = (f'export FAKE_BB_MODE={mode}; '
                 f'mount --make-rprivate / && mount --bind {r}/data {r}/data && '
                 f'mount --bind {r}/stage/data/app {r}/data/app && '
                 f'mount --bind {r}/stage/data/data {r}/data/data && '
                 f'ls -A {r}/data/app | wc -l | sed "s/^/bridged_entries=/" && '
                 f'T= DATA={r}/data STAGE={r}/stage PROC=/proc FAKE_BB={r}/bb '
                 f'sh {self.script} bring-add com.anthropic.claude')
        return subprocess.run(['unshare', '-m', 'sh', '-c', outer], capture_output=True, text=True)

    def test_one_uis_app_is_found_under_the_bridges(self):
        done = self.run_bridged()
        out = done.stdout
        self.assertEqual(0, done.returncode, out + done.stderr)
        self.assertIn('bridged_entries=0', out)
        view = f'{self.r}/stage/incoming/onui_data'
        self.assertIn(f'host={view}', out)
        self.assertIn(f'apk={view}/app/~~c1==/com.anthropic.claude-R==/base.apk', out)
        self.assertIn(f'ce={view}/data/com.anthropic.claude', out)
        self.assertIn('prefs', out)

    def test_the_view_is_read_only(self):
        out = self.run_bridged().stdout
        self.assertIn('READONLY', out)
        self.assertFalse((self.r / 'data/app/written').exists())
        opts = next(l for l in out.splitlines() if l.startswith('opts='))[5:].split(',')
        self.assertIn('ro', opts)
        self.assertIn('nosuid', opts)
        self.assertIn('nodev', opts)

    def test_a_view_left_writable_is_unmounted_and_refused(self):
        done = self.run_bridged('skip-remount')
        out = done.stdout
        self.assertEqual(3, done.returncode, out + done.stderr)
        view = f'{self.r}/stage/incoming/onui_data'
        self.assertIn(f"@@REFUSED could not make One UI's data read only (mountinfo: {view} rw", out)
        self.assertNotIn('left=', out)
        self.assertNotIn('host=', out)
        self.assertNotIn('WRITABLE', out)
        self.assertFalse((self.r / 'data/app/written').exists())

    def test_a_failing_mount_table_lookup_does_not_matter(self):
        # The phone: busybox could not find the view in /proc/mounts.
        done = self.run_bridged('one-arg-fails')
        out = done.stdout
        self.assertEqual(0, done.returncode, out + done.stderr)
        self.assertNotIn("can't find", done.stderr)
        self.assertIn('READONLY', out)
        self.assertIn('prefs', out)

    def test_it_reexecs_once_keeping_the_pid(self):
        out = self.run_bridged().stdout
        line = next(l for l in out.splitlines() if l.startswith('pid='))
        pid, ns = line.split()
        self.assertEqual(pid[4:], ns[3:])

    def test_the_view_goes_with_the_namespace(self):
        self.run_bridged()
        view = self.r / 'stage/incoming/onui_data'
        self.assertEqual([], list(view.iterdir()))


class BringHostViewSourceTest(unittest.TestCase):
    def test_bring_add_opens_the_view_after_its_checks(self):
        body = function('do_bring_add')
        self.assertLess(body.index('is not in the catalog'), body.index('bring_host_view "$1"'))
        self.assertLess(body.index('bring_host_view "$1"'), body.index('bring_one "$1"'))

    def test_the_remount_names_source_and_view(self):
        self.assertIn('"$BB" mount -o remount,bind,ro,nosuid,nodev,noexec "$DATA" "$BV"', function('bring_host_view'))

    def test_tests_never_enter_a_namespace(self):
        self.assertIn('[ -z "$T" ] || return 0', function('bring_host_view'))

    def test_stamp_keeps_one_uis_path(self):
        self.assertIn('"${BRING_HOST:+$DATA}${first#${BRING_HOST:-}}"', SCRIPT)


if __name__ == '__main__':
    unittest.main()
