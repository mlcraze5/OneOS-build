#!/bin/sh
# Build a ColorOS set's SystemUI_wave.dex and ColorPanoramicSystemUI.apk from its stock SystemUI.apk.
# Usage: [APKTOOL="java -jar apktool.jar"] scripts/make-coloros-wave-set.sh <stock SystemUI.apk> <out dir>
#
# x9u-in-1105-sultra's two files were first built on a machine whose tree was lost; this rebuilds
# them from the repo alone (apktool 2.9.3 on the November image's stock SystemUI 620aff68… gives the
# pinned c0bf8bb1 and d9ce350d of set r5; r4's patch gave 02fc1190 and 6dc45991). The wave dex is
# the fingerprint-wave patch's dex, as in make-systemui-wave.sh. The merged APK is the same decoded tree with make-coloros-panoramic-aod.py's
# two smali edits on top, so one APK carries both: its wave+AOD dex and the dex with DozeService go
# into the stock APK with apk-replace-dex.py, which keeps the signing block where PackageManager
# looks for it.
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
patch_file="$root/switcher/patches/systemui-fingerprint-wave/systemui-fingerprint-wave.patch"
[ $# -eq 2 ] || { echo "usage: [APKTOOL=...] $0 <stock SystemUI.apk> <out dir>" >&2; exit 2; }
stock=$1
out=$2
apktool=${APKTOOL:-apktool}
[ -f "$stock" ] || { echo "no such APK: $stock" >&2; exit 1; }
mkdir -p "$out"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

# smali -> classes.dex, smali_classesN -> classesN.dex
dex_of() {
    case $1 in
        smali) echo classes.dex ;;
        smali_classes[0-9]*) echo "classes${1#smali_classes}.dex" ;;
        *) echo "not a smali dir: $1" >&2; return 1 ;;
    esac
}

# The fingerprint wave touches one dex; take it from the patch rather than assume classes3.
wave_dirs=$(sed -n 's|^+++ b/\([^/]*\)/.*|\1|p' "$patch_file" | sort -u)
[ "$(printf '%s\n' "$wave_dirs" | wc -l)" -eq 1 ] || {
    echo "the wave patch touches more than one smali dir: $wave_dirs" >&2; exit 1; }
wave_dex=$(dex_of "$wave_dirs")

$apktool d -f --no-res -o "$work/dec" "$stock" >/dev/null
patch -p1 -d "$work/dec" < "$patch_file" >/dev/null
$apktool b "$work/dec" -o "$work/r1.apk" >/dev/null
unzip -p "$work/r1.apk" "$wave_dex" > "$out/SystemUI_wave.dex"

# Wallpaper AOD on the same tree: patch_smali and patch_doze, each on the one smali file that
# defines its class; prints the dex each lands in.
aod_dexes=$(python3 - "$root/scripts/make-coloros-panoramic-aod.py" "$work/dec" <<'EOF'
import glob, importlib.util, os, sys
spec = importlib.util.spec_from_file_location('panoramic_aod', sys.argv[1])
aod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(aod)
dec = sys.argv[2]
for rel, fn in (('com/oplus/systemui/aod/display/SmoothTransitionController.smali', aod.patch_smali),
                ('com/android/systemui/doze/DozeService.smali', aod.patch_doze)):
    hits = glob.glob(os.path.join(dec, 'smali*', rel))
    if len(hits) != 1:
        sys.exit(f'{rel}: {len(hits)} matches in {dec}')
    with open(hits[0]) as f:
        text = f.read()
    with open(hits[0], 'w') as f:
        f.write(fn(text))
    print(os.path.relpath(hits[0], dec).split(os.sep)[0])
EOF
)
$apktool b "$work/dec" -o "$work/r2.apk" >/dev/null

# The wave dex first, then each further dex the AOD edits touched, in the order they were patched.
dexes=$wave_dex
for d in $aod_dexes; do
    n=$(dex_of "$d")
    case " $dexes " in *" $n "*) ;; *) dexes="$dexes $n" ;; esac
done
cur=$stock
k=0
for n in $dexes; do
    unzip -p "$work/r2.apk" "$n" > "$work/$n"
    k=$((k + 1))
    python3 "$root/scripts/apk-replace-dex.py" "$cur" "$n" "$work/$n" "$work/step$k.apk" >/dev/null
    cur=$work/step$k.apk
done
cp "$cur" "$out/ColorPanoramicSystemUI.apk"

sha256sum "$out/SystemUI_wave.dex" "$out/ColorPanoramicSystemUI.apk"
