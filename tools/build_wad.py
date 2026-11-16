#!/usr/bin/env python3
"""Build the game data image for the Cardputer "wad" flash partition.

    IWAD + PWADs (+ DeHackEd patches), from a mod profile  ->  data/game.wad

    tools/build_wad.py --profile tools/mods/d4v_scythe.json
    (normally run by tools/build_mod.sh together with deh2c.py)

Steps:
  1. Merge the PWAD into the IWAD (TW's SS_/PP_/FF_ namespaces go into
     S_/P_/F_; same-name lumps are replaced).
  2. Keep only what MAP01-MAP10 and the engine can reach:
       - textures used by the maps (+ switch partners, animation ranges, sky),
         rebuilt TEXTURE1/PNAMES and only the patches those need;
       - flats used by the maps (+ animation ranges, sky, finale flats);
       - sprite frames reachable from the DeHackEd-patched state graph;
       - sounds reachable from that graph and from engine code; all resampled
         to the mixer rate (TW ships some 22 kHz sounds);
       - music for MAP01-10, title, intermission and text screens;
       - the UI lumps the engine opens by name.
  3. Write data/game_vanilla.wad (normal Doom format, for checking on a PC
     with the profile's .deh files).
  4. Convert to the GBADoom in-flash format (pre-baked vertexes, lines,
     segs, sides; MUS -> MIDI; half-resolution sprites and 32x32 flats
     unless --no-half-*) and write data/game.wad, which the firmware embeds.
  5. Validate and fail if anything the engine needs is missing or the
     firmware would not fit next to M5Launcher.

The result contains commercial Doom II data: personal use only.
"""

import argparse
import collections
import math
import os
import re
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import deh2c  # noqa: E402
import hud_bar  # noqa: E402
import texture_pack  # noqa: E402

DOOM_SRC = os.path.join(ROOT, 'main', 'doom', 'source')
# Doom II monsters (THINGS doomednums), for per-level counts
MONSTER_DOOMEDNUMS = {7, 9, 16, 58, 64, 65, 66, 67, 68, 69, 71, 84, 3001, 3002, 3003, 3004, 3005, 3006}
MAP_LUMPS = ['THINGS', 'LINEDEFS', 'SIDEDEFS', 'VERTEXES', 'SEGS', 'SSECTORS',
             'NODES', 'SECTORS', 'REJECT', 'BLOCKMAP']
MIX_RATE = 11025
NUM_MAPS = 10

# M5Launcher keeps itself in 0x10000-0x170000 (app + coredump); an installed
# app gets the rest of the 8 MB flash. The code itself is ~0.8 MB.
LAUNCHER_APP_SPACE = 0x800000 - 0x170000
CODE_RESERVE = 0xE0000

# Doom II music by map (S_ChangeMusic: mus_runnin + gamemap - 1), plus
# title, intermission and the text screens.
MAP_MUSIC = ['D_RUNNIN', 'D_STALKS', 'D_COUNTD', 'D_BETWEE', 'D_DOOM', 'D_THE_DA', 'D_SHAWN',
             'D_DDTBLU', 'D_IN_CIT', 'D_DEAD', 'D_STLKS2', 'D_THEDA2', 'D_DOOM2', 'D_DDTBL2',
             'D_RUNNI2', 'D_DEAD2', 'D_STLKS3', 'D_ROMERO', 'D_SHAWN2', 'D_MESSAG', 'D_COUNT2',
             'D_DDTBL3', 'D_AMPIE', 'D_THEDA3', 'D_ADRIAN', 'D_MESSG2', 'D_COUNT3', 'D_ROMER2',
             'D_TENSE', 'D_SHAWN3', 'D_OPENIN', 'D_EVIL']
SCREEN_MUSIC = ['D_DM2TTL', 'D_DM2INT', 'D_READ_M']

# Finale backgrounds: after MAP06 (C1TEXT) and our MAP10 ending.
FINALE_FLATS = ['SLIME16']

# Things the engine spawns from non-action code (see p_mobj.c, p_inter.c,
# p_map.c, p_telept.c); action functions are scanned automatically.
ROOT_THINGS = ['MT_PLAYER', 'MT_PUFF', 'MT_BLOOD', 'MT_TFOG', 'MT_IFOG', 'MT_TELEPORTMAN',
               'MT_CLIP', 'MT_SHOTGUN', 'MT_CHAINGUN']
ROOT_STATES = ['S_GIBS', 'S_PLAY_ATK1', 'S_PLAY_ATK2', 'S_PUFF3', 'S_BLOOD2', 'S_BLOOD3',
               'S_PLAY', 'S_PLAY_RUN1']

# Not needed on the device.
# Not needed: attract demos, DOS/ZDoom extras, and Doom 1 (or MAP30 cast)
# screens the Doom II code paths never reach.
DROP_GLOBAL = re.compile(r'^(DEMO\d|ENDOOM|DMXGUS|DMXGUSC|GENMIDI_|CONSBACK|CREDIT|HELP\d?|BOSSBACK|'
                         r'DP\w+|LEGACY|INFO|S_SKIN.*|VICTORY2|PFUB\d|END\d|M_EPI\d|M_EPISOD|M_ZDOOM|'
                         r'WIMAP\d|WIA\d+)$')

# Lumps whose names the engine builds with sprintf().
PRINTF_LUMPS = [r'STCFN\d{3}', r'CWILV\d\d', r'WINUM\d', r'STGANUM\d', r'STTNUM\d', r'STYSNUM\d',
                r'STKEYS\d', r'STGNUM\d', r'STFST\d\d', r'STFTR\d0', r'STFTL\d0', r'STFOUCH\d',
                r'STFEVL\d', r'STFKILL\d', r'AMMNUM\d', r'STTPRCNT', r'STTMINUS', r'BRDR_\w+']


# ---------------------------------------------------------------- WAD I/O

class Wad:
    def __init__(self, path=None):
        self.lumps = []     # [name, bytes]
        if path:
            with open(path, 'rb') as f:
                data = f.read()
            ident, n, off = struct.unpack_from('<4sii', data)
            assert ident in (b'IWAD', b'PWAD'), path
            for i in range(n):
                pos, size, name = struct.unpack_from('<ii8s', data, off + 16 * i)
                name = name.split(b'\0')[0].decode('latin-1').upper()
                self.lumps.append([name, data[pos:pos + size]])

    def names(self):
        return [n for n, _ in self.lumps]

    def find(self, name):
        for i in range(len(self.lumps) - 1, -1, -1):
            if self.lumps[i][0] == name:
                return i
        return -1

    def get(self, name):
        i = self.find(name)
        return self.lumps[i][1] if i >= 0 else None


def write_wad(path, lumps, dir_first=False):
    """dir_first: GBADoom layout (directory right after the header, lumps
    4-byte aligned) as written by the original converter."""
    out = bytearray()
    entries = []
    if dir_first:
        pos = 12 + 16 * len(lumps)
        pos = (pos + 3) & ~3
        body = bytearray()
        stored = {}     # identical lumps (shared music, mirrored frames) are stored once
        for name, data in lumps:
            if data and bytes(data) in stored:
                entries.append((stored[bytes(data)], len(data), name))
                continue
            if data:
                stored[bytes(data)] = pos + len(body)
            entries.append((pos + len(body) if data else 0, len(data), name))
            body += data
            body += b'\0' * ((-len(body)) & 3)
        out += struct.pack('<4sii', b'IWAD', len(lumps), 12)
        for p, s, n in entries:
            out += struct.pack('<ii8s', p, s, n.encode('latin-1'))
        out += b'\0' * (((12 + 16 * len(lumps) + 3) & ~3) - len(out))
        out += body
    else:
        body = bytearray()
        for name, data in lumps:
            entries.append((12 + len(body) if data else 0, len(data), name))
            body += data
        out += struct.pack('<4sii', b'IWAD', len(lumps), 12 + len(body))
        out += body
        for p, s, n in entries:
            out += struct.pack('<ii8s', p, s, n.encode('latin-1'))
    with open(path, 'wb') as f:
        f.write(out)
    return len(out)


def sections(wad):
    """Split into global lumps, maps and the S/P/F namespaces (DeuTex-style
    double-letter markers count as the same namespace)."""
    glob, sprites, patches, flats, maps = [], collections.OrderedDict(), collections.OrderedDict(), \
        collections.OrderedDict(), collections.OrderedDict()
    sec = None
    lumps = wad.lumps
    i = 0
    while i < len(lumps):
        name, data = lumps[i]
        m = re.match(r'^([SPF])\1?(\d)?_(START|END)$', name)
        if m:
            sec = m.group(1) if m.group(3) == 'START' else None
            i += 1
            continue
        if sec is None and re.match(r'^(MAP\d\d|E\dM\d)$', name) and i + 1 < len(lumps) \
                and lumps[i + 1][0] == 'THINGS':
            maps[name] = {k: lumps[i + 1 + j][1] for j, k in enumerate(MAP_LUMPS)
                          if i + 1 + j < len(lumps) and lumps[i + 1 + j][0] == k}
            i += 1 + len(maps[name])
            continue
        if sec == 'S':
            sprites[name] = data
        elif sec == 'P':
            patches[name] = data
        elif sec == 'F':
            flats[name] = data
        else:
            glob.append([name, data])
        i += 1
    return glob, sprites, patches, flats, maps


# ---------------------------------------------------------------- textures

def parse_pnames(data):
    n = struct.unpack_from('<i', data)[0]
    return [data[4 + 8 * i:12 + 8 * i].split(b'\0')[0].decode('latin-1').upper() for i in range(n)]


def parse_textures(data, pnames):
    n = struct.unpack_from('<i', data)[0]
    offs = struct.unpack_from('<%di' % n, data, 4)
    tex = collections.OrderedDict()
    for o in offs:
        name = data[o:o + 8].split(b'\0')[0].decode('latin-1').upper()
        masked, w, h, coldir, pc = struct.unpack_from('<ihhih', data, o + 8)
        patches = []
        for j in range(pc):
            ox, oy, p, sd, cm = struct.unpack_from('<hhhhh', data, o + 22 + 10 * j)
            patches.append((ox, oy, pnames[p], sd, cm))
        tex[name] = (masked, w, h, coldir, patches)
    return tex


def build_textures(tex):
    pnames = []
    index = {}
    for _, (_, _, _, _, patches) in tex.items():
        for p in patches:
            if p[2] not in index:
                index[p[2]] = len(pnames)
                pnames.append(p[2])
    pn = struct.pack('<i', len(pnames)) + b''.join(n.encode('latin-1').ljust(8, b'\0') for n in pnames)
    body = bytearray()
    offs = []
    base = 4 + 4 * len(tex)
    for name, (masked, w, h, coldir, patches) in tex.items():
        offs.append(base + len(body))
        body += name.encode('latin-1').ljust(8, b'\0')
        body += struct.pack('<ihhih', masked, w, h, coldir, len(patches))
        for ox, oy, p, sd, cm in patches:
            body += struct.pack('<hhhhh', ox, oy, index[p], sd, cm)
    t1 = struct.pack('<i', len(tex)) + struct.pack('<%di' % len(offs), *offs) + bytes(body)
    return t1, pn, pnames


def c_table_names(src, table):
    s = open(os.path.join(DOOM_SRC, src), encoding='latin-1').read()
    s = s[s.index(table):]
    s = s[:s.index('};')]
    return s


def anim_ranges():
    body = c_table_names('p_spec.c', 'animdefs[]')
    return [(t.strip() == 'true', a, b) for t, a, b in
            re.findall(r'\{\s*(true|false),\s*"(\w+)",\s*"(\w+)"', body)]


def switch_pairs():
    body = c_table_names('p_switch.c', 'alphSwitchList[]')
    return re.findall(r'\{\s*"(\w+)",\s*"(\w+)"', body)


# ---------------------------------------------------------------- reachability

def scan_actions():
    """A_* function -> MT_/S_/sfx_ names it can produce, and the sounds all
    other engine code can play (always reachable).

    Only MT_ names passed to a *Spawn* call count: A_Look and friends also
    compare against MT_SPIDER/MT_CYBORG, which spawns nothing. Spawns in
    helpers (A_PainAttack -> A_PainShootSkull -> P_SpawnMobj) are followed
    through the call graph."""
    funcs = {}
    skip = {'info.c', 'f_finale.c', 'sounds.c', 'd_items.c'}
    for f in sorted(os.listdir(DOOM_SRC)):
        if not f.endswith('.c') or f in skip:
            continue
        s = open(os.path.join(DOOM_SRC, f), encoding='latin-1').read()
        s = re.sub(r'/\*.*?\*/', '', s, flags=re.S)
        s = re.sub(r'//.*', '', s)
        for m in re.finditer(r'\n[\w \t\*]*?\b(\w+)\s*\([^;{)]*\)\s*\{', s):
            name = m.group(1)
            i = m.end()
            depth = 1
            while depth and i < len(s):
                depth += {'{': 1, '}': -1}.get(s[i], 0)
                i += 1
            body = s[m.end():i]
            spawns = set()
            for call in re.finditer(r'\b\w*Spawn\w*\s*\(([^;]*)', body):
                spawns |= set(re.findall(r'\bMT_[A-Z0-9_]+\b', call.group(1)))
            funcs[name] = {
                'spawns': spawns,
                'states': set(re.findall(r'\bS_[A-Z0-9_]+\b', body)),
                'sfx': set(re.findall(r'\bsfx_\w+\b', body)),
                'calls': set(re.findall(r'\b([A-Za-z_]\w*)\s*\(', body)),
            }

    def closure(name, seen):
        if name in seen or name not in funcs:
            return set(), set(), set()
        seen.add(name)
        f = funcs[name]
        mt, st, sfx = set(f['spawns']), set(f['states']), set(f['sfx'])
        for c in f['calls']:
            a, b, c2 = closure(c, seen)
            mt |= a
            st |= b
            sfx |= c2
        return mt, st, sfx

    acts = {}
    always = set()
    for name, f in funcs.items():
        if name.startswith('A_'):
            mt, st, sfx = closure(name, set())
            acts[name] = mt | st | sfx
        else:
            always |= f['sfx']
    return acts, always


def reachable(t, states, mobj, weapons, used_doomednums, spr_renames=None, extra_things=(), extra_psp=(), removed_weapons=()):
    """Sprite frames, things and sounds the game can reach. Also returns the
    sprite prefixes only ever drawn as the player's weapon (psprites), which
    stay full resolution."""
    spr_renames = spr_renames or {}
    acts, always_sfx = scan_actions()
    mt_index = {m['name']: i for i, m in enumerate(t.mobj)}
    st_index = {n: i for i, n in enumerate(t.st_enum)}

    things = set(ROOT_THINGS) | set(extra_things)
    for i, m in enumerate(mobj):
        try:
            if int(m['doomednum']) in used_doomednums:
                things.add(t.mobj[i]['name'])
        except ValueError:
            pass

    seen_mt, seen_st = set(), set()
    sfx = set(always_sfx)
    q_mt = list(things)
    q_st = [st_index[s] for s in ROOT_STATES]
    for w in weapons:
        q_st += [st_index[w[f]] for f in deh2c.WEAPON_FIELDS[1:]]
    q_st += [st_index[x] for x in extra_psp]     # entered by the engine (magazine reloads)
    # a removed weapon's own states (A_WeaponReady names the chainsaw's idle
    # state for its sound; that must not keep the chainsaw's art)
    banned, q = set(), [st_index[w[f]] for w in removed_weapons for f in deh2c.WEAPON_FIELDS[1:]]
    while q:
        s = q.pop()
        if s not in banned and s:
            banned.add(s)
            q.append(st_index[states[s][4]])
    banned_names = {n for n, i in st_index.items() if i in banned}

    while q_mt or q_st:
        while q_mt:
            n = q_mt.pop()
            if n in seen_mt or n not in mt_index:
                continue
            seen_mt.add(n)
            m = mobj[mt_index[n]]
            for f in deh2c.MOBJ_STATE_FIELDS:
                if m[f] in st_index:
                    q_st.append(st_index[m[f]])
            for f in deh2c.MOBJ_SOUND_FIELDS:
                sfx.add(m[f])
        while q_st:
            s = q_st.pop()
            if s in seen_st or s not in states:
                continue
            seen_st.add(s)
            st = states[s]
            q_st.append(st_index[st[4]])
            for r in acts.get(st[3], ()):
                if r.startswith('MT_'):
                    q_mt.append(r)
                elif r.startswith('S_') and r in st_index and r not in banned_names:
                    q_st.append(st_index[r])
                elif r.startswith('sfx_'):
                    sfx.add(r)

    def prefix(spr):
        name = t.spr_names[t.spr_enum.index(spr)]
        return spr_renames.get(name, name)

    frames = collections.defaultdict(set)   # sprite prefix -> frame letters
    for s in seen_st:
        spr, fr = states[s][0], int(states[s][1], 0) & 0x7fff
        frames[prefix(spr)].add(chr(ord('A') + fr))

    # psprite states: weapon states and what their actions jump to
    psp, q = set(), [st_index[w[f]] for w in weapons for f in deh2c.WEAPON_FIELDS[1:]] + \
        [st_index[x] for x in extra_psp]
    while q:
        s = q.pop()
        if s in psp or s not in states:
            continue
        psp.add(s)
        q.append(st_index[states[s][4]])
        q += [st_index[r] for r in acts.get(states[s][3], ()) if r.startswith('S_') and r in st_index]
    # (prefix, frame letter) drawn only as the weapon: D4V draws parts of
    # some weapons with spare frames of sprites that monsters also use.
    def pf(s):
        return (prefix(states[s][0]), chr(ord('A') + (int(states[s][1], 0) & 0x7fff)))
    world = seen_st - psp
    weapon_only = {pf(s) for s in psp} - {pf(s) for s in world}

    # Monster frames (MF_COUNTKILL after DeHackEd): kept at full height.
    def flags(v):
        try:
            return int(v, 0)
        except ValueError:
            return sum(deh2c.VANILLA_MF.get(x.strip(), 0) for x in v.split('|'))
    enemy = set()
    for n in seen_mt:
        m = mobj[mt_index[n]]
        if not flags(m['flags']) & deh2c.VANILLA_MF['MF_COUNTKILL']:
            continue
        q = [st_index[m[f]] for f in deh2c.MOBJ_STATE_FIELDS if m[f] in st_index]
        seen = set()
        while q:
            s = q.pop()
            if s in seen or s not in states:
                continue
            seen.add(s)
            q.append(st_index[states[s][4]])
            q += [st_index[r] for r in acts.get(states[s][3], ()) if r.startswith('S_') and r in st_index]
        enemy |= {pf(s) for s in seen}
    enemy -= weapon_only
    return seen_mt, seen_st, frames, sfx, weapon_only, enemy


def is_weapon_lump(name, weapon_frames):
    """Every frame stored in this sprite lump is drawn only as the weapon."""
    return all((name[:4], f) in weapon_frames for f in sprite_lump_frames(name))


def sprite_lump_frames(name):
    """TROOA1 -> {'A'}, TROOA2A8 -> {'A'}, SARGB3B7 -> {'B'}."""
    out = {name[4]}
    if len(name) >= 8:
        out.add(name[6])
    return out


def check_sprites(sprites, frames, source):
    """Every reachable frame that exists in the source WADs must be complete
    (rotation 0, or all of 1-8). Frames the source never had (vanilla's
    S_LIGHTDONE points at SHTG E) are not our problem."""
    errors = []
    for prefix, letters in sorted(frames.items()):
        for fr in sorted(letters):
            if not any(n[:4] == prefix and fr in sprite_lump_frames(n) for n in source):
                continue
            rots = set()
            for n in sprites:
                if n[:4] != prefix:
                    continue
                if n[4] == fr:
                    rots.add(n[5])
                if len(n) >= 8 and n[6] == fr:
                    rots.add(n[7])
            if '0' not in rots and not all(str(r) in rots for r in range(1, 9)):
                errors.append('%s%s (rotations %s)' % (prefix, fr, ''.join(sorted(rots)) or 'none'))
    return errors


# ---------------------------------------------------------------- sounds

def resample_dmx(data, max_rate):
    fmt, rate, count = struct.unpack_from('<HHI', data)
    if fmt != 3 or rate <= max_rate:
        return data
    samples = data[8:8 + count]
    # DMX pads 16 samples at both ends; keep that layout.
    pad = 16 if count > 32 else 0
    core = samples[pad:len(samples) - pad] if pad else samples
    n_out = int(len(core) * max_rate / rate)
    step = rate / max_rate
    out = bytearray()
    for i in range(n_out):
        a = int(i * step)
        b = min(int((i + 1) * step), len(core))
        seg = core[a:max(b, a + 1)]
        out.append(sum(seg) // len(seg))
    if pad:
        out = bytes([out[0]] * pad) + out + bytes([out[-1]] * pad)
    return struct.pack('<HHI', 3, max_rate, len(out)) + bytes(out)


# ---------------------------------------------------------------- GBA map format

MATCH_SKIP = (r'^(DOOR|SW[12]|STEP|EXIT|BIGDOOR|SPCDOOR|LITE|SKY|RSKY|FIRE|GSTFONT|BLODGR|BLODRIP|SLADRIP|'
              r'ROCKRED|WFALL|SFALL|BFALL|DBRAIN|BRNSMAL|MIDBARS|MIDGRATE|MIDSPACE|MIDVINE)')
MATCH_SKIP_FLATS = r'^(F_SKY|NUKAGE|FWATER|SWATER|LAVA|BLOOD|SLIME|RROCK0[5-8]|GATE|TLITE|CEIL1_2|FLAT22)'
# animations cycle by name: one replacement for the whole range
MATCH_ANIMS = (r'^(FIREBLU|FIRELAV|FIREMAG|FIREWALL|FIRELAVA|BFALL|SFALL|WFALL|BLODGR|BLODRIP|SLADRIP|GSTFONT|'
               r'ROCKRED|DBRAIN|NUKAGE|FWATER|SWATER|LAVA|BLOOD|SLIME|RROCK0[5-8])')


# Doom texture kinds -> the families of a texture set that can stand in for
# them (Ashes 2063 names: BRIK, RUIN, OFIC, CONS...): tried first, by look
TEXTURE_KINDS = [
    (r'^(BRICK|BRNBIGL|BIGBRIK|BRNSMAL|BRICKLIT)', r'^(BRIK|WALL|RUIN|HOUS|TOWN|CITY|SHOP)'),
    (r'^(STONE|ROCK|ASHWALL|SP_ROCK|TANROCK|ZIMMER|GSTONE|GRAYVINE|GSTVINE|BSTONE|ZDOOR)', r'^(ROCK|CONC|RUIN|DAM|BOG)'),
    (r'^(METAL|SHAWN|SUPPORT|TEKWALL|PIPE|ICKWALL|SILVER|SPCDOOR|STEEL|TEKGREN|TEKBRON|TEKLITE)', r'^(IRON|INDUS|PIPE|RUST|WARE|BASE|GARAG)'),
    (r'^(WOOD|BIGDOOR5|BIGDOOR6|PANEL|PANCASE|PANBOOK|PANBORD|PANBLACK|PANRED)', r'^(WOOD|HOUS|BOG|BAR|KITCHEN|OFIC)'),
    (r'^(MARB|GSTFONT|GSTSATYR|GSTLION|GSTGARG|STUCCO|PLAT|CEMENT|BROVINE)', r'^(STUC|PLAS|OFIC|CONC|HOSP|MALL)'),
    (r'^(STARTAN|STARG|STARBR|BROWN|GRAY|SLAD|SLOPPY|SKSNAKE|COMPBLUE|COMPOHSO|BLAKWAL|MODWALL|NUKE)', r'^(BASE|WARE|INDUS|CONC|SUB|OFIC|IRON)'),
    (r'^(COMP|SPACEW|PLANET|COMPUTE|SILVER2)', r'^(CONS|COMP|BASE)'),
    (r'^(LITE|LIGHT)', r'^(LIGT|WINDOW|GLASS)'),
    (r'^(R?SKY)', r'^(ASKY)'),
    (r'^(STEP)', r'^(STEP|CONC|IRON)'),
    (r'^(CRATE|CRATINY|CRATWIDE|CRATELIT)', r'^(CONTAN|WARE|TRUCK|WOOD|JUNK)'),
    (r'^(MIDBARS|MIDGRATE|MIDBRN|MIDSPACE|MIDVINE|BRNSMAL)', r'^(FENC|GATE|VINES|GLASS)'),
    (r'^(SKIN|SP_FACE|SP_HOT|FIRE|BLOOD|GSTMOSS|ROCKRED|SFALL|BFALL|WFALL|SLADRIP|BLODRIP)', r'^(RUIN|VINES|FALL|CYFAL|ROCK|RUST)'),
]
DOOM_DOORS = r'^(BIGDOOR|DOOR[0-9]|SPCDOOR|EXITDOOR)'
SET_DOORS = r'^(DOOR|GATE|BASEDOOR|ELECDOOR)'
SWITCH_WALLS = r'^(WALL|CONC|IRON|BASE|INDUS|WARE|OFIC|BRIK|STUC|PLAS|HOUS|TOWN|RUIN|RUST)'


def texture_dir_set(src, pal):
    """A GZDoom texture set laid out as files (Ashes 2063's Textures/, patches/,
    FLATS/ and its TEXTURES definitions) as (textures, patches, flats) in the
    shape parse_textures() / sections() give."""
    root = os.path.join(ROOT, src['dir'])
    images = {}
    for sub in ('Textures', 'patches'):
        d = os.path.join(root, sub)
        for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            images.setdefault(os.path.splitext(f)[0].upper()[:8], os.path.join(d, f))

    pa = {}

    def patch(name):
        if name not in pa and name in images:
            path = images[name]
            raw = open(path, 'rb').read()
            if raw[:4] == b'\x89PNG':
                if struct.unpack('>I', raw[20:24])[0] > 254:     # taller than a Doom picture can be
                    return None
                pa[name] = texture_pack.png_patch(path, pal)
            else:
                pa[name] = raw
        return pa.get(name)
    tex = collections.OrderedDict()
    for defs in src.get('defs', []):
        text = open(os.path.join(ROOT, defs), encoding='latin-1').read()
        for m in re.finditer(r'^\s*(?:Wall)?Texture\s+"?([\w-]+)"?\s*,\s*(\d+)\s*,\s*(\d+)\s*\{(.*?)^\s*\}', text, re.M | re.S | re.I):
            pats = [(int(x), int(y), pn.upper()[:8], 0, 0)
                    for pn, x, y in re.findall(r'Patch\s+"?([\w-]+)"?\s*,\s*(-?\d+)\s*,\s*(-?\d+)', m.group(4), re.I)]
            if pats and all(patch(pn) for _, _, pn, _, _ in pats):
                tex[m.group(1).upper()[:8]] = (0, int(m.group(2)), int(m.group(3)), 0, pats)
    for name in images:
        if name not in tex and patch(name):
            w, h = struct.unpack_from('<hh', pa[name])
            tex[name] = (0, w, h, 0, [(0, 0, name, 0, 0)])
    fl = {}
    fd = os.path.join(root, 'FLATS')
    for f in sorted(os.listdir(fd)) if os.path.isdir(fd) else []:
        path, name = os.path.join(fd, f), os.path.splitext(f)[0].upper()[:8]
        raw = open(path, 'rb').read()
        if raw[:4] == b'\x89PNG':
            rows = texture_pack._png_rgba(path, {})
            if len(rows) >= 64 and len(rows[0]) >= 64:
                fl[name] = bytes(pal.match(*rows[y][x][:3]) for y in range(64) for x in range(64))
        elif len(raw) == 4096:
            fl[name] = raw
        else:
            try:
                img, _, _ = hud_bar.patch_pixels(raw)
                if len(img) >= 64 and len(img[0]) >= 64:
                    fl[name] = bytes((img[y][x] or 0) for y in range(64) for x in range(64))
            except Exception:
                pass
    return tex, pa, fl


def texture_look(img, pal):
    """Colour layout of a palette image (rows of indices / None): 8x8 cell
    averages and how much of it is see-through."""
    h, w = len(img), len(img[0])
    cells, holes = [], 0
    for cy in range(8):
        for cx in range(8):
            acc, n = [0, 0, 0], 0
            for y in range(cy * h // 8, max(cy * h // 8 + 1, (cy + 1) * h // 8)):
                for x in range(cx * w // 8, max(cx * w // 8 + 1, (cx + 1) * w // 8)):
                    c = img[y][x]
                    if c is None:
                        holes += 1
                        continue
                    r, g, b = pal.rgb[c]
                    acc[0] += r; acc[1] += g; acc[2] += b; n += 1
            cells.append(tuple(v / n for v in acc) if n else (0, 0, 0))
    # busyness: mean brightness step between neighbouring pixels (stripes and
    # checks average out to the same grey as a plain surface)
    lum = [[None if c is None else pal.rgb[c][0] * 3 + pal.rgb[c][1] * 6 + pal.rgb[c][2] for c in row] for row in img]
    steps = [abs(row[x] - row[x + 1]) for row in lum for x in range(w - 1) if row[x] is not None and row[x + 1] is not None]
    steps += [abs(lum[y][x] - lum[y + 1][x]) for y in range(h - 1) for x in range(w)
              if lum[y][x] is not None and lum[y + 1][x] is not None]
    cells.append((sum(steps) / max(1, len(steps)) / 10,) * 3)
    return cells, holes > 0


def look_distance(a, b):
    colour = sum(2 * (p[0] - q[0]) ** 2 + 4 * (p[1] - q[1]) ** 2 + 3 * (p[2] - q[2]) ** 2 for p, q in zip(a[:-1], b[:-1]))
    return colour + 9 * 64 * (a[-1][0] - b[-1][0]) ** 2       # busyness counts like the whole grid


def match_textures(profile, glob, patches, flats, mod_art, used_tex, used_flats, pal, switch_kinds=None):
    """Profile "texture_match": {"wad": ...}: a texture set with names of its
    own (Duke Nukem 3D's, in Doom's palette) stands in for the stock ones by
    look. Returns how many textures and flats were replaced."""
    src = profile['texture_match']
    if src.get('dir'):
        theirs, pa, fl = texture_dir_set(src, pal)
    else:
        g, _, pa, fl, _ = sections(Wad(os.path.join(ROOT, src['wad'])))
        g = dict(g)
        pa = dict(pa)
        their_pnames = parse_pnames(g['PNAMES'])
        for n in their_pnames:          # patches may sit outside P_START/P_END
            if n not in pa and n in g:
                pa[n] = g[n]
        theirs = parse_textures(g['TEXTURE1'], their_pnames)
        if 'TEXTURE2' in g:
            theirs.update(parse_textures(g['TEXTURE2'], their_pnames))
    ours = parse_textures(glob['TEXTURE1'], parse_pnames(glob['PNAMES']))
    doom_size = {n: (v[1], v[2]) for n, v in ours.items()}
    # "all": nothing keeps Doom's look - doors, switches, steps, lights and
    # skies take a replacement of the very same size (they line up with the
    # map), each animation one replacement for all its frames
    everything = src.get('all')
    skip = re.compile(src.get('skip', MATCH_SKIP))
    anims = re.compile(MATCH_ANIMS)
    group_pick = {}
    looks = {}
    for name, (masked, w, h, coldir, pats) in theirs.items():
        if w < 16 or h < 16 or any(p[2] not in pa for p in pats):
            continue
        img, _, _ = hud_bar.patch_pixels(texture_pack.bake_texture(w, h, pats, pa, pal))
        looks[name] = (h,) + texture_look(img, pal)
    renamed, taken, chosen = {}, 0, {}
    # an animation's other frames get the same replacement as the used one
    base = lambda x: re.sub(r'\d+$', '', x)
    used_tex = set(used_tex) | {o for o in ours if anims.match(o) and any(base(u) == base(o) for u in used_tex if anims.match(u))}
    used_flats = set(used_flats) | {o for o in flats if anims.match(o) and any(base(u) == base(o) for u in used_flats if anims.match(u))}
    for name in sorted(used_tex):
        if name not in ours or (skip.match(name) and not everything):
            continue
        masked, w, h, coldir, pats = ours[name]
        if any(p[2] not in patches for p in pats) or (not everything and any(p[2] in mod_art for p in pats)):
            continue    # "all" replaces the level pack's own textures too
        group = re.sub(r'\d+$', '', name) if anims.match(name) else None
        # "force": {"BIGDOOR1": "DOOR31"} - a hand pick wins over the look
        # (a door the maps show cropped needs one that reads at any height)
        forced = src.get('force', {}).get(name)
        if forced in theirs:
            best = (0, forced)
        elif group in group_pick:
            best = group_pick[group]
        else:
            img, _, _ = hud_bar.patch_pixels(texture_pack.bake_texture(w, h, pats, patches, pal))
            cells, holes = texture_look(img, pal)
            same_w = skip.match(name)
            fits = [n for n, lk in looks.items()
                    if lk[0] == h and lk[2] == holes and (not same_w or theirs[n][1] == w)]
            if not fits and same_w:     # e.g. an 8-wide door track: a repeating one
                fits = [n for n, lk in looks.items() if lk[0] == h and lk[2] == holes]
            if re.match(DOOM_DOORS, name):      # doors only from the set's doors
                doors = [n for n in looks if re.match(SET_DOORS, n) and looks[n][0] == h]
                fits = [n for n in doors if theirs[n][1] == w] or doors or fits
            else:
                fits = [n for n in fits if not re.match(SET_DOORS, n)] or fits     # doors only on doors
                if name.startswith(('SW1', 'SW2')):     # a plain wall behind the switch panel
                    fits = [n for n in fits if re.match(SWITCH_WALLS, n)] or fits
                for doom_kind, set_kind in TEXTURE_KINDS:   # the same kind of surface first
                    if re.match(doom_kind, name):
                        fits = [n for n in fits if re.match(set_kind, n)] or fits
                        break
            best = min((look_distance(cells, looks[n][1]), n) for n in fits) if fits else None
            if group:
                group_pick[group] = best
        if not best:
            continue
        mine = theirs[best[1]]
        new = []
        for ox, oy, pn, sd, cm in mine[4]:
            if pn not in renamed:
                renamed[pn] = 'XD%04d' % len(renamed)
                patches[renamed[pn]] = pa[pn]
            new.append((ox, oy, renamed[pn], sd, cm))
        ours[name] = (mine[0], mine[1], mine[2], mine[3], new)
        chosen[name] = best[1]
        taken += 1
    # switches: the wall picked for SW1xxx with one of the set's switch panels
    # in the middle - off (SW1) and on (SW2) - chosen by what the switch does
    # in the maps: an access keypad for doors, a call box for lifts, a lever
    # for exits, a keypad otherwise
    panels = src.get('switch_panels')
    if panels:
        for name in sorted(used_tex):
            twin = 'SW2' + name[3:]
            if not name.startswith('SW1') or name not in chosen or twin not in ours:
                continue
            off_p, on_p = panels.get((switch_kinds or {}).get(name, 'door'), panels['door'])
            if off_p not in pa or on_p not in pa:
                continue
            w, h = doom_size[name]
            base = theirs[chosen[name]][4]
            for doom, panel in ((name, off_p), (twin, on_p)):
                new = []
                for ox, oy, pn, sd, cm in base + [(None, None, panel, 0, 0)]:
                    if pn not in renamed:
                        renamed[pn] = 'XD%04d' % len(renamed)
                        patches[renamed[pn]] = pa[pn]
                    if ox is None:      # the panel, centred
                        pw, ph = struct.unpack_from('<hh', pa[pn])
                        ox, oy = (w - pw) // 2, (h - ph) // 2
                    new.append((ox, oy, renamed[pn], sd, cm))
                ours[doom] = (0, w, h, 0, new)
                chosen[doom] = '%s+%s' % (chosen[name], panel)
    glob['TEXTURE1'], glob['PNAMES'], _ = build_textures(ours)
    glob.pop('TEXTURE2', None)
    # flats
    fskip = re.compile(src.get('skip_flats', MATCH_SKIP_FLATS))
    flat_looks = {n: texture_look([list(d[64 * y:64 * y + 64]) for y in range(64)], pal)[0]
                  for n, d in fl.items() if len(d) == 4096}
    flats_taken = 0
    flat_group = {}
    for n in sorted(used_flats):
        if n not in flats or (n in mod_art and not everything) or n.startswith('F_SKY') or len(flats[n]) != 4096 or not flat_looks:
            continue
        if fskip.match(n) and not everything:
            continue
        group = re.sub(r'\d+$', '', n) if anims.match(n) else None
        if n in fl and len(fl[n]) == 4096 and src.get('dir'):    # the set redraws Doom's own flat
            flats[n] = fl[n]
            chosen[n] = n
            flats_taken += 1
            continue
        if group in flat_group:
            best = flat_group[group]
        else:
            cells = texture_look([list(flats[n][64 * y:64 * y + 64]) for y in range(64)], pal)[0]
            best = min((look_distance(cells, lk), m) for m, lk in flat_looks.items())
            if group:
                flat_group[group] = best
        flats[n] = fl[best[1]]
        chosen[n] = best[1]
        flats_taken += 1
    return taken, flats_taken, chosen


# Pixel digits drawn for the 240x135 panel (scaled art blurs at this size):
# 6x9 with two-pixel strokes for the main numbers, 4x6 for the reserve.
HUD_BIG = ['.####.|##..##|##..##|##..##|##..##|##..##|##..##|##..##|.####.',
           '..##..|.###..|..##..|..##..|..##..|..##..|..##..|..##..|.####.',
           '.####.|##..##|....##|....##|...##.|..##..|.##...|##....|######',
           '.####.|##..##|....##|....##|..###.|....##|....##|##..##|.####.',
           '...##.|..###.|.####.|##.##.|##.##.|######|...##.|...##.|...##.',
           '######|##....|##....|#####.|....##|....##|....##|##..##|.####.',
           '.####.|##..##|##....|#####.|##..##|##..##|##..##|##..##|.####.',
           '######|....##|....##|...##.|...##.|..##..|..##..|..##..|..##..',
           '.####.|##..##|##..##|##..##|.####.|##..##|##..##|##..##|.####.',
           '.####.|##..##|##..##|##..##|.#####|....##|....##|##..##|.####.']
HUD_SMALL = ['.##.|#..#|#..#|#..#|#..#|.##.', '.#..|##..|.#..|.#..|.#..|###.',
             '.##.|#..#|..#.|.#..|#...|####', '###.|...#|.##.|...#|...#|###.',
             '#..#|#..#|####|...#|...#|...#', '####|#...|###.|...#|...#|###.',
             '.##.|#...|###.|#..#|#..#|.##.', '####|...#|..#.|.#..|.#..|.#..',
             '.##.|#..#|.##.|#..#|#..#|.##.', '.##.|#..#|#..#|.###|...#|.##.']


def hud_overlay_lumps(profile, glob):
    """Overlay HUD art (engine st_stuff.c MOD_HUD_OVERLAY), drawn 1:1 on the
    240x135 panel: pixel digits in Ashes 2063's HUD green (HUDN big, HUDS
    small, one column of spacing), a slash, Ashes' heart and shield icons at
    half size and its key cards/keys (HUDKEY0-5)."""
    art = os.path.join(ROOT, profile.get('hud_art', 'wads/ashesweap/pk/Graphics'))
    pal = texture_pack.Palette(glob['PLAYPAL'][:768])
    green = pal.match(96, 232, 96)

    def glyph(rows):
        rows = rows.split('|')
        return hud_bar.make_patch([[green if c == '#' else None for c in r] + [None] for r in rows], 0, 0)
    out = []
    for i in range(10):
        out.append(('HUDN%d' % i, glyph(HUD_BIG[i])))
        out.append(('HUDS%d' % i, glyph(HUD_SMALL[i])))
    out.append(('HUDSLASH', glyph('...#|...#|..#.|..#.|.#..|.#..|#...|#...|#...')))
    out.append(('HUDHLTH', texture_pack.png_patch(os.path.join(art, 'hud_hlth.png'), pal, 1, 2)))
    out.append(('HUDARMR', texture_pack.png_patch(os.path.join(art, 'hud_armr.png'), pal, 1, 2)))
    for i in range(6):      # blue/yellow/red card, then skull keys
        out.append(('HUDKEY%d' % i, texture_pack.png_patch(os.path.join(art, 'STKEYS%d' % i), pal)))
    return out


def gba_level(lumps, tex_index):
    vx = lumps['VERTEXES']
    nv = len(vx) // 4
    verts = [struct.unpack_from('<hh', vx, 4 * i) for i in range(nv)]
    vfix = [(x << 16, y << 16) for x, y in verts]
    new_vx = b''.join(struct.pack('<ii', x, y) for x, y in vfix)

    ld = lumps['LINEDEFS']
    nl = len(ld) // 14
    raw_lines = [struct.unpack_from('<hhhhhHH', ld, 14 * i) for i in range(nl)]
    lines_out = bytearray()
    line_sides = []
    for i, (v1, v2, flags, special, tag, s0, s1) in enumerate(raw_lines):
        (x1, y1), (x2, y2) = vfix[v1 & 0xffff], vfix[v2 & 0xffff]
        dx, dy = x2 - x1, y2 - y1
        if not dx:
            slope = 1       # ST_VERTICAL
        elif not dy:
            slope = 0       # ST_HORIZONTAL
        else:
            slope = 2 if (dy > 0) == (dx > 0) else 3   # ST_POSITIVE / ST_NEGATIVE
        bbox = [max(y1, y2), min(y1, y2), min(x1, x2), max(x1, x2)]  # TOP BOTTOM LEFT RIGHT
        lines_out += struct.pack('<iiiiIiiHHiiiiHhhH', x1, y1, x2, y2, i, dx, dy, s0, s1,
                                 bbox[0], bbox[1], bbox[2], bbox[3],
                                 flags & 0xffff, special, tag, slope)
        line_sides.append((s0, s1, flags))

    sd = lumps['SIDEDEFS']
    ns = len(sd) // 30
    sides_out = bytearray()
    side_sector = []
    for i in range(ns):
        xo, yo = struct.unpack_from('<hh', sd, 30 * i)
        top, bot, mid = (sd[30 * i + 4 + 8 * k:30 * i + 12 + 8 * k].split(b'\0')[0].decode('latin-1').upper()
                         for k in range(3))
        sector = struct.unpack_from('<h', sd, 30 * i + 28)[0]
        side_sector.append(sector)
        sides_out += struct.pack('<hhhhhh', xo, yo, tex_index.get(top, 0), tex_index.get(bot, 0),
                                 tex_index.get(mid, 0), sector)

    sg = lumps['SEGS']
    nseg = len(sg) // 12
    segs_out = bytearray()
    NO_INDEX = 0xffff
    for i in range(nseg):
        v1, v2, angle, linedef, side, offset = struct.unpack_from('<HHhHhh', sg, 12 * i)
        (x1, y1), (x2, y2) = vfix[v1], vfix[v2]
        s0, s1, flags = line_sides[linedef]
        sidenum = (s0, s1)[side]
        front = side_sector[sidenum] if sidenum != NO_INDEX else NO_INDEX
        back = NO_INDEX
        if flags & 4:   # ML_TWOSIDED
            other = (s0, s1)[side ^ 1]
            if other != NO_INDEX:
                back = side_sector[other]
        segs_out += struct.pack('<iiiiiIHHHH', x1, y1, x2, y2, (offset << 16), (angle << 16) & 0xffffffff,
                                sidenum, linedef, front & 0xffff, back & 0xffff)

    # Subsectors with their sector worked out (engine subsector_t: numlines,
    # firstline, sector, pad), and each sector's line list and sound origin
    # (SECLINES: u16 start[numsectors + 1], u16 line numbers, pad to 4, then
    # fixed x, y per sector): read in place from flash instead of being built
    # in the zone at level load.
    ss = lumps['SSECTORS']
    ssect_out = bytearray()
    for i in range(len(ss) // 4):
        count, first = struct.unpack_from('<HH', ss, 4 * i)
        sec = None
        for k in range(first, first + count):
            linedef, side = struct.unpack_from('<Hh', sg, 12 * k + 6)
            sidenum = line_sides[linedef][side]
            if sidenum != NO_INDEX:
                sec = side_sector[sidenum]
                break
        if sec is None:
            raise SystemExit('subsector %d is part of no sector' % i)
        ssect_out += struct.pack('<HHHH', count, first, sec, 0)

    nsec = len(lumps['SECTORS']) // 26
    sec_lines = [[] for _ in range(nsec)]
    for i, (s0, s1, flags) in enumerate(line_sides):
        front = side_sector[s0] if s0 != NO_INDEX else None
        back = side_sector[s1] if s1 != NO_INDEX else None
        if front is not None:
            sec_lines[front].append(i)
        if back is not None and back != front:
            sec_lines[back].append(i)
    starts, flat = [], []
    for ls in sec_lines:
        starts.append(len(flat))
        flat += ls
    starts.append(len(flat))
    if len(flat) > 0xffff:
        raise SystemExit('SECLINES: %d sector lines, more than 65535' % len(flat))

    out = dict(lumps)
    out['VERTEXES'] = new_vx
    out['LINEDEFS'] = bytes(lines_out)
    out['SIDEDEFS'] = bytes(sides_out)
    out['SEGS'] = bytes(segs_out)
    out['SSECTORS'] = bytes(ssect_out)
    # then each sector's sound origin (fixed x, y; 4-aligned), worked out the
    # way the engine did: the centre of M_AddToBox's box over its lines
    INT_MAX, INT_MIN = 0x7fffffff, -0x80000000
    half = lambda v: int(v / 2)             # C division truncates
    orgs = bytearray()
    for ls in sec_lines:
        top, bottom, left, right = INT_MIN, INT_MAX, INT_MAX, INT_MIN
        for i in ls:
            v1, v2 = raw_lines[i][0] & 0xffff, raw_lines[i][1] & 0xffff
            for x, y in (vfix[v1], vfix[v2]):
                if x < left:
                    left = x
                elif x > right:
                    right = x
                if y < bottom:
                    bottom = y
                elif y > top:
                    top = y
        orgs += struct.pack('<ii', half(right) + half(left), half(top) + half(bottom))
    seclines = struct.pack('<%dH' % len(starts), *starts) + struct.pack('<%dH' % len(flat), *flat)
    seclines += b'\0' * (-len(seclines) % 4)
    out['SECLINES'] = seclines + bytes(orgs)
    return out


# ---------------------------------------------------------------- rescale (DO_RESCALE)

def rescale_patch(data):
    """Half-resolution patch (after GbaWadUtil rescale_sprite()): keep the
    full-size header and post lengths, store every other column and every
    other pixel of each post (ceil(len/2) bytes, so a 1-pixel post keeps its
    pixel). The renderer (HALF_RES_SPRITES) samples at half resolution and
    steps posts by ceil(len/2) + 4."""
    w, h, lo, to = struct.unpack_from('<hhhh', data)
    cols = struct.unpack_from('<%dI' % w, data, 8)
    head = struct.pack('<hhhh', w, h, lo, to)
    ncols = (w + 1) // 2
    body = bytearray()
    offs = []
    base = 8 + 4 * ncols
    for c in range(0, w, 2):
        offs.append(base + len(body))
        p = cols[c]
        while data[p] != 0xff:
            top, n = data[p], data[p + 1]
            px = data[p + 3:p + 3 + n]
            body += bytes([top, n, 0]) + px[0::2] + b'\0'
            p += 4 + n
        body.append(0xff)
    return head + struct.pack('<%dI' % ncols, *offs) + bytes(body)


def rescale_patch_x(data):
    """Every other column, posts untouched (HALFSPR bit 0 only): enemies keep
    their full height detail."""
    w, h, lo, to = struct.unpack_from('<hhhh', data)
    cols = struct.unpack_from('<%dI' % w, data, 8)
    ncols = (w + 1) // 2
    body = bytearray()
    offs = []
    base = 8 + 4 * ncols
    for c in range(0, w, 2):
        offs.append(base + len(body))
        p = cols[c]
        while data[p] != 0xff:
            n = data[p + 1]
            body += data[p:p + 4 + n]
            p += 4 + n
        body.append(0xff)
    return struct.pack('<hhhh', w, h, lo, to) + struct.pack('<%dI' % ncols, *offs) + bytes(body)


SPRITE_QUALITY = 'half'     # profile "sprite_quality": "full" keeps all but weapons at full size


def sprite_half_flags(name, weapon_frames, enemy_frames, enabled, size=None):
    """HALFSPR flags for a sprite lump: 4 stored at the 3/4 scale weapons are
    drawn at (no detail lost), 1 columns halved (enemies), 3 columns and rows
    halved (items, decorations, effects)."""
    if not enabled:
        return 0
    if is_weapon_lump(name, weapon_frames):
        return 4
    if SPRITE_QUALITY == 'full':
        return 0
    if size and size[0] * size[1] <= 256:
        return 0    # projectiles, sparks: halving saves nothing, magnified up close they turn to blocks
    if any((name[:4], f) in enemy_frames for f in sprite_lump_frames(name)):
        return 1
    return 3


def scaled_psprite(data, nudge, name, pal):
    """Weapon frame at 3/4 scale (cached in build/sprcache). `nudge` (profile
    "psprite_nudge"): {lump name prefix: [left, up]} moves frames in 320x200
    pixels first, e.g. a weapon drawn mostly under the status bar."""
    import hashlib
    lo, to = struct.unpack_from('<hh', data, 4)
    for prefix, (dx, dy) in sorted(nudge.items()):
        if name.startswith(prefix):
            lo, to = lo + dx, to + dy
    data = data[:4] + struct.pack('<hh', lo, to) + data[8:]
    cache = os.path.join(os.path.dirname(texture_pack.CACHE), 'sprcache')
    path = os.path.join(cache, hashlib.sha1(data + bytes(pal.rgb[0]) + bytes(pal.rgb[255]) +
                                            texture_pack.RESAMPLE.encode()).hexdigest() + '.lmp')
    if os.path.exists(path):
        return open(path, 'rb').read()
    out = texture_pack.scale_patch(data, pal)
    os.makedirs(cache, exist_ok=True)
    open(path, 'wb').write(out)
    return out


def rescale_flat(data):
    return bytes(data[64 * r + c] for r in range(0, 64, 2) for c in range(0, 64, 2))


# ---------------------------------------------------------------- main

def engine_literals():
    lits = set()
    for f in os.listdir(DOOM_SRC):
        if f.endswith('.c'):
            s = open(os.path.join(DOOM_SRC, f), encoding='latin-1').read()
            lits |= {x.upper() for x in re.findall(r'"([A-Za-z0-9_]{3,8})"', s)}
    return lits


def mus2mid(data, tmpdir):
    tool = os.path.join(ROOT, 'build', 'host', 'mus2mid')
    if not os.path.exists(tool):
        os.makedirs(os.path.dirname(tool), exist_ok=True)
        subprocess.check_call(['cc', '-O2', '-w', '-I' + os.path.join(HERE, 'host', 'stub'),
                               '-I' + os.path.join(HERE, 'wadconverter'), '-o', tool,
                               os.path.join(HERE, 'host', 'mus2mid_main.c'),
                               os.path.join(HERE, 'wadconverter', 'mus2mid.c')])
    src = os.path.join(tmpdir, 'in.mus')
    dst = os.path.join(tmpdir, 'out.mid')
    with open(src, 'wb') as f:
        f.write(data)
    subprocess.check_call([tool, src, dst])
    with open(dst, 'rb') as f:
        return f.read()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--profile', help='mod profile (tools/mods/*.json): IWAD, PWADs in load order, .deh files, maps')
    ap.add_argument('--iwad', default=os.path.expanduser('~/Library/Application Support/gzdoom/DOOM2.WAD'))
    ap.add_argument('--no-pwad', action='store_true', help='plain Doom II MAP01-10 (bring-up test)')
    ap.add_argument('--out', default=os.path.join(ROOT, 'data', 'game.wad'))
    ap.add_argument('--sfx-rate', type=int, default=MIX_RATE, help='resample sounds above this rate')
    ap.add_argument('--drop-screens', action='store_true', help='drop INTERPIC (TITLEPIC is reused)')
    ap.add_argument('--half-sprites', action=argparse.BooleanOptionalAction, default=True,
                    help='half-resolution sprites (firmware: HALF_RES_SPRITES)')
    ap.add_argument('--half-flats', action=argparse.BooleanOptionalAction, default=True,
                    help='32x32 flats (firmware: HALF_RES_FLATS)')
    ap.add_argument('--budget', type=lambda x: int(x, 0), default=LAUNCHER_APP_SPACE - CODE_RESERVE,
                    help='max data size (default: what fits next to M5Launcher)')
    ap.add_argument('--music', action=argparse.BooleanOptionalAction, default=True)
    args = ap.parse_args()

    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)

    profile = deh2c.load_profile(args.profile) if args.profile else {}
    if args.no_pwad:
        profile = {'pwads': [], 'deh': []}
    elif not profile:
        ap.error('need --profile (or --no-pwad)')
    global SPRITE_QUALITY
    SPRITE_QUALITY = profile.get('sprite_quality', 'half')
    texture_pack.RESAMPLE = profile.get('sprite_resample', 'average')
    first_map, last_map = profile.get('maps', [1, NUM_MAPS])
    iwad_path = profile.get('iwad', args.iwad)

    t = deh2c.load_tables()
    patch = deh2c.load_patch(t, profile['deh'], profile.get('transplant', []), profile.get('zweapons', []),
                             profile.get('state_chains'), profile.get('extra_ammo'), profile.get('sound_variants'))
    states, mobj, weapons = deh2c.apply_deh(t, patch)

    # ---- merge, in load order (later files win, like -file a.wad b.wad)
    glob = collections.OrderedDict()
    sprites = collections.OrderedDict()
    patches = {}
    flats = collections.OrderedDict()       # replaced in place, new ones appended
    all_maps = {}
    # texture_wads (e.g. Freedoom) only re-skin walls and floors: their patches
    # and flats replace the IWAD's same-named ones, before the PWADs load.
    texture_wads = profile.get('texture_wads', [])
    iwad_glob = None
    mod_art = set()     # patches and flats the PWADs bring (kept over a texture pack)
    wad_maps, wad_glob = {}, {}     # per PWAD, for map_list entries [pwad index, map]
    merged_tex, tex_sources = collections.OrderedDict(), 0
    for path in [iwad_path] + texture_wads + profile['pwads']:
        g, sp, pa, fl, mp = sections(Wad(path))
        if iwad_glob is None:
            iwad_glob = dict(g)
        if path in profile['pwads']:
            wad_maps[profile['pwads'].index(path)] = dict(mp)
            wad_glob[profile['pwads'].index(path)] = dict(g)
        if path in profile['pwads']:
            mod_art |= set(pa) | set(fl)
        if path in texture_wads:
            patches.update(pa)
            flats.update((n, d) for n, d in fl.items() if n in flats)
            continue
        for n, d in g:
            glob[n] = d
        gd = dict(g)
        if 'TEXTURE1' in gd and 'PNAMES' in gd:
            # textures of all the WADs together (two map packs): a later
            # WAD's definition wins over an earlier one of the same name
            merged_tex.update(parse_textures(gd['TEXTURE1'], parse_pnames(gd['PNAMES'])))
            tex_sources += path in profile['pwads']
        sprites.update(sp)
        patches.update(pa)
        flats.update(fl)
        all_maps.update(mp)
    if tex_sources > 1:
        glob['TEXTURE1'], glob['PNAMES'], _ = build_textures(merged_tex)
    # ---- profile "texture_source": {"wad": "wads/hacx/HACX.WAD", "skip": regex}:
    # another game's walls and floors under the same names (Hacx reuses Doom
    # II's). A stock texture (only IWAD patches, no PWAD art) takes that
    # game's definition when the height matches - a different width only
    # changes how often it repeats - unless `skip` matches (doors, switches,
    # steps: their art lines up with the map). Its patches come in renamed
    # (XP0000...) so nothing else changes; its flats replace stock ones.
    src = profile.get('texture_source')
    if src:
        g, _, pa, fl, _ = sections(Wad(os.path.join(ROOT, src['wad'])))
        g = dict(g)
        theirs = parse_textures(g['TEXTURE1'], parse_pnames(g['PNAMES']))
        if 'TEXTURE2' in g:
            theirs.update(parse_textures(g['TEXTURE2'], parse_pnames(g['PNAMES'])))
        ours = parse_textures(glob['TEXTURE1'], parse_pnames(glob['PNAMES']))
        skip = re.compile(src.get('skip', r'^(DOOR|SW[12]|STEP|EXIT|BIGDOOR|SPCDOOR|LITE)'))
        renamed, taken = {}, 0
        for name, (masked, w, h, coldir, pats) in list(ours.items()):
            mine = theirs.get(name)
            if not mine or mine[2] != h or skip.match(name) or any(p[2] in mod_art for p in pats):
                continue
            new = []
            for ox, oy, p, sd, cm in mine[4]:
                if p not in pa:
                    break
                if p not in renamed:
                    renamed[p] = 'XP%04d' % len(renamed)
                    patches[renamed[p]] = pa[p]
                new.append((ox, oy, renamed[p], sd, cm))
            else:
                ours[name] = (mine[0], mine[1], mine[2], mine[3], new)
                taken += 1
        glob['TEXTURE1'], glob['PNAMES'], _ = build_textures(ours)
        glob.pop('TEXTURE2', None)
        flats_taken = 0
        for n, d in fl.items():
            if n in flats and n not in mod_art and n != 'F_SKY1':
                flats[n] = d
                flats_taken += 1
        print('texture_source %s: %d textures, %d flats' % (src['wad'], taken, flats_taken))
    if profile.get('texture_match'):
        used_tex, used_flats = set(), set()
        for m in all_maps.values():
            sd = m['SIDEDEFS']
            for k in range(len(sd) // 30):
                for q in range(3):
                    used_tex.add(sd[30 * k + 4 + 8 * q:30 * k + 12 + 8 * q].split(b'\0')[0].decode('latin-1').upper())
            se = m['SECTORS']
            for k in range(len(se) // 26):
                for q in range(2):
                    used_flats.add(se[26 * k + 4 + 8 * q:26 * k + 12 + 8 * q].split(b'\0')[0].decode('latin-1').upper())
        # what each switch texture does in the maps (its lines' specials)
        DOOR = {1, 26, 27, 28, 29, 31, 32, 33, 34, 42, 46, 61, 63, 99, 103, 111, 112, 113, 114, 115, 116, 117, 118,
                133, 134, 135, 136, 137, 175, 196}
        LIFT = {10, 14, 15, 21, 53, 54, 62, 66, 67, 68, 69, 87, 88, 95, 120, 121, 122, 123}
        EXIT = {11, 51, 52, 124, 197, 198}
        kinds = collections.defaultdict(collections.Counter)
        for m in all_maps.values():
            sd, ld = m['SIDEDEFS'], m['LINEDEFS']
            for k in range(len(ld) // 14):
                special, s0 = struct.unpack_from('<h', ld, 14 * k + 6)[0], struct.unpack_from('<H', ld, 14 * k + 10)[0]
                if not special or s0 == 0xffff or 30 * s0 + 30 > len(sd):
                    continue
                kind = 'door' if special in DOOR else 'lift' if special in LIFT else 'exit' if special in EXIT else 'other'
                for q in range(3):
                    tex = sd[30 * s0 + 4 + 8 * q:30 * s0 + 12 + 8 * q].split(b'\0')[0].decode('latin-1').upper()
                    if tex.startswith('SW1'):
                        kinds[tex][kind] += 1
        switch_kinds = {t: max(c, key=lambda k: (c[k], k == 'door')) for t, c in kinds.items()}
        pal_m = texture_pack.Palette(glob['PLAYPAL'][:768])
        taken, flats_taken, chosen = match_textures(profile, glob, patches, flats, mod_art, used_tex, used_flats, pal_m,
                                                    switch_kinds)
        print('texture_match %s: %d textures, %d flats' % (profile['texture_match'].get('wad') or profile['texture_match'].get('dir'), taken, flats_taken))
        with open(os.path.join(os.path.dirname(args.out), 'texture_match.txt'), 'w') as f:
            f.write(''.join('%s -> %s\n' % kv for kv in sorted(chosen.items())))
    # ---- profile "sprite_wad": {"wad": "wads/hacx/HACX.WAD", "prefixes": [...]}:
    # another game's art under Doom's sprite names (Hacx's office chairs,
    # lamps and plants for Doom's candles, torches and impaled bodies). A
    # prefix is taken only when that game has every frame letter Doom's does.
    src = profile.get('sprite_wad')
    if src:
        _, their_sp, _, _, _ = sections(Wad(os.path.join(ROOT, src['wad'])))
        taken = []
        for pre in src['prefixes']:
            ours_l = {n[4] for n in sprites if n.startswith(pre)} | {n[6] for n in sprites if n.startswith(pre) and len(n) >= 8}
            theirs_n = [n for n in their_sp if n.startswith(pre)]
            theirs_l = {n[4] for n in theirs_n} | {n[6] for n in theirs_n if len(n) >= 8}
            if not theirs_n or not ours_l <= theirs_l:
                continue
            for n in [n for n in sprites if n.startswith(pre)]:
                del sprites[n]
            sprites.update((n, their_sp[n]) for n in theirs_n)
            taken.append(pre)
        print('sprite_wad %s: %s' % (src['wad'], ' '.join(taken)))

    # ---- monsters from another mod's PNG sprites (profile "sprite_sets"):
    # {"dir": folder, "to": "POSS", "frames": {"*": "VUL1", "G": "RGAL:H"},
    # "scale": [4, 5]} draws a Doom monster with those frames (its behaviour
    # stays vanilla); mirrored rotation pairs (VUL1A2A8) are kept.
    pal_s = texture_pack.Palette(glob['PLAYPAL'][:768])
    for rule in profile.get('sprite_sets', []):
        folder = os.path.join(ROOT, rule['dir'])
        num, den = rule.get('scale', [1, 1])
        files = {}      # (prefix, frame, rotation) -> (file, mirrored)
        for f in sorted(os.listdir(folder)):
            n = os.path.splitext(f)[0].upper()
            if len(n) >= 6 and os.path.isfile(os.path.join(folder, f)) and (f.lower().endswith('.png') or ('.' not in f and
                                open(os.path.join(folder, f), 'rb').read(4) == b'\x89PNG')):   # Ashes leaves some without .png
                files[(n[:4], n[4], n[5])] = (f, False)
                if len(n) >= 8:
                    files[(n[:4], n[6], n[7])] = (f, True)
        to = rule['to']
        frames = rule['frames']
        # the target's own frame letters, plus any the rule adds (keep_frames)
        letters = sorted({n[4] for n in sprites if n.startswith(to)} | {n[6] for n in sprites if n.startswith(to) and len(n) >= 8}
                         | {k for k in frames if k != '*'})
        cache = {}

        pal_rule = pal_s.reds() if rule.get('palette') == 'red' else pal_s     # "palette": "red" for blood

        def pic(f, mirrored, scale):
            if (f, scale) not in cache:
                cache[(f, scale)] = texture_pack.png_patch(os.path.join(folder, f), pal_rule, *scale)
            return hud_bar.mirror_patch(cache[(f, scale)]) if mirrored else cache[(f, scale)]
        for n in [n for n in sprites if n.startswith(to)]:
            del sprites[n]
        for letter in letters:
            src = frames.get(letter, frames['*'])
            sp, sl = (src.split(':') + [letter])[:2]
            for rot in '012345678':
                if (sp, sl, rot) in files:
                    f, mirrored = files[(sp, sl, rot)]
                    scale = tuple(rule.get('frame_scale', {}).get(letter, (num, den)))
                    sprites['%s%s%s' % (to, letter, rot)] = pic(f, mirrored, scale)
        print('sprites %s: from %s' % (to, ' '.join(sorted({(frames.get(x, frames['*']) + ':')[:4] for x in letters}))))

    # ---- GZDoom weapons (deh2c.py zweapons): TEXTURES composites, lifted so
    # art drawn for a fullscreen HUD clears the status bar
    # profile "weapon_offset": [right, down] moves every one of them, in
    # 320x200 pixels (the Ashes guns are drawn for a centred fullscreen HUD)
    import zdoom
    assets = {}
    off_right, off_down = profile.get('weapon_offset', [0, 0])
    for lump, (root, lift, num, den) in sorted(patch.zsprites.items()):
        if root not in assets:
            assets[root] = zdoom.Assets(root, [os.path.join(ROOT, f) for f in profile.get('sprite_textures', [])])
        pic = assets[root].patch(lump, pal_s)
        if pic is None:
            print('WARNING: no sprite %s in %s' % (lump, root))
            continue
        if num != den:
            pic = texture_pack.scale_patch(pic, pal_s, num, den)
        lo, to = struct.unpack_from('<hh', pic, 4)
        sprites[lump] = pic[:4] + struct.pack('<hh', lo - off_right, to + lift - off_down) + pic[8:]

    for target, root, lump, num, den in patch.zpickups:
        lump = lump if len(lump) > 5 else lump + '0'
        if root not in assets:
            assets[root] = zdoom.Assets(root, [os.path.join(ROOT, f) for f in profile.get('sprite_textures', [])])
        pic = assets[root].patch(lump, pal_s)
        if pic is None:
            print('WARNING: no pickup sprite %s in %s' % (lump, root))
            continue
        for n in [n for n in sprites if n.startswith(target)]:
            del sprites[n]
        sprites[target + 'A0'] = texture_pack.scale_patch(pic, pal_s, num, den) if num != den else pic

    # ---- sounds from OGG/WAV files (profile "sounds_replace": {"DSPOSIT1": file})
    for name, path in list(profile.get('sounds_replace', {}).items()) + sorted(patch.zsounds.items()):
        pcm = subprocess.run(['ffmpeg', '-v', 'error', '-i', os.path.join(ROOT, path), '-ac', '1', '-ar', '11025',
                              '-f', 'u8', '-'], check=True, capture_output=True).stdout
        pad = 16
        body = bytes([pcm[0]] * pad) + pcm + bytes([pcm[-1]] * pad)
        glob[name] = struct.pack('<HHI', 3, 11025, len(body)) + body

    # profile "music_share": {"D_STALKS": "D_THE_DA"} plays one level's song
    # for another (the WAD stores it once): music is ~40 KB a track
    for n, src in profile.get('music_share', {}).items():
        if src not in glob:
            raise SystemExit('music_share: no %s' % src)
        glob[n] = glob[src]

    maps = collections.OrderedDict()
    # profile "map_list": [1, 4, 5] plays those levels as MAP01, MAP02, ...
    # (their music and name patches move with them); an entry [i, 3] takes
    # MAP03 of the i-th PWAD, so two map packs can be mixed.
    map_list = profile.get('map_list') or list(range(first_map, last_map + 1))
    remap = {}
    for k, src in enumerate(map_list):
        dst = (first_map if profile.get('map_list') is None else 1) + k
        wad, src = (src[0], src[1]) if isinstance(src, list) else (None, src)
        name = 'MAP%02d' % src
        pool = all_maps if wad is None else wad_maps[wad]
        if name not in pool:
            raise SystemExit('missing ' + name)
        maps['MAP%02d' % dst] = pool[name]
        remap[dst] = (wad, src)
    if profile.get('map_list'):
        moved = {}
        for dst, (wad, src) in remap.items():
            # a picked map keeps its own pack's music and name patch, or the IWAD's
            own = glob if wad is None else dict(iwad_glob, **wad_glob[wad])
            for a, b in ((MAP_MUSIC[src - 1], MAP_MUSIC[dst - 1]), ('CWILV%02d' % (src - 1), 'CWILV%02d' % (dst - 1))):
                if a in own:
                    moved[b] = own[a]
        glob.update(moved)

    report = collections.OrderedDict()

    # ---- distance fog (profile "fog": {"color": [r, g, b], ...}): COLORMAP's 32
    # light ramps fade toward the fog colour instead of black; the engine adds
    # ramp steps with distance (MOD_FOG_START/RANGE, r_hotpath.iwram.c R_FogMap).
    if profile.get('fog'):
        fr, fg, fb = profile['fog'].get('color', [40, 44, 48])
        pal_f = texture_pack.Palette(glob['PLAYPAL'][:768])
        cmap = bytearray(glob['COLORMAP'])
        for k in range(32):
            mix = k / 31.0
            for i in range(256):
                r, g, b = pal_f.rgb[i]
                cmap[k * 256 + i] = pal_f.match(int(r + (fr - r) * mix), int(g + (fg - g) * mix),
                                                int(b + (fb - b) * mix))
        glob['COLORMAP'] = bytes(cmap)

    # ---- monster swap (profile "monster_swap": {doomednum: [doomednums]}):
    # e.g. demons into human enemies; a list is cycled through per type.
    swap = profile.get('monster_swap', {})
    if swap:
        used = collections.Counter()
        for name, m in maps.items():
            th = bytearray(m['THINGS'])
            for i in range(len(th) // 10):
                typ = struct.unpack_from('<h', th, 10 * i + 6)[0]
                to = swap.get(str(typ))
                if to is not None:
                    to = to[used[typ] % len(to)] if isinstance(to, list) else to
                    used[typ] += 1
                    struct.pack_into('<h', th, 10 * i + 6, to)
            maps[name] = dict(m, THINGS=bytes(th))
        report['monster swap'] = '%d things' % sum(used.values())

    # ---- weapon placement. Extra weapons (deh2c.py transplants) take the
    # place of some vanilla pickups ("place": [{"replace": doomednum, "maps":
    # [..], "every": n}]); dm_weapons: deathmatch-only weapons (Scythe's SSG,
    # plasma rifle, BFG) appear in single player too.
    weapon_dn = {82, 2001, 2002, 2003, 2004, 2005, 2006} | {e['doomednum'] for e in patch.extra_weapons}
    placed = collections.OrderedDict()
    for e in patch.extra_weapons:
        for rule in e['spec'].get('place', []):
            seen = 0
            for num in rule['maps']:
                name = 'MAP%02d' % num
                if name not in maps:
                    continue
                th = bytearray(maps[name]['THINGS'])
                for i in range(len(th) // 10):
                    if struct.unpack_from('<h', th, 10 * i + 6)[0] != rule['replace']:
                        continue
                    if struct.unpack_from('<h', th, 10 * i + 8)[0] & 16:    # multiplayer only
                        continue
                    if seen % rule.get('every', 1) == 0:
                        struct.pack_into('<h', th, 10 * i + 6, e['doomednum'])
                        placed.setdefault(e['spec'].get('name', e['doomednum']), []).append(name)
                    seen += 1
                maps[name] = dict(maps[name], THINGS=bytes(th))
    # ---- profile "place_things": [{"replace": 2046, "with": 2004, "maps": [9],
    # "every": n, "dm": bool}]: per-level swaps of Doom's own things, e.g. one
    # deathmatch-only weapon made single-player ("dm": true) on a chosen level
    for rule in profile.get('place_things', []):
        seen = 0
        for num in rule['maps']:
            name = 'MAP%02d' % num
            if name not in maps:
                continue
            th = bytearray(maps[name]['THINGS'])
            for i in range(len(th) // 10):
                typ, flags = struct.unpack_from('<hh', th, 10 * i + 6)
                if typ != rule['replace'] or bool(flags & 16) != bool(rule.get('dm')):
                    continue
                if seen % rule.get('every', 1) == 0:
                    struct.pack_into('<h', th, 10 * i + 6, rule['with'])
                    th[10 * i + 8] &= ~16 & 0xff
                    placed.setdefault('thing %d' % rule['with'], []).append(name)
                seen += 1
            maps[name] = dict(maps[name], THINGS=bytes(th))
    # ---- profile "add_things": [{"thing": 2012, "per_monsters": 5, "min": 2,
    # "maps": [..], "spread_from": [doomednums]}]: more of a thing on every
    # level (or those maps), one per n single-player monsters. Each
    # sits 24-40 units beside an existing pickup (the mapper made that spot
    # reachable), in the same sector (no line crossed on the way, none within
    # 18 units), the pickups farthest from that kind of thing (health by
    # default) first.
    for rule in profile.get('add_things', []):
        near = set(rule.get('near', [2007, 2008, 2048, 2049, 2010, 2046, 2047, 17, 8, 2011, 2012, 2014, 2015,
                                      2018, 2019, 2001, 2002, 2003, 2004, 82])) | {e['doomednum'] for e in patch.extra_weapons}
        health = set(rule.get('spread_from', [2011, 2012, 2013, 2023])) | {rule['thing']}
        added = []
        for name, m in maps.items():
            if rule.get('maps') and int(name[3:]) not in rule['maps']:
                continue
            th, vx, ld = m['THINGS'], m['VERTEXES'], m['LINEDEFS']
            things = [struct.unpack_from('<hhhhh', th, 10 * i) for i in range(len(th) // 10)]
            lines = []
            for i in range(len(ld) // 14):
                a, b = struct.unpack_from('<HH', ld, 14 * i)
                lines.append(struct.unpack_from('<hh', vx, 4 * a) + struct.unpack_from('<hh', vx, 4 * b))
            monsters = sum(1 for t in things if t[3] in MONSTER_DOOMEDNUMS and t[4] & 2 and not t[4] & 16)
            want = max(rule.get('min', 0), monsters // rule.get('per_monsters', 5))
            have = [(t[0], t[1]) for t in things if t[3] in health and not t[4] & 16]
            anchors = [t for t in things if t[3] in near and not t[4] & 16]
            new = []

            def cross(p, q, l):
                def side(ax, ay, bx, by, cx, cy):
                    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
                d1 = side(l[0], l[1], l[2], l[3], p[0], p[1])
                d2 = side(l[0], l[1], l[2], l[3], q[0], q[1])
                d3 = side(p[0], p[1], q[0], q[1], l[0], l[1])
                d4 = side(p[0], p[1], q[0], q[1], l[2], l[3])
                return (d1 > 0) != (d2 > 0) and (d3 > 0) != (d4 > 0)

            def wall_dist(p, l):
                dx, dy = l[2] - l[0], l[3] - l[1]
                k = max(0.0, min(1.0, ((p[0] - l[0]) * dx + (p[1] - l[1]) * dy) / float(dx * dx + dy * dy or 1)))
                return math.hypot(p[0] - l[0] - k * dx, p[1] - l[1] - k * dy)

            def spot(a):
                for r in (32, 24, 40):
                    for k in range(8):
                        p = (int(a[0] + r * math.cos(k * math.pi / 4)), int(a[1] + r * math.sin(k * math.pi / 4)))
                        if any(cross((a[0], a[1]), p, l) or wall_dist(p, l) < 18 for l in lines):
                            continue
                        if any(math.hypot(p[0] - t[0], p[1] - t[1]) < 20 for t in things + new):
                            continue
                        return p
                return None

            while len(new) < want and anchors:
                far = lambda t: min([math.hypot(t[0] - x, t[1] - y) for x, y in have] or [1e9])
                a = max(anchors, key=far)
                anchors.remove(a)
                p = spot(a)
                if p:
                    new.append((p[0], p[1], 0, rule['thing'], a[4] & 7))
                    have.append(p)
            if new:
                maps[name] = dict(m, THINGS=th + b''.join(struct.pack('<hhhhh', *t) for t in new))
                added.append('%s+%d' % (name, len(new)))
        report['added thing %d' % rule['thing']] = ' '.join(added)
    if profile.get('dm_weapons'):
        for name, m in maps.items():
            th = bytearray(m['THINGS'])
            for i in range(len(th) // 10):
                if struct.unpack_from('<h', th, 10 * i + 6)[0] in weapon_dn:
                    th[10 * i + 8] &= ~16 & 0xff     # MTF_NOTSINGLE
            maps[name] = dict(m, THINGS=bytes(th))
    for k, v in placed.items():
        report['placed %s' % k] = ' '.join(v)
    # ---- profile "thin_things": {doomednum: n} keeps every n-th of that thing,
    # [k, n] keeps k of every n (DBP MAP05 lays 226 armour bonuses, Dark
    # Covenant hundreds of imps: each one is a mobj in the zone)
    thin = {int(k): (v if isinstance(v, list) else [1, v]) for k, v in profile.get('thin_things', {}).items()}
    if thin:
        dropped = collections.Counter()
        for name, m in maps.items():
            th, seen = m['THINGS'], collections.Counter()
            keep = bytearray()
            for i in range(len(th) // 10):
                typ = struct.unpack_from('<h', th, 10 * i + 6)[0]
                if typ in thin:     # n = 0: drop them all
                    seen[typ] += 1
                    k_of, every = thin[typ]
                    if not every or (seen[typ] - 1) % every >= k_of:
                        dropped[typ] += 1
                        continue
                keep += th[10 * i:10 * i + 10]
            maps[name] = dict(m, THINGS=bytes(keep))
        report['thinned things'] = ' '.join('%d: -%d' % kv for kv in sorted(dropped.items()))

    # ---- textures
    pnames = parse_pnames(glob['PNAMES'])
    tex = parse_textures(glob['TEXTURE1'], pnames)
    if 'TEXTURE2' in glob:
        tex.update(parse_textures(glob['TEXTURE2'], pnames))
    used_tex, used_flats, doomednums = set(), set(), set()
    for m in maps.values():
        sd = m['SIDEDEFS']
        for i in range(len(sd) // 30):
            for k in range(3):
                n = sd[30 * i + 4 + 8 * k:30 * i + 12 + 8 * k].split(b'\0')[0].decode('latin-1').upper()
                if n and n != '-':
                    used_tex.add(n)
        se = m['SECTORS']
        for i in range(len(se) // 26):
            used_flats.add(se[26 * i + 4:26 * i + 12].split(b'\0')[0].decode('latin-1').upper())
            used_flats.add(se[26 * i + 12:26 * i + 20].split(b'\0')[0].decode('latin-1').upper())
        th = m['THINGS']
        for i in range(len(th) // 10):
            doomednums.add(struct.unpack_from('<h', th, 10 * i + 6)[0])

    missing_tex = sorted(n for n in used_tex if n not in tex)
    keep_tex = set(used_tex) | {'SKY1'} & set(tex)    # MAP01-11 sky
    for a, b in switch_pairs():
        if a in keep_tex or b in keep_tex:
            keep_tex |= {a, b} & set(tex)
    tex_order = list(tex)
    flat_order = list(flats)
    for is_tex, end, start in anim_ranges():
        order = tex_order if is_tex else flat_order
        used = keep_tex if is_tex else used_flats
        if start in order and end in order:
            rng = order[order.index(start):order.index(end) + 1]
            if used & set(rng):
                used |= set(rng)
    keep_tex.add(tex_order[0])     # texture 0 means "no texture"
    new_tex = collections.OrderedDict((n, tex[n]) for n in tex_order if n in keep_tex)
    assert len(new_tex) <= 1024, 'side_t stores texture numbers in 10 bits'

    # ---- texture pack (JDoom layout): replaces the stock walls and floors,
    # not the mod's own art (D4V's doors, switches, liquids) or the sky.
    # Textures at least half_width_min wide are stored at half width (TEXTURE1
    # columndirectory = 1, R_LoadTexture's xshift) to fit the flash budget.
    tpack = profile.get('texture_pack')
    pack_flats = {}
    if tpack:
        imgs = texture_pack.index(tpack['dir'])
        pal = texture_pack.Palette(glob['PLAYPAL'][:768])
        half_min = tpack.get('half_width_min', 1 << 15)
        k = 0
        for name, (masked, w, h, coldir, plist) in list(new_tex.items()):
            if (name not in imgs['textures'] or name.startswith('SKY') or h > 128
                    or any(pt[2] in mod_art for pt in plist)):
                continue
            half = w >= half_min
            pname = 'DTX%05d' % k
            k += 1
            patches[pname] = texture_pack.to_patch(
                texture_pack.load(imgs['textures'][name], w // 2 if half else w, h), pal)
            new_tex[name] = (masked, w, h, 1 if half else 0, [(0, 0, pname, 0, 0)])
        for name in used_flats:
            if name in imgs['flats'] and name in flats and name not in mod_art:
                pack_flats[name] = texture_pack.to_flat(texture_pack.load(imgs['flats'][name], 64, 64), pal)
        report['texture pack'] = '%d textures, %d flats' % (k, len(pack_flats))

    # ---- wide textures merged into one half-width patch each (profile
    # "half_textures": {"min_width": 128}): big custom texture sets fit.
    half_tex = profile.get('half_textures')
    if half_tex:
        pal = texture_pack.Palette(glob['PLAYPAL'][:768])
        k = 0
        for name, (masked, w, h, coldir, plist) in list(new_tex.items()):
            if coldir == 1 or w < half_tex.get('min_width', 128) or h > 255 or w % 2 or name.startswith('SKY'):
                continue
            pname = 'DTH%05d' % k
            k += 1
            if half_tex.get('height'):   # quarter size: every other column and row (HALFSPR 3 layout)
                patches[pname] = rescale_patch(texture_pack.bake_texture(w, h, plist, patches, pal))
                new_tex[name] = (masked, w, h, 3, [(0, 0, pname, 0, 0)])
            else:
                patches[pname] = texture_pack.bake_texture(w, h, plist, patches, pal, half=True)
                new_tex[name] = (masked, w, h, 1, [(0, 0, pname, 0, 0)])
        report['half-width textures'] = str(k)
    texture1, pnames_lump, need_patches = build_textures(new_tex)
    missing_patches = sorted(p for p in need_patches if p not in patches)
    out_patches = [(p, patches[p]) for p in need_patches if p in patches]

    # ---- flats
    used_flats |= {'F_SKY1'} | set(FINALE_FLATS) | ({profile['end_flat']} if 'end_flat' in profile else set())
    missing_flats = sorted(f for f in used_flats if f not in flats)
    out_flats = [(n, pack_flats.get(n, d)) for n, d in flats.items() if n in used_flats]

    # ---- sprites
    spr_renames = deh2c.name_renames(t, patch)[1]
    gore_things = ['MT_MISC71', 'MT_MISC84', 'MT_MISC85'] if profile.get('gore') else []   # p_inter.c death pools
    removed = set(profile.get('remove_weapons', []))     # their art never shows
    seen_mt, seen_st, frames, sfx, weapon_sprites, enemy_sprites = reachable(t, states, mobj,
                                                                                     [w for i, w in enumerate(weapons) if i not in removed],
                                                                                     doomednums, spr_renames,
                                                                                     list(patch.extra_mobj) + gore_things,
                                                                                     [st for _, st in patch.weapon_mag.values()],
                                                                                     [w for i, w in enumerate(weapons) if i in removed])
    for pre, letters in profile.get('keep_frames', {}).items():    # frames code picks, not states
        frames.setdefault(pre, set()).update(letters)
    out_sprites = [(n, d) for n, d in sprites.items()
                   if n[:4] in frames and sprite_lump_frames(n) & frames[n[:4]]]
    sprite_errors = check_sprites(dict(out_sprites), frames, sprites)

    # ---- sounds
    sfx_lumps = {}
    sounds_c = open(os.path.join(DOOM_SRC, 'sounds.c'), encoding='latin-1').read()
    entries = re.findall(r'\{\s*"(\w*)",\s*\w+,\s*-?\d+,\s*(&S_sfx\[(sfx_\w+)\]|0)', sounds_c)
    renamed = deh2c.name_renames(t, patch)[0]      # DeHackEd Text renames (D4V: pistol -> pisto1)
    entries = [(renamed.get(n, n), a, b) for n, a, b in entries]
    sfx_names = {t.sfx_enum[i]: (e[0], e[2]) for i, e in enumerate(entries) if i < len(t.sfx_enum)}
    for s in sorted(sfx | patch.extra_sfx):
        if s not in sfx_names:
            continue
        name, link = sfx_names[s]
        if link:
            name = sfx_names[link][0]
        sfx_lumps['DS' + name.upper()] = True
    sfx_lumps['DSPISTOL'] = True    # I_InitSound's fallback
    out_sounds = []
    for n in sorted(sfx_lumps):
        d = glob.get(n)
        if d is not None:
            r = resample_dmx(d, profile.get('sfx_rate', args.sfx_rate))
            # profile "sfx_long": [bytes, rate] - long sounds (monster deaths,
            # sight calls) at a lower rate still, to fit the flash budget
            if 'sfx_long' in profile and len(r) > profile['sfx_long'][0]:
                r = resample_dmx(d, profile['sfx_long'][1])
            out_sounds.append((n, r))

    # ---- music
    music = [MAP_MUSIC[i - 1] for i in range(first_map, last_map + 1)] + SCREEN_MUSIC
    out_music = [(n, glob[n]) for n in music if n in glob and args.music]

    # ---- other global lumps the engine opens by name
    lits = engine_literals()
    printf_re = re.compile('^(%s)$' % '|'.join(PRINTF_LUMPS))
    extra_dir = os.path.join(HERE, 'wadconverter', 'extralumps')
    extras = collections.OrderedDict()
    for f in sorted(os.listdir(extra_dir)):
        with open(os.path.join(extra_dir, f), 'rb') as fh:
            extras[f.split('.')[0].upper()] = fh.read()
    out_glob = []
    for n, d in glob.items():
        if n.startswith(('D_', 'DS', 'DP')) or n in ('TEXTURE1', 'TEXTURE2', 'PNAMES') or DROP_GLOBAL.match(n):
            continue
        if n.startswith('CWILV') and not (first_map - 1 <= int(n[5:]) < last_map):
            continue
        if args.drop_screens and n == 'INTERPIC':
            continue
        # Only what the engine opens by name (string literals and sprintf
        # patterns in main/doom/source): Doom 1 extras (VICTORY2, M_EPI*),
        # STBAR (the GBA status bar is built in) and ZDoom-only lumps drop out.
        if n in lits or printf_re.match(n) or n in ('PLAYPAL', 'COLORMAP', 'GENMIDI'):
            out_glob.append((n, extras.pop(n, d)))
    out_glob += list(extras.items())
    # Brightness (m_menu.c M_ChangeGamma -> V_SetPalLump) swaps in PLAYPAL1..5,
    # which GBADoom shipped as lumps: the palettes under a gamma curve
    have = {n for n, _ in out_glob}
    for k in range(1, 6):
        if 'PLAYPAL%d' % k not in have:
            curve = bytes(round(255 * (v / 255) ** (1 / (1 + 0.1 * k))) for v in range(256))
            out_glob.append(('PLAYPAL%d' % k, glob['PLAYPAL'].translate(curve)))
    # A mod's own status bar replaces the built-in GBA one, fitted into the
    # 240-wide layout; its tall numbers become the (10 px) STGANUM digits.
    if glob.get('STBAR') and glob['STBAR'] != iwad_glob.get('STBAR'):
        pal = glob['PLAYPAL']
        out_glob.append(('STBARGBA', hud_bar.build_bar(glob['STBAR'], glob.get('STARMS'), pal)))
        if glob.get('STTNUM0') != iwad_glob.get('STTNUM0'):
            out_glob = [(n, hud_bar.narrow_digit(glob['STTNUM' + n[7]], 10, pal)
                         if re.fullmatch(r'STGANUM\d', n) else d) for n, d in out_glob]
    if profile.get('hud') == 'overlay':
        # Overlay HUD (engine MOD_HUD_OVERLAY): no status bar or face; Ashes
        # digits and icons at panel resolution instead.
        stbar = re.compile(r'^(STF\w+|STBAR|STARMS|STBARGBA|STGNUM\d|STYSNUM\d|STTNUM\d|STGANUM\d|'
                           r'STKEYS\d|STTPRCNT|STTMINUS|AMMNUM\d)$')
        out_glob = [(n, d) for n, d in out_glob if not stbar.match(n)] + hud_overlay_lumps(profile, glob)
    if profile.get('ui'):
        import ui_art
        out_glob = ui_art.apply(profile['ui'], out_glob, glob['PLAYPAL'])
    for n, src in profile.get('lump_alias', {}).items():     # e.g. INTERPIC -> TITLEPIC
        data = dict(out_glob).get(src)
        if data is None:
            raise SystemExit('lump_alias: no %s' % src)
        out_glob = [(k, data if k == n else d) for k, d in out_glob]
    if args.drop_screens:
        lits.discard('INTERPIC')

    must_keep = ['PLAYPAL', 'COLORMAP', 'GENMIDI', 'TITLEPIC', 'DSPISTOL', 'M_THERMM',
                 'WIENTER', 'WIF', 'WIOSTK', 'WIOSTI', 'WITIME', 'WIPAR', 'WISUCKS', 'WIMSTT', 'WIPCNT',
                 'WICOLON', 'WIMINUS', 'WISCRT2'] + \
                ['CWILV%02d' % i for i in range(first_map - 1, last_map)] + ['STCFN%03d' % i for i in range(33, 96)] + \
                ([] if args.drop_screens else ['INTERPIC']) + \
                (['HUDN0', 'HUDSLASH', 'HUDKEY5'] if profile.get('hud') == 'overlay' else ['STTPRCNT'])
    present = {n for n, _ in out_glob} | {n for n, _ in out_sounds}
    missing_must = [n for n in must_keep if n not in present]

    # ---- vanilla image (PC check)
    lumps = []
    lumps += out_glob
    lumps += [('TEXTURE1', texture1), ('PNAMES', pnames_lump)]
    lumps += out_sounds + out_music
    for name, m in maps.items():
        lumps.append((name, b''))
        lumps += [(k, m[k]) for k in MAP_LUMPS]
    lumps += [('S_START', b'')] + out_sprites + [('S_END', b'')]
    lumps += [('P_START', b'')] + out_patches + [('P_END', b'')]
    lumps += [('F_START', b'')] + out_flats + [('F_END', b'')]
    vanilla_path = os.path.join(out_dir, 'game_vanilla.wad')
    write_wad(vanilla_path, lumps)

    # ---- device image
    tex_index = {n: i for i, n in enumerate(new_tex)}
    import tempfile
    tmp = tempfile.mkdtemp()
    dev = []
    for n, d in lumps:
        if n.startswith('D_') and d[:4] == b'MUS\x1a':
            d = mus2mid(d, tmp)
        dev.append([n, d])
    # maps
    i = 0
    while i < len(dev):
        n = dev[i][0]
        if n in maps:
            level = {dev[i + 1 + j][0]: dev[i + 1 + j][1] for j in range(len(MAP_LUMPS))}
            conv = gba_level(level, tex_index)
            for j in range(len(MAP_LUMPS)):
                dev[i + 1 + j][1] = conv[dev[i + 1 + j][0]]
            dev.insert(i + 1 + len(MAP_LUMPS), ['SECLINES', conv['SECLINES']])   # ML_SECLINES
            i += 2 + len(MAP_LUMPS)
        else:
            i += 1
    pal34 = texture_pack.Palette(glob['PLAYPAL'][:768])
    sec = None
    for l in dev:
        if l[0] in ('S_START', 'P_START', 'F_START'):
            sec = l[0][0]
            continue
        if l[0].endswith('_END'):
            sec = None
            continue
        if sec == 'S' and l[1]:
            hf = sprite_half_flags(l[0], weapon_sprites, enemy_sprites, args.half_sprites,
                                   struct.unpack_from('<hh', l[1]))
            if hf == 3:
                l[1] = rescale_patch(l[1])
            elif hf == 1:
                l[1] = rescale_patch_x(l[1])
            elif hf == 4:
                l[1] = scaled_psprite(l[1], profile.get('psprite_nudge', {}), l[0], pal34)
        elif sec == 'F' and len(l[1]) == 4096 and args.half_flats:
            l[1] = rescale_flat(l[1])
    # Per sprite lump (S_START..S_END order): 1 = stored at half resolution.
    # Weapons (psprites) stay full resolution: they fill the bottom of the view.
    halfspr = bytearray()
    sec = None
    for n, d in dev:
        if n == 'S_START':
            sec = 'S'
            continue
        if n == 'S_END':
            break
        if sec:
            # header sizes: unchanged by the halving, and weapons are flagged before the size test
            halfspr.append(sprite_half_flags(n, weapon_sprites, enemy_sprites, args.half_sprites,
                                             struct.unpack_from('<hh', d)))
    dev.insert(0, ['HALFSPR', bytes(halfspr)])
    # Checked against the firmware's HALF_RES_* at startup (d_main.c).
    dev.insert(0, ['TWFORMAT', bytes([(1 if args.half_sprites else 0) | (2 if args.half_flats else 0) | 4])])
    size = write_wad(args.out, [(n, d) for n, d in dev], dir_first=True)

    # ---- report
    def total(items):
        return sum(len(d) for _, d in items)

    cat = collections.OrderedDict()
    for n, d in dev:
        if n in maps or n in MAP_LUMPS or n == 'SECLINES':
            k = 'maps'
        elif n.startswith('D_'):
            k = 'music'
        elif n.startswith('DS'):
            k = 'sfx'
        else:
            k = None
        if k:
            cat[k] = cat.get(k, 0) + len(d)
    cat['sprites'] = total([(n, d) for n, d in dev if (n, True) and n in dict(out_sprites)])
    cat['patches'] = total([(n, d) for n, d in dev if n in dict(out_patches)])
    cat['flats'] = total([(n, d) for n, d in dev if n in dict(out_flats)])
    cat['ui+other'] = size - sum(cat.values())
    limit = args.budget
    print('full-resolution weapon sprite frames: %d (%s)' % (len(weapon_sprites), ' '.join(sorted({p for p, f in weapon_sprites}))))
    print('full-height enemy sprite frames: %d (%s)' % (len(enemy_sprites), ' '.join(sorted({p for p, f in enemy_sprites}))))
    print('textures %d (of %d), patches %d, flats %d, sprite lumps %d (of %d), sounds %d, music %d' % (
        len(new_tex), len(tex), len(out_patches), len(out_flats), len(out_sprites), len(sprites),
        len(out_sounds), len(out_music)))
    for k, v in report.items():
        print('%s: %s' % (k, v))
    for k, v in cat.items():
        print('  %-9s %8.0f KB' % (k, v / 1024))
    print('%s: %d bytes (%.2f MB) of %d (%.2f MB) budget, %s' % (
        args.out, size, size / 1048576, limit, limit / 1048576,
        'fits' if size <= limit else 'DOES NOT FIT (%d KB over)' % ((size - limit) // 1024)))
    print('%s: PC check image' % vanilla_path)

    errors = []
    if missing_tex:
        errors.append('textures used by maps but not defined: %s' % missing_tex)
    if missing_patches:
        errors.append('patches missing: %s' % missing_patches)
    if missing_flats:
        errors.append('flats missing: %s' % missing_flats)
    if sprite_errors:
        errors.append('sprite frames missing: %s' % sprite_errors)
    if missing_must:
        errors.append('engine lumps missing: %s' % missing_must)
    if size > limit:
        errors.append('data does not fit the budget (M5Launcher free space minus code)')
    for e in errors:
        print('ERROR: ' + e)
    sys.exit(1 if errors else 0)


if __name__ == '__main__':
    main()
