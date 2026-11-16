// Input: Cardputer keyboard (IO matrix on the original, TCA8418 on the ADV)
// -> key up/down events for the engine.
#include "hal.h"

#include "keyboard/Keyboard.h"

#include <M5Unified.h>
#include <string.h>

// Engine key codes for the non-printing keys (match g_game.c).
#define K_BKSP  0x01
#define K_TAB   0x02
#define K_FN    0x03
#define K_SHIFT 0x04
#define K_ENT   0x05
#define K_CTRL  0x06
#define K_OPT   0x07
#define K_ALT   0x08

#define KB_ROWS 4
#define KB_COLS 14

// Physical key -> engine key code (see g_game.c for what each code does).
// Backspace is an alias of ` (menu / back).
static const uint8_t keymap[KB_ROWS][KB_COLS] = {
    {'`',   '1',     '2',  '3', '4', '5', '6', '7', '8', '9', '0', '-',  '=',  '`'},
    {K_TAB, 'q',     'w',  'e', 'r', 't', 'y', 'u', 'i', 'o', 'p', '[',  ']',  '\\'},
    {K_FN,  K_SHIFT, 'a',  's', 'd', 'f', 'g', 'h', 'j', 'k', 'l', ';',  '\'', K_ENT},
    {K_CTRL, K_OPT,  K_ALT, 'z', 'x', 'c', 'v', 'b', 'n', 'm', ',', '.',  '/',  ' '},
};

static Keyboard_Class keyboard;
static bool key_down[KB_ROWS][KB_COLS];

#define QUEUE_SIZE 32
static uint8_t queue[QUEUE_SIZE];
static unsigned int q_head, q_tail;

static void push_event(uint8_t evt)
{
    unsigned int next = (q_tail + 1) % QUEUE_SIZE;

    if(next != q_head)
    {
        queue[q_tail] = evt;
        q_tail = next;
    }
}

static void scan(void)
{
    bool now[KB_ROWS][KB_COLS];

    memset(now, 0, sizeof(now));

    keyboard.updateKeyList();

    for(const auto& k : keyboard.keyList())
    {
        if(k.x >= 0 && k.x < KB_COLS && k.y >= 0 && k.y < KB_ROWS)
            now[k.y][k.x] = true;
    }

    for(int y = 0; y < KB_ROWS; y++)
    {
        for(int x = 0; x < KB_COLS; x++)
        {
            if(now[y][x] != key_down[y][x])
            {
                key_down[y][x] = now[y][x];
                push_event((now[y][x] ? 0x80 : 0) | (keymap[y][x] & 0x7f));
            }
        }
    }
}

void HAL_InputInit(void)
{
    keyboard.begin();
}

uint8_t HAL_InputPollEvent(void)
{
    if(q_head == q_tail)
        scan();

    if(q_head == q_tail)
        return 0;

    uint8_t evt = queue[q_head];
    q_head = (q_head + 1) % QUEUE_SIZE;

    return evt;
}
