/* Headless host harness: runs the device engine against data/game.wad.
 *
 *   tools/host/run_sim.sh [maps...]
 *
 * For each map: start it on "Hurt me plenty" in god mode, walk forward and
 * fire for a while, log zone usage and renderer peaks, write a screenshot
 * (build/sim/MAPxx.png). Exits non-zero on I_Error. Pointers are 64-bit
 * here, so zone usage reads higher than on the ESP32. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <zlib.h>

#include "hal/hal.h"
#include "hal/panel_blit.h"
#include "doomdef.h"
#include "doomstat.h"
#include "d_event.h"
#include "g_game.h"
#include "z_zone.h"
#include "global_data.h"
#include "doom_iwad.h"
#include "tables.h"
#include "p_mobj.h"
#include "p_pspr.h"
#include "info.h"
#include "r_defs.h"
#include "w_wad.h"
#include "d_englsh.h"

#undef printf   /* doom_quiet.h is force-included everywhere */

#define K_OPT 0x07
#define K_CTRL 0x06
#define K_ENT 0x05

extern int doom_main(int argc, const char* const* argv);
extern boolean P_TeleportMove(mobj_t* thing, fixed_t x, fixed_t y, boolean boss);

static uint8_t fb[HAL_FB_WIDTH * HAL_FB_HEIGHT];
static uint8_t pal[768];
static uint32_t now_ms;
static int frame;

static int maps[32];
static int nmaps, cur;
static int map_frame;
static int peak_used;

#define FRAMES_PER_MAP 1000

/* newlib extras the engine uses that macOS libc lacks */
char* itoa(int v, char* buf, int base)
{
    sprintf(buf, base == 16 ? "%x" : "%d", v);
    return buf;
}

char* strupr(char* s)
{
    for(char* p = s; *p; p++)
        if(*p >= 'a' && *p <= 'z')
            *p -= 32;
    return s;
}

size_t heap_caps_get_largest_free_block(unsigned caps)
{
    /* SIM_HEAP_KB caps the zone like the device's heap does (host structs
       are ~1.5x the device's, so scale a device figure up before use). */
    return (getenv("SIM_HEAP_KB") ? atoi(getenv("SIM_HEAP_KB")) : 560) * 1024;
}

size_t heap_caps_get_free_size(unsigned caps)
{
    return 64 * 1024;
}

void HAL_VideoInit(void) {}
unsigned short* HAL_VideoBackBuffer(void) { return (unsigned short*)fb; }
void HAL_VideoSetPalette(const uint8_t* rgb) { memcpy(pal, rgb, 768); panel_set_palette(rgb); }
void HAL_VideoShowError(const char* msg) { fprintf(stderr, "FATAL: %s\n", msg); exit(2); }
void HAL_SoundStart(hal_mix_fn mix) {}
int HAL_WadMap(void) { return 1; }
int HAL_SdMount(void) { return 0; }
void HAL_SettingsSave(const void* d, unsigned s, unsigned o) {}
void HAL_SettingsLoad(void* d, unsigned s, unsigned o) { memset(d, 0, s); }
void HAL_InputInit(void) {}
void HAL_GyroInit(void) {}
void HAL_GyroRead(int* t, int* l, int held) { *t = 0; *l = 0; }
static hal_gyro_config_t gyro_cfg = { 1, 5, 5, 0, 0, 0 };
int HAL_GyroAvailable(void) { return 0; }
hal_gyro_config_t* HAL_GyroConfig(void) { return &gyro_cfg; }
void HAL_GyroSaveConfig(void) {}
int HAL_GyroCalibrate(void) { return 0; }
/* The game loop polls the clock while waiting for the next tic, so time has
 * to move on every call or it spins forever. */
uint32_t HAL_TimeMs(void) { return now_ms += 2; }

static uint8_t pending[8];
static int npending;

uint8_t HAL_InputPollEvent(void)
{
    if(!npending)
        return 0;
    uint8_t e = pending[0];
    memmove(pending, pending + 1, --npending);
    return e;
}

static void key(uint8_t code, int down)
{
    if(npending < 8)
        pending[npending++] = (down ? 0x80 : 0) | code;
}

static void put32(FILE* f, uint32_t v)
{
    uint8_t b[4] = {v >> 24, v >> 16, v >> 8, v};
    fwrite(b, 1, 4, f);
}

static void chunk(FILE* f, const char* type, const uint8_t* data, uint32_t len)
{
    put32(f, len);
    uint8_t* buf = malloc(len + 4);
    memcpy(buf, type, 4);
    memcpy(buf + 4, data, len);
    fwrite(buf, 1, len + 4, f);
    put32(f, crc32(0, buf, len + 4));
    free(buf);
}

static void screenshot(const char* path)
{
    /* What the 240x135 panel shows (same conversion as the device), 2x. */
    static uint16_t panel[PANEL_W * PANEL_H];
    panel_convert_native(panel, fb, 0, PANEL_H);
    int w = PANEL_W * 2, h = PANEL_H * 2;
    size_t rawlen = (size_t)h * (1 + w * 3);
    uint8_t* raw = malloc(rawlen);
    for(int y = 0; y < h; y++)
    {
        uint8_t* r = raw + y * (1 + w * 3);
        *r++ = 0;
        for(int x = 0; x < w; x++)
        {
            uint16_t c = panel[(y / 2) * PANEL_W + x / 2];
            *r++ = (c >> 8) & 0xf8; *r++ = (c >> 3) & 0xfc; *r++ = (c << 3) & 0xf8;
        }
    }
    uLongf zlen = compressBound(rawlen);
    uint8_t* z = malloc(zlen);
    compress(z, &zlen, raw, rawlen);
    FILE* f = fopen(path, "wb");
    fwrite("\x89PNG\r\n\x1a\n", 1, 8, f);
    uint8_t ihdr[13] = {0, 0, w >> 8, w & 255, 0, 0, h >> 8, h & 255, 8, 2, 0, 0, 0};
    chunk(f, "IHDR", ihdr, 13);
    chunk(f, "IDAT", z, zlen);
    chunk(f, "IEND", NULL, 0);
    fclose(f);
    free(raw);
    free(z);
}

void HAL_VideoPresent(void)
{
    frame++;
    map_frame++;
    now_ms += 29;   /* ~1 tic per frame */

    /* VIDEO=1: every frame of the title and the first VIDEO_FRAMES (560)
       frames of each map -> build/sim/video/NNNNN.png (~35 fps, ffmpeg it) */
    if(getenv("VIDEO") && (cur == 0 || (_g->gamestate == GS_LEVEL &&
        map_frame < (getenv("VIDEO_FRAMES") ? atoi(getenv("VIDEO_FRAMES")) : 560))))
    {
        static int vframe;
        char p_[48];
        snprintf(p_, sizeof p_, "build/sim/video/%05d.png", vframe++);
        screenshot(p_);
    }

    if(cur == 0 && map_frame == 50)
        screenshot("build/sim/title.png");

    if(cur == 0 && map_frame == 60)
    {
        G_DeferedInitNew(sk_medium, 1, maps[0]);
        map_frame = 0;
        cur = 1;
        return;
    }

    if(cur == 0)
        return;

    if(_g->gamestate == GS_LEVEL)
    {
        int used, total;
        Z_GetStats(&used, &total);
        if(used > peak_used)
            peak_used = used;

        _g->player.cheats |= CF_GODMODE;
        if(_g->player.health < 100)
            _g->player.health = _g->player.mo->health = 100;

        /* walk, shoot, turn, jump (Cardputer layout: ; fwd, ctrl fire, / turn, space jump) */
        if(map_frame < 560 && !getenv("WEAPONTEST") && !getenv("MAGTEST") && !getenv("GORETEST") && !getenv("SHOWTEST") && !getenv("BOOMTEST") && !getenv("VIEWAT") && !getenv("MENUTEST"))
        {
            if(map_frame % 70 == 5) { key(';', 1); key(K_CTRL, 1); }
            if(map_frame % 70 == 40) { key(';', 0); key(K_CTRL, 0); key('/', 1); key(' ', 1); }
            if(map_frame % 70 == 55) { key('/', 0); key(' ', 0); }
            if(map_frame % 70 == 60) key('e', 1);       /* next weapon */
            if(map_frame % 70 == 62) key('e', 0);
        }
    }

    /* every map: a view before any menu opens */
    if(map_frame == 300)
    {
        char path[64];
        snprintf(path, sizeof(path), "build/sim/MAP%02d_view.png", _g->gamemap);
        screenshot(path);
    }

    /* first map only: look up + screenshot, then the menu */
    if(cur == 1)
    {
        if(map_frame == 570) key('q', 1);
        if(map_frame == 590) key('q', 0);
        if(map_frame == 600) screenshot("build/sim/look.png");
        if(map_frame == 610) key('s', 1);
        if(map_frame == 612) key('s', 0);
        if(map_frame == 640) key('`', 1);
        if(map_frame == 642) key('`', 0);
        if(map_frame == 660) screenshot("build/sim/menu.png");
        if(map_frame == 662) key(K_ENT, 1);
        if(map_frame == 664) key(K_ENT, 0);
        if(map_frame == 675) screenshot("build/sim/menu_skill.png");
        if(map_frame == 680) key('`', 1);
        if(map_frame == 682) key('`', 0);
        if(map_frame == 684) key('`', 1);
        if(map_frame == 686) key('`', 0);
    }

    /* VIEWAT="x,y,deg;x,y,deg...": stand at each spot facing deg (0 = east,
       90 = north) and screenshot it (build/sim/viewatMM_N.png) */
    if(getenv("VIEWAT") && _g->gamestate == GS_LEVEL && map_frame >= 10)
    {
        const char* s = getenv("VIEWAT");
        int n = (map_frame - 10) / 20, t = (map_frame - 10) % 20, x, y, deg;

        for(int i = 0; i < n && s; i++)
            s = strchr(s, ';') ? strchr(s, ';') + 1 : NULL;
        if(s && sscanf(s, "%d,%d,%d", &x, &y, &deg) == 3)
        {
            if(t == 0)
            {
                extern void P_MapEnd(void);
                P_TeleportMove(_g->player.mo, x << FRACBITS, y << FRACBITS, false);
                P_MapEnd();     /* clears tmthing for the next tic's P_MapStart */
                _g->player.mo->angle = (angle_t)((long long)deg * 0x100000000LL / 360);
            }
            if(getenv("VIEWWALK") && (t == 1 || t == 8))   /* step forward: picks things up */
                key(';', t == 1);
            if(t == 15)
            {
                char p_[48];
                snprintf(p_, sizeof p_, "build/sim/viewat%02d_%d.png", maps[cur - 1], n);
                screenshot(p_);
                printf("viewat %d: owned", n);
                for(int w = 0; w < NUMWEAPONS; w++)
                    if(_g->player.weaponowned[w])
                        printf(" %d", w);
                printf(", ready %d, ammo", _g->player.readyweapon);
                for(int a = 0; a < NUMAMMO; a++)
                    printf(" %d", _g->player.ammo[a]);
                printf("\n");
            }
        }
        else if(!s && t == 0)
            map_frame = FRAMES_PER_MAP - 1;
        if(s)
            return;
    }

    /* MENUTEST=1: Options, Controls (scrolled, rebinding Jump to J), Gyro Aim
       screenshots (build/sim/menu_*.png); one step every 6 frames */
    if(getenv("MENUTEST") && cur >= 1 && map_frame >= 30)
    {
        static const struct { int key; const char* shot; } steps[] = {
            {'`', 0}, {'.', 0}, {K_ENT, "menu_options"},
            {'.', 0}, {'.', 0}, {'.', 0}, {'.', 0}, {'.', 0}, {'.', 0}, {K_ENT, "menu_controls"},
            {'.', 0}, {'.', 0}, {'.', 0}, {'.', 0}, {'.', 0}, {'.', 0}, {'.', 0}, {'.', 0}, {'.', 0},
            {'.', 0}, {K_ENT, "menu_bindwait"}, {'j', "menu_bound"},
            {'.', 0}, {'.', 0}, {'.', 0}, {'.', 0}, {'.', 0}, {'.', 0}, {'.', 0}, {'.', 0}, {'.', 0},
            {'.', "menu_controls_end"}, {K_ENT, "menu_reset"},
            {K_CTRL, 0}, {'.', 0}, {K_ENT, "menu_gyro"}, {'/', 0}, {'.', 0}, {'/', 0}, {'/', 0}, {'.', 0},
            {'.', 0}, {'.', 0}, {'.', 0}, {K_ENT, "menu_gyro2"},
        };
        const int n = sizeof(steps) / sizeof(steps[0]);
        int k = (map_frame - 30) / 6, t = (map_frame - 30) % 6;

        if(k < n)
        {
            if(t == 0) key(steps[k].key, 1);
            if(t == 1) key(steps[k].key, 0);
            if(t == 5 && steps[k].shot)
            {
                char p_[48];
                snprintf(p_, sizeof p_, "build/sim/%s.png", steps[k].shot);
                screenshot(p_);
            }
        }
        else if(k == n && t == 0)
            map_frame = FRAMES_PER_MAP - 1;
        return;
    }

    /* MAGTEST=1: hold fire with the starting weapon through a magazine, then
       press R; log the magazine and screenshot the reload */
    /* GORETEST=1: a zombieman 96 units ahead, shot (blood) then killed
       (death burst + floor pool), screenshots of each */
    if(getenv("GORETEST") && _g->gamestate == GS_LEVEL)
    {
        extern mobj_t* P_SpawnMobj(fixed_t x, fixed_t y, fixed_t z, mobjtype_t type);
        extern void P_DamageMobj(mobj_t *target, mobj_t *inflictor, mobj_t *source, int damage);
        extern void P_SpawnBlood(fixed_t x, fixed_t y, fixed_t z, int damage);
        static mobj_t* victim;
        const int f = map_frame;
        mobj_t* pl = _g->player.mo;

        if(f == 30)
        {
            const unsigned an = pl->angle >> ANGLETOFINESHIFT;
            victim = P_SpawnMobj(pl->x + 96 * finecosine[an], pl->y + 96 * finesine[an], ONFLOORZ, MT_POSSESSED);
        }
        if(victim && f >= 40 && f < 52 && !(f & 3))
            P_SpawnBlood(victim->x, victim->y, victim->z + 32 * FRACUNIT, 10);
        if(victim && f == 44)
            { char p_[48]; snprintf(p_, sizeof p_, "build/sim/gore%02d_hit.png", maps[cur - 1]); screenshot(p_); }
        if(victim && f == 60)
            P_DamageMobj(victim, pl, pl, 1000);
        if(f == 64)
            { char p_[48]; snprintf(p_, sizeof p_, "build/sim/gore%02d_death.png", maps[cur - 1]); screenshot(p_); }
        if(f == 140)
            { char p_[48]; snprintf(p_, sizeof p_, "build/sim/gore%02d_pool.png", maps[cur - 1]); screenshot(p_); }
    }

    /* SHOWTEST=1: three humans killed by a normal death 160 units ahead and a
       row of pickups at 96, screenshot once the corpses settle */
    if(getenv("SHOWTEST") && _g->gamestate == GS_LEVEL)
    {
        extern mobj_t* P_SpawnMobj(fixed_t x, fixed_t y, fixed_t z, mobjtype_t type);
        extern void P_DamageMobj(mobj_t *target, mobj_t *inflictor, mobj_t *source, int damage);
        static const mobjtype_t body[3] = {MT_POSSESSED, MT_SHOTGUY, MT_CHAINGUY};
        static const mobjtype_t item[5] = {MT_CLIP, MT_MISC22, MT_MISC11, MT_MISC10, MT_MISC0};
        static mobj_t* dead[8];
        mobj_t* pl = _g->player.mo;
        const unsigned an = pl->angle >> ANGLETOFINESHIFT;
        const fixed_t c = finecosine[an], s = finesine[an];

        if(map_frame == 30)
        {
            if(getenv("LOWDETAIL"))
                _g->highDetail = 0;
            const char* only = getenv("SHOWONLY") ? getenv("SHOWONLY") : "";
            for(int i = 0; i < 3 && strcmp(only, "items"); i++)
                dead[i] = P_SpawnMobj(pl->x + 200 * c - (i - 1) * 56 * s, pl->y + 200 * s + (i - 1) * 56 * c, ONFLOORZ, body[i]);
            for(int i = 0; i < 5 && strcmp(only, "bodies"); i++)
                dead[3 + i] = P_SpawnMobj(pl->x + 96 * c - (i - 2) * 24 * s, pl->y + 96 * s + (i - 2) * 24 * c, ONFLOORZ, item[i]);
        }
        if(map_frame == 40)
            for(int i = 0; i < 3; i++)
                if(dead[i])
                    P_DamageMobj(dead[i], pl, pl, dead[i]->health);
        if(map_frame == 140)
        {
            char p_[48];
            snprintf(p_, sizeof p_, "build/sim/show%02d.png", maps[cur - 1]);
            screenshot(p_);
            for(int i = 0; i < 8; i++)
                if(dead[i])
                {
                    const spriteframe_t* sf = &_g->sprites[dead[i]->sprite].spriteframes[dead[i]->frame & FF_FRAMEMASK];
                    printf("show: type %d sprite %d frame %d lump %s\n", dead[i]->type, dead[i]->sprite,
                           dead[i]->frame & FF_FRAMEMASK, W_GetNameForNum(sf->lump[0] + _g->firstspritelump));
                }
        }
    }

    /* BOOMTEST=1: a barrel shot 160 units ahead-left and a rocket bursting in
       mid-air ahead-right, screenshots through the explosion */
    if(getenv("BOOMTEST") && _g->gamestate == GS_LEVEL)
    {
        extern mobj_t* P_SpawnMobj(fixed_t x, fixed_t y, fixed_t z, mobjtype_t type);
        extern void P_DamageMobj(mobj_t *target, mobj_t *inflictor, mobj_t *source, int damage);
        extern void P_ExplodeMissile(mobj_t* mo);
        static mobj_t* barrel;
        mobj_t* pl = _g->player.mo;
        const unsigned an = pl->angle >> ANGLETOFINESHIFT;
        const fixed_t c = finecosine[an], s = finesine[an];

        if(map_frame == 30)
        {
            barrel = P_SpawnMobj(pl->x + 220 * c + 70 * s, pl->y + 220 * s - 70 * c, ONFLOORZ, MT_BARREL);
            mobj_t* r = P_SpawnMobj(pl->x + 220 * c - 70 * s, pl->y + 220 * s + 70 * c, pl->z + 32 * FRACUNIT, MT_ROCKET);
            P_DamageMobj(barrel, pl, pl, 100);
            P_ExplodeMissile(r);
        }
        if(map_frame == 31 || map_frame == 35 || map_frame == 40 || map_frame == 46 || map_frame == 54)
            { char p_[48]; snprintf(p_, sizeof p_, "build/sim/boom_%d.png", map_frame); screenshot(p_); }
    }

    if(getenv("MAGTEST") && _g->gamestate == GS_LEVEL)
    {
        int f = map_frame;
        if(f == 30) key(0x06, 1);
        if(f == 230) key(0x06, 0);
        if(f == 260) key('r', 1);
        if(f == 262) key('r', 0);
        if(f % 10 == 0 && f >= 30 && f <= 330)
        {
            printf("magtest %d: weapon %d mag %d ammo %d state %d\n", f, _g->player.readyweapon,
                   _g->player.mag[_g->player.readyweapon], _g->player.ammo[0],
                   _g->player.psprites[0].state ? (int)(_g->player.psprites[0].state - states) : -1);
            fflush(stdout);
        }
        if(f == 40 || f == 120 || f == 140 || f == 160 || f == 280)
        {
            char path[64];
            snprintf(path, sizeof(path), "build/sim/mag_%d.png", f);
            screenshot(path);
        }
    }

    /* WEAPONTEST=1: idkfa, then select and fire every weapon: each slot key
       pressed again moves to the slot's next weapon (extras included) */
    if(getenv("WEAPONTEST") && cur >= 1 && _g->gamestate == GS_LEVEL)
    {
        static const char cheat[] = "idkfa";
        const char* keys = getenv("WEAPONKEYS") ? getenv("WEAPONKEYS") : "112333344556677";
        int f = map_frame - 20;
        const int n = (int)strlen(keys);

        if(f >= 0 && f < 10)
            key(cheat[f / 2], (f & 1) == 0);
        else if(f >= 20 && f < 20 + n * 60)
        {
            int k = (f - 20) / 60, t = (f - 20) % 60;

            if(t == 0)
            {
                key(keys[k], 1);
                printf("weapon %d: key %c\n", k, keys[k]);
                fflush(stdout);
            }
            if(t == 2) key(keys[k], 0);
            if(t == 20) key(0x06, 1);   /* ctrl: fire */
            char tbuf[8];
            snprintf(tbuf, sizeof tbuf, ",%d,", t);
            if(getenv("WEAPONSHOTS") ? strstr(getenv("WEAPONSHOTS"), tbuf) != NULL     /* ",21,22,23," */
                                     : (t == 16 || t == 24 || t == 30 || t == 44))
            {
                char path[64];
                snprintf(path, sizeof(path), "build/sim/weapon%02d_%d.png", k, t);
                screenshot(path);
            }
            if(t == 30)
            {
                printf("weapon %d: ready %d\n", k, _g->player.readyweapon);
                fflush(stdout);
            }
            if(t == 50) key(0x06, 0);
            if(getenv("PSPDEBUG") && t >= 20 && t <= 50)
            {
                const pspdef_t* ps = &_g->player.psprites[0];
                printf("t %d: state %d sprite %d frame %d sx %d sy %d\n", t, ps->state ? (int)(ps->state - states) : -1,
                       ps->state ? ps->state->sprite : -1, ps->state ? ps->state->frame & 0x7fff : -1, ps->sx >> 16, ps->sy >> 16);
            }
        }
    }

    /* UITEST=1: leave each map at frame 40, screenshot the stats, press fire,
       screenshot "next stop" and any text screen (MAP06 interlude, ending).
       UITEST=msg: the nightmare prompt over the view */
    if(getenv("UITEST"))
    {
        extern void G_ExitLevel(void);
        extern void M_StartMessage(const char *string, void *routine, boolean input);
        static int ui_frame, fin_frame;
        const int msg = !strcmp(getenv("UITEST"), "msg");

        if(map_frame == 1)
            ui_frame = fin_frame = 0;
        if(msg && _g->gamestate == GS_LEVEL && map_frame == 20)
            M_StartMessage(NIGHTMARE, NULL, true);
        if(msg && map_frame == 26)
            screenshot("build/sim/ui_msg.png");
        if(msg && map_frame == 28)
            key(K_ENT, 1);
        if(msg && map_frame == 30)
        {
            key(K_ENT, 0);
            _g->player.message = GOTBACKPACK;
        }
        if(msg && map_frame == 34)
            screenshot("build/sim/ui_hudmsg.png");
        if(msg && map_frame >= 40 && map_frame < 50 && !(map_frame & 1))
        {
            extern void M_ChangeGamma(int choice);
            M_ChangeGamma(1);       /* brightness up to 5: PLAYPAL1..5 */
            if(map_frame == 40)
                screenshot("build/sim/ui_gamma0.png");
        }
        if(msg && map_frame == 52)
            screenshot("build/sim/ui_gamma5.png");
        if(!msg && _g->gamestate == GS_LEVEL && map_frame == 40)
            G_ExitLevel();
        if(!msg && map_frame > 40)
        {
            char p_[48];
            ui_frame++;
            if(ui_frame == 170)
                { snprintf(p_, sizeof p_, "build/sim/ui_stats%02d.png", maps[cur - 1]); screenshot(p_); }
            if(ui_frame == 180 || ui_frame == 186) key(K_CTRL, 1);
            if(ui_frame == 182 || ui_frame == 188) key(K_CTRL, 0);
            if(ui_frame == 200)
                { snprintf(p_, sizeof p_, "build/sim/ui_next%02d.png", maps[cur - 1]); screenshot(p_); }
            if(_g->gamestate == GS_FINALE && !fin_frame)
                fin_frame = ui_frame;
            if(fin_frame && ui_frame == fin_frame + 900)
                { snprintf(p_, sizeof p_, "build/sim/ui_text%02d.png", maps[cur - 1]); screenshot(p_); }
        }
        if(map_frame < 1400)
            return;
    }

    if(map_frame == FRAMES_PER_MAP || map_frame == 1400)
    {
        extern int r_overflow_drawsegs, r_overflow_openings, r_peak_drawsegs;
        printf("render limits: drawsegs peak %d/%d, overflows: drawsegs %d openings %d\n", r_peak_drawsegs,
               _g->maxdrawsegs, r_overflow_drawsegs, r_overflow_openings);
        r_peak_drawsegs = r_overflow_drawsegs = r_overflow_openings = 0;
        char path[64];
        int used, total;
        Z_GetStats(&used, &total);
        snprintf(path, sizeof(path), "build/sim/MAP%02d.png", maps[cur - 1]);
        screenshot(path);
        printf("MAP%02d ok: gamestate %d, zone used %d (peak %d) of %d, kills %d/%d -> %s\n",
               maps[cur - 1], _g->gamestate, used, peak_used, total,
               _g->player.killcount, _g->totalkills, path);
        fflush(stdout);
#ifdef SIM_TRACE_MEM
        { extern void Z_DumpBlocks(void); Z_DumpBlocks(); }
#endif
        peak_used = 0;

        if(cur == nmaps)
            exit(0);

        npending = 0;
        key(';', 0); key(K_CTRL, 0); key('/', 0); key(' ', 0);
        G_DeferedInitNew(sk_medium, 1, maps[cur]);
        cur++;
        map_frame = 0;
    }
}

int main(int argc, char** argv)
{
    const char* wad = getenv("TW_WAD") ? getenv("TW_WAD") : "data/game.wad";
    FILE* f = fopen(wad, "rb");
    if(!f) { perror(wad); return 1; }
    fseek(f, 0, SEEK_END);
    long len = ftell(f);
    rewind(f);
    doom_iwad = malloc(len);
    fread(doom_iwad, 1, len, f);
    fclose(f);
    doom_iwad_len = len;

    for(int i = 1; i < argc && nmaps < 32; i++)
        maps[nmaps++] = atoi(argv[i]);
    if(!nmaps)
        for(int i = 1; i <= 10; i++)
            maps[nmaps++] = i;

    doom_main(0, NULL);
    return 0;
}
