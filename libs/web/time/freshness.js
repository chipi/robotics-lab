// How old a reading is, as the three words the status badge knows. A reading is fresh below staleAfterS, stale from staleAfterS up to
// (not including) offlineAfterS, and offline from offlineAfterS on. An age that is not a finite number (never heard from) is offline.
export function freshness(ageS, { staleAfterS = 5, offlineAfterS = 30 } = {}) {
  const a = Number(ageS);
  if (ageS === null || ageS === undefined || !Number.isFinite(a)) return 'offline';
  if (a >= offlineAfterS) return 'offline';
  if (a >= staleAfterS) return 'stale';
  return 'fresh';
}
