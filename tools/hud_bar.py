"""Fit a mod's 320x32 Doom status bar into the engine's 240x32 GBA layout.

The engine draws a raw 240x32 background (built-in GBA Doom II bar unless the
WAD has an STBARGBA lump) and its widgets at the GBA positions.  A mod's
STBAR/STARMS are cut into the regions those widgets need and each region is
narrowed by dropping its least visible columns (the ones closest to their
neighbour), which keeps bevels, labels and the % signs intact.

STBARGBA = 240*32 palette indices + layout trailer (see LAYOUT below and
ST_loadGraphics in st_stuff.c).
"""
import struct

W, H = 240, 32

# (src x0, src x1, dst width) in left-to-right order; dst widths sum to 240.
# Source is Doom's 320 layout with STARMS pasted over the frags panel.
SEGMENTS = [
    (0, 47, 34),     # ammo           -> 0..34    (number right edge 32)
    (47, 90, 32),    # health digits  -> 34..66   (right edge 66)
    (90, 104, 13),   # health %       -> 66..79
    (104, 144, 30),  # arms           -> 79..109  (digits at 82 + 8*i)
    (144, 177, 28),  # face           -> 109..137 (face at 104 + 5)
    (177, 222, 29),  # armor digits   -> 137..166 (right edge 166)
    (222, 236, 13),  # armor %        -> 166..179
    (236, 249, 10),  # keys           -> 179..189
    (249, 273, 13),  # ammo labels    -> 189..202
    (273, 289, 15),  # ammo counts    -> 202..217 (right edge 217)
    (289, 298, 6),   # slashes        -> 217..223
    (298, 314, 15),  # max ammo       -> 223..238 (right edge 238)
    (314, 320, 2),   # border         -> 238..240
]

# Trailer: magic, tall number y, armor x, key x, ammo x, max ammo x, face x.
LAYOUT_MAGIC = b'TWSB'


def patch_pixels(p):
    w, h, lo, to = struct.unpack('<HHhh', p[:8])
    img = [[None] * w for _ in range(h)]
    for x in range(w):
        o = struct.unpack('<I', p[8 + 4 * x:12 + 4 * x])[0]
        while p[o] != 255:
            top, ln = p[o], p[o + 1]
            for i in range(ln):
                if top + i < h:
                    img[top + i][x] = p[o + 3 + i]
            o += ln + 4
    return img, lo, to


def make_patch(img, lo=0, to=0, max_run=128):
    h = len(img)
    w = len(img[0])
    cols = []
    for x in range(w):
        col = b''
        y = 0
        while y < h:
            if img[y][x] is None:
                y += 1
                continue
            start = y
            run = []
            while y < h and img[y][x] is not None and len(run) < max_run:
                run.append(img[y][x])
                y += 1
            col += bytes([start, len(run), run[0]]) + bytes(run) + bytes([run[-1]])
        cols.append(col + b'\xff')
    out = struct.pack('<HHhh', w, h, lo, to)
    off = 8 + 4 * w
    for c in cols:
        out += struct.pack('<I', off)
        off += len(c)
    return out + b''.join(cols)


def _rgb(pal, c):
    return pal[3 * c:3 * c + 3] if c is not None else (255, 0, 255)


def _coldiff(pal, a, b):
    d = 0
    for pa, pb in zip(a, b):
        if (pa is None) != (pb is None):
            d += 400
        elif pa is not None and pa != pb:
            # squared luma: background noise is cheap, glyph edges expensive
            ra, rb = _rgb(pal, pa), _rgb(pal, pb)
            dl = (2 * (ra[0] - rb[0]) + 5 * (ra[1] - rb[1]) + (ra[2] - rb[2])) // 8
            d += dl * dl
    return d


def narrow(cols, width, pal, keep_edges=1):
    """Drop columns until `width` remain, each time the one most like its
    left neighbour (outer `keep_edges` columns are never dropped)."""
    cols = list(cols)
    while len(cols) > width:
        best, bi = None, None
        for i in range(keep_edges, len(cols) - keep_edges):
            d = _coldiff(pal, cols[i], cols[i - 1])
            if best is None or d < best:
                best, bi = d, i
        del cols[bi]
    return cols


def build_bar(stbar, starms, pal):
    """stbar/starms: patch lumps. Returns the STBARGBA lump."""
    bar, _, _ = patch_pixels(stbar)
    if starms:
        arms, _, _ = patch_pixels(starms)
        for y in range(min(H, len(arms))):
            for x in range(len(arms[0])):
                if arms[y][x] is not None:
                    bar[y][104 + x] = arms[y][x]
    src_cols = [[bar[y][x] if bar[y][x] is not None else 0 for y in range(H)] for x in range(320)]
    out = []
    for x0, x1, w in SEGMENTS:
        out += narrow(src_cols[x0:x1], w, pal)
    assert len(out) == W, len(out)
    raw = bytes(out[x][y] for y in range(H) for x in range(W))
    return raw + LAYOUT_MAGIC + bytes([3, 166, 180, 217, 238, 105, 0, 0])


def narrow_digit(p, width, pal):
    """Tall-number patch -> `width` columns (STGANUM style)."""
    img, lo, to = patch_pixels(p)
    cols = [[img[y][x] for y in range(len(img))] for x in range(len(img[0]))]
    if len(cols) > width:
        cols = narrow(cols, width, pal)
    h = len(img)
    while len(cols) < width:  # centre narrower glyphs
        if len(cols) % 2:
            cols.append([None] * h)
        else:
            cols.insert(0, [None] * h)
    return make_patch([[cols[x][y] for x in range(width)] for y in range(h)], 0, to)


def mirror_patch(p):
    """The picture flipped left-right (for a rotation stored as the mirror of another)."""
    img, lo, to = patch_pixels(p)
    w = len(img[0])
    return make_patch([row[::-1] for row in img], w - lo, to)

