// The verb registry of the command palette. Apps register verbs; the palette lists them. A verb never starts a goal or takes a robot
// here: that is the app's `run`. `api` and `mcp` are metadata (the route or tool a verb mirrors); the registry only keeps them.
// register({id, title, section, keywords, when, hotkey, run, danger: 'none'|'confirm'|'stop', api, mcp}) -> unregister
// list(ctx) -> the verbs whose when(ctx) holds, the STOP verbs first, then registration order.
export const DANGER = ['none', 'confirm', 'stop'];

export function createRegistry() {
  const verbs = new Map();
  const listeners = new Set();
  const emit = () => { for (const fn of [...listeners]) fn(); };

  function unregister(id) {
    const had = verbs.delete(id);
    if (had) emit();
    return had;
  }

  function register(spec) {
    const { id, title, section = '', keywords = [], when, hotkey = '', run, danger = 'none', api = null, mcp = null } = spec ?? {};
    if (typeof id !== 'string' || !id) throw new TypeError('palette.register: id must be a non-empty string');
    if (typeof title !== 'string' || !title) throw new TypeError(`palette.register(${id}): title must be a non-empty string`);
    if (typeof run !== 'function') throw new TypeError(`palette.register(${id}): run must be a function`);
    if (!DANGER.includes(danger)) throw new RangeError(`palette.register(${id}): danger must be one of ${DANGER.join(', ')}`);
    if (when != null && typeof when !== 'function') throw new TypeError(`palette.register(${id}): when must be a function`);
    if (verbs.has(id)) throw new Error(`palette.register: ${id} is already registered`);
    verbs.set(id, { id, title, section, keywords: [...keywords], when: when ?? null, hotkey, run, danger, api, mcp });
    emit();
    return () => unregister(id);
  }

  function list(ctx) {
    const out = [];
    for (const v of verbs.values()) {
      let ok = true;
      if (v.when) { try { ok = !!v.when(ctx); } catch { ok = false; } }
      if (ok) out.push(v);
    }
    return [...out.filter((v) => v.danger === 'stop'), ...out.filter((v) => v.danger !== 'stop')];
  }

  return { register, unregister, list, get: (id) => verbs.get(id) ?? null, onChange: (fn) => { listeners.add(fn); return () => listeners.delete(fn); } };
}

export const registry = createRegistry();
