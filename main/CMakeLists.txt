file(GLOB DOOM_SRCS ${CMAKE_CURRENT_LIST_DIR}/doom/source/*.c)

# MOD_TABLES=ON (default): use the tables tools/deh2c.py generated from the
# mod profile's DeHackEd patches (main/doom/mod/) instead of stock Doom II.
# tools/build_mod.sh <profile> regenerates them and the embedded data.
option(MOD_TABLES "Use the generated mod tables in main/doom/mod" ON)
set(MOD_DIR ${CMAKE_CURRENT_LIST_DIR}/doom/mod)

if(MOD_TABLES)
    foreach(f info d_items sounds)
        if(NOT EXISTS ${MOD_DIR}/${f}_mod.c)
            message(FATAL_ERROR "${MOD_DIR}/${f}_mod.c missing: run tools/build_mod.sh <profile>")
        endif()
        list(REMOVE_ITEM DOOM_SRCS ${CMAKE_CURRENT_LIST_DIR}/doom/source/${f}.c)
        list(APPEND DOOM_SRCS ${MOD_DIR}/${f}_mod.c)
    endforeach()
endif()

idf_component_register(
    SRCS
        app_main.cpp
        wad_data.S
        hal/video_e32.cpp
        hal/panel_blit.c
        hal/input_e32.cpp
        hal/gyro_e32.cpp
        hal/sound_e32.cpp
        hal/storage_e32.cpp
        keyboard/Keyboard.cpp
        keyboard/KeyboardReader/IOMatrix.cpp
        keyboard/KeyboardReader/TCA8418.cpp
        keyboard/Adafruit_TCA8418/Adafruit_TCA8418.cpp
        ${DOOM_SRCS}
    INCLUDE_DIRS . doom/include doom/mod
    PRIV_REQUIRES esp_timer driver sdmmc fatfs vfs nvs_flash esp_partition spi_flash
)

# The engine is C89-era code full of benign warnings; keep them out of -Werror.
set_source_files_properties(${DOOM_SRCS} PROPERTIES COMPILE_OPTIONS
    "-include;${CMAKE_CURRENT_LIST_DIR}/doom_quiet.h;-Wno-error;-Wno-error=incompatible-pointer-types;-Wno-error=implicit-function-declaration;-Wno-error=int-conversion;-Wno-incompatible-pointer-types;-Wno-unused-variable;-Wno-unused-function;-Wno-pointer-sign;-Wno-implicit-fallthrough;-Wno-char-subscripts;-Wno-parentheses;-Wno-missing-field-initializers;-Wno-sign-compare;-Wno-format")

# Renderer inner loops.
set_source_files_properties(${CMAKE_CURRENT_LIST_DIR}/doom/source/r_hotpath.iwram.c PROPERTIES COMPILE_OPTIONS
    "-include;${CMAKE_CURRENT_LIST_DIR}/doom_quiet.h;-O3;-Wno-error;-Wno-error=incompatible-pointer-types;-Wno-error=implicit-function-declaration;-Wno-error=int-conversion;-Wno-incompatible-pointer-types;-Wno-unused-variable;-Wno-unused-function;-Wno-pointer-sign;-Wno-implicit-fallthrough;-Wno-char-subscripts;-Wno-parentheses;-Wno-sign-compare;-Wno-format")

if(MOD_TABLES)
    target_compile_definitions(${COMPONENT_LIB} PRIVATE MOD_TABLES=1)
endif()

# Half-resolution sprites/flats so code + data fit next to M5Launcher; must
# match the flags data/tw.wad was built with (checked at startup).
option(HALF_RES_SPRITES "Sprites stored at half resolution" ON)
option(HALF_RES_FLATS "Flats stored at 32x32" ON)
target_compile_definitions(${COMPONENT_LIB} PRIVATE
    HALF_RES_SPRITES=$<BOOL:${HALF_RES_SPRITES}> HALF_RES_FLATS=$<BOOL:${HALF_RES_FLATS}>)

# Embedded game data (tools/build_wad.py -> data/game.wad).
set(GAME_WAD_FILE "${CMAKE_CURRENT_LIST_DIR}/../data/game.wad" CACHE FILEPATH "Game data to embed")
if(NOT EXISTS ${GAME_WAD_FILE})
    message(FATAL_ERROR "${GAME_WAD_FILE} missing: run tools/build_wad.py")
endif()
set_source_files_properties(${CMAKE_CURRENT_LIST_DIR}/wad_data.S PROPERTIES
    COMPILE_DEFINITIONS "GAME_WAD_FILE=\"${GAME_WAD_FILE}\""
    OBJECT_DEPENDS ${GAME_WAD_FILE})
