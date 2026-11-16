// Force-included into every engine file (see main/CMakeLists.txt).
// The port is full of debug printf()s, several on per-frame and per-sound
// paths; build with -DDOOM_VERBOSE to get them back.
#pragma once
#include <stdio.h>

#ifndef DOOM_VERBOSE
#define printf(...) ((void)0)
#endif
