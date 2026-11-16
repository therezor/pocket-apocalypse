#!/bin/sh
# Build and run the headless host harness (see sim_main.c).
#   tools/host/run_sim.sh            all 10 maps
#   tools/host/run_sim.sh 2 5        just MAP02 and MAP05
#   MOD_TABLES=0 TW_WAD=data/doom2.wad tools/host/run_sim.sh   (stock tables)
set -e
cd "$(dirname "$0")/../.."
mkdir -p build/sim
DEFS="-DMOD_TABLES=1"
HALF="-DHALF_RES_SPRITES=${HALF_RES_SPRITES:-1} -DHALF_RES_FLATS=${HALF_RES_FLATS:-1}"
SRCS=$(ls main/doom/source/*.c)
if [ "${MOD_TABLES:-1}" = "1" ]; then
    SRCS=$(echo "$SRCS" | grep -v -e '/info.c' -e '/d_items.c' -e '/sounds.c')
    SRCS="$SRCS main/doom/mod/info_mod.c main/doom/mod/d_items_mod.c main/doom/mod/sounds_mod.c"
else
    DEFS=""
fi
cc -O1 -g -fsanitize=address,undefined -fno-sanitize=alignment,shift,signed-integer-overflow -w \
   -Wno-error=implicit-function-declaration -Wno-int-conversion -Wno-incompatible-pointer-types \
   $DEFS $HALF ${SIMDEFS} -include main/doom_quiet.h \
   -Itools/host/sim -Imain -Imain/doom/include -Imain/doom/mod \
   -o build/sim/twsim tools/host/sim_main.c main/hal/panel_blit.c $SRCS -lz
build/sim/twsim "$@"
