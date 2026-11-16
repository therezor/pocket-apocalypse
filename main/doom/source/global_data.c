#include <stdlib.h>
#include <stdio.h>
#include "global_data.h"

#include "z_zone.h"
#include <esp_heap_caps.h>


globals_t* _g = NULL;

// Heap left for malloc()s after startup (savegame files on the SD card).
#define HEAP_KEEP (12 * 1024)

// Drawsegs live outside the zone: Z_Init has taken the largest free block,
// so they come from the smaller heap regions the zone can't use.
static void InitDrawsegs(void)
{
    const unsigned caps = MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT;
    int n = MAXDRAWSEGS;

    while (n > MINDRAWSEGS &&
           (heap_caps_get_largest_free_block(caps) < n * sizeof(drawseg_t) ||
            heap_caps_get_free_size(caps) < n * sizeof(drawseg_t) + HEAP_KEEP))
        n -= 32;

    _g->drawsegs = heap_caps_malloc(n * sizeof(drawseg_t), caps);

    if (!_g->drawsegs)
    {
        n = MINDRAWSEGS;
        _g->drawsegs = Z_Malloc(n * sizeof(drawseg_t), PU_STATIC, NULL);
    }
    _g->maxdrawsegs = n;

    fprintf(stderr, "drawsegs %d, heap left %u (largest %u)\n", n,
            (unsigned)heap_caps_get_free_size(caps), (unsigned)heap_caps_get_largest_free_block(caps));
}

void InitGlobals()
{
    _g = Z_Malloc(sizeof(globals_t), PU_STATIC, NULL);

    memset(_g, 0, sizeof(globals_t));

    #include "global_init.h"

    InitDrawsegs();
}
