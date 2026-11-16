"""Read GZDoom weapon definitions well enough to rebuild them as vanilla
states: DECORATE state sequences, TEXTURES sprite composites, SNDINFO names.

Only what a vanilla weapon can do is kept: each state's sprite, frame,
duration, brightness and one action from ACTION_MAP. Inventory logic (the
magazine bookkeeping, lanterns, upgrades, zoom) is dropped: the engine's own
magazine system (A_LoadMag, P_FireWeapon) replaces it.
"""
import os
import re

import hud_bar
import texture_pack

# DECORATE action -> vanilla/engine action. None drops the action (the state
# keeps its sprite and duration).
ACTION_MAP = {
    'a_raise': 'A_Raise', 'a_lower': 'A_Lower', 'a_refire': 'A_ReFire', 'a_gunflash': 'A_GunFlash',
    'a_light0': 'A_Light0', 'a_light1': 'A_Light1', 'a_light2': 'A_Light2',
    'a_firebullets': 'A_FireMod', 'a_custompunch': 'A_Punch', 'a_punch': 'A_Punch', 'a_saw': 'A_Saw',
    'a_playsound': 'A_WeaponSound', 'a_startsound': 'A_WeaponSound', 'a_playweaponsound': 'A_WeaponSound',
}


class Actor:
    def __init__(self, path, name, extra=None):
        """extra: DECORATE state lines appended to the actor's (a label there
        replaces the actor's own of that name, e.g. a new reload)."""
        text = open(path, encoding='latin-1').read()
        text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
        text = re.sub(r'//[^\n]*', '', text)
        m = re.search(r'^\s*actor\s+%s\b[^\n]*\n' % re.escape(name), text, re.I | re.M)
        assert m, 'no actor %s in %s' % (name, path)
        body = text[m.end():]
        depth, i = 0, 0
        while i < len(body):
            depth += {'{': 1, '}': -1}.get(body[i], 0)
            if depth == 0 and body[i] == '}':
                break
            i += 1
        self.body = body[:i]
        st = re.search(r'\bstates\s*\{', self.body, re.I)
        self.lines = [l.strip() for l in self.body[st.end():].split('\n')]
        if extra:
            text = re.sub(r'//[^\n]*', '', extra)
            self.lines += [l.strip() for l in text.split('\n')]
        self.labels = {}
        for k, l in enumerate(self.lines):
            for lab in re.findall(r'^([A-Za-z_][\w.]*)\s*:', l):
                self.labels[lab.lower()] = k

    def prop(self, name, default=None):
        m = re.search(r'^\s*%s\s+"?([^"\n]+?)"?\s*$' % re.escape(name), self.body, re.I | re.M)
        return m.group(1) if m else default

    def sequence(self, label, skip, stop_labels=(), ready=False, jump=None):
        """Flattened states from `label`: [(sprite, frame, tics, bright, action,
        argument)] and where it continues ('label', name) / ('loop',) /
        ('stop',). Lines matching `skip` (regex) are left out; a goto to
        another label is followed (once)."""
        out, seen, k = [], set(), self.labels[label.lower()] + 1
        start_label = label.lower()
        after_jump = False      # A_JumpIfInventory(..., 1, 1) + "Goto Empty": the goto is the else branch
        skip_states = 0         # A_JumpIfInventory("...Loaded", 1, n): the magazine isn't empty, jump n
        end_of_skip = False     # ...and the goto that closed the skipped branch
        while k < len(self.lines):
            l = self.lines[k]
            k += 1
            if jump and re.search(jump, l, re.I):
                # a conditional jump taken as the way on (lever-action: fired -> "Pump")
                return out, ('label', re.findall(r'"([^"]+)"', l)[-1].lower())
            state = re.match(r'^"?[A-Z0-9#\-]{4}"?\s+([A-Z\[\]\\#]+)\s+-?\d+', l, re.I)
            if skip_states:
                # the dry-fire branch: its states (one per frame letter) and its goto
                if state:
                    skip_states = max(0, skip_states - len(state.group(1)))
                    end_of_skip = not skip_states
                continue
            if end_of_skip:
                if re.match(r'^(goto|loop|stop|wait|fail)\b', l, re.I):
                    continue
                end_of_skip = not state
            if after_jump and re.match(r'^goto\b', l, re.I):
                after_jump = False
                continue
            after_jump = bool(re.search(r'a_jumpifinventory\s*\([^)]*,\s*1\s*\)', l, re.I)) or \
                (after_jump and not l)
            if not l or re.match(r'^[A-Za-z_][\w.]*\s*:\s*$', l):
                lab = l.rstrip(':').strip().lower()
                if lab in stop_labels:
                    return out, ('label', lab)
                continue
            m = re.match(r'^(goto|loop|stop|wait|fail)\b\s*([\w.]*)', l, re.I)
            if m:
                kind = m.group(1).lower()
                if kind == 'loop':
                    return out, ('label', start_label)
                if kind == 'goto':
                    target = m.group(2).lower()
                    if target in seen or target in ('ready', 'readylantern') or target in stop_labels \
                            or target not in self.labels:
                        return out, ('label', target)
                    seen.add(target)
                    k = self.labels[target] + 1
                    continue
                return out, ('stop',)
            # before `skip` (which drops A_JumpIfInventory lines): a loaded-magazine check
            loaded = re.search(r'a_jumpifinventory\s*\(\s*"\w*loaded\w*"\s*,\s*1\s*,\s*(\d+)\s*\)', l, re.I)
            if loaded and int(loaded.group(1)) > 1 and state:
                skip_states = int(loaded.group(1)) - 1
            if skip and re.search(skip, l, re.I):
                continue
            m = re.match(r'^("?[A-Z0-9#\-]{4}"?)\s+([A-Z\[\]\\#]+)\s+(-?\d+)\s*(.*)$', l, re.I)
            if not m:
                continue
            spr, frames, tics, rest = m.group(1).strip('"').upper(), m.group(2).upper(), int(m.group(3)), m.group(4)
            bright = bool(re.match(r'bright\b', rest, re.I))
            rest = re.sub(r'^\s*(bright|fast|slow|nodelay|canraise|offset\([^)]*\))\s*', '', rest, flags=re.I)
            rest = re.sub(r'^\s*(bright|fast|slow)\s*', '', rest, flags=re.I)
            act = re.match(r'^(\w+)\s*(?:\((.*)\))?', rest)
            action, arg = None, None
            if act:
                name = act.group(1).lower()
                arg = act.group(2)
                action = 'A_WeaponReady' if ready and name == 'a_weaponready' else ACTION_MAP.get(name)
                if name in ('a_firecustommissile', 'a_fireprojectile'):
                    what = (arg or '').lower()
                    action = None if re.search(r'smoke|casing|shell|spark|flash|light', what) else \
                        'A_FireMod' if re.search(r'bullet|tracer|pellet', what) else 'A_FireMissile'
                # Ashes plays a distant echo with each shot for far-away
                    # listeners; here it would cut the shot itself off
                if action == 'A_WeaponSound' and re.search(r'"[^"]*dist', arg or '', re.I):
                    action = None
            for f in frames:
                out.append((spr, f, tics, bright, action, arg))
                if action not in ('A_Raise', 'A_Lower', 'A_WeaponReady'):
                    action = None       # other actions run once per line
        return out, ('stop',)


class Assets:
    """TEXTURES composites and plain sprite PNGs of a GZDoom pk3 folder."""

    def __init__(self, root, extra_textures=()):
        """extra_textures: more TEXTURES-format files, read after the
        folder's own (a mod profile's sprite composites)."""
        self.root = root
        self.images = {}
        for d, _, files in os.walk(root):
            for f in files:
                if f.lower().endswith('.png'):
                    self.images.setdefault(os.path.splitext(f)[0].upper(), os.path.join(d, f))
        self.sprites = {}
        for path in [os.path.join(root, 'TEXTURES.txt')] + list(extra_textures):
            if not os.path.exists(path):
                continue
            text = open(path, encoding='latin-1').read()
            for m in re.finditer(r'^\s*Sprite\s+"?(\w+)"?\s*,\s*(\d+)\s*,\s*(\d+)\s*\{(.*?)^\s*\}', text, re.M | re.S | re.I):
                body = m.group(4)
                spec = {'w': int(m.group(2)), 'h': int(m.group(3)), 'offset': (0, 0), 'scale': (1.0, 1.0), 'patches': []}
                o = re.search(r'Offset\s+(-?\d+)\s*,\s*(-?\d+)', body, re.I)
                if o:
                    spec['offset'] = (int(o.group(1)), int(o.group(2)))
                xs = re.search(r'XScale\s+([\d.]+)', body, re.I)
                ys = re.search(r'YScale\s+([\d.]+)', body, re.I)
                spec['scale'] = (float(xs.group(1)) if xs else 1.0, float(ys.group(1)) if ys else 1.0)
                for p in re.finditer(r'Patch\s+"?([\w\-]+)"?\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*(\{[^}]*\})?', body, re.I):
                    opts = (p.group(4) or '').lower()
                    alpha = re.search(r'alpha\s+([\d.]+)', opts)
                    spec['patches'].append((p.group(1).upper(), int(p.group(2)), int(p.group(3)),
                                            'flipx' in opts, float(alpha.group(1)) if alpha else 1.0,
                                            bool(re.search(r'style\s+"?(add|translucent)', opts))))
                self.sprites[m.group(1).upper()] = spec

    def patch(self, lump, pal):
        """Doom picture for sprite lump name `lump` (e.g. REVGA0), in 320x200
        pixels, or None."""
        spec = self.sprites.get(lump)
        if spec is None:
            if lump in self.images:
                return texture_pack.png_patch(self.images[lump], pal)
            return None
        w, h = spec['w'], spec['h']
        canvas = [[None] * w for _ in range(h)]
        for name, px, py, flip, alpha, additive in spec['patches']:
            if name not in self.images:
                continue
            info = {}
            rows = texture_pack._png_rgba(self.images[name], info)
            for y, row in enumerate(rows):
                ty = py + y
                if not 0 <= ty < h:
                    continue
                if flip:
                    row = row[::-1]
                for x, p in enumerate(row):
                    tx = px + x
                    if not 0 <= tx < w or p[3] < 128:
                        continue
                    a = alpha
                    if additive or a < 1.0:
                        under = canvas[ty][tx] or (0, 0, 0)
                        if additive:
                            c = tuple(min(255, under[i] + int(p[i] * a)) for i in range(3))
                        else:
                            c = tuple(int(under[i] * (1 - a) + p[i] * a) for i in range(3))
                        if canvas[ty][tx] is None and a < 0.5:
                            continue
                    else:
                        c = p[:3]
                    canvas[ty][tx] = c
        ys = [y for y in range(h) if any(canvas[y])]
        xs = [x for x in range(w) if any(canvas[y][x] for y in range(h))]
        if not ys:
            return hud_bar.make_patch([[None]], 0, 0)
        x0, x1, y0, y1 = xs[0], xs[-1] + 1, ys[0], ys[-1] + 1
        img = [[pal.match(*c) if c else None for c in canvas[y][x0:x1]] for y in range(y0, y1)]
        ox, oy = spec['offset']
        out = hud_bar.make_patch(img, ox - x0, oy - y0)
        sx, sy = spec['scale']
        if abs(sx - 1) > 0.01:
            # TEXTURES XScale 1.2 = drawn at 1/1.2 size
            out = texture_pack.scale_patch(out, pal, 100, int(round(sx * 100)))
        return out


def sndinfo(root):
    """Logical sound name -> file path (first of a $random list)."""
    files = {}
    for d, _, fs in os.walk(root):
        for f in fs:
            if f.lower().endswith(('.ogg', '.wav', '.mp3', '.flac', '.lmp')):
                files.setdefault(os.path.splitext(f)[0].lower(), os.path.join(d, f))
    names, rnd = {}, {}
    for fn in os.listdir(root):
        if fn.lower().startswith('sndinfo'):
            for l in open(os.path.join(root, fn), encoding='latin-1'):
                l = l.split('//')[0].strip()
                m = re.match(r'\$random\s+(\S+)\s*\{\s*([^}]*)\}', l, re.I)
                if m:
                    rnd[m.group(1).lower()] = m.group(2).split()[0].lower()
                    continue
                m = re.match(r'^([\w/\-.]+)\s+"?([\w/\-.]+)"?\s*$', l)
                if m and not l.startswith('$'):
                    names[m.group(1).lower()] = m.group(2).lower()

    def resolve(name, depth=0):
        name = name.lower()
        if name in rnd and depth < 4:
            return resolve(rnd[name], depth + 1)
        lump = os.path.splitext(os.path.basename(names.get(name, name)))[0].lower()
        return files.get(lump)
    return resolve
