#include "doom_iwad.h"

//Set by the platform layer (main/hal/storage_e32.cpp) before doom_main():
//points at the game data embedded in the app image (main/wad_data.S).
unsigned char * doom_iwad;
unsigned int doom_iwad_len;
