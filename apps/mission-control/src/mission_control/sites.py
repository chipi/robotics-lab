"""Sites, areas and the site's objects (RFC-0014 §3.5). A site is a named place with a kind and a frame;
its areas are polygons the OPERATOR draws (nothing here creates one on a robot's say-so); its objects
carry Mission Control's own stable ids, merged in from the runs that see them."""

import math
import re
import time

from . import geometry, guardrails
from .errors import ApiError, conflict, invalid, not_found
from .store import dumps, loads

# RFC-0016 / semantic_map.py: a detection this close to an object of its kind is that object; for a
# kind a site has one of (the fridge) the gate is wider, because the belief drifts between sightings.
ASSOC_M = 0.5
UNIQUE_M = 1.5
POSITION_BLEND = 0.3
MAX_EVIDENCE = 5
EXPORT_FORMAT = "mission-control-site"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "x"


def _name(value, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise invalid(f"{what} must be a non-empty string")
    return value.strip()


class Sites:
    def __init__(self, store, wall=time.time):
        self.store = store
        self._wall = wall

    # --- sites ---------------------------------------------------------------------------------

    def create(self, name, kind) -> dict:
        name, kind = _name(name, "name"), _name(kind, "kind")
        with self.store.transaction():
            self._unique_site_name(name)
            ids = {r["id"] for r in self.store.all("SELECT id FROM sites")}
            sid, n = _slug(name), 1
            while sid in ids:
                n += 1
                sid = f"{_slug(name)}-{n}"
            now = self._wall()
            self.store.execute("INSERT INTO sites (id, name, kind, created_at, updated_at) VALUES (?,?,?,?,?)",
                               (sid, name, kind, now, now))
        return self.get(sid)

    def _unique_site_name(self, name: str, except_id: str | None = None) -> None:
        for r in self.store.all("SELECT id, name FROM sites WHERE retired = 0"):
            if r["name"].lower() == name.lower() and r["id"] != except_id:
                raise conflict("name_taken", f"a site called {r['name']!r} exists")

    def _row(self, sid: str, *, retired_ok: bool = False) -> dict:
        row = self.store.one("SELECT * FROM sites WHERE id = ?", (sid,))
        if row is None or (row["retired"] and not retired_ok):
            raise not_found("site", sid)
        return row

    def get(self, sid: str) -> dict:
        row = self._row(sid)
        return {
            "id": row["id"], "name": row["name"], "kind": row["kind"], "frame": row["frame"],
            "dock_pose": loads(row["dock_pose"]),
            "counts": {
                "areas": self.store.one("SELECT COUNT(*) AS n FROM areas WHERE site_id = ?", (sid,))["n"],
                "objects": self.store.one("SELECT COUNT(*) AS n FROM objects WHERE site_id = ?", (sid,))["n"],
                "labelled": self.store.one("SELECT COUNT(*) AS n FROM objects WHERE site_id = ? AND label IS NOT NULL",
                                           (sid,))["n"],
            },
        }

    def list(self) -> list:
        return [self.get(r["id"]) for r in self.store.all("SELECT id FROM sites WHERE retired = 0 ORDER BY created_at, rowid")]

    def update(self, sid: str, name=None, kind=None) -> dict:
        row = self._row(sid)
        name = _name(name, "name") if name is not None else row["name"]
        kind = _name(kind, "kind") if kind is not None else row["kind"]
        self._unique_site_name(name, sid)
        self.store.execute("UPDATE sites SET name = ?, kind = ?, updated_at = ? WHERE id = ?", (name, kind, self._wall(), sid))
        return self.get(sid)

    def retire(self, sid: str) -> None:
        self._row(sid)
        robots = [r["robot_id"] for r in self.store.all("SELECT robot_id FROM robot_sites WHERE site_id = ?", (sid,))]
        if robots:
            raise conflict("site_in_use", f"robots are at this site: {', '.join(robots)}", robots=robots)
        self.store.execute("UPDATE sites SET retired = 1, updated_at = ? WHERE id = ?", (self._wall(), sid))

    def set_dock_if_unset(self, sid: str, pose: dict) -> None:
        """The first run at a site sets the site frame from where it starts (§3.5.1)."""
        if self._row(sid)["dock_pose"] is None:
            self.store.execute("UPDATE sites SET dock_pose = ? WHERE id = ?", (dumps(pose), sid))

    # --- the robot's site ----------------------------------------------------------------------

    def robot_site(self, robot_id: str) -> str | None:
        row = self.store.one("SELECT site_id FROM robot_sites WHERE robot_id = ?", (robot_id,))
        return row["site_id"] if row else None

    def assign_robot(self, robot_id: str, sid: str | None) -> None:
        """A robot is at one site at a time (§3.1.1)."""
        if sid is None:
            self.store.execute("DELETE FROM robot_sites WHERE robot_id = ?", (robot_id,))
            return
        self._row(sid)
        self.store.execute("INSERT INTO robot_sites (robot_id, site_id) VALUES (?, ?) "
                           "ON CONFLICT(robot_id) DO UPDATE SET site_id = excluded.site_id", (robot_id, sid))

    # --- areas: the operator's ----------------------------------------------------------------

    def _area_view(self, row: dict, objects=None) -> dict:
        view = {"id": row["id"], "site": row["site_id"], "name": row["name"], "type": row["type"],
                "outline": loads(row["outline"]), "frame": "site"}
        if objects is not None:
            view["objects"] = [o["id"] for o in objects if o["area"] == row["id"]]
        return view

    def _area_rows(self, sid: str) -> list:
        return self.store.all("SELECT * FROM areas WHERE site_id = ? ORDER BY created_at, rowid", (sid,))

    def areas(self, sid: str) -> list:
        self._row(sid)
        objects = self.objects(sid)
        return [self._area_view(r, objects) for r in self._area_rows(sid)]

    def area(self, sid: str, ref: str) -> dict:
        """By id, else by name (case-insensitive)."""
        self._row(sid)
        rows = self._area_rows(sid)
        for r in rows:
            if r["id"] == ref:
                return self._area_view(r)
        for r in rows:
            if r["name"].lower() == str(ref).lower():
                return self._area_view(r)
        raise not_found("area", ref)

    def _check_area_name(self, sid: str, name: str, except_id: str | None = None) -> None:
        for r in self._area_rows(sid):
            if r["name"].lower() == name.lower() and r["id"] != except_id:
                raise conflict("name_taken", f"this site has an area called {r['name']!r}")

    def create_area(self, sid: str, name, type_, outline) -> dict:
        self._row(sid)
        name = _name(name, "name")
        if type_ is not None:
            type_ = _name(type_, "type")
        try:
            outline = geometry.clean_outline(outline)
        except geometry.GeometryError as exc:
            raise invalid(str(exc), "bad_outline") from None
        with self.store.transaction():
            self._check_area_name(sid, name)
            ids = {r["id"] for r in self._area_rows(sid)} | {"at"}  # GET .../areas/at is the point query
            aid, n = _slug(name), 1
            while aid in ids:
                n += 1
                aid = f"{_slug(name)}-{n}"
            now = self._wall()
            self.store.execute("INSERT INTO areas (site_id, id, name, type, outline, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                               (sid, aid, name, type_, dumps(outline), now, now))
        return self.area(sid, aid)

    def update_area(self, sid: str, ref: str, changes: dict) -> dict:
        row = self.area(sid, ref)
        extra = set(changes) - {"name", "type", "outline"}
        if extra:
            raise invalid(f"an area's name, type and outline can change, not {sorted(extra)}")
        name = _name(changes["name"], "name") if "name" in changes else row["name"]
        type_ = row["type"]
        if "type" in changes:
            type_ = None if changes["type"] is None else _name(changes["type"], "type")
        outline = row["outline"]
        if "outline" in changes:
            try:
                outline = geometry.clean_outline(changes["outline"])
            except geometry.GeometryError as exc:
                raise invalid(str(exc), "bad_outline") from None
        self._check_area_name(sid, name, row["id"])
        self.store.execute("UPDATE areas SET name = ?, type = ?, outline = ?, updated_at = ? WHERE site_id = ? AND id = ?",
                           (name, type_, dumps(outline), self._wall(), sid, row["id"]))
        return self.area(sid, row["id"])

    def _guardrail_areas(self, sid: str) -> set:
        return {g["area"] for g in self.guardrails(sid) if g["name"] == "no_go_area"}

    def delete_area(self, sid: str, ref: str) -> None:
        row = self.area(sid, ref)
        if row["id"] in self._guardrail_areas(sid):
            raise conflict("area_in_use", f"{row['name']} is a no-go area of this site's guardrails")
        self.store.execute("DELETE FROM areas WHERE site_id = ? AND id = ?", (sid, row["id"]))

    def merge_areas(self, sid: str, ref: str, other_ref: str, changes: dict | None = None) -> dict:
        """The other area is folded into the first: its outline becomes the convex hull of both, or the
        `outline` given. Merging into a no-go area is allowed; merging one away is not."""
        keep, gone = self.area(sid, ref), self.area(sid, other_ref)
        if keep["id"] == gone["id"]:
            raise invalid("an area cannot merge with itself")
        if gone["id"] in self._guardrail_areas(sid):
            raise conflict("area_in_use", f"{gone['name']} is a no-go area of this site's guardrails")
        changes = dict(changes or {})
        changes.setdefault("outline", geometry.convex_hull(keep["outline"] + gone["outline"]))
        with self.store.transaction():
            self.store.execute("DELETE FROM areas WHERE site_id = ? AND id = ?", (sid, gone["id"]))
            return self.update_area(sid, keep["id"], changes)

    def split_area(self, sid: str, ref: str, line, name_new, name_kept=None) -> list:
        """Cut an area by a line [[x, y], [x, y]]. The area keeps the half on the left of the directed
        line, a new area called `name_new` takes the right. An area that a guardrail names is not split:
        the new half would not be bound by it."""
        row = self.area(sid, ref)
        if row["id"] in self._guardrail_areas(sid):
            raise conflict("area_in_use", f"{row['name']} is a no-go area of this site's guardrails")
        if not (isinstance(line, list) and len(line) == 2 and all(isinstance(p, list) and len(p) == 2 for p in line)):
            raise invalid("line is [[x, y], [x, y]]")
        try:
            left, right = geometry.split_polygon(row["outline"], line[0], line[1])
            left, right = geometry.clean_outline(left), geometry.clean_outline(right)
        except geometry.GeometryError as exc:
            raise invalid(str(exc), "bad_outline") from None
        with self.store.transaction():
            kept = self.update_area(sid, row["id"], {"outline": left, **({"name": name_kept} if name_kept else {})})
            new = self.create_area(sid, name_new, row["type"], right)
        return [kept, new]

    def area_at(self, sid: str, x: float, y: float) -> dict | None:
        """The area that holds a point of the site frame; of nested areas, the smallest. None: no area
        is defined there (§3.5.3)."""
        self._row(sid)
        best = None
        for r in self._area_rows(sid):
            outline = loads(r["outline"])
            if geometry.point_in_polygon([x, y], outline):
                size = geometry.area(outline)
                if best is None or size < best[0]:
                    best = (size, r)
        return self._area_view(best[1]) if best else None

    # --- guardrails: the site's ---------------------------------------------------------------

    def guardrails(self, sid: str) -> list:
        return loads(self._row(sid)["guardrails"])

    def set_guardrails(self, sid: str, entries) -> list:
        """The site's guardrails, including its no-go areas; an area is stored by id."""
        self._row(sid)
        out = []
        for g in guardrails.normalise_list(entries):
            if g["name"] == "no_go_area":
                g = {"name": "no_go_area", "area": self.area(sid, g["area"])["id"]}
            if g not in out:
                out.append(g)
        self.store.execute("UPDATE sites SET guardrails = ?, updated_at = ? WHERE id = ?", (dumps(out), self._wall(), sid))
        return out

    # --- objects -------------------------------------------------------------------------------

    def _object_view(self, row: dict, areas=None) -> dict:
        areas = areas if areas is not None else self._area_rows(row["site_id"])
        holder = None
        for a in areas:
            outline = loads(a["outline"])
            if geometry.point_in_polygon([row["x"], row["y"]], outline):
                size = geometry.area(outline)
                if holder is None or size < holder[0]:
                    holder = (size, a["id"])
        return {
            "id": row["id"], "kind": row["kind"], "label": row["label"], "x": row["x"], "y": row["y"], "frame": "site",
            "parts": loads(row["parts"]), "confirmed": bool(row["confirmed"]), "landmark": row["landmark"],
            "permanence": row["permanence"], "confidence": row["confidence"], "n": row["n"],
            "unique": bool(row["unique_kind"]), "first_seen": row["first_seen"], "last_seen": row["last_seen"],
            "seen_by": loads(row["seen_by"]), "evidence": loads(row["evidence"]),
            "area": holder[1] if holder else None,
        }

    def objects(self, sid: str) -> list:
        self._row(sid)
        areas = self._area_rows(sid)
        rows = self.store.all("SELECT * FROM objects WHERE site_id = ? ORDER BY first_seen, rowid", (sid,))
        return [self._object_view(r, areas) for r in rows]

    def object(self, sid: str, oid: str) -> dict:
        self._row(sid)
        row = self.store.one("SELECT * FROM objects WHERE site_id = ? AND id = ?", (sid, oid))
        if row is None:
            raise not_found("object", oid)
        return self._object_view(row)

    def label(self, sid: str, oid: str, label) -> dict:
        """The operator names an object ("this is my desk"). A label is unique in the site."""
        self.object(sid, oid)
        if label is not None:
            label = _name(label, "label")
            for o in self.objects(sid):
                if o["label"] and o["label"].lower() == label.lower() and o["id"] != oid:
                    raise conflict("label_taken", f"{o['id']} is already called {o['label']!r}")
        self.store.execute("UPDATE objects SET label = ? WHERE site_id = ? AND id = ?", (label, sid, oid))
        return self.object(sid, oid)

    def inventory(self, sid: str) -> dict:
        """The confirmed objects by area, with sightings and confidence (§3.2.1)."""
        areas = self.areas(sid)
        confirmed = [o for o in self.objects(sid) if o["confirmed"]]
        brief = lambda o: {k: o[k] for k in ("id", "kind", "label", "x", "y", "n", "confidence", "landmark", "seen_by")}
        by_area = [{"area": a["id"], "name": a["name"], "objects": [brief(o) for o in confirmed if o["area"] == a["id"]]}
                   for a in areas]
        none = [brief(o) for o in confirmed if o["area"] is None]
        return {"site": sid, "frame": "site", "areas": by_area, "none_defined": none, "confirmed": len(confirmed)}

    # --- export and import (§3.2.1, §3.5.2): the operator's work as a file -------------------------

    def export_site(self, sid: str) -> dict:
        """The site, the operator's areas, its labelled objects and its guardrails, as one JSON document
        to keep in a file, diff and back up. What a robot saw and nobody named is not in it: it is the
        runs' to find again. No-go areas are by area name, so the file does not depend on ids."""
        site = self.get(sid)
        areas = self.areas(sid)
        names = {a["id"]: a["name"] for a in areas}
        guards = [{"name": "no_go_area", "area": names[g["area"]]} if g["name"] == "no_go_area" else g
                  for g in self.guardrails(sid)]
        return {
            "format": EXPORT_FORMAT, "version": 1,
            "site": {"name": site["name"], "kind": site["kind"], "frame": "site", "dock_pose": site["dock_pose"]},
            "areas": [{"name": a["name"], "type": a["type"], "outline": a["outline"]} for a in areas],
            "objects": [{"id": o["id"], "kind": o["kind"], "label": o["label"], "x": o["x"], "y": o["y"],
                         "parts": o["parts"], "landmark": o["landmark"], "unique": o["unique"],
                         "confidence": o["confidence"]} for o in self.objects(sid) if o["label"]],
            "guardrails": guards,
        }

    def import_site(self, sid: str, bundle) -> dict:
        """Merge an export into this site, all or nothing. An area of the same name has its type and outline
        replaced, a new name is created. A labelled object joins the object of its kind within the
        association gate when there is one that has no label (it takes the name), else becomes a new,
        confirmed object; a label that another object here already has is skipped and reported.
        The file's guardrails are added to the site's. The file's site name, kind and dock are not
        applied: the site is the one imported into."""
        self._row(sid)
        if not isinstance(bundle, dict) or bundle.get("format") != EXPORT_FORMAT:
            raise invalid(f"not a Mission Control site file: format is {EXPORT_FORMAT!r}", "bad_bundle")
        if bundle.get("version") != 1:
            raise invalid(f"site file version {bundle.get('version')!r}: this build reads 1", "bad_bundle")
        areas, objects = bundle.get("areas", []), bundle.get("objects", [])
        if not isinstance(areas, list) or not isinstance(objects, list) or not isinstance(bundle.get("guardrails", []), list):
            raise invalid("areas, objects and guardrails are lists", "bad_bundle")
        report = {"areas": {"created": [], "updated": []}, "objects": {"created": [], "labelled": [], "skipped": []},
                  "guardrails": 0}
        now = self._wall()
        with self.store.transaction():
            for a in areas:
                if not isinstance(a, dict):
                    raise invalid("an area is an object", "bad_bundle")
                try:
                    have = self.area(sid, str(a.get("name")))
                except ApiError:
                    have = None
                if have:
                    self.update_area(sid, have["id"], {"type": a.get("type"), "outline": a.get("outline")})
                    report["areas"]["updated"].append(have["id"])
                else:
                    report["areas"]["created"].append(self.create_area(sid, a.get("name"), a.get("type"), a.get("outline"))["id"])
            for o in objects:
                if not (isinstance(o, dict) and isinstance(o.get("kind"), str) and isinstance(o.get("x"), (int, float))
                        and isinstance(o.get("y"), (int, float)) and isinstance(o.get("label"), str) and o["label"].strip()):
                    raise invalid("an object needs kind, x, y and a label", "bad_bundle")
                label = o["label"].strip()
                taken = next((x for x in self.objects(sid) if (x["label"] or "").lower() == label.lower()), None)
                near = self._nearest(sid, o)
                if taken and not (near and near["id"] == taken["id"]):
                    report["objects"]["skipped"].append({"label": label, "why": f"{taken['id']} is already called {taken['label']!r}"})
                    continue
                if near and (near["label"] is None or near["label"].lower() == label.lower()):
                    self.store.execute("UPDATE objects SET label = ? WHERE site_id = ? AND id = ?", (label, sid, near["id"]))
                    report["objects"]["labelled"].append(near["id"])
                    continue
                assoc = {"ids": {}}
                rep = {**o, "id": "import", "confirmed": True, "n": 1}
                oid = self._insert_object(sid, rep, "import", now, assoc)
                self.store.execute("UPDATE objects SET label = ? WHERE site_id = ? AND id = ?", (label, sid, oid))
                report["objects"]["created"].append(oid)
            wanted = []
            for g in bundle.get("guardrails", []):
                g = guardrails.normalise(g)
                if g["name"] == "no_go_area":
                    g = {"name": "no_go_area", "area": self.area(sid, g["area"])["id"]}
                wanted.append(g)
            merged = self.guardrails(sid)
            self.set_guardrails(sid, merged + [g for g in wanted if g not in merged])
            report["guardrails"] = len(wanted)
        return report

    def seed(self, sid: str) -> dict:
        """What a navigator is seeded with (§3.5.2): the confirmed objects and the areas' outlines."""
        return {"objects": [o for o in self.objects(sid) if o["confirmed"]],
                "areas": [{"id": a["id"], "name": a["name"], "type": a["type"], "outline": a["outline"]}
                          for a in self.areas(sid)]}

    def merge_run_objects(self, sid: str, reported: list, robot: str, assoc: dict) -> list:
        """Fold a run's objects into the site's (§3.5.2). `reported` is the navigator's map (the whole map
        each time); `assoc` is the run's own memory, {"ids": {navigator id: site id}, "n": {navigator
        id: sightings already counted}}, which a caller keeps for the run's life because navigator ids
        belong to one run. A navigator object that is
        new to the run joins a site object of its kind within the association gate (wider for a kind
        a site has one of), else it becomes a new site object with a new id. Labels are the operator's
        and are never touched here. Returns [(change, site object id)]."""
        self._row(sid)
        now = self._wall()
        changes = []
        ids, counted = assoc.setdefault("ids", {}), assoc.setdefault("n", {})
        for rep in reported:
            nid = rep["id"]
            n_total = int(rep.get("n", 1))
            row = None
            if nid in ids:
                row = self.store.one("SELECT * FROM objects WHERE site_id = ? AND id = ?", (sid, ids[nid]))
            if row is None:
                row = self._nearest(sid, rep)
            if row is None:
                changes.append(("new", self._insert_object(sid, rep, robot, now, assoc)))
                counted[nid] = n_total
                continue
            ids[nid] = row["id"]
            gained = max(0, n_total - counted.get(nid, 0))
            counted[nid] = n_total
            was_confirmed = bool(row["confirmed"])
            confirmed = was_confirmed or bool(rep.get("confirmed"))
            blend = lambda old, new: old + POSITION_BLEND * (new - old)
            seen_by = loads(row["seen_by"])
            if robot not in seen_by:
                seen_by.append(robot)
            evidence = (loads(row["evidence"]) + list(rep.get("evidence", [])))[-MAX_EVIDENCE:]
            self.store.execute(
                "UPDATE objects SET x = ?, y = ?, parts = ?, confirmed = ?, landmark = MAX(landmark, ?), confidence = MAX(confidence, ?),"
                " n = n + ?, last_seen = ?, seen_by = ?, evidence = ? WHERE site_id = ? AND id = ?",
                (blend(row["x"], rep["x"]), blend(row["y"], rep["y"]), dumps(rep.get("parts") or loads(row["parts"])),
                 int(confirmed), float(rep.get("landmark", 0.0)), float(rep.get("confidence", 0.0)), gained, now,
                 dumps(seen_by), dumps(evidence), sid, row["id"]))
            if gained or confirmed != was_confirmed:
                changes.append(("confirmed" if confirmed and not was_confirmed else "updated", row["id"]))
        return changes

    def _nearest(self, sid: str, rep: dict):
        best = None
        for row in self.store.all("SELECT * FROM objects WHERE site_id = ? AND kind = ?", (sid, rep["kind"])):
            gate = UNIQUE_M if (rep.get("unique") or row["unique_kind"]) else ASSOC_M
            d = math.hypot(row["x"] - rep["x"], row["y"] - rep["y"])
            if d <= gate and (best is None or d < best[0]):
                best = (d, row)
        return best[1] if best else None

    def _insert_object(self, sid: str, rep: dict, robot: str, now: float, assoc: dict) -> str:
        n = 1 + max([int(r["id"].split("-")[1]) for r in self.store.all("SELECT id FROM objects WHERE site_id = ?", (sid,))] or [0])
        oid = f"obj-{n}"
        parts = rep.get("parts") or [[rep["x"], rep["y"], rep.get("hx", 0.2), rep.get("hy", 0.2), 0.0, 0.0, rep.get("height", 0.5)]]
        self.store.execute(
            "INSERT INTO objects (site_id, id, kind, label, x, y, parts, confirmed, landmark, permanence, confidence, n, unique_kind,"
            " first_seen, last_seen, seen_by, evidence) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (sid, oid, rep["kind"], None, float(rep["x"]), float(rep["y"]), dumps(parts), int(bool(rep.get("confirmed"))),
             float(rep.get("landmark", 0.0)), rep.get("permanence"), float(rep.get("confidence", 0.0)), int(rep.get("n", 1)),
             int(bool(rep.get("unique"))), now, now, dumps([robot]), dumps(list(rep.get("evidence", []))[-MAX_EVIDENCE:])))
        assoc["ids"][rep["id"]] = oid
        return oid
