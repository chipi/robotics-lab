// The page's run store (ADR-0011), shared by both renderers: a run is loaded by window, then by record.
//
//   1. the run's summary (key, status, seq, span, events, epochs, stream counts), and the live stream opened from its seq;
//   2. the window of ticks around the playhead, +-30 s, so the page draws at once, wherever in the run the playhead is;
//   3. the rest of the run in windows, in the background, outwards from what is loaded, one window per turn;
//   4. then the records of the live stream, applied in order. `seq` is checked: a gap reconnects from the last seq held.
//
// `fr` is the run's frames (CONTRACT.md) as the renderers read them: arrays indexed by the tick's number in the run, with
// holes where a tick is not loaded (`fr.ranges` lists what is: [first, end) pairs, sorted, merged). A seek into a part
// that is not loaded loads the window around it first. Plans and worlds are indexed by the number the server gave them;
// only those a loaded tick refers to are fetched. The store never rebuilds: it says what it added, wherever it is:
// onAppend({i0, i1, plans: [k, ...], worlds: [k, ...]}).

const API = '/api/v1/';
export const WINDOW_S = 60;
export const AHEAD_S = 30;
const RECORDS = ['tick', 'plan', 'world', 'event', 'epoch', 'segment', 'end'];
const DEPTH_STREAM = { f: 'sensors.depth.floor', o: 'sensors.depth.obstacle', v: 'sensors.depth.overhead', b: 'sensors.depth.below' };
const TICK_FIELDS = ['t', 'belief', 'truth', 'tilt', 'cmd', 'depth', 'plan_at', 'world_at'];
const idle = () => new Promise((r) => setTimeout(r, 0));

// the first index in [a, b) whose time is >= x (strict: > x)
function lower(ts, a, b, x, strict) {
  while (a < b) { const m = (a + b) >> 1; if (strict ? ts[m] <= x : ts[m] < x) a = m + 1; else b = m; }
  return a;
}

export class RunStore {
  constructor({ json, onAppend, onRecord, onStatus, onReload }) {
    Object.assign(this, { json, onAppend, onRecord, onStatus, onReload });
    this.gen = 0; this.run = null; this.pres = null; this.key = null;
    this.seq = 0; this.es = null; this.n0 = 0; this.pumping = null;
    this.fr = this._frames();
  }

  _frames() {
    const fr = { plans: [], worlds: [], ranges: [] };
    for (const f of TICK_FIELDS) fr[f] = [];
    // the loaded tick at or before t (the first one after it when none is before; the nearest across a hole)
    fr.tickAt = (t) => {
      let best = -1;
      for (const [a, b] of fr.ranges) {
        if (t < fr.t[a]) return best >= 0 ? best : a;
        if (t <= fr.t[b - 1]) return lower(fr.t, a, b, t, true) - 1;
        best = b - 1;
      }
      return Math.max(best, 0);
    };
    // the first loaded tick whose time is after x (>= x for firstAt); fr.t.length when there is none
    const first = (strict) => (x) => {
      for (const [a, b] of fr.ranges) if (fr.t[b - 1] > x || (!strict && fr.t[b - 1] >= x)) return lower(fr.t, a, b, x, strict);
      return fr.t.length;
    };
    fr.firstAfter = first(true); fr.firstAt = first(false);
    return fr;
  }

  get ticks() { return this.ranges.reduce((n, [a, b]) => n + b - a, 0); }
  get ranges() { return this.fr.ranges; }
  get total() { return this.run?.ticks ?? 0; }
  get complete() { return this.total === 0 || (this.ranges.length === 1 && this.ranges[0][0] === 0 && this.ranges[0][1] >= this.total); }
  get lastT() { return this.fr.t.length ? this.fr.t[this.fr.t.length - 1] : -Infinity; }
  tickAt(t) { return this.fr.tickAt(t); }

  // true when the window around t is loaded (inside one loaded range, or the range reaches the run's edge)
  covers(t) {
    if (this.complete) return true;
    const t0 = t - AHEAD_S, t1 = t + AHEAD_S, fr = this.fr;
    return fr.ranges.some(([a, b]) => (a === 0 || fr.t[a] <= t0) && (b >= this.total || fr.t[b - 1] >= t1));
  }

  // Open a run: its summary, then the window around `at` ('start', 'end' or a time). Resolves once the page can draw.
  async open(key, at = 'start') {
    this.close();
    const gen = ++this.gen;
    this.key = key;
    const [run, pres] = await Promise.all([this.json(`${API}runs/${key}`), this.json(`${API}runs/${key}/presence`).catch(() => null)]);
    if (gen !== this.gen) return null;
    this.run = run; this.pres = pres; this.fr = this._frames(); this.seq = run.seq; this.n0 = run.ticks;
    const t = at === 'end' ? run.t1 : at === 'start' || at == null ? run.t0 : at;
    this.want = t;
    const count = (id) => run.streams?.find((s) => s.id === id)?.count ?? 0;
    this.planCount = count('plan.path'); this.worldCount = count('world.grid');
    this.fresh = run.ticks === 0 && !run.events.length && !this.planCount && !this.worldCount;
    if (run.status === 'live') this._connect(gen);
    if (this.n0 > 0) await this._fetch(gen, t - AHEAD_S, t + AHEAD_S);
    if (gen !== this.gen) return null;
    this.pumping = this._pump(gen);
    return { run, pres };
  }

  close() {
    this.gen++;
    if (this.es) { this.es.close(); this.es = null; }
  }

  // Resolves when the window around t is loaded: the playhead may be anywhere, the window is fetched first.
  async ensure(t) {
    this.want = t;
    for (let tries = 0, w = AHEAD_S; !this.covers(t) && tries < 4; tries++, w *= 2) await this._fetch(this.gen, t - w, t + w);
  }
  whenComplete() { return this.pumping || Promise.resolve(); }

  async _fetch(gen, from, to) {
    const w = await this.json(`${API}runs/${this.key}/frames?from=${from}&to=${to}`);
    if (gen === this.gen) this._ingest(w);
  }

  // ---- windows ----------------------------------------------------------------------------------------------
  // the rest of the run, outwards from what is loaded, nearest the playhead first
  async _pump(gen) {
    let stuck = 0;
    while (gen === this.gen && !this.complete) {
      const gap = this._nextGap();
      if (!gap) break;
      const before = this.ticks;
      await this._fetch(gen, gap.from, gap.to);
      if (gen !== this.gen) return;
      stuck = this.ticks > before ? 0 : stuck + 1;
      if (stuck > 3) break;                                                          // the server holds fewer ticks than it said
      if (this.covers(this.want)) await idle();                                       // background: let the page breathe
    }
  }

  // the unloaded stretch whose loaded neighbour is nearest the playhead, as a time window starting at that neighbour
  _nextGap() {
    const fr = this.fr, n = this.total, r = fr.ranges, gaps = [];
    if (!r.length) return n ? { from: this.want - AHEAD_S, to: this.want + AHEAD_S } : null;
    if (r[0][0] > 0) gaps.push({ at: fr.t[r[0][0]], from: fr.t[r[0][0]] - WINDOW_S, to: fr.t[r[0][0]] });
    for (let k = 0; k < r.length; k++) {
      const end = r[k][1], next = r[k + 1] ? r[k + 1][0] : n;
      if (end < next) gaps.push({ at: fr.t[end - 1], from: fr.t[end - 1], to: fr.t[end - 1] + WINDOW_S });
    }
    gaps.sort((x, y) => Math.abs(x.at - this.want) - Math.abs(y.at - this.want));
    return gaps[0] || null;
  }

  _addRange(a, b) {
    const r = this.fr.ranges;
    r.push([a, b]);
    r.sort((x, y) => x[0] - y[0]);
    for (let k = 0; k + 1 < r.length;) { if (r[k][1] >= r[k + 1][0]) { r[k][1] = Math.max(r[k][1], r[k + 1][1]); r.splice(k + 1, 1); } else k++; }
  }

  // put a window's ticks where they belong; what was not loaded before is reported, run by run
  _ingest(w) {
    const fr = this.fr, runs = [];
    let cur = null;
    for (let k = 0; k < w.t.length; k++) {
      const i = w.i0 + k;
      if (i >= this.n0) break;                                                       // later ticks come by record
      if (fr.t[i] !== undefined) { cur = null; continue; }
      for (const f of TICK_FIELDS) fr[f][i] = w[f][k];
      if (cur && cur[1] === i) cur[1] = i + 1; else { cur = [i, i + 1]; runs.push(cur); }
    }
    const plans = [], worlds = [];
    for (const [k, p] of Object.entries(w.plans)) if (!fr.plans[+k]) { fr.plans[+k] = p; plans.push(+k); }
    for (const [k, x] of Object.entries(w.worlds)) if (!fr.worlds[+k]) { fr.worlds[+k] = x; worlds.push(+k); }
    for (const [a, b] of runs) this._addRange(a, b);
    runs.forEach(([a, b], n) => this.onAppend({ i0: a, i1: b, plans: n ? [] : plans, worlds: n ? [] : worlds }));
    if (!runs.length && (plans.length || worlds.length)) this.onAppend({ i0: 0, i1: 0, plans, worlds });
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
        this._apply(kind, JSON.parse(e.data));
      });
    }
    es.addEventListener('status', (e) => {
      if (gen !== this.gen || es !== this.es) return;
      const d = JSON.parse(e.data);
      if (d.generation != null && d.generation !== this.run.generation) { this.onReload(); return; }      // the file was read again from its start
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
      const i = r.ticks;
      fr.t[i] = d.t; fr.belief[i] = d.belief; fr.truth[i] = d.truth; fr.tilt[i] = d.tilt; fr.cmd[i] = d.cmd; fr.depth[i] = d.depth;
      fr.plan_at[i] = this.planCount - 1; fr.world_at[i] = this.worldCount - 1;
      r.ticks = i + 1;
      this._addRange(i, i + 1);
      this._count('belief.pose'); this._count('belief.track');
      if (d.truth) { this._count('truth.pose'); this._count('truth.track'); }
      if (d.tilt) this._count('sensors.tilt');
      if (d.depth?.length) { this._count('sensors.depth'); for (const p of d.depth) this._count(DEPTH_STREAM[p[3]] ?? DEPTH_STREAM.o); }
      this.onAppend({ i0: i, i1: i + 1, plans: [], worlds: [] });
    } else if (kind === 'plan') {
      this._span(d.t);
      fr.plans[this.planCount] = { t: d.t, path: d.path };
      this.onAppend({ i0: 0, i1: 0, plans: [this.planCount], worlds: [] });
      this.planCount++;
      this._count('plan.path');
    } else if (kind === 'world') {
      this._span(d.t);
      fr.worlds[this.worldCount] = { t: d.t, grid: d.grid, obstacles: d.obstacles, drops: d.drops };
      this.onAppend({ i0: 0, i1: 0, plans: [], worlds: [this.worldCount] });
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
    const ts = r.t1 - r.t0;
    if (kind === 'tick' && ts > 0 && r.ticks > 1) for (const s of r.streams) if (s.rate_hz != null || s.id.startsWith('belief.')) s.rate_hz = Math.round((s.count / ts) * 10) / 10;
    r.seq = this.seq;
    this.onRecord(kind, d);
  }
}
