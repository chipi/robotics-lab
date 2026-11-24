"""Colour maths for the token checks (standard library only): sRGB, WCAG contrast, OKLab/OKLCH (Ottosson 2020), colour-blind simulation
(Machado 2009, severity 1.0, applied in linear RGB). Used by test_tokens.py; the token values were derived with the same functions."""

import math
import re

PROTAN = ((0.152286, 1.052583, -0.204868), (0.114503, 0.786281, 0.099216), (-0.003882, -0.048116, 1.051998))
DEUTAN = ((0.367322, 0.860646, -0.227968), (0.280085, 0.672501, 0.047413), (-0.011820, 0.042940, 0.968881))


def parse(c: str):
    """'#rgb', '#rrggbb', '#rrggbbaa' or 'rgba(r, g, b, a)' -> (r, g, b, a) with r, g, b in 0..255 and a in 0..1."""
    c = c.strip()
    m = re.fullmatch(r"#([0-9a-fA-F]{3,8})", c)
    if m:
        h = m.group(1)
        if len(h) in (3, 4):
            h = "".join(ch * 2 for ch in h)
        if len(h) not in (6, 8):
            raise ValueError(c)
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), (int(h[6:8], 16) / 255 if len(h) == 8 else 1.0)
    m = re.fullmatch(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)", c)
    if m:
        return float(m.group(1)), float(m.group(2)), float(m.group(3)), float(m.group(4) or 1)
    raise ValueError(f"not a colour: {c}")


def over(fg: str, bg: str):
    """fg composited over an opaque bg -> (r, g, b) 0..255 floats."""
    r, g, b, a = parse(fg)
    br, bg_, bb, _ = parse(bg)
    return (r * a + br * (1 - a), g * a + bg_ * (1 - a), b * a + bb * (1 - a))


def to_lin(v):
    v /= 255
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def from_lin(v):
    v = max(0.0, min(1.0, v))
    return 255 * (12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055)


def lin(rgb):
    return tuple(to_lin(v) for v in rgb[:3])


def hexof(rgb):
    return "#" + "".join(f"{round(max(0, min(255, v))):02x}" for v in rgb[:3])


def luminance(rgb):
    r, g, b = lin(rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(fg_rgb, bg_rgb):
    a, b = luminance(fg_rgb), luminance(bg_rgb)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def oklab_from_lin(l3):
    r, g, b = l3
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l, m, s = (math.copysign(abs(x) ** (1 / 3), x) for x in (l, m, s))
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s)


def lin_from_oklab(lab):
    L, a, b = lab
    l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
            -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
            -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)


def oklab(rgb):
    return oklab_from_lin(lin(rgb))


def oklch_to_rgb(L, C, h, fit=True):
    """OKLCH -> sRGB 0..255; when out of gamut the chroma is reduced (hue and lightness kept)."""
    def conv(c):
        a, b = c * math.cos(math.radians(h)), c * math.sin(math.radians(h))
        return lin_from_oklab((L, a, b))
    lo, hi = 0.0, C
    rgb = conv(C)
    if fit and not all(-1e-4 <= v <= 1 + 1e-4 for v in rgb):
        for _ in range(40):
            mid = (lo + hi) / 2
            if all(-1e-4 <= v <= 1 + 1e-4 for v in conv(mid)):
                lo = mid
            else:
                hi = mid
        rgb = conv(lo)
    return tuple(from_lin(v) for v in rgb)


def delta_e(a_rgb, b_rgb):
    """Euclidean distance in OKLab (about 0.02 is a just-noticeable difference)."""
    x, y = oklab(a_rgb), oklab(b_rgb)
    return math.dist(x, y)


def simulate(rgb, matrix):
    r, g, b = lin(rgb)
    out = tuple(row[0] * r + row[1] * g + row[2] * b for row in matrix)
    return tuple(from_lin(v) for v in out)
