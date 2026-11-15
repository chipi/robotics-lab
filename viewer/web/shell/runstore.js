// The page's run store (ADR-0011), shared by both renderers: a run is loaded by window, then by record.
//
//   1. the run's summary (key, status, seq, span, events, epochs, stream counts), and the live stream opened from its seq;
//   2. the ticks up to the playhead + 30 s, in windows of 60 s, so the page draws at once;
//   3. the rest of the run in windows, in the background, one window per turn of the event loop;
//   4. then the records of the live stream, applied in order. `seq` is checked: a gap reconnects from the last seq held.
//
// `fr` is the run's frames (CONTRACT.md) as the renderers read them: arrays indexed by tick, loaded from the first tick
// on without a hole, so a renderer takes appends only. Plans and worlds are indexed by the number the server gave them;
// only those a loaded tick refers to are fetched (the others are holes). The store never rebuilds: it appends, and says
// what it appended: onAppend({i0, i1, plans: [k, ...], worlds: [k, ...]}).

const API = '/api/v1/';
export const WINDOW_S = 60;
export const AHEAD_S = 30;
const RECORDS = ['tick', 'plan', 'world', 'event', 'epoch', 'segment', 'end'];
const DEPTH_STREAM = { f: 'sensors.depth.floor', o: 'sensors.depth.obstacle', v: 'sensors.depth.overhead', b: 'sensors.depth.below' };
const emptyFrames = () => ({ t: [], belief: [], truth: [], tilt: [], cmd: [], depth: [], plan_at: [], world_at: [], plans: [], worlds: [] });
const idle = () => new Promise((r) => setTimeout(r, 0));

export class RunStore {
  constructor({ json, onAppend, onRecord, onStatus, onReload }) {
    Object.assign(this, { json, onAppend, onRecord, onStatus, onReload });
    this.gen = 0; this.run = null; this.fr = emptyFrames(); this.pres = null; this.key = null;
    this.seq = 0; this.es = null; this.waiters = []; this.complete = false;
  }

  get ticks() { return this.fr.t.length; }
  get lastT() { return this.fr.t.length ? this.fr.t[this.fr.t.length - 1] : -Infinity; }
  covers(t) { return this.complete || this.lastT >= t + AHEAD_S; }

  // Open a run: its summary, then the window around `at` ('start', 'end' or a time). Resolves once the page can draw.
  async open(key, at = 'start') {
    this.close();
    const gen = ++this.gen;
    this.key = key;
    const [run, pres] = await Promise.all([this.json(`${API}runs/${key}`), this.json(`${API}runs/${key}/presence`).catch(() => null)]);
    if (gen !== this.gen) return null;
    this.run = run; this.pres = pres; this.fr = emptyFrames(); this.seq = run.seq; this.n0 = run.ticks;
    const t = at === 'end' ? run.t1 : at === 'start' || at == null ? run.t0 : at;
    this.complete = this.n0 === 0; this.queue = []; this.want = t + AHEAD_S;
    const count = (id) => run.streams?.find((s) => s.id === id)?.count ?? 0;
    this.planCount = count('plan.path'); this.worldCount = count('world.grid');
    this.fresh = run.ticks === 0 && !run.events.length && !this.planCount && !this.worldCount;
    if (run.status === 'live') this._connect(gen);
    this._pump = this._load(gen);
    await this.ensure(t);
    return { run, pres };
  }

  close() {
    this.gen++;
    if (this.es) { this.es.close(); this.es = null; }
    for (const w of this.waiters.splice(0)) w.resolve();
  }

  // Resolves when the ticks up to t + 30 s are loaded (the loader goes on in the background either way).
  ensure(t) {
    this.want = Math.max(this.want ?? -Infinity, t + AHEAD_S);
    if (this.covers(t)) return Promise.resolve();
    return new Promise((resolve) => this.waiters.push({ t, resolve }));
  }
  whenComplete() { return this._pump; }

  _wake() {
    const all = this.waiters.splice(0);
    for (const w of all) if (this.covers(w.t)) w.resolve(); else this.waiters.push(w);
  }

  // ---- windows ----------------------------------------------------------------------------------------------
  async _load(gen) {
    let from = null;
    while (gen === this.gen && this.ticks < this.n0) {
      const to = (this.ticks ? this.lastT : this.run.t0) + WINDOW_S;
      const w = await this.json(`${API}runs/${this.key}/frames?${from === null ? '' : `from=${from}&`}to=${to}`);
      if (gen !== this.gen) return;
      this._ingest(w);
      if (from !== null && from > this.run.t1 + 1 && this.ticks < this.n0) break;      // the server holds fewer ticks than it said
      from = to;
      this._wake();
      if (this.covers(this.want - AHEAD_S)) await idle();                              // background: let the page breathe
    }
    if (gen !== this.gen) return;
    this.complete = true;
    this._wake();
    const queued = this.queue.splice(0);
    for (const [kind, d] of queued) this._apply(kind, d);
  }

  _ingest(w) {
    const fr = this.fr, loaded = fr.t.length;
    if (w.i0 > loaded) throw new Error(`frames window starts at tick ${w.i0}, the page holds ${loaded}`);
    const first = loaded - w.i0, last = Math.min(w.t.length, this.n0 - w.i0);
    for (let k = first; k < last; k++) for (const f of ['t', 'belief', 'truth', 'tilt', 'cmd', 'depth', 'plan_at', 'world_at']) fr[f].push(w[f][k]);
    const plans = [], worlds = [];
    for (const [k, p] of Object.entries(w.plans)) if (!fr.plans[+k]) { fr.plans[+k] = p; plans.push(+k); }
    for (const [k, x] of Object.entries(w.worlds)) if (!fr.worlds[+k]) { fr.worlds[+k] = x; worlds.push(+k); }
    if (fr.t.length > loaded || plans.length || worlds.length) this.onAppend({ i0: loaded, i1: fr.t.length, plans, worlds });
  }

  // ---- live, by record ------------------------------------------------------------------------------------------
  _connect(gen) {
    if (this.es) this.es.close();
    const es = this.es = new EventSource(`${API}runs/${this.key}/live?since=${this.seq}`);
    for (const kind of RECORDS) {
      es.addEventListener(kind, (e) => {
        if (gen !== this.gen || es !== this.es) return;
        const id = +e.lastEventId;
        if (id !== this.seq + 1) { this._connect(gen); return; }              // a gap: start again from the last seq held
        this.seq = id;
        const d = JSON.parse(e.data);
        if (this.complete) this._apply(kind, d); else this.queue.push([kind, d]);
      });
    }
    es.addEventListener('status', (e) => {
      if (gen !== this.gen || es !== this.es) return;
      const d = JSON.parse(e.data);
      if (d.done) { this.run.status = d.status; if (d.status !== 'live') { es.close(); this.es = null; } this.onStatus(d); }
    });
    es.addEventListener('rewritten', () => { if (gen === this.gen) this.onReload(); });
  }

  _span(t) {
    const r = this.run;
    if (this.fresh) { r.t0 = t; r.t1 = t; this.fresh = false; } else { r.t0 = Math.min(r.t0, t); r.t1 = Math.max(r.t1, t); }
  }

  _count(id, n = 1) {
    const s = this.run.streams.find((x) => x.id === id);
    if (!s) return;
    s.count += n; s.missing = s.count === 0; delete s.why;
  }

  _apply(kind, d) {
    const r = this.run, fr = this.fr;
    if (kind === 'tick') {
      this._span(d.t);
      const i0 = fr.t.length;
      fr.t.push(d.t); fr.belief.push(d.belief); fr.truth.push(d.truth); fr.tilt.push(d.tilt); fr.cmd.push(d.cmd); fr.depth.push(d.depth);
      fr.plan_at.push(this.planCount - 1); fr.world_at.push(this.worldCount - 1);
      r.ticks = fr.t.length;
      this._count('belief.pose'); this._count('belief.track');
      if (d.truth) { this._count('truth.pose'); this._count('truth.track'); }
      if (d.tilt) this._count('sensors.tilt');
      if (d.depth?.length) { this._count('sensors.depth'); for (const p of d.depth) this._count(DEPTH_STREAM[p[3]] ?? DEPTH_STREAM.o); }
      this.onAppend({ i0, i1: i0 + 1, plans: [], worlds: [] });
    } else if (kind === 'plan') {
      this._span(d.t);
      fr.plans[this.planCount] = { t: d.t, path: d.path };
      this.onAppend({ i0: fr.t.length, i1: fr.t.length, plans: [this.planCount], worlds: [] });
      this.planCount++;
      this._count('plan.path');
    } else if (kind === 'world') {
      this._span(d.t);
      fr.worlds[this.worldCount] = { t: d.t, grid: d.grid, obstacles: d.obstacles, drops: d.drops };
      this.onAppend({ i0: fr.t.length, i1: fr.t.length, plans: [], worlds: [this.worldCount] });
      this.worldCount++;
      this._count('world.grid');
      for (const [id, list] of [['world.obstacles', d.obstacles], ['world.drops', d.drops]]) {
        const s = r.streams.find((x) => x.id === id);
        if (s) { s.count = list.length; s.missing = !list.length; }
      }
    } else if (kind === 'event') {
      this._span(d.t);
      r.events.push({ t: d.t, kind: d.kind, text: d.text });
      this._count('events');
    } else if (kind === 'epoch') {
      r.epochs.push({ from_t: d.t, map_to_world: d.map_to_world });
    } else if (kind === 'segment') {
      r.segments.push(d);
    } else if (kind === 'end') {
      r.status = d.verdict === 'stopped' ? 'stopped' : 'ended'; r.verdict = d.verdict;
    }
    const span = fr.t.length > 1 ? fr.t[fr.t.length - 1] - fr.t[0] : 0;
    if (kind === 'tick' && span) for (const s of r.streams) if (s.rate_hz != null || s.id.startsWith('belief.')) s.rate_hz = Math.round((s.count / span) * 10) / 10;
    r.seq = this.seq;
    this.onRecord(kind, d);
  }
}
