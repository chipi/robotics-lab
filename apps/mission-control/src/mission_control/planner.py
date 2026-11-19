"""Goals in words (RFC-0014 §3.4.5, O14): `plan(text, context) -> goal specs`. An independent module with one function; nothing
else in Mission Control imports a model client.

- **The phrase matcher** needs no model and is always there. It matches the simplest goals ("go to the fridge", "go to the
  kitchen", "explore the kitchen", "take an inventory", "go to 1.5, 0.5") against what the site's map knows: the operator's areas
  and objects and the kinds the robots' recognisers know. It returns a goal or nothing.
- **An LLM is one more way to plan, never required, and off unless `planner.json` is configured** (beside the robot files, not in the
  database): an OpenAI-compatible chat completions endpoint at a base URL, a model name and a key read from a file or the environment.
  Nothing here calls any address by default, and the tests only call a stand-in on loopback.
- **The output is data, not action.** Each goal is validated like any goal (an unknown kind or field is dropped), the plan is
  read back in words, and nothing runs until the operator starts it. A plan's guardrails join the goal's; a goal never loosens the
  site's or the robot's (guardrails.merge), so a plan cannot either. The planner has no path to drive, stop or fire."""

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

from . import goals
from .errors import ApiError, invalid

NUM = r"-?\d+(?:\.\d+)?"
LLM_TIMEOUT_S = 30.0
CONTACT_WORDS = r"(?:without|and don'?t|but don'?t|avoid)\s+(?:touching|bumping|hitting|bumping into|hit|touch)\s+(?:anything|things|stuff|the furniture)"


def _clean(s: str) -> str:
    s = re.sub(r"\b(the|my|a|an|to|please|then)\b", " ", s.lower())
    return re.sub(r"[^a-z0-9 _\-.]", " ", s).strip()


class Context:
    """What the planner knows: the site's areas and objects, and the kinds the robots can recognise."""

    def __init__(self, areas=(), objects=(), kinds=(), site=None):
        self.areas, self.objects, self.kinds, self.site = list(areas), list(objects), sorted(set(kinds)), site

    def area(self, words: str):
        w = _clean(words)
        return next((a for a in self.areas if w in (_clean(a["name"]), _clean(a["id"]))), None)

    def object(self, words: str):
        """The label of an object, else a kind: (label, kind) with at most one set."""
        w = _clean(words)
        for o in self.objects:
            if o.get("label") and _clean(o["label"]) == w:
                return {"label": o["label"]}
        kind = next((k for k in self.kinds + sorted({o["kind"] for o in self.objects})
                     if w in (_clean(k), _clean(k.replace("_", " ")))), None)
        return {"kind": kind} if kind else None

    def to_json(self) -> dict:
        return {"site": self.site, "areas": [{"id": a["id"], "name": a["name"], "type": a.get("type")} for a in self.areas],
                "objects": [{"id": o["id"], "kind": o["kind"], "label": o.get("label"), "area": o.get("area")} for o in self.objects],
                "kinds": self.kinds}


def match(text: str, ctx: Context) -> list:
    """The phrase matcher: goals for what it understands, none for what it does not."""
    t = text.strip()
    low = t.lower()
    extra = {"must_not": ["contact"]} if re.search(CONTACT_WORDS, low) else {}
    low = re.sub(CONTACT_WORDS, " ", low).strip(" ,.;")
    m = re.fullmatch(rf"(?:please\s+)?(?:go|drive|walk|move)(?:\s+to)?\s*\(?\s*({NUM})\s*[, ]\s*({NUM})\s*\)?", low)
    if m:
        return [{"name": f"go to ({m[1]}, {m[2]})", "kind": "point", "params": {"x": float(m[1]), "y": float(m[2])}, **extra}]
    m = re.fullmatch(r"(?:please\s+)?(?:go|drive|walk|move|navigate|bring me|come)\s+(?:to\s+)?(?:the\s+|my\s+)?(.+)", low)
    if m:
        what = m[1]
        area = ctx.area(what)
        if area:
            return [{"name": f"go to the {area['name']}", "kind": "go_to_area", "params": {"area": area["id"]}, **extra}]
        obj = ctx.object(what)
        if obj:
            return [{"name": f"go to {what}", "kind": "go_to_object", "params": obj, **extra}]
        return []
    m = re.fullmatch(r"(?:please\s+)?(?:explore|map|look around|scout)(?:\s+(?:in\s+)?(?:the\s+)?(.*))?", low)
    if m:
        what = (m[1] or "").strip()
        if what in ("", "everything", "all", "the site", "site", "the flat", "the apartment", "the house", "around"):
            return [{"name": "explore the site", "kind": "explore", "params": {"site": True}, **extra}]
        area = ctx.area(what)
        if area:
            return [{"name": f"explore the {area['name']}", "kind": "explore", "params": {"area": area["id"]}, **extra}]
        return []
    m = re.fullmatch(r"(?:please\s+)?(?:(?:take\s+an?\s+)?inventory|find all (?:the )?objects|what(?:'s| is) (?:there|in the (?:flat|apartment|house|site)))(?:\s+(?:of|in)\s+(?:the\s+)?(.*))?", low)
    if m:
        what = (m[1] or "").strip()
        if not what or what in ("site", "the site", "flat", "apartment", "house"):
            return [{"name": "inventory of the site", "kind": "inventory", "params": {"areas": []}, **extra}]
        area = ctx.area(what)
        if area:
            return [{"name": f"inventory of the {area['name']}", "kind": "inventory", "params": {"areas": [area["id"]]}, **extra}]
        return []
    return []


class LlmPlanner:
    """An OpenAI-compatible chat completions client. Built only from a planner.json; nothing is called until `plan` is."""

    def __init__(self, base_url: str, model: str, api_key: str | None, timeout_s: float = LLM_TIMEOUT_S):
        self.base_url, self.model, self.api_key, self.timeout_s = base_url.rstrip("/"), model, api_key, timeout_s

    SYSTEM = ("You turn a request for a robot into goals, as JSON only: {\"goals\": [{\"name\": str, \"kind\": one of point, go_to_object, "
              "go_to_area, explore, inventory, \"params\": object, \"must_not\": [contact | fall | stuck | {\"name\": \"max_speed\", \"mps\": n} | "
              "{\"name\": \"time_limit\", \"seconds\": n}]}]}. params: point {x, y}; go_to_object exactly one of kind, label, id, and optionally area; "
              "go_to_area {area}; explore {area} or {site: true}; inventory {areas: [...]}. Use only the areas, labels and kinds in the context. "
              "If the request is not a goal for the robot, answer {\"goals\": []}.")

    def plan(self, text: str, ctx: Context) -> list:
        body = {"model": self.model, "temperature": 0,
                "messages": [{"role": "system", "content": self.SYSTEM},
                             {"role": "user", "content": json.dumps({"request": text, "context": ctx.to_json()})}]}
        headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {})}
        req = urllib.request.Request(self.base_url + "/chat/completions", data=json.dumps(body).encode(), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                answer = json.loads(resp.read())
            content = answer["choices"][0]["message"]["content"]
        except (urllib.error.URLError, TimeoutError, KeyError, IndexError, ValueError) as exc:
            raise ApiError(502, "planner_failed", f"the planner did not answer: {type(exc).__name__}: {exc}") from None
        found = re.search(r"\{.*\}", content, re.S)
        try:
            specs = json.loads(found.group(0))["goals"] if found else []
        except (ValueError, KeyError, TypeError):
            raise ApiError(502, "planner_failed", "the planner's answer is not the goals JSON") from None
        return specs if isinstance(specs, list) else []


def load_planner(path) -> LlmPlanner | None:
    """planner.json: {"base_url", "model", "api_key_env"? | "api_key_file"?, "timeout_s"?}. None when there is no file: the LLM is off."""
    if path is None or not Path(path).is_file():
        return None
    cfg = json.loads(Path(path).read_text())
    key = None
    if cfg.get("api_key_file"):
        key = Path(os.path.expanduser(cfg["api_key_file"])).read_text().strip()
    elif cfg.get("api_key_env"):
        key = os.environ.get(cfg["api_key_env"])
    return LlmPlanner(cfg["base_url"], cfg["model"], key, float(cfg.get("timeout_s", LLM_TIMEOUT_S)))


def read_back(goal: dict) -> str:
    """A validated goal in words, for the operator to confirm."""
    p = goal["params"]
    what = {"point": lambda: f"go to ({p['x']:g}, {p['y']:g})",
            "go_to_object": lambda: "go to the " + (f"object called '{p['label']}'" if "label" in p else f"object {p['id']}" if "id" in p else p["kind"])
            + (f" in {p['area']}" if "area" in p else ""),
            "go_to_area": lambda: f"go to the area {p['area']}",
            "explore": lambda: "explore " + (f"the area {p['area']}" if "area" in p else "the whole site"),
            "inventory": lambda: "take an inventory of " + (", ".join(p["areas"]) if p["areas"] else "the whole site")}[goal["kind"]]()
    must = ", ".join(g["name"] + "".join(f" {v:g}" for k, v in g.items() if k in ("mps", "seconds", "m")) for g in goal["must_not"])
    return what + (f", and must not: {must}" if must else "")


def plan(text, ctx: Context, llm: LlmPlanner | None = None) -> dict:
    """The matcher first; the model only when the matcher found nothing and one is configured. Returns the proposed goals, validated,
    with their read-back; runs nothing."""
    if not isinstance(text, str) or not text.strip():
        raise invalid("text is the request in words")
    source, specs = "matcher", match(text, ctx)
    if not specs and llm is not None:
        source, specs = "llm", llm.plan(text, ctx)
    proposed, dropped = [], []
    for spec in specs:
        try:
            g = goals.validate(spec, require_name=False)
            proposed.append({"goal": g, "read_back": read_back(g)})
        except ApiError as exc:
            dropped.append({"goal": spec, "why": str(exc)})
    return {"source": source if proposed or dropped else ("llm" if llm is not None else "matcher"), "llm_configured": llm is not None,
            "goals": proposed, "dropped": dropped, "confirm_required": True,
            "message": None if proposed else ("no goal matched" + ("" if llm is not None else ", and no LLM planner is configured"))}
