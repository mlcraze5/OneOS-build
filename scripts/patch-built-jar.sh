#!/bin/sh
# Apply one more smali patcher to an already-built guard jar (a set's
# services_patched.jar), without the guest image: decode the jar, run the
# patcher, rebuild, and put only the dex files the patcher names into a copy of
# the jar (the same step as make-overlays.sh; every other entry stays byte for
# byte). For sets whose image is no longer on the server.
#
# Usage: scripts/patch-built-jar.sh <built jar> <patcher.py> <out jar>
set -e
JAR="$1"; PATCHER="$2"; OUT="$3"
[ -f "$JAR" ] && [ -f "$PATCHER" ] && [ -n "$OUT" ] || { echo "usage: $0 <built jar> <patcher.py> <out jar>" >&2; exit 2; }
ROOT=$(cd "$(dirname "$0")/.." && pwd)
APKTOOL=${APKTOOL:-$(ls "$ROOT"/mysticgsi/tools/apktool/*.jar 2>/dev/null | head -1)}
JAR=$(realpath "$JAR"); PATCHER=$(realpath "$PATCHER"); OUT=$(realpath -m "$OUT")
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
java -jar "$APKTOOL" d -q -f -r -o "$W/src" "$JAR"
# smali 3 refuses the hidden-API "blacklist" flags below API 29, and framework
# jars still declare minSdkVersion 28 (as make-overlays.sh's decode does).
sed -i 's/^  minSdkVersion: .*/  minSdkVersion: 29/' "$W/src/apktool.yml"
DIRS=$(python3 -I "$PATCHER" "$W/src")
[ -n "$DIRS" ] || { echo "$PATCHER changed nothing" >&2; exit 1; }
java -jar "$APKTOOL" b -q -o "$W/rebuilt.jar" "$W/src"
cp "$JAR" "$W/out.jar"
for d in $DIRS; do
    DEX="$(echo "$d" | sed 's/^smali_//; s/^smali$/classes/').dex"
    rm -rf "$W/dex" && mkdir -p "$W/dex"
    unzip -q -o "$W/rebuilt.jar" "$DEX" -d "$W/dex"
    # apktool stamps the dex it rebuilds with the wall clock, so re-running this
    # otherwise reproducible step (the dex bytes are deterministic) would change
    # only that one zip entry's mtime and so the jar's sha256. Honour
    # SOURCE_DATE_EPOCH (set it to pin a release jar's hash); unset, the dex keeps
    # its build-time mtime as before.
    python3 - "$W/out.jar" "$W/dex/$DEX" "$DEX" <<'PY'
import os, sys, time, zipfile
jar, dex, name = sys.argv[1:4]
tmp = jar + ".tmp"
sde = os.environ.get("SOURCE_DATE_EPOCH")
with zipfile.ZipFile(jar) as src, zipfile.ZipFile(tmp, "w") as dst:
    for entry in src.infolist():
        if entry.filename != name:
            dst.writestr(entry, src.read(entry.filename))
    if sde:
        zi = zipfile.ZipInfo.from_file(dex, name)
        zi.date_time = time.gmtime(int(sde))[:6]  # UTC, so the pin is TZ-independent
        zi.compress_type = zipfile.ZIP_STORED
        with open(dex, "rb") as fh:
            dst.writestr(zi, fh.read())
    else:
        dst.write(dex, name, compress_type=zipfile.ZIP_STORED)
os.replace(tmp, jar)
PY
    echo "replaced $DEX"
done
python3 "$ROOT/scripts/check-dex.py" "$W/out.jar" >&2 || true
mv "$W/out.jar" "$OUT"
echo "built $OUT"
