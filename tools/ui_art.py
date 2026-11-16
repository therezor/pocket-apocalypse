"""Generated UI art (profile "ui"): the small HUD/message font, the menu
font, the title screen and menu logo, all at the panel's own 240x135
pixels so nothing is shrunk from 320x200 on the device.

  "ui": {
    "small_font": {"fon2": "wads/ashes_ui/SMALLFNT.lmp", "color": [r, g, b]},
    "menu_font": {"ttf": "/System/Library/Fonts/Supplemental/Krungthep.ttf", "size": 13},
    "title": {"name": "POCKET APOCALYPSE", "font": "...ttf", "background": "wads/ashes_ui/CUT3BACK"},
    "interpic": "wads/ashes_ui/INTERPIC"
  }

Fonts and backgrounds are read here; text is rasterised with macOS
CoreText through a small Swift script (tools/ui_text.swift).
"""
import os
import struct
import subprocess

import hud_bar
import texture_pack

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_fon2(path):
    """ZDoom FON2 font -> (height, {char code: rows of palette indices}, palette).
    Index 0 is transparent."""
    d = open(path, 'rb').read()
    assert d[:4] == b'FON2', path
    h, first, last, const, _shade, palsize, flags = struct.unpack_from('<HBBBBBB', d, 4)
    p = 12 + (2 if flags & 1 else 0)    # skip the kerning value
    n = last - first + 1
    if const:
        widths = [struct.unpack_from('<H', d, p)[0]] * n
        p += 2
    else:
        widths = list(struct.unpack_from('<%dH' % n, d, p))
        p += 2 * n
    pal = [tuple(d[p + 3 * i:p + 3 * i + 3]) for i in range(palsize + 1)]
    p += 3 * (palsize + 1)
    glyphs = {}
    for i, w in enumerate(widths):
        if not w:
            continue
        need, out = w * h, bytearray()
        while len(out) < need:      # ByteRun1
            c = d[p]
            p += 1
            if c < 128:
                out += d[p:p + c + 1]
                p += c + 1
            elif c > 128:
                out += bytes([d[p]]) * (257 - c)
                p += 1
        glyphs[first + i] = [list(out[y * w:(y + 1) * w]) for y in range(h)]
    return h, glyphs, pal


def small_font_lumps(spec, pal):
    """STCFN033..095 from a FON2 font with a 1-pixel outline (Ashes SMALLFNT):
    outline black, the two body shades in spec "color". The last column (an
    outline the next glyph's first one repeats) is dropped: the font's -1
    kerning, as the HUD advances by patch width."""
    _, glyphs, fpal = load_fon2(os.path.join(ROOT, spec['fon2']))
    r, g, b = spec.get('color', [236, 214, 160])
    lum = [sum(c) for c in fpal]
    body = sorted({v for gl in glyphs.values() for row in gl for v in row if v > 1}, key=lambda v: lum[v])
    shade = {1: pal.match(0, 0, 0)}
    for k, v in enumerate(body):
        f = 0.62 + 0.38 * k / max(1, len(body) - 1)     # darkest body shade at 62%
        shade[v] = pal.match(int(r * f), int(g * f), int(b * f))
    out = {}
    for code in range(33, 96):
        gl = glyphs.get(code)
        if gl is None:
            continue
        rows = [[shade[v] if v else None for v in row[:-1] or row] for row in gl]
        while rows and all(v is None for v in rows[-1]):
            rows.pop()      # blank bottom rows
        out['STCFN%03d' % code] = hud_bar.make_patch(rows)
    return out


def swift(*args):
    subprocess.run(['swift', os.path.join(ROOT, 'tools', 'ui_text.swift')] + [str(a) for a in args],
                   check=True, capture_output=True)


def cached(key, make):
    """Run make(dir) once per key (fonts, sizes, texts) under build/texcache/ui."""
    import hashlib
    d = os.path.join(texture_pack.CACHE, 'ui', hashlib.sha1(repr(key).encode()).hexdigest()[:16])
    if not os.path.isdir(d):
        os.makedirs(d + '.tmp', exist_ok=True)
        make(d + '.tmp')
        os.rename(d + '.tmp', d)
    return d


def coverage(path):
    """Grey PNG -> rows of 0..255."""
    return [[p[0] for p in row] for row in texture_pack._png_rgba(path)]


MENU_CELL_H = 14    # m_font.h MF_LINE_H


def menu_font_lump(spec):
    """MFONT: the menu font (m_font.c) rendered from a TrueType font, codes
    32..126: "MF", cell height, count, the count widths, then each glyph's
    width x height levels (0 clear, 1..3 dim to full ink)."""
    size, base = spec.get('size', 13), spec.get('baseline', 11)
    d = cached(('glyphs', spec['ttf'], size, MENU_CELL_H, base),
               lambda out: swift('glyphs', spec['ttf'], size, MENU_CELL_H, base, out))
    widths, data = [], bytearray()
    for code in range(32, 127):
        rows = coverage(os.path.join(d, '%d.png' % code))
        widths.append(len(rows[0]))
        for row in rows:
            data += bytes(0 if v < 48 else 1 if v < 112 else 2 if v < 184 else 3 for v in row)
    return b'MF' + bytes([MENU_CELL_H, len(widths)]) + bytes(widths) + bytes(data)


def text_mask(font, size, text):
    """Coverage rows of one line of text, cropped to its ink (+2 px)."""
    d = cached(('text', font, size, text), lambda out: swift('text', font, size, os.path.join(out, 't.png'), text))
    return coverage(os.path.join(d, 't.png'))


def logo_rgba(spec, scale):
    """The game name as RGBA rows: the small first word over the big rest,
    fire gradient, black outline and drop shadow. scale 1 = menu size."""
    words = spec['name'].split(' ', 1)
    small = text_mask(spec.get('small_font', spec['font']), round(spec.get('small_size', 12) * scale), words[0])
    big = text_mask(spec['font'], round(spec.get('size', 30) * scale), words[-1])
    w = max(len(small[0]), len(big[0])) + 4
    h = len(small) + len(big) + 3
    ink = [[0] * w for _ in range(h)]       # 0 none, 1 small word, 2 big word
    for mask, top, kind in ((small, 0, 1), (big, len(small) - 1, 2)):
        left = (w - len(mask[0])) // 2
        for y, row in enumerate(mask):
            for x, v in enumerate(row):
                if v >= 128:
                    ink[top + y][left + x] = kind
    top_c, mid_c, bot_c = spec.get('gradient', [[255, 236, 140], [255, 150, 40], [190, 36, 18]])
    word_c = spec.get('small_color', [228, 228, 220])
    out = [[None] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            if ink[y][x]:
                continue
            near = any(ink[yy][xx] for yy in range(max(0, y - 1), min(h, y + 2))
                       for xx in range(max(0, x - 1), min(w, x + 2)))
            shadow = y >= 2 and x >= 2 and ink[y - 2][x - 2]
            if near or shadow:
                out[y][x] = (0, 0, 0)
    rows = [y for y in range(h) if 2 in ink[y]]
    y0, y1 = rows[0], rows[-1]
    for y in range(h):
        t = (y - y0) / max(1, y1 - y0)
        a, b, f = (top_c, mid_c, t * 2) if t < 0.5 else (mid_c, bot_c, t * 2 - 1)
        fire = tuple(int(a[i] + (b[i] - a[i]) * f) for i in range(3))
        for x in range(w):
            if ink[y][x] == 2:
                out[y][x] = fire
            elif ink[y][x] == 1:
                out[y][x] = tuple(word_c)
    return out


def background(path, w, h):
    """A picture cropped to w:h about its centre, then resized to w x h."""
    full = texture_pack._png_rgba(path)
    sh, sw = len(full), len(full[0])
    if sw * h > sh * w:
        cw, ch = sh * w // h, sh
    else:
        cw, ch = sw, sw * h // w
    x0, y0 = (sw - cw) // 2, (sh - ch) // 2
    out = []
    for y in range(h):
        ya, yb = y0 + y * ch // h, max(y0 + y * ch // h + 1, y0 + (y + 1) * ch // h)
        row = []
        for x in range(w):
            xa, xb = x0 + x * cw // w, max(x0 + x * cw // w + 1, x0 + (x + 1) * cw // w)
            n = (yb - ya) * (xb - xa)
            px = [full[yy][xx] for yy in range(ya, yb) for xx in range(xa, xb)]
            row.append(tuple(sum(p[i] for p in px) // n for i in range(3)))
        out.append(row)
    return out


def to_patch(rows, pal):
    return hud_bar.make_patch([[pal.match(*p) if p is not None else None for p in row] for row in rows])


def title_lumps(spec, pal):
    """TITLEPIC (240x135, drawn 1:1 by d_main.c) and M_LOGO (main menu)."""
    bg = background(os.path.join(ROOT, spec['background']), 240, 135)
    logo = logo_rgba(spec, spec.get('title_scale', 1.3))
    lw, lh = len(logo[0]), len(logo)
    ox, oy = (240 - lw) // 2, spec.get('title_y', 6)
    for y in range(135):
        dim = 0.55 + 0.45 * min(1.0, max(0.0, (y - oy - lh * 0.6) / (lh * 0.8)))   # darker behind the name
        bg[y] = [tuple(int(c * dim) for c in p) for p in bg[y]]
    for y, row in enumerate(logo):
        for x, p in enumerate(row):
            if p is not None and 0 <= oy + y < 135 and 0 <= ox + x < 240:
                bg[oy + y][ox + x] = p
    if spec.get('tagline'):
        tag = text_mask(spec.get('small_font', spec['font']), spec.get('tagline_size', 9), spec['tagline'])
        tx, ty = (240 - len(tag[0])) // 2, 135 - len(tag) - 2
        for y, row in enumerate(tag):
            for x, v in enumerate(row):
                if v >= 128:
                    bg[ty + y + 1][tx + x + 1] = (0, 0, 0)
                    bg[ty + y][tx + x] = tuple(spec.get('small_color', [228, 228, 220]))
    return {'TITLEPIC': to_patch(bg, pal), 'M_LOGO': to_patch(logo_rgba(spec, 1.0), pal)}


def apply(ui, out_glob, playpal):
    """Replace / add the generated lumps in out_glob [(name, data)]."""
    pal = texture_pack.Palette(playpal[:768])
    new = {}
    if ui.get('small_font'):
        new.update(small_font_lumps(ui['small_font'], pal))
    if ui.get('menu_font'):
        new['MFONT'] = menu_font_lump(ui['menu_font'])
    if ui.get('title'):
        new.update(title_lumps(ui['title'], pal))
    if ui.get('interpic'):      # drawn 1:1 by wi_stuff.c
        new['INTERPIC'] = to_patch(background(os.path.join(ROOT, ui['interpic']), 240, 135), pal)
    names = {n for n, _ in out_glob}
    out_glob = [(n, new.get(n, d)) for n, d in out_glob]
    out_glob += [(n, d) for n, d in sorted(new.items()) if n not in names]
    return out_glob
