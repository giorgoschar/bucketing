import type { components } from '../../api/schema'

export type SearchEntry = components['schemas']['EntryHit']
export type SearchItem = components['schemas']['ItemHit']
export type SearchPantry = components['schemas']['PantryHit']
export type SearchResponse = components['schemas']['SearchOut']

export type GroupKey = 'entries' | 'bills' | 'pantry' | 'statements' | 'settings'

/** One selectable row. `to` is the router destination it opens. */
export interface SearchOption {
  /** DOM id, set by flatten(): the listbox's aria-activedescendant points at it. */
  id: string
  group: GroupKey
  label: string
  sub?: string
  /** The row's right-hand text (an entry's signed amount). */
  end?: string
  to: string
  /** The trailing "See all in Activity" row (not counted as a result). */
  seeAll?: boolean
}

export interface SearchGroup { key: GroupKey; title: string; options: SearchOption[] }

/** How the server groups fared: `done`, still `loading`, `offline` or `failed` (a 429 too). */
export type ServerStatus = 'idle' | 'loading' | 'done' | 'offline' | 'failed'

export const GROUP_TITLES: Record<GroupKey, string> = {
  entries: 'Entries',
  bills: 'Bills and income',
  pantry: 'Pantry',
  statements: 'Statements',
  settings: 'Settings',
}
