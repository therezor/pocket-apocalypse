/* Emacs style mode select   -*- C++ -*-
 *-----------------------------------------------------------------------------
 *
 *
 *  PrBoom: a Doom port merged with LxDoom and LSDLDoom
 *  based on BOOM, a modified and improved DOOM engine
 *  Copyright (C) 1999 by
 *  id Software, Chi Hoang, Lee Killough, Jim Flynn, Rand Phares, Ty Halderman
 *  Copyright (C) 1999-2000 by
 *  Jess Haas, Nicolas Kalkhof, Colin Phipps, Florian Schulze
 *  Copyright 2005, 2006 by
 *  Florian Schulze, Colin Phipps, Neil Stevens, Andrey Budko
 *
 *  This program is free software; you can redistribute it and/or
 *  modify it under the terms of the GNU General Public License
 *  as published by the Free Software Foundation; either version 2
 *  of the License, or (at your option) any later version.
 *
 *  This program is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.
 *
 *  You should have received a copy of the GNU General Public License
 *  along with this program; if not, write to the Free Software
 *  Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA
 *  02111-1307, USA.
 *
 * DESCRIPTION:
 *  System interface for sound.
 *
 *-----------------------------------------------------------------------------
 */

#include <stdint.h>
#include <string.h>

#include "doomtype.h"
#include "z_zone.h"
#include "i_sound.h"
#include "w_wad.h"
#include "lprintf.h"
#include "s_sound.h"
#include "doomdef.h"
#include "doomstat.h"
#include "d_main.h"

#include "global_data.h"
#include "oplplayer.h"

#include "hal/hal.h"

#include <freertos/FreeRTOS.h>

// Music is OPL2 emulation (dbopl) rendered on core 1 with the SFX mix.
// Set to 0 to save CPU on core 1.
#ifndef DOOM_MUSIC
#define DOOM_MUSIC 1
#endif

static const music_player_t *music_player = &opl_synth_player;
static volatile boolean musicPlaying = false;
static volatile int musicVolume = 15;   // _g does not exist yet when the mixer starts
static const void* registeredSong;      // one song at a time; the int handle is just 1

int snd_card = 1;
int mus_card = DOOM_MUSIC;
int snd_samplerate = HAL_SOUND_RATE;

#define NUM_MIX_CHANNELS 8

// One playing sound effect. Written by the game (core 0), read by the mixer
// (core 1); every access goes through snd_lock.
typedef struct
{
    const uint8_t* data;    // unsigned 8-bit PCM, DMX header already skipped
    uint32_t length;        // samples
    uint32_t pos;           // 16.16 sample position
    uint32_t step;          // 16.16 source samples per output sample
    int vol;                // 0..127
    int id;                 // sfx id, 0 when free
    int handle;
    int starttic;
} mix_channel_t;

static mix_channel_t mixch[NUM_MIX_CHANNELS];
static portMUX_TYPE snd_lock = portMUX_INITIALIZER_UNLOCKED;
static int next_handle = 1;

// Decoded DMX lumps, filled once by I_InitSound (the data stays in flash).
static const uint8_t* sfx_data[NUMSFX];
static uint32_t sfx_len[NUMSFX];
static uint32_t sfx_step[NUMSFX];

static void I_DecodeSfx(int lump, const uint8_t** data, uint32_t* len, uint32_t* step)
{
    const uint8_t* p = (const uint8_t*)W_CacheLumpNum(lump);
    int size = W_LumpLength(lump);

    *data = NULL;
    *len = 0;
    *step = FRACUNIT;

    if(size < 8 || p[0] != 3 || p[1] != 0)
        return;

    unsigned int rate = p[2] | (p[3] << 8);
    uint32_t count = p[4] | (p[5] << 8) | (p[6] << 16) | ((uint32_t)p[7] << 24);

    if(count > (uint32_t)(size - 8))
        count = size - 8;

    p += 8;

    // DMX pads each sound with 16 samples on both ends.
    if(count > 32)
    {
        p += 16;
        count -= 32;
    }

    if(!rate)
        rate = HAL_SOUND_RATE;

    *data = p;
    *len = count;
    *step = (uint32_t)(((uint64_t)rate << FRACBITS) / HAL_SOUND_RATE);
}

static int I_SfxLump(const sfxinfo_t* sfx)
{
    char name[9];

    snprintf(name, sizeof(name), "ds%s", sfx->name);

    int lump = W_CheckNumForName(name);

    return lump >= 0 ? lump : W_CheckNumForName("dspistol");
}

int I_GetSfxLumpNum(sfxinfo_t* sfx)
{
    return I_SfxLump(sfx);
}

void I_SetChannels(void)
{
}

int I_StartSound(int id, int channel, int vol, int sep, int pitch, int priority)
{
    if(id <= 0 || id >= NUMSFX || !sfx_data[id])
        return -1;

    if(vol > 127)
        vol = 127;

    portENTER_CRITICAL(&snd_lock);

    int slot = -1;

    // Chainsaw & co. play one at a time.
    if(id == sfx_sawup || id == sfx_sawidl || id == sfx_sawful ||
       id == sfx_sawhit || id == sfx_stnmov || id == sfx_pistol)
    {
        for(int i = 0; i < NUM_MIX_CHANNELS; i++)
        {
            if(mixch[i].id == id)
            {
                slot = i;
                break;
            }
        }
    }

    if(slot < 0)
    {
        int oldest = 0;

        for(int i = 0; i < NUM_MIX_CHANNELS; i++)
        {
            if(!mixch[i].id)
            {
                slot = i;
                break;
            }

            if(mixch[i].starttic < mixch[oldest].starttic)
                oldest = i;
        }

        if(slot < 0)
            slot = oldest;
    }

    mix_channel_t* c = &mixch[slot];

    c->data = sfx_data[id];
    c->length = sfx_len[id];
    c->pos = 0;
    c->step = sfx_step[id];
    c->vol = vol;
    c->id = id;
    c->starttic = _g->gametic;
    c->handle = next_handle++;

    if(next_handle > 0x7fffff)
        next_handle = 1;

    int handle = c->handle;

    portEXIT_CRITICAL(&snd_lock);

    return handle;
}

static mix_channel_t* I_FindChannel(int handle)
{
    for(int i = 0; i < NUM_MIX_CHANNELS; i++)
        if(mixch[i].id && mixch[i].handle == handle)
            return &mixch[i];

    return NULL;
}

void I_StopSound(int handle)
{
    portENTER_CRITICAL(&snd_lock);

    mix_channel_t* c = I_FindChannel(handle);

    if(c)
        c->id = 0;

    portEXIT_CRITICAL(&snd_lock);
}

int I_SoundIsPlaying(int handle)
{
    portENTER_CRITICAL(&snd_lock);

    int playing = I_FindChannel(handle) != NULL;

    portEXIT_CRITICAL(&snd_lock);

    return playing;
}

int I_AnySoundStillPlaying(void)
{
    int playing = 0;

    portENTER_CRITICAL(&snd_lock);

    for(int i = 0; i < NUM_MIX_CHANNELS; i++)
        playing |= mixch[i].id;

    portEXIT_CRITICAL(&snd_lock);

    return playing != 0;
}

void I_UpdateSoundParams(int handle, int vol, int sep, int pitch)
{
    if(vol > 127)
        vol = 127;

    portENTER_CRITICAL(&snd_lock);

    mix_channel_t* c = I_FindChannel(handle);

    if(c)
        c->vol = vol;

    portEXIT_CRITICAL(&snd_lock);
}

// Mixer, runs on core 1 from the HAL sound task.
static int16_t music_buf[HAL_SOUND_BLOCK * 2];

static void I_MixSound(int16_t* out, int samples)
{
    int32_t acc[HAL_SOUND_BLOCK];
    mix_channel_t local[NUM_MIX_CHANNELS];

    memset(acc, 0, sizeof(int32_t) * samples);

    portENTER_CRITICAL(&snd_lock);
    memcpy(local, mixch, sizeof(local));
    portEXIT_CRITICAL(&snd_lock);

    for(int i = 0; i < NUM_MIX_CHANNELS; i++)
    {
        mix_channel_t* c = &local[i];

        if(!c->id)
            continue;

        const uint8_t* data = c->data;
        uint32_t pos = c->pos;
        const uint32_t end = c->length << FRACBITS;
        const uint32_t step = c->step;
        const int vol = c->vol;

        for(int s = 0; s < samples; s++)
        {
            if(pos >= end)
            {
                c->id = 0;
                break;
            }

            acc[s] += ((int)data[pos >> FRACBITS] - 128) * vol;
            pos += step;
        }

        c->pos = pos;
    }

    // Write back positions unless the game restarted the channel meanwhile.
    portENTER_CRITICAL(&snd_lock);

    for(int i = 0; i < NUM_MIX_CHANNELS; i++)
    {
        if(mixch[i].id && mixch[i].handle == local[i].handle)
        {
            mixch[i].pos = local[i].pos;

            if(!local[i].id)
                mixch[i].id = 0;
        }
    }

    portEXIT_CRITICAL(&snd_lock);

    if(musicPlaying && musicVolume > 0)
    {
        // Stereo s16; both channels carry the same signal.
        music_player->render(music_buf, samples);

        for(int s = 0; s < samples; s++)
            acc[s] += music_buf[s * 2];
    }

    for(int s = 0; s < samples; s++)
    {
        int32_t v = acc[s];

        if(v > 32767)
            v = 32767;
        else if(v < -32768)
            v = -32768;

        out[s] = (int16_t)v;
    }
}

void I_InitSound(void)
{
    lprintf(LO_INFO, "I_InitSound: ");

    for(int i = 1; i < NUMSFX; i++)
    {
        const sfxinfo_t* sfx = &S_sfx[i];

        // Alias? Example is the chaingun sound linked to pistol.
        if(sfx->link)
            sfx = sfx->link;

        int lump = I_SfxLump(sfx);

        if(lump >= 0)
            I_DecodeSfx(lump, &sfx_data[i], &sfx_len[i], &sfx_step[i]);
    }

    if(mus_card)
    {
        if(music_player->init(snd_samplerate))
        {
            music_player->setvolume(musicVolume);
        }
        else
        {
            lprintf(LO_INFO, "I_InitSound: music init failed");
            mus_card = 0;
        }
    }

    HAL_SoundStart(I_MixSound);

    lprintf(LO_INFO, "I_InitSound: sound module ready");
}

void I_ShutdownSound(void)
{
    if(mus_card)
        music_player->shutdown();
}

void I_ShutdownMusic(void)
{
    if(mus_card)
        music_player->shutdown();
}

void I_InitMusic(void)
{
}

void I_PlaySong(int handle, int looping)
{
    if(!mus_card)
        return;

    music_player->play(registeredSong, looping);
    musicPlaying = true;
}

void I_PauseSong (int handle)
{
    if(!mus_card)
        return;

    music_player->pause();
    musicPlaying = false;
}

void I_ResumeSong (int handle)
{
    if(!mus_card)
        return;

    music_player->resume();
    musicPlaying = true;
}

void I_StopSong(int handle)
{
    if(!mus_card)
        return;

    musicPlaying = false;
    music_player->stop();
}

void I_UnRegisterSong(int handle)
{
    if(mus_card && registeredSong)
        music_player->unregistersong(registeredSong);

    registeredSong = NULL;
}

// Music lumps are converted to MIDI at WAD build time (tools/wadconverter).
int I_RegisterSong(const void *data, size_t len)
{
    if(!mus_card)
        return 0;

    registeredSong = music_player->registersong(data, len);

    return registeredSong ? 1 : 0;
}

int I_RegisterMusic( const char* filename, musicinfo_t *song )
{
    return 1;
}

void I_SetMusicVolume(int volume)
{
    musicVolume = volume;

    if(mus_card)
        music_player->setvolume(volume);
}
