#!/usr/bin/env bash
# Usage: SPCOMP=/path/to/addons/sourcemod/scripting/spcomp64 ./scripts/build_plugins.sh
set -euo pipefail
cd "$(dirname "$0")/../sourcemod/scripting"
: "${SPCOMP:?set SPCOMP to spcomp64 path (SourceMod 1.12)}"
SMINC="$(dirname "$SPCOMP")/include"
mkdir -p ../plugins
for sp in *.sp; do
  "$SPCOMP" -i"$SMINC" -iinclude "$sp" -o "../plugins/${sp%.sp}.smx"
done
