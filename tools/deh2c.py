#!/usr/bin/env python3
"""Bake vanilla DeHackEd patches into the engine's const tables.

GBADoom keeps states[], mobjinfo[] and weaponinfo[] as const data in flash,
so a .deh cannot be applied at run time without copying ~40 KB of tables into
RAM. Instead this tool rewrites copies of the table sources:

    main/doom/source/info.c     -> main/doom/mod/info_mod.c
    main/doom/source/d_items.c  -> main/doom/mod/d_items_mod.c
    main/doom/source/sounds.c   -> main/doom/mod/sounds_mod.c
    (Misc/Ammo/Text, profile)   -> main/doom/mod/mod_gen.h

Usually driven by a mod profile (tools/mods/*.json, see build_mod.sh):
    tools/deh2c.py --profile tools/mods/d4v_scythe.json
Patches are applied in order, like -deh a.deh -deh b.deh.

Only entries the patch touches are rewritten, so an empty patch reproduces
the originals byte for byte (--selftest checks that).

Entries are keyed by their `// S_x` / `// MT_x` comments and checked against
the info.h enums: DeHackEd numbers are vanilla indices, and one mis-parsed
line would shift every later edit onto the wrong entry.

Also importable: load_tables() + apply_deh() give build_wad.py the patched
state graph for sprite pruning.
"""

import argparse
import copy
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOOM = os.path.join(ROOT, 'main', 'doom')
OUT = os.path.join(DOOM, 'mod')

VANILLA_STATES = 967
VANILLA_THINGS = 137

MOBJ_FIELDS = ['doomednum', 'spawnstate', 'spawnhealth', 'seestate', 'seesound',
               'reactiontime', 'attacksound', 'painstate', 'painchance', 'painsound',
               'meleestate', 'missilestate', 'deathstate', 'xdeathstate', 'deathsound',
               'speed', 'radius', 'height', 'mass', 'damage', 'activesound', 'flags',
               'raisestate']

MOBJ_STATE_FIELDS = {'spawnstate', 'seestate', 'painstate', 'meleestate', 'missilestate',
                     'deathstate', 'xdeathstate', 'raisestate'}
MOBJ_SOUND_FIELDS = {'seesound', 'attacksound', 'painsound', 'deathsound', 'activesound'}

DEH_THING = {
    'ID #': 'doomednum', 'Initial frame': 'spawnstate', 'Hit points': 'spawnhealth',
    'First moving frame': 'seestate', 'Alert sound': 'seesound',
    'Reaction time': 'reactiontime', 'Attack sound': 'attacksound',
    'Injury frame': 'painstate', 'Pain chance': 'painchance', 'Pain sound': 'painsound',
    'Close attack frame': 'meleestate', 'Far attack frame': 'missilestate',
    'Death frame': 'deathstate', 'Exploding frame': 'xdeathstate',
    'Death sound': 'deathsound', 'Speed': 'speed', 'Width': 'radius', 'Height': 'height',
    'Mass': 'mass', 'Missile damage': 'damage', 'Action sound': 'activesound',
    'Bits': 'flags', 'Respawn frame': 'raisestate',
}

# weaponinfo_t field order in d_items.c
WEAPON_FIELDS = ['ammo', 'upstate', 'downstate', 'readystate', 'atkstate', 'flashstate']
# DeHackEd's names are swapped relative to the engine fields (as in
# Chocolate Doom's deh_weapon.c): "Deselect frame" is the raise state.
DEH_WEAPON = {'Ammo type': 'ammo', 'Deselect frame': 'upstate', 'Select frame': 'downstate',
              'Bobbing frame': 'readystate', 'Shooting frame': 'atkstate',
              'Firing frame': 'flashstate'}
AMMO_NAMES = ['am_clip', 'am_shell', 'am_cell', 'am_misl']

# Vanilla MF_* bits; DeHackEd "Bits" values are raw masks in this layout.
VANILLA_MF = {
    'MF_SPECIAL': 0x1, 'MF_SOLID': 0x2, 'MF_SHOOTABLE': 0x4, 'MF_NOSECTOR': 0x8,
    'MF_NOBLOCKMAP': 0x10, 'MF_AMBUSH': 0x20, 'MF_JUSTHIT': 0x40, 'MF_JUSTATTACKED': 0x80,
    'MF_SPAWNCEILING': 0x100, 'MF_NOGRAVITY': 0x200, 'MF_DROPOFF': 0x400,
    'MF_PICKUP': 0x800, 'MF_NOCLIP': 0x1000, 'MF_SLIDE': 0x2000, 'MF_FLOAT': 0x4000,
    'MF_TELEPORT': 0x8000, 'MF_MISSILE': 0x10000, 'MF_DROPPED': 0x20000,
    'MF_SHADOW': 0x40000, 'MF_NOBLOOD': 0x80000, 'MF_CORPSE': 0x100000,
    'MF_INFLOAT': 0x200000, 'MF_COUNTKILL': 0x400000, 'MF_COUNTITEM': 0x800000,
    'MF_SKULLFLY': 0x1000000, 'MF_NOTDMATCH': 0x2000000,
    'MF_TRANSLATION': 0xc000000, 'MF_TRANSSHIFT': 26, 'MF_TOUCHY': 0x10000000,
}


def read(path):
    # newline='': keep CRLF, DeHackEd Text lengths may count it as 2 chars
    with open(path, encoding='latin-1', newline='') as f:
        return f.read()


def enum_names(text, first, last):
    body = text[text.index(first + ','):text.index(last)]
    body = re.sub(r'//.*', '', body)
    body = re.sub(r'/\*.*?\*/', '', body, flags=re.S)
    return re.findall(r'^\s*([A-Za-z_]\w*)\s*(?:=\s*[^,]+)?,', body, re.M)


class Tables:
    pass


def load_tables():
    t = Tables()
    info_h = read(os.path.join(DOOM, 'include', 'info.h'))
    info_c = read(os.path.join(DOOM, 'source', 'info.c'))
    sounds_h = read(os.path.join(DOOM, 'include', 'sounds.h'))

    t.spr_enum = enum_names(info_h, 'SPR_TROO', 'NUMSPRITES')
    t.st_enum = enum_names(info_h, 'S_NULL', 'NUMSTATES')
    t.mt_enum = enum_names(info_h, 'MT_PLAYER', 'NUMMOBJTYPES')
    t.sfx_enum = enum_names(sounds_h, 'sfx_None', 'NUMSFX')

    # sprnames[] gives the 4-letter lump prefixes, in SPR_ order.
    sn = info_c[info_c.index('sprnames['):]
    sn = sn[:sn.index('};')]
    t.spr_names = re.findall(r'"(\w{4})"', sn)
    assert len(t.spr_names) >= len(t.spr_enum) - 1, 'sprnames vs SPR_ enum'

    # states[]: one line per entry, keyed by its trailing comment.
    t.info_c = info_c
    t.state_lines = {}    # enum index -> (line number in info_c.splitlines(), fields)
    lines = info_c.split('\n')
    st_index = {n: i for i, n in enumerate(t.st_enum)}
    in_states = False
    for ln, line in enumerate(lines):
        if line.startswith('const state_t states'):
            in_states = True
            continue
        if in_states and line.startswith('};'):
            break
        if not in_states or '{SPR_' not in line:
            continue
        m = re.match(r'\s*\{(SPR_\w+),\s*(-?\w+),\s*(-?\d+),\s*(\w+),\s*(\w+)(?:,\s*(-?\d+),\s*(-?\d+))?\}', line)
        name = re.search(r'//\s*(S_\w+)', line)
        assert m and name, 'unparsed state line %d: %s' % (ln + 1, line)
        idx = st_index[name.group(1)]
        assert idx not in t.state_lines, 'duplicate state ' + name.group(1)
        t.state_lines[idx] = (ln, list(m.groups()))
    for i in range(VANILLA_STATES):
        assert i in t.state_lines, 'state %d (%s) missing from info.c' % (i, t.st_enum[i])

    # mobjinfo[]: blocks of 23 commented lines.
    t.mobj = []
    mstart = next(i for i, l in enumerate(lines) if l.startswith('const mobjinfo_t mobjinfo'))
    i = mstart
    while len(t.mobj) < len(t.mt_enum):
        while i < len(lines) and not re.match(r'\s*\{\s*//\s*MT_\w+', lines[i]):
            if lines[i].startswith('};'):
                break
            i += 1
        if i >= len(lines) or lines[i].startswith('};'):
            break
        name = re.search(r'(MT_\w+)', lines[i]).group(1)
        fields = {}
        field_lines = {}
        for k, fname in enumerate(MOBJ_FIELDS):
            fl = lines[i + 1 + k]
            v = re.match(r'\s*(.+?),?\s*//', fl)
            assert v, 'unparsed mobjinfo line %d: %s' % (i + 2 + k, fl)
            fields[fname] = v.group(1).strip().rstrip(',').strip()
            field_lines[fname] = i + 1 + k
        assert re.match(r'\s*\}', lines[i + 1 + len(MOBJ_FIELDS)]), 'mobjinfo block %s not 23 fields' % name
        assert t.mt_enum[len(t.mobj)] == name, 'mobjinfo order: expected %s got %s' % (t.mt_enum[len(t.mobj)], name)
        t.mobj.append({'name': name, 'fields': fields, 'lines': field_lines})
        i += 1 + len(MOBJ_FIELDS)
    assert len(t.mobj) >= VANILLA_THINGS, 'only %d mobjinfo entries parsed' % len(t.mobj)

    # MF_* values must match vanilla for raw "Bits" to mean the same thing.
    for k, v in VANILLA_MF.items():
        m = re.search(r'#define\s+%s\s+\(?(?:\(int\))?\s*(0x[0-9a-fA-F]+|\d+)' % k,
                      read(os.path.join(DOOM, 'include', 'p_mobj.h')))
        if m:
            assert int(m.group(1), 0) == v, '%s differs from vanilla' % k

    # weaponinfo[]
    items = read(os.path.join(DOOM, 'source', 'd_items.c'))
    t.items_c = items
    body = items[items.index('weaponinfo[NUMWEAPONS]'):]
    body = body[:body.index('};')]
    toks = re.findall(r'\b(am_\w+|S_\w+)\b', body)
    assert len(toks) % 6 == 0
    t.weapons = [dict(zip(WEAPON_FIELDS, toks[i:i + 6])) for i in range(0, len(toks), 6)]

    t.sounds_c = read(os.path.join(DOOM, 'source', 'sounds.c'))
    t.englsh_h = read(os.path.join(DOOM, 'include', 'd_englsh.h'))
    return t


def state_fields(t, i):
    return list(t.state_lines[i][1])


# Sound each gun action plays (calls P_WeaponSfx in p_pspr.c / p_enemy.c).
ACTION_SFX = {'A_FirePistol': 'sfx_pistol', 'A_FireCGun': 'sfx_pistol', 'A_FireShotgun': 'sfx_shotgn',
              'A_FireShotgun2': 'sfx_dshtgn', 'A_OpenShotgun2': 'sfx_dbopn',
              'A_LoadShotgun2': 'sfx_dbload', 'A_CloseShotgun2': 'sfx_dbcls', 'A_FireMissile': 'sfx_rlaunc',
              'A_FirePlasma': 'sfx_plasma', 'A_BFGsound': 'sfx_bfg'}


class Patch:
    def __init__(self):
        self.states = {}          # index -> [spr, frame, tics, action, next, misc1, misc2]
        self.mobj = {}            # index -> {field: value}
        self.weapons = {}         # index -> {field: value}
        self.sound_priority = {}  # sfx index -> priority
        self.misc = {}
        self.maxammo = {}
        self.clipammo = {}
        self.texts = []           # (old, new)
        self.kv_seen = 0          # key lines consumed, checked against the file
        self.pspr_overrides = []  # (state, kind, from, to) -> MOD_PSPR_OVERRIDES
        self.extra_sfx = set()    # sounds only the overrides play
        self.extra_mobj = set()   # things only the overrides spawn (projectile copies)
        self.extra_weapons = []   # wp_extra*: slot, ammo per shot, pickup thing
        self.extra_ammo = []      # am_rifle pickups: thing, clip loads, message
        self.sfx_variants = []    # (base sfx, [alternative sfx]) picked at random
        self.bex_strings = {}     # BEX [STRINGS]: mnemonic -> text
        self.zsprites = {}        # zweapons: sprite lump -> (pk3 folder, lift)
        self.zsounds = {}         # zweapons: DSxxxx lump -> sound file
        self.weapon_fire = {}     # weapon -> (damage, pellets, spread) for A_FireMod
        self.weapon_punch = {}    # weapon -> (min, max) damage for A_Punch
        self.weapon_mag = {}      # weapon -> (magazine size, reload state)
        self.zpickups = []        # (vanilla pickup sprite, pk3 folder, lump, num, den): its art replaced


HEADER = re.compile(r'(Thing|Frame|Pointer|Weapon|Sound|Ammo|Text|Misc|Cheat|Sprite|Codep|\[)')


def text_block(raw, i):
    """Text block whose header is line i of raw.split('\\n'). DeHackEd counts
    the old/new lengths either with CRLF as 2 characters (DOS-written patches,
    e.g. D4V) or as 1 (e.g. Twilight Warrior); take the reading after which the
    next line is blank, a header or the end. Returns (old, new, next_line)."""
    raw_lines = raw.split('\n')
    a, b = map(int, re.match(r'Text (\d+) (\d+)', raw_lines[i].strip()).groups())
    start = sum(len(l) + 1 for l in raw_lines[:i + 1])
    for body in (raw[start:], raw[start:].replace('\r', '')):
        after = body[a + b:].lstrip('\r')
        following = [l for l in after.split('\n')[1:] if l.strip()]
        if after.strip() == '' or (after.startswith('\n') and
                                   (not following or HEADER.match(following[0].lstrip()))):
            used = body[:a + b]
            old, new = used[:a].replace('\r', ''), used[a:].replace('\r', '')
            return old, new, i + 1 + (old + new).count('\n') + 1
    raise AssertionError('Text block at line %d: lengths match neither CRLF convention' % (i + 1))


def parse_deh(t, text, p=None):
    """Parse one patch. Pass the Patch from a previous file to apply several
    in order (codepointers still copy the vanilla action, as DeHackEd does)."""
    if p is None:
        p = Patch()
    raw = text
    text = text.replace('\r', '')
    lines = text.split('\n')
    i = 0
    orig_action = {k: v[1][3] for k, v in t.state_lines.items()}

    def kv_block(start):
        kv = {}
        j = start
        # A block is its "key = value" lines; it ends at a blank line or at the
        # next header (no '='). Keys may start like headers ("Sprite number").
        while j < len(lines) and lines[j].strip() and ('=' in lines[j] or lines[j].lstrip().startswith('#')):
            # keys may contain '#' ("ID # = 67"); comment lines were skipped above
            m = None if lines[j].lstrip().startswith('#') else re.match(r'\s*([^=]+?)\s*=\s*(.*?)\s*$', lines[j])
            if m:
                kv[m.group(1)] = m.group(2)
                p.kv_seen += 1
            j += 1
        return kv, j

    def state_name(n):
        n = int(n)
        assert 0 <= n < VANILLA_STATES, 'frame %d out of vanilla range' % n
        return t.st_enum[n]

    def sfx_name(n):
        return t.sfx_enum[int(n)]

    while i < len(lines):
        line = lines[i]
        m = re.match(r'Thing (\d+)', line)
        if m:
            n = int(m.group(1)) - 1     # DeHackEd things are 1-based
            assert 0 <= n < VANILLA_THINGS
            kv, i = kv_block(i + 1)
            ch = p.mobj.setdefault(n, {})
            for k, v in kv.items():
                f = DEH_THING.get(k)
                assert f, 'unknown Thing field %r' % k
                if f in MOBJ_STATE_FIELDS:
                    ch[f] = state_name(v)
                elif f in MOBJ_SOUND_FIELDS:
                    ch[f] = sfx_name(v)
                else:
                    ch[f] = str(int(v))
            continue
        m = re.match(r'Frame (\d+)', line)
        if m:
            n = int(m.group(1))
            assert 0 <= n < VANILLA_STATES
            kv, i = kv_block(i + 1)
            st = p.states.setdefault(n, state_fields(t, n))
            for k, v in kv.items():
                if k == 'Sprite number':
                    st[0] = t.spr_enum[int(v)]
                elif k == 'Sprite subnumber':
                    st[1] = str(int(v))
                elif k == 'Duration':
                    st[2] = str(int(v))
                elif k == 'Next frame':
                    st[4] = state_name(v)
                elif k == 'Unknown 1':
                    st[5] = str(int(v))
                elif k == 'Unknown 2':
                    st[6] = str(int(v))
                else:
                    raise AssertionError('unknown Frame field %r' % k)
            continue
        m = re.match(r'Pointer \d+ \(Frame (\d+)\)', line)
        if m:
            n = int(m.group(1))
            kv, i = kv_block(i + 1)
            src = int(kv['Codep Frame'])
            st = p.states.setdefault(n, state_fields(t, n))
            st[3] = orig_action[src]    # the ORIGINAL action of frame src
            continue
        m = re.match(r'Weapon (\d+)', line)
        if m:
            n = int(m.group(1))
            kv, i = kv_block(i + 1)
            w = p.weapons.setdefault(n, {})
            for k, v in kv.items():
                f = DEH_WEAPON.get(k)
                assert f, 'unknown Weapon field %r' % k
                if f == 'ammo':
                    # DeHackEd: 0 bullets, 1 shells, 2 cells, 3 rockets, 5 none
                    w[f] = AMMO_NAMES[int(v)] if int(v) < 4 else 'am_noammo'
                else:
                    w[f] = state_name(v)
            continue
        m = re.match(r'Sound (\d+)', line)
        if m:
            n = int(m.group(1))
            kv, i = kv_block(i + 1)
            for k, v in kv.items():
                if k == 'Value':
                    p.sound_priority[n] = int(v)
            continue
        m = re.match(r'Ammo (\d+)', line)
        if m:
            n = int(m.group(1))
            kv, i = kv_block(i + 1)
            for k, v in kv.items():
                if k == 'Max ammo':
                    p.maxammo[n] = int(v)
                elif k == 'Per ammo':
                    p.clipammo[n] = int(v)
            continue
        if line.strip().upper() == '[STRINGS]':
            i += 1
            while i < len(lines) and not lines[i].lstrip().startswith('['):
                m = re.match(r'\s*(\w+)\s*=\s*(.*)$', lines[i])
                if m:
                    p.kv_seen += 1
                    value = m.group(2)
                    while value.endswith('\\') and i + 1 < len(lines):
                        i += 1
                        value = value[:-1] + lines[i].strip()
                    p.bex_strings[m.group(1).upper()] = value.replace('\\n', '\n')
                i += 1
            continue
        m = re.match(r'Cheat\b', line)
        if m:
            kv, i = kv_block(i + 1)    # cheat renames: the engine keeps Doom's codes
            continue
        m = re.match(r'Misc\b', line)
        if m:
            kv, i = kv_block(i + 1)
            p.misc.update({k: int(v) for k, v in kv.items()})
            continue
        m = re.match(r'Text (\d+) (\d+)', line)
        if m:
            old, new, i = text_block(raw, i)
            p.texts.append((old, new))
            continue
        i += 1
    return p


def apply_deh(t, p):
    """Patched views for build_wad.py: states, mobj fields, weapons."""
    states = {i: list(v[1]) for i, v in t.state_lines.items()}
    for i, st in p.states.items():
        states[i] = list(st)
    mobj = [dict(m['fields']) for m in t.mobj]
    for i, ch in p.mobj.items():
        mobj[i].update(ch)
    weapons = [dict(w) for w in t.weapons]
    for i, ch in p.weapons.items():
        weapons[i].update(ch)
    return states, mobj, weapons


# Projectile each firing action spawns (P_WeaponSpawn in p_pspr.c).
ACTION_SPAWN = {'A_FireMissile': 'MT_ROCKET', 'A_FirePlasma': 'MT_PLASMA', 'A_FireBFG': 'MT_BFG'}
# Map pickup (doomednum) and pickup message of each vanilla weapon.
WEAPON_PICKUP = {2: 2001, 3: 2002, 4: 2003, 5: 2004, 6: 2006, 7: 2005, 8: 82}
WEAPON_GOT = {2: 'GOTSHOTGUN', 3: 'GOTCHAINGUN', 4: 'GOTLAUNCHER', 5: 'GOTPLASMA', 6: 'GOTBFG9000',
              7: 'GOTCHAINSAW', 8: 'GOTSHOTGUN2'}
NUM_VANILLA_WEAPONS = 9


def transplant(t, p, text, src, dst, spec=None):
    """Weapon `src` as the patch `text` makes it (applied on top of p)
    becomes weapon `dst` of p, so both versions are in the game: D4V's extra
    weapons each rewrite a vanilla weapon's frames (the HAR the chaingun's);
    transplanted they get a slot of their own (wp_extra*) and the original
    stays.

    States of the transplanted weapon (and of its pickup and projectile) that
    differ from p's, or lead to ones that do, are copied into S_MODSPARE*;
    sprites and sounds the patch renamed differently go to SPR_MD* /
    sfx_mod*. An extra weapon gets its own pickup thing (MT_MODSPARE*,
    spec['doomednum']); a projectile the patch changed (the grenade
    launcher's rocket) is copied too. What a copied state loses with its
    number (A_FireCGun's flash offset, a renamed action's sound, the
    projectile) goes to MOD_PSPR_OVERRIDES."""
    spec = spec or {}
    q = parse_deh(t, text, copy.deepcopy(p))
    sa, ma, _ = apply_deh(t, p)
    sb, mb, wb = apply_deh(t, q)
    snd_a, spr_a, _ = name_renames(t, p)
    snd_b, spr_b, _ = name_renames(t, q)
    idx = {n: i for i, n in enumerate(t.st_enum)}
    spr_idx = {n: i for i, n in enumerate(t.spr_enum)}
    mt_idx = {n: i for i, n in enumerate(t.mt_enum)}
    sfx_base = re.findall(r'^\s*\{\s*"(\w*)",', t.sounds_c[t.sounds_c.index('S_sfx[]'):], re.M)
    sfx_idx = {n: i for i, n in enumerate(t.sfx_enum)}

    def spr_name(spr, ren):
        n = t.spr_names[spr_idx[spr]]
        return ren.get(n, n)

    def sfx_enum(v):     # mobjinfo sound fields: sfx_* or a plain number
        return t.sfx_enum[int(v)] if re.match(r'-?\d+$', v) else v

    def snd_name(sfx, ren):
        n = sfx_base[sfx_idx[sfx_enum(sfx)]]
        return ren.get(n, n)

    def key(st, ren):
        return (spr_name(st[0], ren),) + tuple(st[1:])

    def chain(roots):
        out, todo = set(), [r for r in roots if r]
        while todo:
            n = todo.pop()
            if n and n not in out:
                out.add(n)
                todo.append(idx[sb[n][4]])
        return out

    def mobj_roots(m):
        return [idx[m[f]] for f in MOBJ_STATE_FIELDS if m[f] in idx]

    w = wb[src]
    flash = idx[w['flashstate']]
    weapon_states = chain([idx[w[f]] for f in WEAPON_FIELDS[1:]] + [flash + 1])
    extra = dst >= NUM_VANILLA_WEAPONS
    pickup = None
    if extra:
        dn = str(WEAPON_PICKUP[src])
        pickup = next(i for i, m in enumerate(mb) if m['doomednum'] == dn)
    projectiles = sorted({mt_idx[ACTION_SPAWN[sb[n][3]]] for n in weapon_states if sb[n][3] in ACTION_SPAWN})
    reach = set(weapon_states)
    for m in projectiles + ([pickup] if pickup is not None else []):
        reach |= chain(mobj_roots(mb[m]))

    def needs_sound(n):
        sfx = ACTION_SFX.get(sb[n][3])
        return sfx and snd_name(sfx, snd_a) != snd_name(sfx, snd_b)

    def close(move):
        while True:
            more = {n for n in reach if n not in move and idx[sb[n][4]] in move}
            if not more:
                return move
            move |= more

    move = close({n for n in reach if key(sb[n], spr_b) != key(sa[n], spr_a) or needs_sound(n)
                  or sb[n][3] == 'A_FireCGun'})
    snd_fields = MOBJ_SOUND_FIELDS
    cloned = [m for m in projectiles
              if any(mb[m][f] != ma[m][f] for f in MOBJ_FIELDS if f not in snd_fields)
              or any(snd_name(mb[m][f], snd_b) != snd_name(ma[m][f], snd_a) for f in snd_fields)
              or chain(mobj_roots(mb[m])) & move]
    move = close(move | {n for n in weapon_states if sb[n][3] in ACTION_SPAWN
                         and mt_idx[ACTION_SPAWN[sb[n][3]]] in cloned})
    if flash in move or flash + 1 in move:
        move |= {flash, flash + 1}

    used = {i for i in p.states if t.st_enum[i].startswith('S_MODSPARE')}
    spare = [i for i, n in enumerate(t.st_enum) if n.startswith('S_MODSPARE') and i not in used]
    new = {}
    if flash in move:   # A_FireCGun / A_FirePlasma pick flashstate + 0 or 1
        k = next(k for k in range(len(spare) - 1) if spare[k + 1] == spare[k] + 1)
        new[flash], new[flash + 1] = spare.pop(k), spare.pop(k)
    for n in sorted(move - set(new)):
        assert spare, 'out of S_MODSPARE states'
        new[n] = spare.pop(0)

    names_a = [spr_a.get(x, x) for x in t.spr_names]
    used_spr = {old for old, _ in p.texts if re.match(r'MD\d\d$', old)}
    spr_map = {}

    def map_sprite(spr):
        nb = spr_name(spr, spr_b)
        if nb == spr_name(spr, spr_a):
            return spr
        if nb in names_a:
            return t.spr_enum[names_a.index(nb)]
        if nb not in spr_map:
            free = next(x for x in t.spr_names if re.match(r'MD\d\d$', x) and x not in used_spr)
            used_spr.add(free)
            p.texts.append((free, nb))
            spr_map[nb] = 'SPR_' + free
        return spr_map[nb]

    names_snd = [snd_a.get(x, x) for x in sfx_base]

    def map_sound(sfx):
        nb = snd_name(sfx, snd_b)
        if nb in names_snd:
            return t.sfx_enum[names_snd.index(nb)]
        free = next(x for x in sfx_base if re.match(r'mod\d+$', x) and x not in {o for o, _ in p.texts})
        p.texts.append((free, nb))
        names_snd[sfx_base.index(free)] = nb
        return 'sfx_' + free

    def map_state(name):
        return t.st_enum[new.get(idx[name], idx[name])] if name in idx else name

    for n, m in new.items():
        st = list(sb[n])
        st[0] = map_sprite(st[0])
        st[4] = map_state(st[4])
        p.states[m] = st
        sfx = ACTION_SFX.get(st[3])
        if needs_sound(n):
            to = map_sound(sfx)
            p.pspr_overrides.append((t.st_enum[m], 'PSPR_SFX', sfx, to))
            p.extra_sfx.add(to)
        if st[3] == 'A_FireCGun':
            p.pspr_overrides.append((t.st_enum[m], 'PSPR_FLASHOFS', '0', str(n - idx['S_CHAIN1'])))

    used_mt = set(p.mobj) | {mt_idx[e['pickup']] for e in p.extra_weapons}
    spare_mt = [i for i, n in enumerate(t.mt_enum) if n.startswith('MT_MODSPARE') and i not in used_mt]

    def clone(m, doomednum):
        assert spare_mt, 'out of MT_MODSPARE things'
        c = spare_mt.pop(0)
        fields = dict(mb[m])
        for f in MOBJ_STATE_FIELDS:
            fields[f] = map_state(fields[f])
        for f in snd_fields:
            if sfx_enum(fields[f]) != 'sfx_None':
                fields[f] = map_sound(fields[f])
                p.extra_sfx.add(fields[f])
        fields['doomednum'] = str(doomednum)
        p.mobj[c] = fields
        p.extra_mobj.add(t.mt_enum[c])
        return t.mt_enum[c]

    for m in cloned:
        to = clone(m, -1)
        for n in weapon_states:
            if ACTION_SPAWN.get(sb[n][3]) == t.mt_enum[m]:
                p.pspr_overrides.append((t.st_enum[new[n]], 'PSPR_SPAWN', t.mt_enum[m], to))

    p.weapons[dst] = {f: (w[f] if f == 'ammo' else map_state(w[f])) for f in WEAPON_FIELDS}
    if extra:
        actions = {sb[n][3] for n in weapon_states}
        ammo = (q.misc.get('BFG Cells/Shot', 40) if 'A_FireBFG' in actions
                else 2 if 'A_FireShotgun2' in actions else 1)
        # DeHackEd Text replaces the original string; a later patch wins.
        vanilla = macro_strings(t.englsh_h).get(WEAPON_GOT[src], '')
        got_a = ([n for o, n in p.texts if o == vanilla] or [vanilla])[-1]
        msg = ([n for o, n in q.texts if o == vanilla] or [vanilla])[-1]
        if spec.get('message') or msg == got_a:
            msg = spec.get('message', 'You got the %s!' % spec.get('name', 'new weapon'))
        p.extra_weapons.append({'weapon': dst, 'slot': spec['slot'], 'ammo': ammo,
                                'pickup': clone(pickup, spec['doomednum']), 'doomednum': spec['doomednum'],
                                'message': msg, 'spec': spec})
    return sorted(new.items())


ZSKIP = (r'lamp|lantern|lightlit|flashlit|batteries|jumpifinventory|giveinventory|takeinventory|spawnitemex|'
         r'alertmonsters|checkreload|firecustommissile\("gunsmoke|a_setpitch|a_setangle|a_quake|zoomfactor|overlay')


def zweapon(t, p, spec):
    """A GZDoom weapon (DECORATE states, TEXTURES sprites, SNDINFO sounds;
    tools/zdoom.py) as weapon spec['into']: its Ready/Select/Deselect/Fire/
    Reload sequences become S_MODSPARE states, its sprites SPR_MD* names, its
    sounds sfx_mod* (played by A_WeaponSound through MOD_PSPR_OVERRIDES).
    Bullets go through A_FireMod (spec "fire": [damage, pellets, spread
    degrees]); spec "mag" gives it a magazine, refilled by A_LoadMag at the
    end of the reload animation."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import zdoom
    root = os.path.join(ROOT, spec['root'])
    extra = read(os.path.join(ROOT, spec['decorate_extra'])) if spec.get('decorate_extra') else None
    actor = zdoom.Actor(os.path.join(root, spec['decorate']), spec['actor'], extra)
    sound = zdoom.sndinfo(root)
    skip = spec.get('skip', ZSKIP)
    labels = dict(spec['labels'])
    for x in labels.pop('extra', []):      # further labels the others continue into
        labels['x:' + x.lower()] = x
    roles = [r for r in ('ready', 'select', 'deselect', 'fire', 'reload', 'reload_loop', 'reload_end')
             if r in labels] + [r for r in labels if r.startswith('x:')]
    by_label = {labels[r].lower(): r for r in roles}
    seqs = {}
    for r in roles:
        role_skip = skip + ('|' + spec['skip_' + r] if spec.get('skip_' + r) else '')
        seqs[r] = list(actor.sequence(labels[r], role_skip, by_label, ready=(r == 'ready'),
                                      jump=spec.get('jump_' + r)))
    if spec.get('fire_min_tics') and 'fire' in seqs:
        # "fire_min_tics": at least that many tics from the trigger to the
        # first A_ReFire (Ashes lets a held trigger refire after 2-3 tics)
        seq = seqs['fire'][0]
        k = next((i for i, st in enumerate(seq) if st[4] == 'A_ReFire'), len(seq))
        total = sum(max(st[2], 0) for st in seq[:k])
        if 0 < k and total < spec['fire_min_tics']:
            pad = spec['fire_min_tics'] - total
            j = max([i for i in range(k) if seq[i][2] > 0] or [k - 1])
            if seq[j][3] and k < len(seq):
                # the muzzle flash (bright) keeps its length: the wait shows
                # the gun's next frame instead of a frozen flash
                seq.insert(k, (seq[k][0], seq[k][1], pad, False, None, None))
            else:
                seq[j] = seq[j][:2] + (seq[j][2] + pad,) + seq[j][3:]
    ready_spr, ready_frame = seqs['ready'][0][0][:2]
    if 'reload_loop' in seqs:
        # shell by shell: start -> insert one (A_LoadOne repeats it) -> end
        seqs['reload'][1] = ('label', labels['reload_loop'].lower())
        seqs['reload_loop'][0].append(('TNT1', 'A', 0, False, 'A_LoadOne', None))
        seqs['reload_loop'][1] = ('label', labels['reload_end'].lower())
    elif 'reload' in seqs:
        seqs['reload'][0].append(('TNT1', 'A', 0, False, 'A_LoadMag', None))
    used = {i for i in p.states if t.st_enum[i].startswith('S_MODSPARE')}
    spare = [i for i, n in enumerate(t.st_enum) if n.startswith('S_MODSPARE') and i not in used]
    idx = {}
    for r in roles:
        assert len(spare) >= len(seqs[r][0]), 'out of S_MODSPARE states'
        idx[r] = [spare.pop(0) for _ in seqs[r][0]]
    first = {r: t.st_enum[idx[r][0]] for r in roles}

    def follow(nxt):
        if nxt[0] == 'label' and nxt[1] in by_label:
            return first[by_label[nxt[1]]]
        return first['ready']

    names_a = set(name_renames(t, p)[1].values()) | set(t.spr_names)
    taken_spr = {o for o, _ in p.texts if re.match(r'MD\d\d$', o)}
    taken_sfx = {o for o, _ in p.texts}
    sfx_base = re.findall(r'^\s*\{\s*"(\w*)",', t.sounds_c[t.sounds_c.index('S_sfx[]'):], re.M)
    renamed = {n: o for o, n in p.texts}

    def sprite(name):
        if name == 'TNT1':
            return 'SPR_TNT1'
        if name in renamed and re.match(r'MD\d\d$', renamed[name]):
            return 'SPR_' + renamed[name]
        assert name not in names_a, 'sprite %s clashes with an existing one' % name
        free = next(x for x in t.spr_names if re.match(r'MD\d\d$', x) and x not in taken_spr)
        taken_spr.add(free)
        p.texts.append((free, name))
        renamed[name] = free
        return 'SPR_' + free

    def sfx(path):
        lump = re.sub(r'\W', '', os.path.splitext(os.path.basename(path))[0]).upper()[:6]
        while 'DS' + lump in p.zsounds and p.zsounds['DS' + lump] != path:
            lump = lump[:5] + chr(ord(lump[5:6] or '0') + 1)
        if lump.lower() in renamed:
            return 'sfx_' + renamed[lump.lower()]
        free = next(x for x in sfx_base if re.match(r'mod\d+$', x) and x not in taken_sfx)
        taken_sfx.add(free)
        p.texts.append((free, lump.lower()))
        renamed[lump.lower()] = free
        p.zsounds['DS' + lump] = path
        return 'sfx_' + free

    for r in roles:
        seq, nxt = seqs[r]
        for k, (spr, f, tics, bright, action, arg) in enumerate(seq):
            if spr in ('----', '####'):
                spr, f = ready_spr, ready_frame
            st = idx[r][k]
            name = t.st_enum[st]
            nextname = t.st_enum[idx[r][k + 1]] if k + 1 < len(seq) else follow(nxt)
            if action == 'A_WeaponSound':
                m = re.search(r'"([^"]+)"', arg or '')
                path = sound(m.group(1)) if m else None
                if path:
                    to = sfx(path)
                    p.pspr_overrides.append((name, 'PSPR_SFX', 'sfx_None', to))
                    p.extra_sfx.add(to)
                else:
                    action = None
            if action == 'A_FireMissile' and spec.get('missile_as_bullet'):
                action = 'A_FireMod'    # e.g. crossbow bolts: one hard-hitting instant shot
            if action == 'A_FireMissile' and spec.get('projectile'):
                # "projectile": "MT_PLASMA" - fired instead of a rocket (a DeHackEd
                # patch gives that thing its look, speed and damage)
                p.pspr_overrides.append((name, 'PSPR_SPAWN', 'MT_ROCKET', spec['projectile']))
                p.extra_mobj.add(spec['projectile'])
            if action == 'A_LoadOne':
                p.pspr_overrides.append((name, 'PSPR_LOOP', '0', first['reload_loop']))
            if action in ACTION_SFX and action != 'A_WeaponSound':
                # the Ashes sounds are separate A_WeaponSound states: mute the vanilla one
                p.pspr_overrides.append((name, 'PSPR_SFX', ACTION_SFX[action], 'sfx_None'))
            p.states[st] = [sprite(spr), str((ord(f) - 65) | (0x8000 if bright else 0)), str(tics),
                            action or 'NULL', nextname, '0', '0']
            if spr != 'TNT1':
                p.zsprites['%s%s0' % (spr, f)] = (root, spec.get('lift', 0), 1, 1)
    dst = spec['into']
    if spec.get('pickup_replaces'):     # a vanilla weapon slot: its map pickup gets the Ashes art
        num, den = spec.get('pickup_scale', [1, 1])
        p.zpickups.append((spec['pickup_replaces'], root, spec['pickup'], num, den))
    if dst == 'extra':
        # its own pickup thing: the shotgun pickup's properties, the Ashes sprite
        dst = NUM_VANILLA_WEAPONS + len(p.extra_weapons)
        assert dst < len(t.weapons), 'out of wp_extra slots'
        mobj = apply_deh(t, p)[1]
        base = next(i for i, m in enumerate(mobj) if m['doomednum'] == '2001')
        used_mt = set(p.mobj) | {i for i, n in enumerate(t.mt_enum)
                                 if n in {e['pickup'] for e in p.extra_weapons}}
        mt = next(i for i, n in enumerate(t.mt_enum) if n.startswith('MT_MODSPARE') and i not in used_mt)
        st = spare.pop(0)
        pspr, pframe = spec['pickup'][:4], spec['pickup'][4]
        p.states[st] = [sprite(pspr), str(ord(pframe) - 65), '-1', 'NULL', 'S_NULL', '0', '0']
        num, den = spec.get('pickup_scale', [1, 1])
        p.zsprites['%s%s0' % (pspr, pframe)] = (root, 0, num, den)
        fields = dict(mobj[base])
        fields.update({'doomednum': str(spec['doomednum']), 'spawnstate': t.st_enum[st]})
        p.mobj[mt] = fields
        p.extra_weapons.append({'weapon': dst, 'slot': spec['slot'], 'ammo': 1, 'pickup': t.mt_enum[mt],
                                'doomednum': spec['doomednum'],
                                'message': actor.prop('Inventory.Pickupmessage', 'You got the %s!' % spec['name']),
                                'spec': spec})
    p.weapons[dst] = {'ammo': spec.get('ammo', 'am_noammo'), 'upstate': first['select'],
                      'downstate': first['deselect'], 'readystate': first['ready'],
                      'atkstate': first['fire'], 'flashstate': 'S_LIGHTDONE'}
    fire = spec.get('fire')
    if fire is None:    # A_FireBullets(spread_h, spread_v, count, damage, ...): -1 = one accurate bullet
        for r in roles:
            for _, _, _, _, action, arg in seqs[r][0]:
                m = re.match(r'\s*([\d.]+)\s*,\s*[\d.]+\s*,\s*(-?\d+)\s*,\s*(\d+)', arg or '') \
                    if action == 'A_FireMod' else None
                if m and fire is None:
                    fire = [int(m.group(3)), max(1, int(m.group(2))), float(m.group(1))]
    if fire:
        damage, pellets, spread = fire
        p.weapon_fire[dst] = (damage, pellets, int(spread * 11930464 / 255))
    if spec.get('punch'):   # [min, max] melee damage (A_CustomPunch turns into A_Punch)
        p.weapon_punch[dst] = tuple(spec['punch'])
    if spec.get('mag'):
        p.weapon_mag[dst] = (spec['mag'], first['reload'])


def extra_ammo(t, p, spec):
    """Profile "extra_ammo": {"max": 150, "clip": 15, "pickups": [{"doomednum":
    4210, "root": pk3 folder, "pickup": "556AA", "pickup_scale": [3, 5],
    "clips": 2, "message": "..."}]}: a fifth ammo type, am_rifle, for the
    weapons whose "ammo" names it, and its map pickups (the clip's properties,
    the mod's sprite; place them with build_wad's place_things / add_things)."""
    p.maxammo[4] = spec['max']
    p.clipammo[4] = spec['clip']
    mobj = apply_deh(t, p)[1]
    base = next(i for i, m in enumerate(mobj) if m['doomednum'] == '2007')
    used = {i for i in p.states if t.st_enum[i].startswith('S_MODSPARE')}
    spare = [i for i, n in enumerate(t.st_enum) if n.startswith('S_MODSPARE') and i not in used]
    taken_spr = {o for o, _ in p.texts if re.match(r'MD\d\d$', o)}
    for pk in spec['pickups']:
        used_mt = set(p.mobj) | {i for i, n in enumerate(t.mt_enum)
                                 if n in {e['pickup'] for e in p.extra_weapons}}
        mt = next(i for i, n in enumerate(t.mt_enum) if n.startswith('MT_MODSPARE') and i not in used_mt)
        st = spare.pop(0)
        name, frame = pk['pickup'][:4], pk['pickup'][4]
        free = next(x for x in t.spr_names if re.match(r'MD\d\d$', x) and x not in taken_spr)
        taken_spr.add(free)
        p.texts.append((free, name))
        p.states[st] = ['SPR_' + free, str(ord(frame) - 65), '-1', 'NULL', 'S_NULL', '0', '0']
        num, den = pk.get('pickup_scale', [1, 1])
        p.zsprites['%s%s0' % (name, frame)] = (os.path.join(ROOT, pk['root']), 0, num, den)
        fields = dict(mobj[base])
        fields.update({'doomednum': str(pk['doomednum']), 'spawnstate': t.st_enum[st]})
        p.mobj[mt] = fields
        p.extra_ammo.append({'pickup': t.mt_enum[mt], 'clips': pk.get('clips', 1), 'message': pk['message']})


def sound_variants(t, p, variants):
    """Profile "sound_variants": {"DSDMACT": [sound files]}: more lines for a
    voice that has only one (every enemy of a kind saying the same thing gets
    old). Each file takes a spare sfx_mod slot; s_sound.c picks one of the
    base and its alternatives at random (MOD_SFX_VARIANTS)."""
    taken = {o for o, _ in p.texts}
    renamed = {n: o for o, n in p.texts}
    table = t.sounds_c[t.sounds_c.index('S_sfx[]'):]
    sfx_base = re.findall(r'^\s*\{\s*"(\w*)",', table, re.M)
    prio = dict((n, int(v)) for n, v in re.findall(r'^\s*\{\s*"(\w*)",\s*\w+,\s*(\d+)', table, re.M))
    for base, files in variants.items():
        name = base[2:].lower()
        # a variant keeps its voice's priority (spare slots have the weapons' 64,
        # so chatter would cut gunfire off)
        base_prio = p.sound_priority.get(sfx_base.index(name), prio.get(name, 64))
        alts = []
        for path in files:
            lump = re.sub(r'\W', '', os.path.splitext(os.path.basename(path))[0]).upper()[:6]
            while 'DS' + lump in p.zsounds and p.zsounds['DS' + lump] != path:
                lump = lump[:5] + chr(ord(lump[5:6] or '0') + 1)
            if lump.lower() not in renamed:
                free = next((x for x in sfx_base if re.match(r'mod\d+$', x) and x not in taken), None)
                assert free, 'out of sfx_mod slots for sound_variants'
                taken.add(free)
                p.texts.append((free, lump.lower()))
                renamed[lump.lower()] = free
                p.zsounds['DS' + lump] = path
                p.sound_priority[sfx_base.index(free)] = base_prio
            alts.append('sfx_' + renamed[lump.lower()])
        p.sfx_variants.append(('sfx_' + base[2:].lower(), alts))


def state_chains(t, p, chains):
    """Profile "state_chains": {"S_EXPLODE1": [[sprite, frame, tics, action,
    bright], ...]}. The named state becomes the first entry, the others take
    S_MODSPARE states and the last one ends in S_NULL (e.g. a longer rocket
    explosion). A sprite name the engine lacks takes a free MD## slot."""
    used = {i for i in p.states if t.st_enum[i].startswith('S_MODSPARE')}
    spare = [i for i, n in enumerate(t.st_enum) if n.startswith('S_MODSPARE') and i not in used]
    taken_spr = {o for o, _ in p.texts if re.match(r'MD\d\d$', o)}
    renamed = {n: o for o, n in p.texts}
    st_idx = {n: i for i, n in enumerate(t.st_enum)}

    def sprite(name):
        if name in renamed and re.match(r'MD\d\d$', renamed[name]):
            return 'SPR_' + renamed[name]
        if name in t.spr_names and not re.match(r'MD\d\d$', name):
            return 'SPR_' + name
        free = next(x for x in t.spr_names if re.match(r'MD\d\d$', x) and x not in taken_spr)
        taken_spr.add(free)
        p.texts.append((free, name))
        renamed[name] = free
        return 'SPR_' + free

    for first, seq in chains.items():
        assert len(spare) >= len(seq) - 1, 'out of S_MODSPARE states'
        ids = [st_idx[first]] + [spare.pop(0) for _ in seq[1:]]
        for k, (spr, frame, tics, action, bright) in enumerate(seq):
            st = state_fields(t, ids[k])
            st[0] = sprite(spr)
            st[1] = str((ord(frame) - ord('A')) | (0x8000 if bright else 0))
            st[2] = str(tics)
            st[3] = action or 'NULL'
            st[4] = t.st_enum[ids[k + 1]] if k + 1 < len(ids) else 'S_NULL'
            p.states[ids[k]] = st


def load_patch(t, dehs, transplants=(), zweapons=(), chains=None, ammo=None, variants=None):
    """Apply the patches in order, then the weapon transplants ("into":
    "extra" takes the next wp_extra* slot), GZDoom weapons and state chains."""
    p = None
    for deh in dehs:
        text = read(deh)
        seen = p.kv_seen if p else 0
        p = parse_deh(t, text, p)
        # Every "key = value" line outside Text blocks must have been consumed.
        expect = count_key_lines(text)
        assert p.kv_seen - seen == expect, '%s: parsed %d of %d key lines' % (deh, p.kv_seen - seen, expect)
    p = p or Patch()
    for tr in transplants:
        into = tr['into']
        if into == 'extra':
            into = NUM_VANILLA_WEAPONS + len(p.extra_weapons)
            assert into < len(t.weapons), 'out of wp_extra slots'
        transplant(t, p, read(tr['deh']), tr['weapon'], into, tr)
    for spec in zweapons:
        zweapon(t, p, spec)
    if ammo:
        extra_ammo(t, p, ammo)
    if variants:
        sound_variants(t, p, variants)
    state_chains(t, p, chains or {})
    return p


def c_unescape(lit):
    return bytes(lit, 'latin-1').decode('unicode_escape')


def c_escape(s):
    return s.replace('\\', '\\\\').replace('"', '\\"')


def macro_strings(header, commented=False):
    """name -> decoded string for every string #define (or for the
    commented-out `//#define` originals GBADoom left next to its shortened
    replacements)."""
    out = {}
    prefix = r'^//\s*#define' if commented else r'^#define'
    for m in re.finditer(prefix + r'\s+(\w+)\s+((?:.*\\\n)*.*)$', header, re.M):
        body = m.group(2)
        if commented:
            body = body.split(' - ')[0] if '" - ' in body else body
        lits = re.findall(r'"((?:[^"\\]|\\.)*)"', body)
        if lits:
            out[m.group(1)] = ''.join(c_unescape(x) for x in lits)
    return out


def norm(s):
    return ' '.join(s.split()).upper()


def reflow(text, width):
    paras = re.split(r'\n\s*\n', text.strip('\n'))
    out = []
    for para in paras:
        words = para.split()
        line = ''
        lines = []
        for w in words:
            if line and len(line) + 1 + len(w) > width:
                lines.append(line)
                line = w
            else:
                line = (line + ' ' + w) if line else w
        if line:
            lines.append(line)
        out.append('\n'.join(lines))
    return '\n\n'.join(out)


def name_renames(t, p):
    """Text blocks that rename a sound (S_sfx[].name, e.g. D4V's pistol ->
    pisto1) or a sprite (sprnames[]). Returns (sounds, sprites, rest)."""
    sfx_names = re.findall(r'^\s*\{\s*"(\w*)",', t.sounds_c, re.M)
    sounds, sprites, rest = {}, {}, []
    for old, new in p.texts:
        if old in sfx_names and 0 < len(new) <= 6 and re.match(r'^\w+$', new):
            sounds[old] = new
        elif len(old) == 4 and old in t.spr_names and len(new) == 4 and re.match(r'^\w+$', new):
            sprites[old] = new
        else:
            rest.append((old, new))
    return sounds, sprites, rest


def text_overrides(t, p):
    import difflib

    strings = macro_strings(t.englsh_h)
    # DeHackEd matches against vanilla text: where GBADoom shortened a string
    # and kept the vanilla one as a comment, match on the comment.
    originals = dict(strings)
    originals.update({k: v for k, v in macro_strings(t.englsh_h, commented=True).items() if k in strings})

    by_norm = {}
    for name, s in originals.items():
        by_norm.setdefault(norm(s), []).append(name)
    overrides = []
    unmatched = []
    for old, new in name_renames(t, p)[2]:
        names = by_norm.get(norm(old))
        if not names and len(old) > 60:
            # Long texts were re-worded slightly when GBADoom re-wrapped them.
            best = max(originals, key=lambda n: difflib.SequenceMatcher(None, norm(old), norm(originals[n])).ratio())
            if difflib.SequenceMatcher(None, norm(old), norm(originals[best])).ratio() > 0.6:
                names = [best]
        if not names:
            unmatched.append(old)
            continue
        for name in names:
            orig = strings[name]
            if '\n' in orig and len(orig) > 60:
                # GBADoom re-wrapped the long texts for its narrow screen.
                width = max(len(x) for x in orig.split('\n'))
                value = reflow(new, width)
            else:
                value = new.strip()
            overrides.append((name, value))
    for name, value in p.bex_strings.items():
        if name in strings:
            overrides.append((name, value))
        else:
            unmatched.append('[STRINGS] ' + name)
    return overrides, unmatched


def emit(t, p, outdir, profile=None):
    profile = profile or {}
    os.makedirs(outdir, exist_ok=True)

    # info_mod.c
    lines = t.info_c.split('\n')
    for i, st in sorted(p.states.items()):
        ln, orig = t.state_lines[i]
        if st == orig:
            continue
        comment = lines[ln][lines[ln].index('//'):]
        lines[ln] = '  {%s,%s,%s,%s,%s,%s,%s},  %s' % (st[0], st[1], st[2], st[3], st[4],
                                                      st[5] or '0', st[6] or '0', comment)
    for i, ch in sorted(p.mobj.items()):
        m = t.mobj[i]
        for f, v in ch.items():
            if m['fields'][f] == v:
                continue
            ln = m['lines'][f]
            comment = lines[ln][lines[ln].index('//'):]
            lines[ln] = '    %s,    %s' % (v, comment) if f != 'raisestate' else '    %s    %s' % (v, comment)
    text = '\n'.join(lines)
    snd_ren, spr_ren, _ = name_renames(t, p)
    if spr_ren:
        start = text.index('sprnames[')
        end = text.index('};', start)
        block = text[start:end]
        for old, new in spr_ren.items():
            block = block.replace('"%s"' % old, '"%s"' % new, 1)
        text = text[:start] + block + text[end:]
    write(os.path.join(outdir, 'info_mod.c'), text)

    # d_items_mod.c
    items = t.items_c
    if p.weapons:
        head = items[:items.index('weaponinfo[NUMWEAPONS]')]
        body = items[items.index('weaponinfo[NUMWEAPONS]'):]
        end = body.index('};')
        tail = body[end:]
        body = body[:end]
        # Rebuild entry by entry: replace the six tokens of each patched weapon.
        entries = re.findall(r'\{[^{}]*\}', body)
        for i, ch in p.weapons.items():
            e = entries[i]
            toks = re.findall(r'\b(am_\w+|S_\w+)\b', e)
            vals = dict(zip(WEAPON_FIELDS, toks))
            vals.update(ch)
            ne = e
            for f, old in zip(WEAPON_FIELDS, toks):
                ne = re.sub(r'\b%s\b' % re.escape(old), '\x00' + f + '\x00', ne, count=1)
            for f in WEAPON_FIELDS:
                ne = ne.replace('\x00' + f + '\x00', vals[f])
            body = body.replace(e, ne, 1)
        items = head + body + tail
    write(os.path.join(outdir, 'd_items_mod.c'), items)

    # sounds_mod.c
    snd = t.sounds_c.split('\n')
    sfx_start = next(i for i, l in enumerate(snd) if 'S_sfx[]' in l)     # not S_music[]'s entries
    entry_lines = [i for i, l in enumerate(snd) if i > sfx_start and re.match(r'\s*\{\s*"\w*",', l)]
    for i in entry_lines:
        m = re.match(r'(\s*\{\s*")(\w*)(".*)', snd[i])
        if m and m.group(2) in snd_ren:
            snd[i] = m.group(1) + snd_ren[m.group(2)] + m.group(3)
    for n, prio in p.sound_priority.items():
        ln = entry_lines[n]
        snd[ln] = re.sub(r'^(\s*\{\s*"\w*",\s*\w+,\s*)\d+', lambda m: m.group(1) + str(prio), snd[ln])
    write(os.path.join(outdir, 'sounds_mod.c'), '\n'.join(snd))

    # mod_gen.h
    overrides, unmatched = text_overrides(t, p)
    if profile.get('map_list'):     # level names follow their levels
        dst = {'HUSTR_%d' % src: 'HUSTR_%d' % (k + 1) for k, src in enumerate(profile['map_list'])
               if not isinstance(src, list)}       # [pwad, map] entries: name them in "strings"
        overrides = [(dst[n], v) for n, v in overrides if not n.startswith('HUSTR_') or n in dst]
    overrides += [(k, v) for k, v in profile.get('strings', {}).items()]
    h = ['// Generated by tools/deh2c.py from %s. Do not edit.' % profile.get('name', 'the DeHackEd patches'),
         '#ifndef MOD_GEN_H', '#define MOD_GEN_H', '']
    h.append('#define MOD_NAME "%s"' % c_escape(profile.get('name', 'Doom')))
    if 'maps' in profile:
        h.append('#define MOD_FIRST_MAP %d' % profile['maps'][0])
        h.append('#define MOD_LAST_MAP %d' % profile['maps'][1])
    if 'end_flat' in profile:
        h.append('#define MOD_ENDFLAT "%s"' % profile['end_flat'])
    for i, name in enumerate(profile.get('skills', [])[:5]):
        h.append('#define MOD_SKILL_%d "%s"' % (i + 1, c_escape(name)))
    if 'end_text' in profile:
        lines = profile['end_text']
        h.append('#define MOD_ENDTEXT \\\n  %s' % ' \\\n  '.join(
            '"%s%s"' % (c_escape(x), '\\n' if k < len(lines) - 1 else '') for k, x in enumerate(lines)))
    if 'Initial Bullets' in p.misc:
        h.append('#define DEH_INITIAL_BULLETS %d' % p.misc['Initial Bullets'])
    if 'Initial Health' in p.misc:
        h.append('#define DEH_INITIAL_HEALTH %d' % p.misc['Initial Health'])
    if 'BFG Cells/Shot' in p.misc:
        h.append('#define DEH_BFGCELLS %d' % p.misc['BFG Cells/Shot'])
    if p.maxammo:
        base = [200, 50, 300, 50, 0]
        for n, v in p.maxammo.items():
            base[n] = v
        h.append('#define DEH_MAXAMMO {%s}' % ', '.join(map(str, base)))
    if p.clipammo:
        base = [10, 4, 20, 1, 0]
        for n, v in p.clipammo.items():
            base[n] = v
        h.append('#define DEH_CLIPAMMO {%s}' % ', '.join(map(str, base)))
    if profile.get('gore'):
        h.append('#define MOD_GORE %d' % profile['gore'])
    if profile.get('grenade'):     # rockets fly as tumbling grenades in an arc (p_mobj.c)
        h.append('#define MOD_GRENADE 1')
    if profile.get('ui'):   # panel-font intermission (wi_stuff.c), tools/ui_art.py lumps
        h.append('#define MOD_UI_TEXT 1')
    if profile.get('explosion_drop'):   # base-anchored explosion art centred on rocket impacts (p_mobj.c)
        h.append('#define MOD_EXPLOSION_DROP %d' % profile['explosion_drop'])
    if profile.get('hud') == 'overlay':     # fullscreen view + overlay HUD (build_wad.py HUD* lumps)
        h.append('#define MOD_HUD_OVERLAY 1')
    if profile.get('fog'):
        h.append('#define MOD_FOG_START %d' % profile['fog'].get('start', 256))
        h.append('#define MOD_FOG_RANGE %d' % profile['fog'].get('range', 1024))
    vslots = [1, 2, 3, 4, 5, 6, 7, 1, 3]
    for w in profile.get('remove_weapons', []):
        vslots[w] = 0
    for z in profile.get('zweapons', []):   # "slot" on one in a vanilla weapon's place: its key
        if isinstance(z.get('into'), int) and z.get('slot'):
            vslots[z['into']] = z['slot']
    if vslots != [1, 2, 3, 4, 5, 6, 7, 1, 3]:
        h.append('#define MOD_VANILLA_SLOTS %s' % ', '.join(map(str, vslots)))
    if p.extra_weapons:
        slots, ammo = ['0'] * 6, ['1'] * 6
        for e in p.extra_weapons:
            slots[e['weapon'] - NUM_VANILLA_WEAPONS] = str(e['slot'])
            ammo[e['weapon'] - NUM_VANILLA_WEAPONS] = str(e['ammo'])
        h.append('#define MOD_WEAPON_SLOTS %s' % ', '.join(slots))
        h.append('#define MOD_WEAPON_AMMO %s' % ', '.join(ammo))
        h.append('#define MOD_WEAPON_PICKUPS \\\n  %s' % ', \\\n  '.join(
            '{%s, wp_extra%d, "%s"}' % (e['pickup'], e['weapon'] - NUM_VANILLA_WEAPONS, c_escape(e['message']))
            for e in p.extra_weapons))
    if p.sfx_variants:
        most = max(len(a) for _, a in p.sfx_variants)
        h.append('#define MOD_SFX_VARIANTS_MAX %d' % most)
        h.append('#define MOD_SFX_VARIANTS \\\n  %s' % ', \\\n  '.join(
            '{%s, %d, %s}' % (b, len(a), ', '.join(a + ['sfx_None'] * (most - len(a)))) for b, a in p.sfx_variants))
    if p.extra_ammo:
        h.append('#define MOD_AMMO_PICKUPS \\\n  %s' % ', \\\n  '.join(
            '{%s, am_rifle, %d, "%s"}' % (e['pickup'], e['clips'], c_escape(e['message'])) for e in p.extra_ammo))
    if p.weapon_fire:
        h.append('#define MOD_WEAPON_FIRE \\\n  %s' % ', \\\n  '.join(
            '{%d, %d, %d, %d}' % ((w,) + v) for w, v in sorted(p.weapon_fire.items())))
    if p.weapon_punch:
        h.append('#define MOD_WEAPON_PUNCH \\\n  %s' % ', \\\n  '.join(
            '{%d, %d, %d}' % ((w,) + v) for w, v in sorted(p.weapon_punch.items())))
    if p.weapon_mag:
        h.append('#define MOD_WEAPON_MAG \\\n  %s' % ', \\\n  '.join(
            '{%d, %d, %s}' % (w, n, st) for w, (n, st) in sorted(p.weapon_mag.items())))
    if p.pspr_overrides:
        h.append('#define MOD_PSPR_OVERRIDES \\\n  %s' % ', \\\n  '.join(
            '{%s, %s, %s, %s}' % o for o in p.pspr_overrides))
    unsupported = sorted(k for k in p.misc if k not in ('Initial Bullets', 'Initial Health', 'BFG Cells/Shot'))
    h.append('')
    h.append('#endif')
    h.append('')
    h.append('// String overrides, included at the end of d_englsh.h.')
    h.append('#ifdef MOD_STRINGS')
    for name, value in overrides:
        parts = value.split('\n')
        lits = ['"%s%s"' % (c_escape(x), '\\n' if k < len(parts) - 1 else '') for k, x in enumerate(parts)]
        h.append('#undef %s' % name)
        h.append('#define %s \\\n  %s' % (name, ' \\\n  '.join(lits)))
    h.append('#endif')
    write(os.path.join(outdir, 'mod_gen.h'), '\n'.join(h) + '\n')
    return overrides, unmatched, unsupported


def count_key_lines(text):
    expect = 0
    lines = text.replace('\r', '').split('\n')
    i = 0
    while i < len(lines):
        m = re.match(r'Text (\d+) (\d+)', lines[i])
        if m:
            i = text_block(text, i)[2]
            continue
        if '=' in lines[i] and not lines[i].lstrip().startswith('#') and \
                not re.match(r'(Doom version|Patch format)', lines[i]):
            expect += 1
        i += 1
    return expect


def load_profile(path):
    """Mod profile: JSON with paths relative to the repo root."""
    import json
    with open(path) as f:
        prof = json.load(f)
    for k in ('iwad', 'pwads', 'deh', 'texture_wads'):
        if k in prof:
            v = prof[k]
            fix = lambda x: os.path.expanduser(x if os.path.isabs(os.path.expanduser(x)) else os.path.join(ROOT, x))
            prof[k] = [fix(x) for x in v] if isinstance(v, list) else fix(v)
    if 'map_list' in prof:      # chosen levels, played as MAP01..MAPnn
        prof['maps'] = [1, len(prof['map_list'])]
    return prof


def write(path, text):
    with open(path, 'w', encoding='latin-1') as f:
        f.write(text)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('deh', nargs='*', help='DeHackEd patches, applied in order')
    ap.add_argument('--profile', help='mod profile (tools/mods/*.json): patches, map range, ending')
    ap.add_argument('--out', default=OUT)
    ap.add_argument('--selftest', action='store_true', help='empty patch must reproduce the sources')
    args = ap.parse_args()

    t = load_tables()

    if args.selftest:
        import tempfile
        d = tempfile.mkdtemp()
        emit(t, Patch(), d)
        ok = True
        for src, gen in (('source/info.c', 'info_mod.c'), ('source/d_items.c', 'd_items_mod.c'),
                         ('source/sounds.c', 'sounds_mod.c')):
            same = read(os.path.join(DOOM, src)) == read(os.path.join(d, gen))
            print('%-18s %s' % (gen, 'identical' if same else 'DIFFERS'))
            ok &= same
        sys.exit(0 if ok else 1)

    profile = load_profile(args.profile) if args.profile else {}
    dehs = args.deh or profile.get('deh', [])
    if not dehs and not profile:
        ap.error('need .deh files or --profile')

    p = load_patch(t, dehs, profile.get('transplant', []), profile.get('zweapons', []), profile.get('state_chains'),
                   profile.get('extra_ammo'), profile.get('sound_variants'))

    overrides, unmatched, unsupported = emit(t, p, args.out, profile)
    print('states %d, things %d, weapons %d, sounds %d, strings %d -> %s' % (
        len(p.states), len(p.mobj), len(p.weapons), len(p.sound_priority), len(overrides), args.out))
    for u in unmatched:
        print('WARNING: Text not matched to any engine string: %r' % u[:60])
    for u in unsupported:
        print('WARNING: Misc field not supported: %r' % u)


if __name__ == '__main__':
    main()
