// The semantic map's colours (RFC-0016), chosen to read on both themes, so not themed: the 3D scene draws with them and the legend names them.
export const SEMANTIC = { object: 0x2e9e5b, landmark: 0xe89a00, seen: 0xd62ba8, wedge: 0x3c78e6, area: 0x7a5cff };
// An object is a landmark when its landmark value is at least this (the operator, 2026-11-18). The video draws the same rule: `LANDMARK_MIN` in
// miniview/video/engines/overlay.py.
export const LANDMARK_MIN = 0.7;
export const cssHex = (n) => '#' + n.toString(16).padStart(6, '0');
