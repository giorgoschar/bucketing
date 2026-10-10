import type { ComposerState } from './state'

/**
 * A form that is open when the window crosses 1024 px is unmounted (panel <-> full screen) and mounted again
 * in the other layout. It parks what was typed here at the moment of the crossing, and the next composer with
 * the same key picks it up, so nothing typed is lost (Phase A review focus 3). Memory only, and only ever
 * written at a crossing: a draft never outlives the swap it was made for.
 */
const parked = new Map<string, ComposerState>()

/** "new", "edit:<id>" or "copy:<id>": one per kind of form, so an edit never picks up an add's draft. */
export const draftKey = (editId: string | undefined, copyOf: string | null): string =>
  editId ? `edit:${editId}` : copyOf ? `copy:${copyOf}` : 'new'

export const parkDraft = (key: string, s: ComposerState): void => void parked.set(key, s)
export const parkedDraft = (key: string): ComposerState | undefined => parked.get(key)
export const dropDraft = (key: string): void => void parked.delete(key)
