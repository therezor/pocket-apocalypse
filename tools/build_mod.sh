#!/bin/sh
# Build a game for the Cardputer from a mod profile:
#   tools/build_mod.sh tools/mods/d4v_scythe.json
#   tools/build_mod.sh tools/mods/twilight.json
# 1. bake the profile's DeHackEd patches into main/doom/mod/ (deh2c.py)
# 2. build the trimmed game data data/game.wad (build_wad.py)
# 3. build build/twilight_warrior.bin with the data embedded
# Then install it with tools/launcher_install.py (M5Launcher, over USB).
set -e
cd "$(dirname "$0")/.."
PROFILE=${1:?usage: tools/build_mod.sh tools/mods/<profile>.json}
python3 -I tools/deh2c.py --profile "$PROFILE"
python3 -I tools/build_wad.py --profile "$PROFILE"
. tools/idf_env.sh
if [ ! -f build/build.ninja ]; then
    cmake -S . -B build -G Ninja -DIDF_TARGET=esp32s3 -DPYTHON="$IDF_PYTHON_ENV_PATH/bin/python" -DSDKCONFIG=build/sdkconfig
fi
ninja -C build
