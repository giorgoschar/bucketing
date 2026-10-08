/**
 * Per-row send lanes (polish P2): writes that name the same lane are sent one after another, never
 * overlapping, so a fast double tap can't let an untick reach the server before its tick. Module-level, so
 * every screen showing the row (the list's stepper, the detail's) shares the lane.
 */
const lanes = new Map<string, Promise<void>>()
/** Calls on each key not yet settled, the running one included. */
const counts = new Map<string, number>()
/** Bumped by resetLanes, so a call from before a reset never touches the new maps. */
let generation = 0

/** Run `fn` once every earlier call on `key` has settled (resolved or not). */
export function inLane<T>(key: string, fn: () => Promise<T>): Promise<T> {
  const prev = lanes.get(key) ?? Promise.resolve()
  const gen = generation
  counts.set(key, (counts.get(key) ?? 0) + 1)
  const run = prev.then(fn).finally(() => {
    if (gen !== generation) return
    const n = (counts.get(key) ?? 1) - 1
    if (n > 0) counts.set(key, n)
    else counts.delete(key)
  })
  const tail = run.then(() => undefined, () => undefined)
  lanes.set(key, tail)
  void tail.then(() => { if (gen === generation && lanes.get(key) === tail) lanes.delete(key) })
  return run
}

/** Writes on `key` not yet settled, the running one included. */
export const laneLength = (key: string): number => counts.get(key) ?? 0

/** Resolves when no lane whose key starts with `prefix` has a write in flight (lanes opened meanwhile too). */
export async function lanesSettled(prefix = ''): Promise<void> {
  for (;;) {
    const busy = [...lanes].filter(([k]) => k.startsWith(prefix)).map(([, p]) => p)
    if (busy.length === 0) return
    await Promise.all(busy)
  }
}

/** Tests: forget every lane (a request a test left hanging must not hold up the next test). */
export function resetLanes(): void {
  generation++
  lanes.clear()
  counts.clear()
}
