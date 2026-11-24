// Saved layouts for both apps, in this browser only (never the server). A layout is the panels a viewer left open and the widths they chose;
// its shape is the app's `defaults`, and anything imported or read back is conformed to that shape: unknown keys dropped, wrong types refused.
//
//   rl.layouts.<app>         JSON {version, layouts: {name: state}}
//   rl.layout.current.<app>  the name of the layout in use
//
// An empty object in `defaults` is a free map (panel id -> boolean, say): its keys are the viewer's, its values must be plain scalars.
const SCOPES = ['observatory', 'control'];
const MAX_BYTES = 64 * 1024;
const MAX_NAME = 60;
const MAX_KEYS = 200;
const MAX_ITEMS = 100;
const MAX_STR = 200;
const LEGACY_KEY = 'miniview.left';
const BAD_KEYS = new Set(['__proto__', 'constructor', 'prototype']);

export const DEFAULTS = {
  observatory: { panels: { left: true, right: true, open: {}, angles: true }, widths: { left: 280, right: 320 } },
  control: { panels: { open: {} }, widths: {} },
};

const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const clone = (v) => JSON.parse(JSON.stringify(v));
const scalar = (v) => typeof v === 'boolean' || (typeof v === 'number' && Number.isFinite(v)) || (typeof v === 'string' && v.length <= MAX_STR);

// v conformed to the shape of d; throws a message naming the path when a type is wrong
function conform(v, d, path) {
  if (isObj(d)) {
    if (!isObj(v)) throw new TypeError(`${path} must be an object`);
    const out = {};
    if (Object.keys(d).length === 0) {
      const keys = Object.keys(v).filter((k) => !BAD_KEYS.has(k) && k.length <= MAX_STR);
      if (keys.length > MAX_KEYS) throw new RangeError(`${path} has more than ${MAX_KEYS} keys`);
      for (const k of keys) {
        if (!scalar(v[k])) throw new TypeError(`${path}.${k} must be a boolean, a number or a short string`);
        out[k] = v[k];
      }
      return out;
    }
    for (const k of Object.keys(d)) out[k] = k in v ? conform(v[k], d[k], `${path}.${k}`) : clone(d[k]);
    return out;
  }
  if (Array.isArray(d)) {
    if (!Array.isArray(v)) throw new TypeError(`${path} must be a list`);
    if (v.length > MAX_ITEMS) throw new RangeError(`${path} has more than ${MAX_ITEMS} items`);
    for (const x of v) if (!scalar(x)) throw new TypeError(`${path} holds a value that is not a boolean, a number or a short string`);
    return [...v];
  }
  if (d === null) {
    if (v !== null && !scalar(v)) throw new TypeError(`${path} must be a scalar or null`);
    return v;
  }
  if (typeof v !== typeof d || (typeof v === 'number' && !Number.isFinite(v))) throw new TypeError(`${path} must be a ${typeof d}`);
  return v;
}

const cleanName = (name) => {
  if (typeof name !== 'string') throw new TypeError('a layout name must be a string');
  const n = name.trim();
  if (!n || n.length > MAX_NAME || BAD_KEYS.has(n)) throw new RangeError(`a layout name is 1 to ${MAX_NAME} characters`);
  return n;
};

// storage that may be absent or throw (private mode, quota, blocked): every failure moves the store to memory for good, none reaches the caller
function safeStorage(real) {
  const mem = new Map();
  let live = real;
  const guard = (fn, fallback) => {
    if (!live) return fallback();
    try { return fn(live); } catch { live = null; return fallback(); }
  };
  return {
    get: (k) => guard((s) => s.getItem(k), () => (mem.has(k) ? mem.get(k) : null)),
    set: (k, v) => { mem.set(k, v); guard((s) => s.setItem(k, v), () => {}); },
    del: (k) => { mem.delete(k); guard((s) => s.removeItem(k), () => {}); },
    get durable() { return !!live; },
  };
}

export function createLayoutStore({ app, version = 1, defaults, storage } = {}) {
  if (!SCOPES.includes(app)) throw new RangeError(`createLayoutStore: app must be one of ${SCOPES.join(', ')}`);
  if (!Number.isInteger(version) || version < 1) throw new RangeError('createLayoutStore: version must be a positive integer');
  const shape = defaults ? clone(defaults) : clone(DEFAULTS[app]);
  let real = storage;
  if (real === undefined) { try { real = globalThis.localStorage; } catch { real = null; } }
  const st = safeStorage(real);
  const LAYOUTS = `rl.layouts.${app}`, CURRENT = `rl.layout.current.${app}`;
  const listeners = new Set();
  const emit = () => { for (const fn of [...listeners]) { try { fn(api.current(), api.get()); } catch { /* a listener's error is its own */ } } };

  // the saved layouts as they are now; a blob of another version or one that does not parse is ignored, an entry of the wrong shape is skipped
  function read() {
    let blob;
    try { blob = JSON.parse(st.get(LAYOUTS)); } catch { return null; }
    if (!isObj(blob) || blob.version !== version || !isObj(blob.layouts)) return null;
    const out = {};
    for (const [n, s] of Object.entries(blob.layouts)) {
      if (BAD_KEYS.has(n)) continue;
      try { out[n] = conform(s, shape, n); } catch { /* skipped */ }
    }
    return out;
  }
  const write = (layouts) => st.set(LAYOUTS, JSON.stringify({ version, layouts }));

  // the Observatory's left panel kept its open sections and the joint-angle switch under miniview.left; read once, the first time no layouts are saved
  function migrate() {
    if (app !== 'observatory' || st.get(LAYOUTS) !== null) return;
    let legacy;
    try { legacy = JSON.parse(st.get(LEGACY_KEY)); } catch { return; }
    if (!isObj(legacy)) return;
    const state = clone(shape);
    if (isObj(state.panels)) {
      try {
        if (isObj(legacy.open)) state.panels.open = conform(legacy.open, state.panels.open ?? {}, 'open');
        if (typeof legacy.angles === 'boolean') state.panels.angles = legacy.angles;
      } catch { return; }
    }
    write({ default: state });
    st.set(CURRENT, 'default');
  }
  migrate();

  const api = {
    get() {
      const layouts = read() || {};
      const n = st.get(CURRENT);
      return clone(n && layouts[n] ? layouts[n] : shape);
    },
    current() {
      const n = st.get(CURRENT);
      return n && (read() || {})[n] ? n : null;
    },
    save(name, state) {
      const n = cleanName(name);
      const clean = conform(state, shape, 'layout');
      write({ ...(read() || {}), [n]: clean });
      st.set(CURRENT, n);
      emit();
      return n;
    },
    load(name) {
      const n = cleanName(name);
      const layouts = read() || {};
      if (!layouts[n]) throw new RangeError(`no saved layout named ${n}`);
      st.set(CURRENT, n);
      emit();
      return clone(layouts[n]);
    },
    list() { return Object.keys(read() || {}).sort(); },
    remove(name) {
      const n = cleanName(name);
      const layouts = read() || {};
      if (!layouts[n]) return false;
      delete layouts[n];
      write(layouts);
      if (st.get(CURRENT) === n) st.del(CURRENT);
      emit();
      return true;
    },
    // one layout (the current one when no name is given) as text another browser can import
    exportJSON(name) {
      const n = name === undefined ? api.current() : cleanName(name);
      const layouts = read() || {};
      if (!n || !layouts[n]) throw new RangeError(n ? `no saved layout named ${n}` : 'no layout is in use; name one to export');
      return JSON.stringify({ app, version, name: n, state: layouts[n] }, null, 2);
    },
    // validated before anything is written: a refused import leaves the saved layouts and the current one as they were
    importJSON(text) {
      if (typeof text !== 'string') throw new TypeError('import: a layout is text');
      if (text.length > MAX_BYTES) throw new RangeError(`import: larger than ${MAX_BYTES / 1024} KB`);
      let doc;
      try { doc = JSON.parse(text); } catch { throw new SyntaxError('import: not valid JSON'); }
      if (!isObj(doc)) throw new TypeError('import: not a layout file');
      if (doc.app !== app) throw new RangeError(`import: a layout for ${JSON.stringify(doc.app)}, not ${app}`);
      if (doc.version !== version) throw new RangeError(`import: version ${JSON.stringify(doc.version)}, this build reads version ${version}`);
      const base = cleanName(doc.name);
      const clean = conform(doc.state, shape, 'layout');
      const layouts = read() || {};
      let n = base, i = 2;
      while (layouts[n]) n = `${base.slice(0, MAX_NAME - 4)} ${i++}`;
      write({ ...layouts, [n]: clean });
      st.set(CURRENT, n);
      emit();
      return n;
    },
    onChange(fn) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    get durable() { return st.durable; },
  };
  return api;
}
