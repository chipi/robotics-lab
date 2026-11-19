"""A LEGO robot's description (RFC-0011) from an LDraw model: robot.urdf and one STL per link and colour.

Run with the Python of apps/observatory/.venv (standard library only; the parts library is ldraw.org's complete.zip unpacked in
~/opt/ldraw, or $LDRAW_DIR / --library):
    apps/observatory/.venv/bin/python robots/ldraw/from_ldraw.py <robot> [<robot> ...] [--library DIR]    # or: make robots-lego
    apps/observatory/.venv/bin/python robots/ldraw/from_ldraw.py --tree <robot>      # every part, where it is, which link takes it

`robots/<robot>/kinematics.json` names the model (`source`, an .mpd/.ldr beside it) and says what LDraw does not: which
parts make which link, and each joint.

  {"source": "x.mpd", "entry": "main.ldr", "yaw_deg": 0, "pitch_deg": 0, "detail": "low", "studs": true,
   "drop":  [selector, ...],                       parts left out (cables)
   "root":  "chassis",
   "links": {"chassis": {"rest": true}, "wheel_l": {"include": [selector, ...]}},
   "joints": [{"name": "left", "type": "continuous", "parent": "chassis", "child": "wheel_l",
               "axis": {"part": selector, "origin": [x, y, z], "dir": [x, y, z]}      # the first part the selector matches: its own frame, LDU
                     | {"frame": "submodel", "within": selector, ...same}             # the frame of that submodel's first instance
                     | {"ldraw_origin": [x, y, z], "ldraw_dir": [x, y, z]},           # the model's own frame, LDU
               "limit": [lower, upper]}]}                                              # radians, revolute only

An axis may give `"robot_dir": [x, y, z]` instead of `dir`: the direction in the robot's frame (the pivot is still `origin`).
A `fixed` joint needs no axis (the child sits at its parent's frame) or gives one for its pivot only.
`yaw_deg` and `pitch_deg` turn the whole model into the robot frame (a model posed nose-down, or facing another way).
`detail: "low"` takes LDraw's low-resolution primitives (p/8/) where there are, `studs: false` leaves studs out.

A selector is {"submodel": name, "lines": [a, b], "part": regex, "colour": n}, every key optional, all must hold: the part
sits (at any depth) in a submodel whose short name (its file name after the last " - ", without extension; * matches any
run, case-insensitive) is `name`, at a line of that file numbered a..b (as --tree prints them: 1 is the line after
`0 FILE`); its part number matches the regex; its colour code is n. A list of selectors is all of them. When several
links match a part, the most specific selector (the deepest submodel) wins, then the later link. `rest` takes what no
link takes.

Conventions: 1 LDU = 0.4 mm. LDraw is right-handed with -Y up; the robot frame is ROS's (x forward, y left, z up):
forward = -z of LDraw (towards the viewer of LDraw's default view), left = +x, up = -y, then turned by `yaw_deg` about
z and `pitch_deg` about y. BFC winding is followed, so the STL normals face outwards. The model is moved so its lowest
point is at z = 0; the root link's frame sits at its bounding box's centre (`stand_z` in robot.json is that centre's
height); a joint's frame sits at its pivot, axes parallel to the root's, so every joint origin is a plain offset and
every rpy is 0.
"""

import fnmatch
import json
import math
import os
import re
import struct
import sys
from pathlib import Path

LDU = 0.0004
DEFAULT_LIBRARY = Path(os.environ.get("LDRAW_DIR", Path.home() / "opt" / "ldraw" / "ldraw"))
HERE = Path(__file__).resolve().parent
GREY = (0.5, 0.5, 0.5, 1.0)


def norm(name: str) -> str:
    return name.replace("\\", "/").strip().lower()


class Library:
    """The LDraw parts library: files by lower-case relative name (parts/, p/, parts/s/ as "s/x.dat", p/8/ as "8/x.dat")."""

    def __init__(self, root: Path):
        self.root = Path(root)
        if not (self.root / "LDConfig.ldr").is_file():
            raise FileNotFoundError(f"{root} is not an LDraw library (no LDConfig.ldr); see ~/opt/ldraw")
        self.index = {}
        for sub in ("parts", "p", "models"):               # first one wins
            base = self.root / sub
            if base.is_dir():
                for p in base.rglob("*"):
                    if p.is_file():
                        self.index.setdefault(norm(str(p.relative_to(base))), p)
        self.colours = {}
        for line in (self.root / "LDConfig.ldr").read_text(errors="replace").splitlines():
            m = re.search(r"!COLOUR\s+(\S+)\s+CODE\s+(\d+)\s+VALUE\s+#([0-9A-Fa-f]{6})(?:.*?ALPHA\s+(\d+))?", line)
            if m:
                c = m.group(3)
                self.colours[int(m.group(2))] = (int(c[0:2], 16) / 255, int(c[2:4], 16) / 255, int(c[4:6], 16) / 255,
                                                 int(m.group(4)) / 255 if m.group(4) else 1.0)

    def rgba(self, code: int) -> tuple:
        if code >= 0x2000000:                                   # direct colour 0x2RRGGBB
            return ((code >> 16 & 255) / 255, (code >> 8 & 255) / 255, (code & 255) / 255, 1.0)
        return self.colours.get(code, GREY)


class Source:
    """The files of one model: those an .mpd embeds, else the .ldr itself; resolved before the library."""

    def __init__(self, path: Path, library: Library, entry: str | None = None, detail: str = "low"):
        self.library, self.detail = library, detail
        self.files = {}                                         # lower-case name -> [parsed lines]
        self.kinds = {}                                         # lower-case name -> "Part" / "Model" / ...
        self.cache = {}
        text = Path(path).read_text(errors="replace")
        chunks, cur = [], None
        for raw in text.splitlines():
            if re.match(r"0\s+FILE\s", raw, re.I):
                cur = [raw.split(None, 2)[2].strip(), []]
                chunks.append(cur)
            elif cur is not None:
                cur[1].append(raw)
        if not chunks:                                          # a plain .ldr
            chunks = [[Path(path).name, text.splitlines()]]
        for name, lines in chunks:
            self.files[norm(name)] = parse(lines)
            self.kinds[norm(name)] = next((m.group(1) for m in (re.match(r"0\s+!LDRAW_ORG\s+(\S+)", l, re.I) for l in lines) if m), "Model")
        self.main = norm(entry) if entry else norm(chunks[0][0])
        if self.main not in self.files:
            raise KeyError(f"{entry}: no such file in {path}; has {sorted(self.files)}")

    def resolve(self, name: str):
        """(lines, kind) for a referenced file name: the model's own files, then parts/, p/ (low-res 8/ first when asked)."""
        n = norm(name)
        if n in self.files:
            return self.files[n], self.kinds[n], n
        if self.detail == "low" and ("8/" + n) in self.library.index:
            p = self.library.index["8/" + n]
        elif n in self.library.index:
            p = self.library.index[n]
        else:
            return None, None, n
        if p not in self.cache:
            text = p.read_text(errors="replace").splitlines()
            kind = next((m.group(1) for m in (re.match(r"0\s+!LDRAW_ORG\s+(\S+)", l, re.I) for l in text) if m), "Part")
            self.cache[p] = (parse(text), kind)
        lines, kind = self.cache[p]
        return lines, kind, n


def parse(lines: list) -> list:
    """Parsed lines: ("tri", colour, [9 floats], cw), ("sub", colour, matrix(12), file, invert, lineno), in file order.
    cw: the file's winding is clockwise at this line (BFC); invert: BFC INVERTNEXT preceded."""
    out, cw, invert = [], False, False
    for no, raw in enumerate(lines, 1):
        t = raw.split()
        if not t:
            continue
        if t[0] == "0":
            if len(t) > 1 and t[1].upper() == "BFC":
                w = [x.upper() for x in t[2:]]
                if "INVERTNEXT" in w:
                    invert = True
                if "CW" in w:
                    cw = True
                elif "CCW" in w:
                    cw = False
            continue
        try:
            if t[0] == "1" and len(t) >= 15:
                x, y, z, a, b, c, d, e, f, g, h, i = (float(v) for v in t[2:14])
                out.append(("sub", int(t[1]), [a, b, c, x, d, e, f, y, g, h, i, z], " ".join(t[14:]), invert, no))
            elif t[0] == "3" and len(t) >= 11:
                out.append(("tri", int(t[1]), [float(v) for v in t[2:11]], cw))
            elif t[0] == "4" and len(t) >= 14:
                v = [float(x) for x in t[2:14]]
                out.append(("tri", int(t[1]), v[0:9], cw))
                out.append(("tri", int(t[1]), v[0:3] + v[6:12], cw))
        except ValueError:
            pass
        invert = False if t[0] == "1" else invert
    return out


def det3(m: list) -> float:
    a, b, c, x, d, e, f, y, g, h, i, z = m
    return a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)


def mmul(p: list, q: list) -> list:
    """The 3x4 transform p after q, each [a b c x d e f y g h i z]."""
    pa, pb, pc, px, pd, pe, pf, py, pg, ph, pi, pz = p
    qa, qb, qc, qx, qd, qe, qf, qy, qg, qh, qi, qz = q
    return [pa * qa + pb * qd + pc * qg, pa * qb + pb * qe + pc * qh, pa * qc + pb * qf + pc * qi, pa * qx + pb * qy + pc * qz + px,
            pd * qa + pe * qd + pf * qg, pd * qb + pe * qe + pf * qh, pd * qc + pe * qf + pf * qi, pd * qx + pe * qy + pf * qz + py,
            pg * qa + ph * qd + pi * qg, pg * qb + ph * qe + pi * qh, pg * qc + ph * qf + pi * qi, pg * qx + ph * qy + pi * qz + pz]


IDENT = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0]


def apply(m: list, p: tuple) -> tuple:
    x, y, z = p
    return (m[0] * x + m[1] * y + m[2] * z + m[3], m[4] * x + m[5] * y + m[6] * z + m[7], m[8] * x + m[9] * y + m[10] * z + m[11])


def flatten(src: Source, name: str, memo: dict, studs: bool = True) -> list:
    """A file's triangles in its own frame: [(colour, (v0, v1, v2))], colour 16 where it inherits, wound counter-clockwise."""
    n = norm(name)
    if n in memo:
        return memo[n]
    lines, _, _ = src.resolve(n)
    out = []
    memo[n] = out
    if lines is None:
        src.missing.add(n)
        return out
    for ln in lines:
        if ln[0] == "tri":
            v = ln[2]
            a, b, c = (v[0], v[1], v[2]), (v[3], v[4], v[5]), (v[6], v[7], v[8])
            out.append((16 if ln[1] == 24 else ln[1], (a, c, b) if ln[3] else (a, b, c)))
        else:
            _, col, m, f, invert, _ = ln
            col = 16 if col == 24 else col
            if not studs and re.fullmatch(r"(\d+/)?stud[0-9a-z]*\.dat", norm(f)):
                continue
            flip = invert != (det3(m) < 0)
            for c, (a, b, cc) in flatten(src, f, memo, studs):
                a, b, cc = apply(m, a), apply(m, b), apply(m, cc)
                out.append((col if c == 16 else c, (a, cc, b) if flip else (a, b, cc)))
    return out


class Instance:
    """One leaf part placed in the model."""

    def __init__(self, file: str, matrix: list, colour: int, path: tuple, depth_files: tuple, frames: tuple):
        self.file, self.matrix, self.colour, self.path, self.files, self.frames = file, matrix, colour, path, depth_files, frames
        self.link = None

    @property
    def part(self) -> str:
        return Path(self.file).stem


def walk(src: Source, name: str | None = None, matrix: list = IDENT, colour: int = 16, path: tuple = (), files: tuple = (),
         frames: tuple = ()):
    """Every leaf part (a library part, or an embedded .dat/Part) under `name`, in order, with its world matrix, its colour
    (16 resolved to the nearest real one), its path ((file, line number), ...) from the entry down, and the world frame
    of each file on that path (`frames`, one per entry of `files`, the part's own last)."""
    name = name or src.main
    lines, _, _ = src.resolve(name)
    files = files + (norm(name),)
    frames = frames + (matrix,)
    for ln in lines or []:
        if ln[0] != "sub":
            continue
        _, col, m, f, _inv, no = ln
        col = colour if col in (16, 24) else col
        mm = mmul(matrix, m)
        sub, kind, n = src.resolve(f)
        p = path + ((norm(name), no),)
        if sub is None:
            src.missing.add(n)
            continue
        if n.endswith(".dat") or n not in src.files:
            yield Instance(n, mm, col, p, files + (n,), frames + (mm,))
        else:
            yield from walk(src, n, mm, col, p, files, frames)


def stem(file: str) -> str:
    """A model file's short name: after the last " - ", without its extension ("31313 - track3r.ldr" -> "track3r")."""
    return Path(file.rsplit(" - ", 1)[-1]).stem


def matches(sel, inst: Instance) -> int:
    """How specifically the selector matches the instance (0: not at all, else 1 + the depth of the submodel it names). A list
    of selectors is all of them (the sum of their depths)."""
    if isinstance(sel, list):
        got = [matches(s, inst) for s in sel]
        return 0 if not all(got) else sum(got)
    spec = 1
    if "submodel" in sel:
        key = sel["submodel"].lower()
        hit = [i for i, f in enumerate(inst.files[:-1]) if fnmatch.fnmatchcase(stem(f), key)]
        if "lines" in sel:
            lo, hi = sel["lines"]
            hit = [i for i in hit if lo <= inst.path[i][1] <= hi]
        if not hit:
            return 0
        spec += max(hit) + 1
    elif "lines" in sel:
        raise ValueError(f"a selector with lines needs a submodel: {sel}")
    if "part" in sel and not re.fullmatch(sel["part"], inst.part, re.I):
        return 0
    if "colour" in sel and inst.colour != sel["colour"]:
        return 0
    return spec


def assign(cfg: dict, insts: list) -> None:
    """Give each instance its link (or "" when dropped), per the config's selectors."""
    links = cfg["links"]
    rest = [n for n, s in links.items() if s.get("rest")]
    for inst in insts:
        if any(matches(s, inst) for s in cfg.get("drop", [])):
            inst.link = ""
            continue
        best = (0, -1, None)
        for k, (n, s) in enumerate(links.items()):
            for sel in s.get("include", []):
                sc = matches(sel, inst)
                if sc and (sc, k) > best[:2]:
                    best = (sc, k, n)
        inst.link = best[2] or (rest[0] if rest else None)
        if inst.link is None:
            raise ValueError(f"no link takes {inst.file} at {inst.path}; give one `rest`")




def ros(yaw_deg: float = 0.0, pitch_deg: float = 0.0) -> list:
    """LDraw (x right, y down, z away from the viewer) to the robot frame, rotation only: x = -z, y = x, z = -y; then yaw about
    z, then pitch about y (ROS: positive pitch lowers the nose)."""
    c, s = math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg))
    cp, sp = math.cos(math.radians(pitch_deg)), math.sin(math.radians(pitch_deg))
    yaw = [-s, 0.0, -c, 0.0, c, 0.0, -s, 0.0, 0.0, -1.0, 0.0, 0.0]
    return mmul([cp, 0.0, sp, 0.0, 0.0, 1.0, 0.0, 0.0, -sp, 0.0, cp, 0.0], yaw)


def write_stl(path: Path, tris: list) -> None:
    """Binary STL of [(a, b, c)] points in metres, flat normals from the winding."""
    with open(path, "wb") as fh:
        fh.write(b"robotics-lab from LDraw".ljust(80, b" "))
        fh.write(struct.pack("<I", len(tris)))
        buf = bytearray()
        for a, b, c in tris:
            ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
            vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
            nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
            ln = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
            buf += struct.pack("<12fH", nx / ln, ny / ln, nz / ln, *a, *b, *c, 0)
        fh.write(buf)


def read_stl(path: Path) -> list:
    """The triangles [(a, b, c)] of a binary STL."""
    data = Path(path).read_bytes()
    n = struct.unpack_from("<I", data, 80)[0]
    if len(data) != 84 + 50 * n:
        raise ValueError(f"{path}: not a binary STL ({len(data)} bytes for {n} triangles)")
    out = []
    for i in range(n):
        f = struct.unpack_from("<12f", data, 84 + 50 * i)
        out.append((f[3:6], f[6:9], f[9:12]))
    return out


def unit(v: list) -> list:
    n = math.sqrt(sum(c * c for c in v)) or 1.0
    return [c / n for c in v]


def build(folder: Path, library: Library | None = None, out: Path | None = None, log=print) -> dict:
    """robots/<robot>/kinematics.json and its model to robot.urdf and meshes/. Returns a summary."""
    folder = Path(folder)
    out = Path(out) if out else folder
    cfg = json.loads((folder / "kinematics.json").read_text())
    library = library or Library(DEFAULT_LIBRARY)
    src = Source(folder / cfg["source"], library, cfg.get("entry"), cfg.get("detail", "low"))
    src.missing = set()
    studs = cfg.get("studs", True)
    insts = list(walk(src))
    assign(cfg, insts)
    to_robot = mmul([LDU, 0.0, 0.0, 0.0, 0.0, LDU, 0.0, 0.0, 0.0, 0.0, LDU, 0.0], ros(cfg.get("yaw_deg", 0.0), cfg.get("pitch_deg", 0.0)))
    memo = {}
    geom = {}                                                   # link -> colour -> [tri in robot frame, metres, before the shift]
    n_parts = {}
    for inst in insts:
        if not inst.link:
            continue
        n_parts[inst.link] = n_parts.get(inst.link, 0) + 1
        m = mmul(to_robot, inst.matrix)
        flip = det3(m) < 0
        dst = geom.setdefault(inst.link, {})
        for c, (a, b, cc) in flatten(src, inst.file, memo, studs):
            a, b, cc = apply(m, a), apply(m, b), apply(m, cc)
            dst.setdefault(inst.colour if c == 16 else c, []).append((a, cc, b) if flip else (a, b, cc))
    root = cfg["root"]
    allpts = [p for cols in geom.values() for tris in cols.values() for t in tris for p in t]
    zmin = min(p[2] for p in allpts)
    rp = [p for tris in geom[root].values() for t in tris for p in t]
    lo = [min(p[i] for p in rp) for i in range(3)]
    hi = [max(p[i] for p in rp) for i in range(3)]
    root_origin = [(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2]
    root_origin[2] = (lo[2] + hi[2]) / 2

    def world(p):                                               # the robot frame of the model: lowest point on z = 0, root bbox centre at the origin xy
        return (p[0] - root_origin[0], p[1] - root_origin[1], p[2] - zmin)

    stand_z = root_origin[2] - zmin
    pivots = {root: (0.0, 0.0, stand_z)}
    axes = {}
    for j in cfg.get("joints", []):
        ax = j.get("axis")
        if ax is None:
            if j["type"] != "fixed":
                raise ValueError(f"joint {j['name']}: a {j['type']} joint needs an axis")
            pivots[j["child"]], axes[j["name"]] = None, [0.0, 0.0, 1.0]
            continue
        if "part" in ax or "frame" in ax:
            if "part" in ax:
                cand = [i for i in insts if matches(ax["part"], i)]
                frame = (lambda i: i.matrix)
            else:
                key = ax["frame"].lower()
                cand = [i for i in insts if any(fnmatch.fnmatchcase(stem(f), key) for f in i.files[:-1])
                        and ("within" not in ax or matches(ax["within"], i))]
                frame = (lambda i: i.frames[next(k for k, f in enumerate(i.files[:-1]) if fnmatch.fnmatchcase(stem(f), key))])
            if not cand:
                raise ValueError(f"joint {j['name']}: nothing matches {ax.get('part') or ax['frame']}")
            fm = frame(cand[0])
            org = apply(fm, tuple(ax.get("origin", [0.0, 0.0, 0.0])))
            d = ax.get("dir")
            dr = None if d is None else (fm[0] * d[0] + fm[1] * d[1] + fm[2] * d[2], fm[4] * d[0] + fm[5] * d[1] + fm[6] * d[2],
                                         fm[8] * d[0] + fm[9] * d[1] + fm[10] * d[2])
        else:
            org, dr = tuple(ax["ldraw_origin"]), tuple(ax["ldraw_dir"])
        pivots[j["child"]] = world(apply(to_robot, org))
        if "robot_dir" in ax:
            axes[j["name"]] = unit(ax["robot_dir"])
        else:
            axes[j["name"]] = unit([to_robot[0] * dr[0] + to_robot[1] * dr[1] + to_robot[2] * dr[2],
                                    to_robot[4] * dr[0] + to_robot[5] * dr[1] + to_robot[6] * dr[2],
                                    to_robot[8] * dr[0] + to_robot[9] * dr[1] + to_robot[10] * dr[2]])
    for j in cfg.get("joints", []):                              # a fixed joint without a pivot of its own sits at its parent's
        if pivots[j["child"]] is None:
            pivots[j["child"]] = pivots[j["parent"]]
    missing = [n for n in cfg["links"] if n != root and n not in pivots]
    if missing:
        raise ValueError(f"links without a joint: {missing}")
    (out / "meshes").mkdir(parents=True, exist_ok=True)
    for old in (out / "meshes").glob("*.stl"):
        old.unlink()
    links_xml, summary = [], {"links": {}, "parts": len(insts), "dropped": sum(1 for i in insts if not i.link), "missing": sorted(src.missing)}
    order = [root] + [n for n in cfg["links"] if n != root]
    for name in order:
        vis = []
        cols = geom.get(name, {})
        piv = pivots[name]
        total = 0
        lo2 = [1e9] * 3
        hi2 = [-1e9] * 3
        for col, tris in sorted(cols.items(), key=lambda kv: -len(kv[1])):
            local = []
            for t in tris:
                w = [world(p) for p in t]
                local.append(tuple((q[0] - piv[0], q[1] - piv[1], q[2] - piv[2]) for q in w))
                for q in w:
                    for i in range(3):
                        lo2[i], hi2[i] = min(lo2[i], q[i]), max(hi2[i], q[i])
            r, g, b, a = library.rgba(col)
            fn = f"meshes/{name}_c{col}.stl"
            write_stl(out / fn, local)
            total += len(local)
            vis.append(f'    <visual>\n      <origin xyz="0 0 0" rpy="0 0 0"/>\n      <geometry><mesh filename="{fn}"/></geometry>\n'
                       f'      <material name="{name}_c{col}"><color rgba="{r:.3f} {g:.3f} {b:.3f} {a:.3f}"/></material>\n    </visual>\n')
        links_xml.append(f'  <link name="{name}">\n{"".join(vis)}  </link>\n')
        summary["links"][name] = {"parts": n_parts.get(name, 0), "triangles": total, "colours": len(cols),
                                  "bbox_m": [round(h - l, 4) for l, h in zip(lo2, hi2)] if total else None}
    joints_xml = []
    for j in cfg.get("joints", []):
        par, ch = pivots[j["parent"]], pivots[j["child"]]
        o = [ch[i] - par[i] for i in range(3)]
        ax = axes[j["name"]]
        lim = ""
        if j["type"] == "revolute":
            lo_, hi_ = j["limit"]
            lim = f'\n    <limit lower="{lo_:.6f}" upper="{hi_:.6f}" effort="1" velocity="10"/>'
        joints_xml.append(f'  <joint name="{j["name"]}" type="{j["type"]}">\n    <parent link="{j["parent"]}"/><child link="{j["child"]}"/>\n'
                          f'    <origin xyz="{o[0]:.6f} {o[1]:.6f} {o[2]:.6f}" rpy="0 0 0"/>\n    <axis xyz="{ax[0]:.6f} {ax[1]:.6f} {ax[2]:.6f}"/>{lim}\n  </joint>\n')
    (out / "robot.urdf").write_text(f'<?xml version="1.0"?>\n<!-- Generated by robots/ldraw/from_ldraw.py from {cfg["source"]}; do not edit. -->\n'
                                    f'<robot name="{cfg.get("name", folder.name)}">\n{"".join(links_xml)}{"".join(joints_xml)}</robot>\n')
    summary["stand_z"] = round(stand_z, 4)
    summary["size_m"] = [round(max(p[i] for p in map(world, allpts)) - min(p[i] for p in map(world, allpts)), 4) for i in range(3)]
    return summary


def tree(folder: Path, library: Library | None = None, log=print) -> None:
    """Print every part: its link, its place, its path. For writing kinematics.json."""
    folder = Path(folder)
    cfg = json.loads((folder / "kinematics.json").read_text())
    library = library or Library(DEFAULT_LIBRARY)
    src = Source(folder / cfg["source"], library, cfg.get("entry"), cfg.get("detail", "low"))
    src.missing = set()
    insts = list(walk(src))
    try:
        assign(cfg, insts)
    except ValueError:
        pass
    for i in insts:
        m = i.matrix
        steps = " > ".join(f"{f}:{no}" for f, no in i.path)
        lines = library.index.get(i.file)
        what = lines.read_text(errors="replace").splitlines()[0][2:42] if lines else ""
        log(f"{i.link if i.link is not None else '?':10} {i.part:12} c{i.colour:<4} ({m[3]:8.1f} {m[7]:8.1f} {m[11]:8.1f})  {what:40}  {steps}")


def main(argv: list) -> int:
    lib = DEFAULT_LIBRARY
    if "--library" in argv:
        k = argv.index("--library")
        lib = Path(argv[k + 1]).expanduser()
        del argv[k:k + 2]
    show = "--tree" in argv
    argv = [a for a in argv if a != "--tree"]
    if not argv:
        print(__doc__)
        return 2
    library = Library(lib)
    for name in argv:
        folder = Path(name) if Path(name).is_dir() else HERE.parent / name
        if show:
            tree(folder, library)
            continue
        s = build(folder, library)
        print(f"{folder.name}: {s['parts']} parts ({s['dropped']} dropped), size {s['size_m']} m, stand_z {s['stand_z']} m, "
              f"missing {s['missing'] or 'none'}")
        for n, v in s["links"].items():
            print(f"  {n:16} parts {v['parts']:4} triangles {v['triangles']:7} colours {v['colours']:2} bbox {v['bbox_m']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
