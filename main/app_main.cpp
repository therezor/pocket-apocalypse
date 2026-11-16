// Twilight Warrior for M5Stack Cardputer / Cardputer ADV.
//
// Boot order: M5Unified (display, power, board detection) -> keyboard ->
// SD card (savegames) -> memory-map the game data -> GBADoom main loop.
#include <M5Unified.h>

#include "hal/hal.h"

extern "C" int doom_main(int argc, const char* const* argv);

static void fatal(const char* msg)
{
    printf("%s\n", msg);
    HAL_VideoShowError(msg);

    for(;;)
        vTaskDelay(portMAX_DELAY);
}

extern "C" void app_main(void)
{
    auto cfg = M5.config();
    cfg.internal_imu = true;    // gyro aim (Cardputer ADV)
    cfg.internal_mic = false;
    M5.begin(cfg);
    M5.Display.setBrightness(128);

    HAL_VideoInit();
    HAL_InputInit();
    HAL_GyroInit();
    HAL_SdMount();

    if(!HAL_WadMap())
        fatal("No game data embedded.\nRun tools/build_wad.py and rebuild.");

    printf("Free internal heap before doom_main: %u (largest block %u)\n",
           (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
           (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL));

    doom_main(0, NULL);
}
