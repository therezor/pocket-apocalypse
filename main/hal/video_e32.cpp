// Video: 240x160 palette-indexed engine framebuffer -> 240x135 ST7789.
//
// Native resolution: palette -> RGB565 (panel_blit.c), pushed in strips with
// DMA while the next strip is converted.
#include "hal.h"

#include <M5Unified.h>
#include <esp_heap_caps.h>

#include "panel_blit.h"

#define STRIP_ROWS 15   // 135 = 9 strips

static uint8_t* framebuffer;                    // HAL_FB_WIDTH * HAL_FB_HEIGHT
static uint16_t* strip_buf[2];

void HAL_VideoInit(void)
{
    if(framebuffer)
        return;

    framebuffer = (uint8_t*)heap_caps_malloc(HAL_FB_WIDTH * HAL_FB_HEIGHT, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);

    for(int i = 0; i < 2; i++)
        strip_buf[i] = (uint16_t*)heap_caps_malloc(PANEL_W * STRIP_ROWS * sizeof(uint16_t), MALLOC_CAP_DMA);

    if(!framebuffer || !strip_buf[0] || !strip_buf[1])
    {
        printf("HAL_VideoInit: out of memory\n");
        abort();
    }

    memset(framebuffer, 0, HAL_FB_WIDTH * HAL_FB_HEIGHT);

    M5.Display.setRotation(1);
    M5.Display.fillScreen(TFT_BLACK);
}

unsigned short* HAL_VideoBackBuffer(void)
{
    return (unsigned short*)framebuffer;
}

void HAL_VideoSetPalette(const uint8_t* rgb)
{
    panel_set_palette(rgb);
}

void HAL_VideoPresent(void)
{
    M5.Display.startWrite();

    int b = 0;

    for(int y = 0; y < PANEL_H; y += STRIP_ROWS)
    {
        // The DMA of the other buffer may still run; this one finished
        // before the previous pushImageDMA started.
        panel_convert(strip_buf[b], framebuffer, y, STRIP_ROWS);
        M5.Display.pushImageDMA(0, y, PANEL_W, STRIP_ROWS, (const lgfx::swap565_t*)strip_buf[b]);
        b ^= 1;
    }

    M5.Display.endWrite();
}
void HAL_VideoShowError(const char* msg)
{
    M5.Display.waitDMA();
    M5.Display.fillScreen(TFT_BLACK);
    M5.Display.setTextColor(TFT_RED, TFT_BLACK);
    M5.Display.setTextSize(1);
    M5.Display.setCursor(0, 0);
    M5.Display.println("FATAL:");
    M5.Display.setTextColor(TFT_WHITE, TFT_BLACK);
    M5.Display.println(msg);
}
