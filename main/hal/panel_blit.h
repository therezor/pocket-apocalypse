// Engine framebuffer (240x135 palette indices, same size as the panel) ->
// RGB565 panel rows. Portable C: used by video_e32.cpp on the device and by
// the host simulator.
#ifndef PANEL_BLIT_H
#define PANEL_BLIT_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define PANEL_W 240
#define PANEL_H 135

void panel_set_palette(const uint8_t* rgb);        // 256 * RGB

// Convert rows [y0, y0 + rows) into dst (RGB565, big-endian as the ST7789
// wants it), PANEL_W pixels per row.
void panel_convert(uint16_t* dst, const uint8_t* fb, int y0, int rows);

// Same, little-endian RGB565 (host previews).
void panel_convert_native(uint16_t* dst, const uint8_t* fb, int y0, int rows);

#ifdef __cplusplus
}
#endif

#endif
