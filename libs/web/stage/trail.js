// A fading trail of where a body has been: a line whose newest point is the head colour and whose oldest has faded to the background
// (vertex colours, no alpha, so it needs no sorting and reads on either theme). The page hands in THREE and the two colours as CSS
// text: head (a data colour, e.g. --data-belief) and fadeTo (--scene-bg); setColors re-paints after a theme change.
import { parseColor } from './stage.js';

const token = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

// createTrail(THREE, { max: 600, head, fadeTo }) -> { object, set(points), clear(), setColors({ head, fadeTo }), dispose() }
// set takes points oldest first, as [x, y, z] arrays or a flat array of numbers; more than `max` keeps the newest `max`.
export function createTrail(THREE, { max = 600, head = token('--data-belief'), fadeTo = token('--scene-bg') } = {}) {
  const geometry = new THREE.BufferGeometry();
  const pos = new THREE.BufferAttribute(new Float32Array(max * 3), 3);
  const col = new THREE.BufferAttribute(new Float32Array(max * 3), 3);
  pos.setUsage(THREE.DynamicDrawUsage); col.setUsage(THREE.DynamicDrawUsage);
  geometry.setAttribute('position', pos);
  geometry.setAttribute('color', col);
  geometry.setDrawRange(0, 0);
  const material = new THREE.LineBasicMaterial({ vertexColors: true, toneMapped: false });
  const object = new THREE.Line(geometry, material);
  object.name = 'trail';
  object.frustumCulled = false;
  let n = 0, colors = { head: parseColor(THREE, head).color, fadeTo: parseColor(THREE, fadeTo).color };
  const tmp = new THREE.Color();

  const paint = () => {
    for (let i = 0; i < n; i++) {
      tmp.copy(colors.fadeTo).lerp(colors.head, n > 1 ? i / (n - 1) : 1);
      col.setXYZ(i, tmp.r, tmp.g, tmp.b);
    }
    col.needsUpdate = true;
  };
  return {
    object,
    set(points) {
      const flat = typeof points[0] === 'number';
      const total = flat ? Math.floor(points.length / 3) : points.length;
      const from = Math.max(0, total - max);
      n = total - from;
      for (let i = 0; i < n; i++) {
        if (flat) pos.setXYZ(i, points[(from + i) * 3], points[(from + i) * 3 + 1], points[(from + i) * 3 + 2]);
        else pos.setXYZ(i, ...points[from + i]);
      }
      pos.needsUpdate = true;
      geometry.setDrawRange(0, n);
      paint();
    },
    clear() { n = 0; geometry.setDrawRange(0, 0); },
    setColors({ head: h = head, fadeTo: f = fadeTo } = {}) {
      head = h; fadeTo = f;
      colors = { head: parseColor(THREE, h).color, fadeTo: parseColor(THREE, f).color };
      paint();
    },
    dispose() { geometry.dispose(); material.dispose(); },
  };
}
