/**
 * The one scheduled "replay soon" timer (queue.ts `kick`). Kept apart from queue.ts so `wipe()` in
 * db.ts can cancel it on sign-out without an import cycle (queue.ts imports db.ts).
 */
let kickTimer: ReturnType<typeof setTimeout> | undefined

/** Schedule `fn`; a newer schedule replaces an older one (repeated kicks collapse into one). */
export function scheduleKick(fn: () => void, delayMs: number): void {
  clearTimeout(kickTimer)
  kickTimer = setTimeout(() => {
    kickTimer = undefined
    fn()
  }, delayMs)
}

/** Drop a scheduled kick (sign-out, account switch, tests). */
export function cancelKick(): void {
  clearTimeout(kickTimer)
  kickTimer = undefined
}
