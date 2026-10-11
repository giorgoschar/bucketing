// Hand-typed from Phase C spec §4.1 (GET /api/v1/search); integration aliases these to the generated schema.

export interface SearchEntry { id: string; date: string; label: string; category: string | null; amount: number; currency: string }
export interface SearchItem { id: string; name: string; direction: 'in' | 'out' | string; is_active: boolean }
export interface SearchPantry { id: string; name: string; brand: string | null; quantity: number }
export interface SearchResponse {
  entries: SearchEntry[]
  entries_more: boolean
  items: SearchItem[]
  pantry: SearchPantry[]
}

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
