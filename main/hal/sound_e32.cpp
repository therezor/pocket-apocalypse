// Sound: the engine's mixer runs in a task on core 1 and streams blocks to
// M5.Speaker (NS4168 amp on the original Cardputer, ES8311 codec on the ADV;
// M5Unified handles both).
#include "hal.h"

#include <M5Unified.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

#define SPEAKER_CHANNEL 0
#define NUM_BUFFERS 3   // one being mixed + playing + queued in M5.Speaker

static hal_mix_fn mixer;
static int16_t* buffers[NUM_BUFFERS];

static void sound_task(void*)
{
    int b = 0;

    for(;;)
    {
        // playRaw() keeps a pointer to the buffer: refill one only after it
        // left the speaker's queue (isPlaying: 1 = playing, 2 = also queued).
        while(M5.Speaker.isPlaying(SPEAKER_CHANNEL) >= 2)
            vTaskDelay(1);

        mixer(buffers[b], HAL_SOUND_BLOCK);
        M5.Speaker.playRaw(buffers[b], HAL_SOUND_BLOCK, HAL_SOUND_RATE, false, 1, SPEAKER_CHANNEL, false);

        b = (b + 1) % NUM_BUFFERS;
    }
}

void HAL_SoundStart(hal_mix_fn mix)
{
    mixer = mix;

    for(int i = 0; i < NUM_BUFFERS; i++)
        buffers[i] = (int16_t*)heap_caps_calloc(HAL_SOUND_BLOCK, sizeof(int16_t), MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);

    auto cfg = M5.Speaker.config();
    cfg.task_pinned_core = 1;
    cfg.sample_rate = 22050;
    M5.Speaker.config(cfg);
    M5.Speaker.begin();
    M5.Speaker.setVolume(160);

    xTaskCreatePinnedToCore(sound_task, "doom_snd", 6144, NULL, 5, NULL, 1);
}
