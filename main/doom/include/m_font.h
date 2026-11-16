// Menu text for the 240x135 panel: an 8x16 bitmap font drawn 1:1 into the
// framebuffer (the classic menu graphics lose strokes when shrunk).
#ifndef M_FONT_H
#define M_FONT_H

#define MF_CHAR_W   8
#define MF_CHAR_H   16
#define MF_LINE_H   14      // line pitch; the glyphs' ink fits in 14 rows

typedef enum
{
    MF_WHITE,
    MF_GREY,
    MF_YELLOW,
    MF_RED,
    MF_BLACK,
    MF_DARK,        // translucent-looking backdrop
    MF_NUMCOLORS
} mf_color_t;

int  MF_Color(mf_color_t c);                    // palette index
int  MF_TextWidth(const char* s);               // widest line, pixels
int  MF_TextHeight(const char* s);              // lines * MF_LINE_H
void MF_DrawText(int x, int y, const char* s, mf_color_t c);   // with shadow
void MF_DrawTextCentered(int y, const char* s, mf_color_t c);
void MF_FillRect(int x, int y, int w, int h, mf_color_t c);
void MF_DarkenRect(int x, int y, int w, int h);  // dims what is underneath

#endif
