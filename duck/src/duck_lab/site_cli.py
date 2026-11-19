"""duck-site: the sites the operator keeps (RFC-0016 revision 3), the command around the world model's `Site`.

It lives in the duck's package, not the world model's, because `sim-areas` draws the simulated apartment's rooms
(`nav.rooms`) and places them with the navigator's frames; the world model knows no robot."""

import argparse
import json
import os
import sys
from pathlib import Path

from duck_lab.nav.frames import compose, inverse
from duck_lab.nav.rooms import ROOMS
from worldmodel.objects import load_kinds
from worldmodel.site import Site

# the operator's data, not the repository's (git-ignored); DUCK_SITES for another folder (a container's volume)
SITES = Path(os.environ.get("DUCK_SITES", Path(__file__).resolve().parents[2] / "sites"))


def main() -> None:
    """duck-site: the sites the operator keeps (until Mission Control's site library, RFC-0014)."""
    ap = argparse.ArgumentParser(description=main.__doc__)
    ap.add_argument("--sites", type=Path, default=SITES)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create", help="a new site: duck-site create home --name Home --kind apartment")
    c.add_argument("id")
    c.add_argument("--name", required=True)
    c.add_argument("--kind", required=True, help="apartment, office, warehouse, garden, ...")
    sub.add_parser("list", help="the sites")
    s = sub.add_parser("show", help="a site's objects")
    s.add_argument("id")
    n = sub.add_parser("name", help="name an object: duck-site name home fridge_1 'the big fridge'")
    n.add_argument("id")
    n.add_argument("object")
    n.add_argument("label")
    a = sub.add_parser("area", help="draw an area: duck-site area home --name Kitchen --type kitchen "
                                    "--outline '0,0 2,0 2,1.5 0,1.5' (site frame, metres)")
    a.add_argument("id")
    a.add_argument("--name", required=True)
    a.add_argument("--type", help="kitchen, bedroom, office, ... (optional)")
    a.add_argument("--outline", required=True, help="x,y points in order, separated by spaces")
    sa = sub.add_parser("sim-areas", help="the simulated apartment's six rooms as a site's areas, as the operator "
                                          "would draw them at home (the scoreboard's outlines, moved into the site frame "
                                          "by a run's start.json)")
    sa.add_argument("id")
    sa.add_argument("--start", type=Path, required=True, help="a run's start.json (the dock: map and truth)")
    args = ap.parse_args()
    kinds = load_kinds()
    if args.cmd == "create":
        try:
            site = Site.create(args.sites, args.id, args.name, args.kind, kinds)
        except FileExistsError as e:
            sys.exit(str(e))
        print(f"site {site.sid} ({site.name}, {site.kind}) at {site.folder}")
    elif args.cmd == "list":
        for meta in sorted(args.sites.glob("*/site.json")):
            m = json.loads(meta.read_text())
            print(f"{m['id']}: {m['name']} ({m['kind']})")
    elif args.cmd == "show":
        site = Site.load(args.sites, args.id, kinds)
        print(f"{site.sid}: {site.name} ({site.kind}), {len(site.areas)} areas, {len(site.semantic.objects)} objects")
        for ar in site.areas:
            print(f"  area {ar.aid}: {ar.name}" + (f" ({ar.type})" if ar.type else "") + f", {len(ar.polygon)} points")
        for o in sorted(site.semantic.objects, key=lambda o: o.oid):
            print(f"  {o.oid:20s} {o.kind:14s} ({o.x:+.2f}, {o.y:+.2f}) seen {o.n}"
                  + (f'  "{o.label}"' if o.label else "") + ("  pinned" if o.pinned else ""))
    elif args.cmd == "name":
        site = Site.load(args.sites, args.id, kinds)
        try:
            site.name_object(args.object, args.label)
        except KeyError as e:
            sys.exit(str(e))
        site.save()
        print(f'{args.object} at {site.sid} is now "{args.label}"')
    elif args.cmd == "area":
        site = Site.load(args.sites, args.id, kinds)
        try:
            outline = [tuple(float(v) for v in p.split(",")) for p in args.outline.split()]
            area = site.add_area(args.name, outline, args.type)
        except ValueError as e:
            sys.exit(str(e))
        site.save()
        print(f"area {area.aid} {area.name} at {site.sid}")
    elif args.cmd == "sim-areas":
        site = Site.load(args.sites, args.id, kinds)
        st = json.loads(args.start.read_text())
        map_from_world = compose(tuple(st["map"]), inverse(tuple(st["truth"])))
        for room, (x0, x1, y0, y1) in ROOMS.items():
            corners = [compose(map_from_world, (x, y, 0.0))[:2] for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
            try:
                site.add_area(room, corners, room)
            except ValueError as e:
                print(f"skipped {room}: {e}")
        site.save()
        print(f"{site.sid}: {len(site.areas)} areas")


if __name__ == "__main__":
    main()
