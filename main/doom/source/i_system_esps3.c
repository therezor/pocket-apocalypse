#include <stdarg.h>
#include <stdio.h>
#undef printf

#include "doomdef.h"
#include "doomtype.h"
#include "d_main.h"
#include "d_event.h"

#include "global_data.h"

#include "tables.h"

#include "i_system_esps3.h"

#include "hal/hal.h"

#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

//**************************************************************************************

void I_InitScreen_e32()
{
    HAL_VideoInit();
}

//**************************************************************************************

unsigned short* I_GetBackBuffer()
{
    return HAL_VideoBackBuffer();
}

//**************************************************************************************

unsigned short* I_GetFrontBuffer()
{
    return HAL_VideoBackBuffer();
}

//**************************************************************************************

void I_CreateBackBuffer_e32()
{
}

//**************************************************************************************

void I_FinishUpdate_e32(const byte* srcBuffer, const byte* pallete, const unsigned int width, const unsigned int height)
{
    HAL_VideoPresent();
}

//**************************************************************************************

void I_SetPallete_e32(const byte* pallete)
{
    HAL_VideoSetPalette(pallete);
}

//**************************************************************************************

int I_GetVideoWidth_e32()
{
    return 120;
}

//**************************************************************************************

int I_GetVideoHeight_e32()
{
    return SCREENHEIGHT;
}

//**************************************************************************************

void I_ProcessKeyEvents()
{
    unsigned char evt_cp;

    while((evt_cp = HAL_InputPollEvent()) != 0)
    {
        event_t ev;

        ev.type = (evt_cp & 0x80) ? ev_keydown : ev_keyup;
        ev.data1 = evt_cp & 0x7f;
        D_PostEvent(&ev);
    }
}

//**************************************************************************************

#define MAX_MESSAGE_SIZE 256

//Fatal: a missing lump or an exhausted zone must stop here, not run on.
void I_Error (const char *error, ...)
{
    char msg[MAX_MESSAGE_SIZE];
    va_list v;

    va_start(v, error);
    vsnprintf(msg, sizeof(msg), error, v);
    va_end(v);

    printf("I_Error: %s\n", msg);
    HAL_VideoShowError(msg);

    while(1)
        vTaskDelay(portMAX_DELAY);
}

//**************************************************************************************

void I_Quit_e32()
{
}
