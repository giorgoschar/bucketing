import { useEffect, useMemo, useState } from 'react'
import { api } from '../../api/client'
import { useCachedQuery } from '../../data/cachedQuery'
import { unwrap } from '../../data/http'
import { keys } from '../../data/keys'
import { formatMoney } from '../../ui/format'
import { useOnline } from '../../data/online'
import { settingsOptions, statementOptions } from './localGroups'
import { GROUP_TITLES, type GroupKey, type SearchGroup, type SearchOption, type SearchResponse, type ServerStatus } from './types'

export const DEBOUNCE_MS = 200
export const MIN_CHARS = 2
export const MAX_CHARS = 100

function useDebounced(value: string, ms: number): string {
  const [out, setOut] = useState(value)
  useEffect(() => {
    if (value === out) return
    const t = setTimeout(() => setOut(value), ms)
    return () => clearTimeout(t)
  }, [value, out, ms])
  return out
}

const longDate = (iso: string): string => {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString('en-IE', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
}

function serverOptions(data: SearchResponse, q: string): Record<'entries' | 'bills' | 'pantry', SearchOption[]> {
  const entries: SearchOption[] = data.entries.map((e) => ({
    id: '', group: 'entries', label: e.label || 'Entry',
    sub: [longDate(e.date), e.category].filter(Boolean).join(' · '),
    end: formatMoney(e.amount, { currency: e.currency }), to: `/activity/${encodeURIComponent(e.id)}`,
  }))
  if (entries.length > 0) {
    entries.push({ id: '', group: 'entries', label: 'See all in Activity', to: `/activity?q=${encodeURIComponent(q)}`, seeAll: true })
  }
  return {
    entries,
    bills: data.items.map((i) => ({
      id: '', group: 'bills', label: i.name, sub: `${i.direction === 'in' ? 'Income' : 'Bill'}${i.is_active ? '' : ' · Paused'}`,
      to: `/insights/bills/${encodeURIComponent(i.id)}`,
    })),
    pantry: data.pantry.map((p) => ({
      id: '', group: 'pantry', label: p.name, sub: [p.brand, `${p.quantity} in stock`].filter(Boolean).join(' · '),
      to: `/plan/pantry/${encodeURIComponent(p.id)}`,
    })),
  }
}

export interface Search {
  /** The trimmed text the results belong to. */
  query: string
  /** At least 2 characters have settled: there is something to show. */
  active: boolean
  groups: SearchGroup[]
  /** Every option in display order, ids set (the listbox's aria-activedescendant). */
  options: SearchOption[]
  /** Result count, without the "See all" row. */
  count: number
  status: ServerStatus
}

/**
 * Search everywhere (spec §4.2). Waits 200 ms after typing, needs 2 characters, cancels the previous request
 * and drops any answer that is not for the latest text. The server groups (entries, bills, pantry) come from
 * GET /search; statements and settings are matched on the device, so they work offline and when the server fails.
 * Not a TanStack query: search text is never kept in the query cache or the device cache.
 */
export function useSearch(input: string, idPrefix = 'search-opt'): Search {
  const typed = input.trim()
  const settled = useDebounced(typed, DEBOUNCE_MS)
  // Only text that has settled counts: while the debounce runs, nothing from an earlier query may show or open.
  const q = typed.length >= MIN_CHARS && settled === typed ? typed : ''
  const online = useOnline()
  const [server, setServer] = useState<{ q: string; data: SearchResponse | null; status: ServerStatus } | null>(null)

  const statements = useCachedQuery(keys.statements(), (signal) => unwrap(api.GET('/api/v1/insights/statements', { signal })), { enabled: q !== '' })

  useEffect(() => {
    if (q === '' || q.length > MAX_CHARS || !online) return
    const ctl = new AbortController()
    let current = true
    void (async () => {
      try {
        const data = (await unwrap(api.GET('/api/v1/search', { params: { query: { q } }, signal: ctl.signal })))
        if (current) setServer({ q, data, status: 'done' })
      } catch {
        if (!current) return
        setServer({ q, data: null, status: 'failed' })
      }
    })()
    return () => { current = false; ctl.abort() }
  }, [q, online])

  return useMemo<Search>(() => {
    const empty: Search = { query: typed, active: false, groups: [], options: [], count: 0, status: 'idle' }
    if (q === '') return empty
    const tooLong = q.length > MAX_CHARS
    const answered = server !== null && server.q === q
    const status: ServerStatus = tooLong ? 'idle' : !online ? 'offline' : answered ? server.status : 'loading'
    const fromServer = answered && server.data ? serverOptions(server.data, q) : { entries: [], bills: [], pantry: [] }
    const built: Record<GroupKey, SearchOption[]> = {
      ...fromServer,
      statements: statementOptions(statements.data?.months ?? [], q),
      settings: settingsOptions(q),
    }
    let n = 0
    const groups: SearchGroup[] = (['entries', 'bills', 'pantry', 'statements', 'settings'] as const)
      .map((key) => ({ key, title: GROUP_TITLES[key], options: built[key].map((o) => ({ ...o, id: `${idPrefix}-${n++}` })) }))
      .filter((g) => g.options.length > 0)
    const options = groups.flatMap((g) => g.options)
    return {
      query: q, active: true, groups, options, count: options.filter((o) => !o.seeAll).length, status,
    }
  }, [q, typed, server, online, statements.data, idPrefix])
}
