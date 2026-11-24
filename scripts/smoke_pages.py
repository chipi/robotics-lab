#!/usr/bin/env python3
"""The deploy's browser smoke (phase 5 item 4c, unit C3): the pages of a running stack in headless Chromium, with no console error, no page error and
no failed request. Run by `scripts/deploy.py smoke` in the Observatory's environment (it has Playwright; `make observatory-sync`):

    cd apps/observatory && uv run --frozen python ../../scripts/smoke_pages.py --viewer http://127.0.0.1:8070 --control http://127.0.0.1:8060

Pages: the Observatory's 3D page; Mission Control's page from the Observatory's address (/control/, the one origin) and from its own; the robot page of
every robot Mission Control lists; the watch page of the newest run, when the Observatory has one. With `--goal-point X,Y --goal-robot ID` it also
starts a point goal from the page itself (the page's own `api()`, as its buttons do, through the Observatory's address), waits for the goal run to end
and says how it ended; the exit code is 0 only when it was `reached` (C2: the deployed page drives the simulated duck). `--token` is for a stack that
wants one for actions."""

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

from observatory.shots import launch

ap = argparse.ArgumentParser()
ap.add_argument("--viewer", required=True)
ap.add_argument("--control", required=True)
ap.add_argument("--token")
ap.add_argument("--no-one-origin", action="store_true", help="the commit has no /control/ proxy (a rollback to one before it): Mission Control's pages from its own address only")
ap.add_argument("--goal-point", help="X,Y in metres, the site frame: start this point goal from the page")
ap.add_argument("--goal-robot")
ap.add_argument("--goal-timeout", type=float, default=240.0)
ap.add_argument("--shots", type=Path, help="a folder for a picture of each page")
args = ap.parse_args()
failures, errors = [], []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  [{str(detail)[:200]}]" if detail else ""), flush=True)
    if not ok:
        failures.append(name)


def get_json(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, OSError, ValueError):
        return None


robots = (get_json(args.control + "/api/v1/robots") or {}).get("robots", [])
runs = get_json(args.viewer + "/api/v1/runs") or []
newest = runs[0] if runs and isinstance(runs, list) else None

with sync_playwright() as p:
    browser = launch(p)
    ctx = browser.new_context(viewport={"width": 1280, "height": 800}, color_scheme="dark")
    page = ctx.new_page()
    page.set_default_timeout(15000)
    page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
    page.on("console", lambda m: errors.append("console: " + m.text) if m.type in ("error", "warning") and "GL Driver Message" not in m.text else None)
    page.on("response", lambda r: errors.append(f"http {r.status}: {r.url}") if r.status >= 400 else None)
    page.on("requestfailed", lambda r: errors.append(f"failed: {r.url}") if "/events" not in r.url and "/live" not in r.url else None)

    def visit(name, url, ready, shot=None):
        errors.clear()
        try:
            page.goto(url)
            page.wait_for_load_state("domcontentloaded")
            if ready:
                page.wait_for_function(ready, timeout=20000)
            page.wait_for_timeout(500)
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {str(exc).splitlines()[0]}")
        check(name, not errors, errors[:3])
        if args.shots and shot:
            args.shots.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(args.shots / f"smoke-{shot}.png"))

    try:
        visit("the Observatory's 3D page", args.viewer + "/web/three/", "document.title.length > 0", "observatory")
        mc_ready = "window.__mc && window.__mc.ready"
        mc_base = args.control if args.no_one_origin else args.viewer + "/control"
        if not args.no_one_origin:
            visit("Mission Control's page, from the Observatory's address (/control/)", args.viewer + "/control/", mc_ready, "control-via-observatory")
        visit("Mission Control's page, from its own address", args.control + "/", mc_ready, "control")
        for r in robots:
            visit(f"the robot page of {r['id']}, from {'its own' if args.no_one_origin else 'the Observatory'}'s address", f"{mc_base}/#robot/{r['id']}",
                  "window.__mc && window.__mc.ready && !document.getElementById('robot-page').hidden", f"robot-{r['id']}")
        if newest:
            visit(f"the watch page of the newest run ({newest['key']})", f"{args.viewer}/watch/{newest['key']}", "document.querySelectorAll('canvas').length > 0", "watch")
        else:
            print("SKIP the watch page: the Observatory has no run yet")

        if args.goal_point:
            x, y = (float(v) for v in args.goal_point.split(","))
            errors.clear()
            page.goto(args.viewer + "/control/")
            page.wait_for_function("window.__mc && window.__mc.ready")
            if args.token:
                page.evaluate("(t) => { document.getElementById('token').value = t; document.getElementById('token-set').click(); }", args.token)
            page.wait_for_function("(id) => document.querySelector('#robot-' + id)?.getAttribute('data-online') === 'true'", arg=args.goal_robot, timeout=30000)
            started = page.evaluate("""([id, x, y]) => api('POST', '/goal-runs', {goal: {kind: 'point', params: {x, y}}, robots: [id]})
                                       .then((j) => ({id: j.run.id, state: j.run.state, key: j.run.run_key, watch: j.run.watch}), (e) => ({error: e.code + ': ' + e.message}))""",
                                     [args.goal_robot, x, y])
            check("the page starts the goal through the Observatory's address", "error" not in started, started)
            if "error" not in started:
                end = page.evaluate("""async ([id, secs]) => {
                    const stop = Date.now() + secs * 1000;
                    for (;;) {
                      const r = (await api('GET', '/goal-runs/' + id)).run;
                      if (!['queued', 'running'].includes(r.state) || Date.now() > stop) return {state: r.state, reason: r.reason, decisions: (r.decisions || []).length};
                      await new Promise((ok) => setTimeout(ok, 1000));
                    }
                  }""", [started["id"], args.goal_timeout])
                check(f"the goal run ends reached ({started['key']})", end["state"] == "reached", end)
                print("GOAL " + json.dumps({**started, **end}), flush=True)
                if args.shots:
                    page.screenshot(path=str(args.shots / "smoke-goal.png"))
            check("no console error and no failed request while it ran", not errors, errors[:3])
    finally:
        browser.close()

print("SMOKE PAGES " + ("FAIL: " + "; ".join(failures) if failures else "PASS"))
sys.exit(1 if failures else 0)
