/** The history-state flag that means "the phone search is open": Back removes it, so Back closes the screen. */
export const SEARCH_STATE = 'tameioSearch'
export const searchIsOpen = (state: unknown): boolean =>
  typeof state === 'object' && state !== null && (state as Record<string, unknown>)[SEARCH_STATE] === true
