// See m_font.h.
#include <string.h>

#include "doomdef.h"
#include "doomtype.h"
#include "w_wad.h"
#include "global_data.h"

#include "m_font.h"
#include "m_font_data.h"

#define FB_W 240

static byte colors[MF_NUMCOLORS];
static byte ramps[MF_NUMCOLORS][4];   // MFONT ink levels 1..3 of each colour
static byte darken[256];        // palette index -> darker shade
static boolean ready;

// A mod's own menu font (lump MFONT, tools/ui_art.py), else the built-in
// 8x16 one: "MF", cell height, glyph count (codes 32..), the widths, then
// each glyph's width x height ink levels (0 clear, 1..3 dim to full).
static const byte* mfont_widths;
static const byte* mfont_glyph[96];
static int mfont_h, mfont_count;

static byte nearest(const byte* pal, int r, int g, int b)
{
    int best = 0, bestd = 1 << 30;

    for(int i = 0; i < 256; i++)
    {
        int dr = pal[i*3] - r, dg = pal[i*3+1] - g, db = pal[i*3+2] - b;
        int d = dr*dr*3 + dg*dg*4 + db*db*2;

        if(d < bestd)
        {
            bestd = d;
            best = i;
        }
    }

    return (byte)best;
}

static void MF_Init(void)
{
    const byte* pal = W_CacheLumpName("PLAYPAL");

    colors[MF_WHITE]  = nearest(pal, 235, 235, 235);
    colors[MF_GREY]   = nearest(pal, 150, 150, 150);
    colors[MF_YELLOW] = nearest(pal, 255, 210, 60);
    colors[MF_RED]    = nearest(pal, 220, 40, 30);
    colors[MF_BLACK]  = nearest(pal, 0, 0, 0);
    colors[MF_DARK]   = nearest(pal, 20, 20, 24);

    for(int i = 0; i < 256; i++)
        darken[i] = nearest(pal, pal[i*3] / 3, pal[i*3+1] / 3, pal[i*3+2] / 3);

    for(int c = 0; c < MF_NUMCOLORS; c++)
    {
        const byte* rgb = pal + colors[c] * 3;

        ramps[c][3] = colors[c];
        ramps[c][2] = nearest(pal, rgb[0] * 3 / 4, rgb[1] * 3 / 4, rgb[2] * 3 / 4);
        ramps[c][1] = nearest(pal, rgb[0] / 2, rgb[1] / 2, rgb[2] / 2);
    }

    const int lump = W_CheckNumForName("MFONT");

    if(lump >= 0)
    {
        const byte* d = W_CacheLumpNum(lump);

        mfont_h = d[2];
        mfont_count = d[3] > 96 ? 96 : d[3];
        mfont_widths = d + 4;

        const byte* g = d + 4 + d[3];

        for(int i = 0; i < mfont_count; i++)
        {
            mfont_glyph[i] = g;
            g += mfont_widths[i] * mfont_h;
        }
    }

    ready = true;
}

int MF_Color(mf_color_t c)
{
    if(!ready)
        MF_Init();

    return colors[c];
}

static int MF_Advance(unsigned char c)
{
    if(mfont_widths)
        return (c >= 32 && c - 32 < mfont_count) ? mfont_widths[c - 32] : 0;

    return MF_CHAR_W;
}

int MF_TextWidth(const char* s)
{
    int w = 0, line = 0;

    if(!ready)
        MF_Init();

    for(; *s; s++)
    {
        if(*s == '\n')
        {
            line = 0;
            continue;
        }

        line += MF_Advance((unsigned char)*s);

        if(line > w)
            w = line;
    }

    return w;
}

int MF_TextHeight(const char* s)
{
    int lines = 1;

    for(; *s; s++)
        if(*s == '\n')
            lines++;

    return lines * MF_LINE_H;
}

// ramp[1..3]: the colours of ink levels 1..3 (all one colour for shadows)
static void MF_DrawGlyphs(int x, int y, const char* s, const byte* ramp)
{
    byte* fb = (byte*)_g->screens[0].data;
    const byte color = ramp[3];
    int cx = x;

    for(; *s; s++)
    {
        unsigned char c = (unsigned char)*s;

        if(c == '\n')
        {
            cx = x;
            y += MF_LINE_H;
            continue;
        }

        if(mfont_widths)
        {
            const int w = MF_Advance(c);

            if(w)
            {
                const byte* g = mfont_glyph[c - 32];

                for(int r = 0; r < mfont_h; r++)
                {
                    const int py = y + r;

                    if(py < 0 || py >= SCREENHEIGHT)
                        continue;

                    for(int b = 0; b < w; b++)
                    {
                        const int px = cx + b;
                        const byte v = g[r * w + b];

                        if(v && px >= 0 && px < FB_W)
                            fb[py * FB_W + px] = ramp[v];
                    }
                }
            }

            cx += w;
            continue;
        }

        if(c >= 32 && c < 127)
        {
            const unsigned char* g = mfont8x16[c - 32];

            for(int r = 0; r < MF_CHAR_H; r++)
            {
                int py = y + r - 1;     // glyph rows 0/15 are blank: shift up one

                if(py < 0 || py >= SCREENHEIGHT || !g[r])
                    continue;

                for(int b = 0; b < 8; b++)
                {
                    int px = cx + b;

                    if((g[r] & (0x80 >> b)) && px >= 0 && px < FB_W)
                        fb[py * FB_W + px] = color;
                }
            }
        }

        cx += MF_CHAR_W;
    }
}

void MF_DrawText(int x, int y, const char* s, mf_color_t c)
{
    if(!ready)
        MF_Init();

    const byte shadow[4] = {0, colors[MF_BLACK], colors[MF_BLACK], colors[MF_BLACK]};

    MF_DrawGlyphs(x + 1, y + 1, s, shadow);
    MF_DrawGlyphs(x, y, s, ramps[c]);
}

void MF_DrawTextCentered(int y, const char* s, mf_color_t c)
{
    MF_DrawText((FB_W - MF_TextWidth(s)) / 2, y, s, c);
}

void MF_FillRect(int x, int y, int w, int h, mf_color_t c)
{
    byte* fb = (byte*)_g->screens[0].data;

    if(!ready)
        MF_Init();

    for(int py = y; py < y + h; py++)
        for(int px = x; px < x + w; px++)
            if(px >= 0 && px < FB_W && py >= 0 && py < SCREENHEIGHT)
                fb[py * FB_W + px] = colors[c];
}

void MF_DarkenRect(int x, int y, int w, int h)
{
    byte* fb = (byte*)_g->screens[0].data;

    if(!ready)
        MF_Init();

    for(int py = y; py < y + h; py++)
        for(int px = x; px < x + w; px++)
            if(px >= 0 && px < FB_W && py >= 0 && py < SCREENHEIGHT)
                fb[py * FB_W + px] = darken[fb[py * FB_W + px]];
}
