// Storage: game data in the memory-mapped "wad" flash partition, savegames
// on the microSD card, menu settings in NVS.
#include "hal.h"

#include <M5Unified.h>

#include <esp_timer.h>
#include <esp_vfs_fat.h>
#include <driver/sdspi_host.h>
#include <driver/gpio.h>
#include <nvs_flash.h>
#include <nvs.h>
#include <sys/stat.h>

extern "C" {
#include "doom_iwad.h"
}

extern "C" const uint8_t tw_wad_start[];
extern "C" const uint8_t tw_wad_end[];

int HAL_WadMap(void)
{
    const uint8_t* wad = tw_wad_start;
    const uint32_t size = tw_wad_end - tw_wad_start;

    if(size < 12 || memcmp(wad, "IWAD", 4))
    {
        printf("HAL_WadMap: no IWAD embedded\n");
        return 0;
    }

    uint32_t numlumps, infotableofs;
    memcpy(&numlumps, wad + 4, 4);
    memcpy(&infotableofs, wad + 8, 4);

    doom_iwad = (unsigned char*)wad;
    doom_iwad_len = size;

    printf("HAL_WadMap: %u lumps, %u bytes at %p\n", (unsigned)numlumps, (unsigned)size, wad);
    return 1;
}

// microSD over SPI (pins from M5Unified's Cardputer table).
#define SD_MISO GPIO_NUM_39
#define SD_MOSI GPIO_NUM_14
#define SD_SCLK GPIO_NUM_40
#define SD_CS   GPIO_NUM_12

int HAL_SdMount(void)
{
    // ADV: keep the Cap-bus device on GPIO5 deselected, it shares the SD bus.
    if(M5.getBoard() == m5::board_t::board_M5CardputerADV)
    {
        gpio_reset_pin(GPIO_NUM_5);
        gpio_set_direction(GPIO_NUM_5, GPIO_MODE_OUTPUT);
        gpio_set_level(GPIO_NUM_5, 1);
    }

    sdmmc_host_t host = SDSPI_HOST_DEFAULT();
    host.slot = SPI3_HOST;

    spi_bus_config_t bus = {};
    bus.mosi_io_num = SD_MOSI;
    bus.miso_io_num = SD_MISO;
    bus.sclk_io_num = SD_SCLK;
    bus.quadwp_io_num = -1;
    bus.quadhd_io_num = -1;
    bus.max_transfer_sz = 4096;

    if(spi_bus_initialize(SPI3_HOST, &bus, SPI_DMA_CH_AUTO) != ESP_OK)
        return 0;

    sdspi_device_config_t slot = SDSPI_DEVICE_CONFIG_DEFAULT();
    slot.gpio_cs = SD_CS;
    slot.host_id = SPI3_HOST;

    esp_vfs_fat_sdmmc_mount_config_t mount = {};
    mount.format_if_mount_failed = false;
    mount.max_files = 2;
    mount.allocation_unit_size = 0;

    sdmmc_card_t* card = NULL;

    if(esp_vfs_fat_sdspi_mount("/sd", &host, &slot, &mount, &card) != ESP_OK)
    {
        printf("HAL_SdMount: no SD card, savegames disabled\n");
        spi_bus_free(SPI3_HOST);
        return 0;
    }

    mkdir("/sd/doom", 0777);
    return 1;
}

static nvs_handle_t settings_nvs;

static bool settings_open(void)
{
    if(settings_nvs)
        return true;

    esp_err_t err = nvs_flash_init();

    if(err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND)
    {
        nvs_flash_erase();
        err = nvs_flash_init();
    }

    return err == ESP_OK && nvs_open("doom", NVS_READWRITE, &settings_nvs) == ESP_OK;
}

void HAL_SettingsSave(const void* data, unsigned int size, unsigned int offset)
{
    char key[16];

    if(!settings_open())
        return;

    snprintf(key, sizeof(key), "s%u", offset);
    nvs_set_blob(settings_nvs, key, data, size);
    nvs_commit(settings_nvs);
}

void HAL_SettingsLoad(void* data, unsigned int size, unsigned int offset)
{
    char key[16];
    size_t len = size;

    if(!settings_open())
        return;

    snprintf(key, sizeof(key), "s%u", offset);

    if(nvs_get_blob(settings_nvs, key, data, &len) != ESP_OK || len != size)
        memset(data, 0, size);
}

uint32_t HAL_TimeMs(void)
{
    return (uint32_t)(esp_timer_get_time() / 1000);
}
