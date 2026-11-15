#!/bin/bash
# usage: buildapk.sh <projectdir> <out.apk>   (project: AndroidManifest.xml, src/, optional res/)
set -e
P=/Applications/Unity/Hub/Editor/6000.3.18f1/PlaybackEngines/AndroidPlayer
export JAVA_HOME=$P/OpenJDK PATH=$P/OpenJDK/bin:$PATH
BT=$P/SDK/build-tools/36.0.0; AJ=$P/SDK/platforms/android-34/android.jar
HERE=$(cd "$(dirname "$0")" && pwd); cd "$1"; B=build; rm -rf $B; mkdir -p $B/cls $B/dex
RES=""; if [ -d res ]; then $BT/aapt2 compile --dir res -o $B/res.zip; RES=$B/res.zip; fi
ASSETS=""; [ -d assets ] && ASSETS="-A assets"
$BT/aapt2 link -o $B/base.apk --manifest AndroidManifest.xml -I $AJ $ASSETS $RES ${RES:+--java $B/gen}
SRCS=$(find src -name '*.java'); [ -d $B/gen ] && SRCS="$SRCS $(find $B/gen -name '*.java')"
javac -nowarn -source 11 -target 11 -classpath $AJ -d $B/cls $SRCS 2>&1 | grep -vE "^warning|^Note|bootstrap" || true
$BT/d8 --lib $AJ --min-api 29 --output $B/dex $(find $B/cls -name '*.class')
cp $B/base.apk $B/u.apk; (cd $B/dex && zip -q ../u.apk classes.dex)
$BT/zipalign -f 4 $B/u.apk $B/a.apk
$BT/apksigner sign --ks "$HERE/debug.keystore" --ks-pass pass:android --out "$2" $B/a.apk
echo built "$2"
