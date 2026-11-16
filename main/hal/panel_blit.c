// See panel_blit.h. The engine renders at the panel's native 240x135, so this
// is a straight palette lookup, two pixels per 32-bit word.
#include "panel_blit.h"

static uint16_t pal565[256];                    // native RGB565

void panel_set_palette(const uint8_t* rgb)
{
    for(int i = 0; i < 256; i++, rgb += 3)
        pal565[i] = (uint16_t)(((rgb[0] & 0xf8) << 8) | ((rgb[1] & 0xfc) << 3) | (rgb[2] >> 3));
}

static inline uint32_t swap2(uint32_t v)
{
    return ((v & 0xFF00FF00u) >> 8) | ((v & 0x00FF00FFu) << 8);
}

static void convert(uint16_t* dst, const uint8_t* fb, int y0, int rows, int swap)
{
    const uint8_t* s = fb + y0 * PANEL_W;
    uint32_t* d = (uint32_t*)dst;

    for(int i = 0; i < rows * PANEL_W; i += 2)
    {
        uint32_t v = pal565[s[i]] | ((uint32_t)pal565[s[i + 1]] << 16);
        *d++ = swap ? swap2(v) : v;
    }
}

void panel_convert(uint16_t* dst, const uint8_t* fb, int y0, int rows)
{
    convert(dst, fb, y0, rows, 1);
}

void panel_convert_native(uint16_t* dst, const uint8_t* fb, int y0, int rows)
{
    convert(dst, fb, y0, rows, 0);
}
