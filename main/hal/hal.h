// Platform layer between the GBADoom engine (C) and the Cardputer hardware.
// Implemented in main/hal/*.cpp on top of M5Unified.
#ifndef HAL_H
#define HAL_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// Engine framebuffer geometry: GBADoom renders 120 columns, each stored as a
// doubled byte pair (one unsigned short), so the buffer is 240x135 bytes of
// palette indices: exactly the panel.
#define HAL_FB_WIDTH  240
#define HAL_FB_HEIGHT 135

// Video (video_e32.cpp)
void            HAL_VideoInit(void);
unsigned short* HAL_VideoBackBuffer(void);
void            HAL_VideoSetPalette(const uint8_t* rgb);    // 256 * RGB
void            HAL_VideoPresent(void);
void            HAL_VideoShowError(const char* msg);

// Input (input_e32.cpp). Returns 0 when the queue is empty, otherwise
// (pressed << 7) | keycode, keycode being ASCII or one of the K_* codes
// from g_game.c.
void    HAL_InputInit(void);
uint8_t HAL_InputPollEvent(void);

// Sound (sound_e32.cpp). Starts a task on core 1 that repeatedly calls
// mix(out, HAL_SOUND_BLOCK) and streams the result to the speaker.
#define HAL_SOUND_RATE  11025
#define HAL_SOUND_BLOCK 256
typedef void (*hal_mix_fn)(int16_t* out, int samples);
void HAL_SoundStart(hal_mix_fn mix);

// Storage (storage_e32.cpp)
int  HAL_WadMap(void);          // points doom_iwad at the embedded game data
int  HAL_SdMount(void);         // mounts the microSD card at /sd (savegames)
void HAL_SettingsSave(const void* data, unsigned int size, unsigned int offset);
void HAL_SettingsLoad(void* data, unsigned int size, unsigned int offset);

// Gyro aim (gyro_e32.cpp; Cardputer ADV IMU, a no-op without one).
// Turn / look accumulated since the last call: angleturn in ticcmd units
// (65536 = full turn, + left), look in screen rows (+ up). held: the gyro
// key is down (pauses aim, or with hold_aims enables it).
typedef struct
{
    uint8_t on;             // gyro aim enabled
    uint8_t turn;           // 0..HAL_GYRO_STEPS: view degrees per device degree x2 (0: no turning)
    uint8_t look;           // the same for looking up / down
    uint8_t invert_turn;
    uint8_t invert_look;
    uint8_t hold_aims;      // gyro key: 0 = hold pauses aim, 1 = aim only while held
} hal_gyro_config_t;

#define HAL_GYRO_STEPS 10

void HAL_GyroInit(void);
void HAL_GyroRead(int* angleturn, int* look, int held);
int  HAL_GyroAvailable(void);
hal_gyro_config_t* HAL_GyroConfig(void);    // live settings; the menu edits them
void HAL_GyroSaveConfig(void);
int  HAL_GyroCalibrate(void);               // ~0.4 s held still; 0 if it moved

// Time
uint32_t HAL_TimeMs(void);

#ifdef __cplusplus
}
#endif

#endif
