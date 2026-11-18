"""A site and its semantic map kept between runs (RFC-0016 revision 3; the operator, 2026-11-18: "B yes", sites and
areas, not homes).

A site is a named place robots work in (its kind: apartment, office, ...), with a site frame. In the simulator every run
starts at the dock, so a run's map frame is the site frame and a run's objects can be merged into the site's stored map
directly; at a real site the robot must first recognise where it is (later). Until Mission Control stores sites
(RFC-0014), a site is a folder: site.json (id, name, kind) and semantic_map.json.

Merging a run's map into the site's: each run object is matched to a stored object of the same kind by the semantic
map's association rule (ASSOC_M, UNIQUE_M for unique kinds); a match keeps the stored id, label and pins and takes the
run's position and sightings; no match is a new object with the next stable id. Stored objects not seen in the run
stay (forgetting the unseen is not built: RFC-0016 §4). An object the operator named is never merged into another.
"""

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from duck_lab.world_model.objects import load_kinds
from duck_lab.world_model.semantic_map import ASSOC_M, UNIQUE_M, SemanticMap

# the operator's data, not the repository's (git-ignored); DUCK_SITES for another folder (a container's volume)
SITES = Path(os.environ.get("DUCK_SITES", Path(__file__).resolve().parents[3] / "sites"))


@dataclass
class Site:
    sid: str
    name: str
    kind: str
    folder: Path
    semantic: SemanticMap = field(default=None)

    @classmethod
    def create(cls, root: Path, sid: str, name: str, kind: str, kinds: dict) -> "Site":
        folder = Path(root) / sid
        if (folder / "site.json").exists():
            raise FileExistsError(f"site {sid} exists: {folder}")
        site = cls(sid, name, kind, folder, SemanticMap(kinds, site_kind=kind))
        site.save()
        return site

    @classmethod
    def load(cls, root: Path, sid: str, kinds: dict) -> "Site":
        folder = Path(root) / sid
        meta = json.loads((folder / "site.json").read_text())
        sem = folder / "semantic_map.json"
        semantic = (SemanticMap.from_json(json.loads(sem.read_text()), kinds, site_kind=meta["kind"]) if sem.exists()
                    else SemanticMap(kinds, site_kind=meta["kind"]))
        return cls(meta["id"], meta["name"], meta["kind"], folder, semantic)

    def save(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / "site.json").write_text(json.dumps({"id": self.sid, "name": self.name, "kind": self.kind},
                                                          indent=1))
        (self.folder / "semantic_map.json").write_text(json.dumps(self.semantic.to_json(), indent=1))

    def merge(self, run: SemanticMap) -> dict:
        """Merge a run's confirmed objects into the site's map (the module's doc). Returns {"matched", "added"}."""
        matched, added = 0, 0
        taken = set()
        for o in run.confirmed():
            gate = UNIQUE_M if self.semantic.kinds.get(o.kind, {}).get("unique") else ASSOC_M
            same = [s for s in self.semantic.objects if s.kind == o.kind and s.oid not in taken
                    and math.dist((s.x, s.y), (o.x, o.y)) <= gate]
            if same:
                s = min(same, key=lambda s: math.dist((s.x, s.y), (o.x, o.y)))
                taken.add(s.oid)
                s.parts = [q.shifted(o.x - s.x, o.y - s.y) for q in s.parts]
                s.x, s.y, s.n = o.x, o.y, s.n + o.n
                s.last_t, s.confidence = o.last_t, max(s.confidence, o.confidence)
                s.sources = sorted(set(s.sources) | set(o.sources))
                s.evidence = (s.evidence + o.evidence)[-3:]
                matched += 1
            else:
                o.oid = self.semantic.new_id(o.kind)
                o.label, o.named_by, o.pinned = None, None, False
                self.semantic.objects.append(o)
                taken.add(o.oid)
                added += 1
        return {"matched": matched, "added": added}

    def name_object(self, oid: str, label: str, by: str = "operator") -> None:
        """The operator names an object ("my desk"): the label, who named it, and a pin (never merged away)."""
        o = next((x for x in self.semantic.objects if x.oid == oid), None)
        if o is None:
            raise KeyError(f"no object {oid} at site {self.sid}")
        o.label, o.named_by, o.pinned = label, by, True


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
        print(f"{site.sid}: {site.name} ({site.kind}), {len(site.semantic.objects)} objects")
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


if __name__ == "__main__":
    main()
