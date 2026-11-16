"""Texture packs in the JDoom/GZDoom folder layout (one JPG/PNG per texture
or flat name, e.g. the Dark Textures Pack: data/jdoom/TEXTURES, .../flats)
converted to Doom data: each texture becomes one patch, each flat a 64x64
raw lump, colour-matched to the game's PLAYPAL.

Images are resized to the texture's size with macOS sips (cached under
build/texcache) and decoded here, so no image library is needed.
"""
import os
import struct
import subprocess
import zlib

import hud_bar

CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'build', 'texcache')


def index(root, games=('Doom2',)):
    """name -> image path for TEXTURES and flats; a game subfolder (Doom2/)
    overrides the shared images."""
    out = {}
    for kind in ('TEXTURES', 'flats'):
        names = {}
        base = os.path.join(root, kind)
        for d in [base] + [os.path.join(base, g) for g in games]:
            if not os.path.isdir(d):
                continue
            for f in sorted(os.listdir(d)):
                p = os.path.join(d, f)
                if os.path.isfile(p) and f.lower().endswith(('.png', '.jpg', '.jpeg')):
                    names[os.path.splitext(f)[0].upper()] = p
        out[kind.lower()] = names
    return out


def _png_rgba(path, info=None):
    """RGBA rows of an 8-bit PNG (grey, RGB, palette, +alpha). `info` gets
    the ZDoom grAb offsets if the file has them."""
    data = open(path, 'rb').read()
    assert data[:8] == b'\x89PNG\r\n\x1a\n', path
    pos, idat, w = 8, b'', 0
    plte, trns = b'', b''
    while pos < len(data):
        n, typ = struct.unpack_from('>I4s', data, pos)
        chunk = data[pos + 8:pos + 8 + n]
        if typ == b'IHDR':
            w, h, depth, ctype, _, _, interlace = struct.unpack('>IIBBBBB', chunk)
            if interlace:   # Adam7: let ffmpeg rewrite it (that drops grAb: read it here first)
                grab = struct.unpack('>ii', data[data.index(b'grAb') + 4:data.index(b'grAb') + 12]) \
                    if b'grAb' in data else None
                os.makedirs(CACHE, exist_ok=True)
                flat = os.path.join(CACHE, 'deint_' + os.path.basename(path))
                subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', path, '-pix_fmt', 'rgba', flat],
                               check=True, capture_output=True)
                rows = _png_rgba(flat)
                if info is not None and grab:
                    info['grab'] = grab
                return rows
            assert depth == 8 and ctype in (0, 2, 3, 4, 6), (path, depth, ctype)
        elif typ == b'IDAT':
            idat += chunk
        elif typ == b'PLTE':
            plte = chunk
        elif typ == b'tRNS':
            trns = chunk
        elif typ == b'grAb' and info is not None:
            info['grab'] = struct.unpack('>ii', chunk)
        pos += 12 + n
    bpp = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    raw = zlib.decompress(idat)
    stride = w * bpp
    rows, prev, i = [], bytearray(stride), 0
    for _ in range(h):
        f = raw[i]
        line = bytearray(raw[i + 1:i + 1 + stride])
        i += 1 + stride
        for x in range(stride):
            a = line[x - bpp] if x >= bpp else 0
            b = prev[x]
            c = prev[x - bpp] if x >= bpp else 0
            if f == 1:
                line[x] = (line[x] + a) & 255
            elif f == 2:
                line[x] = (line[x] + b) & 255
            elif f == 3:
                line[x] = (line[x] + (a + b) // 2) & 255
            elif f == 4:
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        px = [tuple(line[x * bpp:x * bpp + bpp]) for x in range(w)]
        if ctype == 3:          # palette (+ tRNS alpha)
            px = [tuple(plte[3 * p[0]:3 * p[0] + 3]) + ((trns[p[0]] if p[0] < len(trns) else 255),) for p in px]
        elif ctype in (0, 4):   # grey (+ alpha)
            px = [(p[0], p[0], p[0], p[1] if ctype == 4 else 255) for p in px]
        elif ctype == 2:
            px = [p + (255,) for p in px]
        rows.append(px)
        prev = line
    return rows


def load(path, w, h):
    """Image resized to w x h -> rows of (r, g, b, a)."""
    os.makedirs(CACHE, exist_ok=True)
    out = os.path.join(CACHE, '%s_%dx%d.png' % (os.path.splitext(os.path.basename(path))[0], w, h))
    if not os.path.exists(out) or os.path.getmtime(out) < os.path.getmtime(path):
        subprocess.run(['sips', '-s', 'format', 'png', '-z', str(h), str(w), path, '--out', out],
                       check=True, capture_output=True)
    rows = _png_rgba(out)
    assert len(rows) == h and len(rows[0]) == w, (path, w, h, len(rows[0]), len(rows))
    return rows


class Palette:
    def __init__(self, playpal):
        self.rgb = [tuple(playpal[3 * i:3 * i + 3]) for i in range(256)]
        self.cache = {}

    def match(self, r, g, b):
        k = (r >> 3, g >> 3, b >> 3)
        c = self.cache.get(k)
        if c is None:
            r, g, b = (k[0] << 3) + 4, (k[1] << 3) + 4, (k[2] << 3) + 4
            c = min(self.indices(), key=lambda i: 2 * (self.rgb[i][0] - r) ** 2 + 4 * (self.rgb[i][1] - g) ** 2
                    + 3 * (self.rgb[i][2] - b) ** 2)
            self.cache[k] = c
        return c

    def indices(self):
        return range(256)

    def reds(self):
        """The same palette limited to its reds (and black): blood art
        whose dark shades would otherwise match Doom's olive greens."""
        sub = Palette(b''.join(bytes(c) for c in self.rgb))
        keep = [0] + [i for i, (r, g, b) in enumerate(self.rgb) if r > 30 and r > 1.6 * max(g, b)]
        sub.indices = lambda: keep
        return sub


def to_patch(rows, pal):
    """Transparent pixels (alpha < 128) stay holes, as in masked textures."""
    img = [[pal.match(*p[:3]) if p[3] >= 128 else None for p in row] for row in rows]
    return hud_bar.make_patch(img)


def to_flat(rows, pal):
    return bytes(pal.match(*p[:3]) for row in rows for p in row)


# "average": box-filter colours, then the nearest palette entry (smooth but it
# invents in-between colours); "majority": the colour covering most of each
# output pixel (keeps the art's own colours: crisper sprites)
RESAMPLE = 'average'


def scale_patch(data, pal, num=3, den=4):
    """Doom picture resized by num/den with a box filter (colours averaged
    over the covered source pixels, then palette-matched; a pixel stays
    transparent unless at least half of its area is opaque). Offsets scale too."""
    img, lo, to = hud_bar.patch_pixels(data)
    h, w = len(img), len(img[0])
    nw, nh = (w * num + den - 1) // den, (h * num + den - 1) // den

    def weights(n_out, n_in):
        res = []
        for o in range(n_out):
            a, b = o * den / num, min((o + 1) * den / num, n_in)
            ws, i = [], int(a)
            while i < b:
                ws.append((i, min(b, i + 1) - max(a, i)))
                i += 1
            res.append(ws)
        return res

    wx, wy = weights(nw, w), weights(nh, h)
    rgb = pal.rgb
    out = []
    for oy in range(nh):
        row = []
        for ox in range(nw):
            r = g = b = cov = tot = 0.0
            votes = {}
            for iy, fy in wy[oy]:
                src = img[iy]
                for ix, fx in wx[ox]:
                    f = fx * fy
                    tot += f
                    c = src[ix]
                    if c is not None:
                        p = rgb[c]
                        r += p[0] * f
                        g += p[1] * f
                        b += p[2] * f
                        cov += f
                        votes[c] = votes.get(c, 0) + f
            if cov * 2 < tot:
                row.append(None)
            elif RESAMPLE == 'majority':
                row.append(max(votes, key=votes.get))
            else:
                row.append(pal.match(int(r / cov), int(g / cov), int(b / cov)))
        out.append(row)
    return hud_bar.make_patch(out, int(round(lo * num / den)), int(round(to * num / den)))


def bake_texture(w, h, plist, patches, pal, half=False):
    """A multi-patch wall texture drawn into one patch (optionally at half
    width: column pairs averaged). Columns stay one post for heights up to 255,
    as the renderer's single-patch path expects."""
    img = [[None] * w for _ in range(h)]
    for ox, oy, pname, _, _ in plist:
        if pname not in patches:
            continue
        pix, _, _ = hud_bar.patch_pixels(patches[pname])
        for y, row in enumerate(pix):
            ty = oy + y
            if 0 <= ty < h:
                for x, c in enumerate(row):
                    tx = ox + x
                    if c is not None and 0 <= tx < w:
                        img[ty][tx] = c
    if half:
        rgb = pal.rgb
        out = []
        for row in img:
            nr = []
            for x in range(0, w, 2):
                a, b = row[x], row[x + 1] if x + 1 < w else None
                if a is None or b is None:
                    nr.append(a if b is None else b)
                else:
                    pa, pb = rgb[a], rgb[b]
                    nr.append(a if a == b else pal.match((pa[0] + pb[0]) // 2, (pa[1] + pb[1]) // 2,
                                                         (pa[2] + pb[2]) // 2))
            out.append(nr)
        img = out
    return hud_bar.make_patch(img, max_run=255)


def png_patch(path, pal, num=1, den=1):
    """A ZDoom-style PNG sprite (grAb offsets) as a Doom picture, scaled num/den."""
    info = {}
    rows = _png_rgba(path, info)
    lo, to = info.get('grab', (len(rows[0]) // 2, len(rows)))
    patch = hud_bar.make_patch([[pal.match(*p[:3]) if p[3] >= 128 else None for p in row] for row in rows], lo, to)
    return scale_patch(patch, pal, num, den) if num != den else patch

