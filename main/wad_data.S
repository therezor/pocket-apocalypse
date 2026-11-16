// Game data (data/game.wad from tools/build_wad.py) embedded in the app image,
// so M5Launcher can install the whole game as one .bin. It is read in place
// through the flash cache like any other rodata; lumps need 4-byte alignment.
    .section .rodata.tw_wad, "a"
    .balign 16
    .global tw_wad_start
tw_wad_start:
    .incbin GAME_WAD_FILE
    .global tw_wad_end
tw_wad_end:
    .balign 4
