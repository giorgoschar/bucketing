import { useCallback, useId, useState, type KeyboardEvent } from 'react'
import { useNavigate } from 'react-router'
import { useSearch, type Search } from './useSearch'

export interface SearchField {
  value: string
  setValue: (v: string) => void
  search: Search
  listId: string
  /** The option the keyboard is on, or -1. */
  active: number
  activeId: string | undefined
  pick: (to: string) => void
  onKeyDown: (e: KeyboardEvent) => void
}

/**
 * The state shared by the desktop box and the phone screen: the text, the keyboard position and what a
 * result does. Up/Down move across groups, Enter opens, Esc clears and then calls `onEscape`.
 */
export function useSearchField(opts: { onEscape: () => void; afterPick?: () => void; replace?: boolean }): SearchField {
  const navigate = useNavigate()
  const [value, setValueRaw] = useState('')
  const [cursor, setCursor] = useState(-1)
  const listId = useId()
  const search = useSearch(value, `${listId}-opt`)
  const n = search.options.length
  // The cursor belongs to one list of results: a new answer starts again from the top.
  const [forList, setForList] = useState(search.options)
  if (forList !== search.options) { setForList(search.options); setCursor(-1) }
  const active = cursor >= 0 && cursor < n ? cursor : -1

  const setValue = useCallback((v: string) => { setValueRaw(v); setCursor(-1) }, [])
  const { onEscape, afterPick, replace } = opts
  const pick = useCallback((to: string) => {
    setValueRaw('')
    afterPick?.()
    void navigate(to, { replace })
  }, [navigate, afterPick, replace])

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      if (n === 0) return
      e.preventDefault()
      const step = e.key === 'ArrowDown' ? 1 : -1
      setCursor(active === -1 ? (step === 1 ? 0 : n - 1) : (active + step + n) % n)
    } else if (e.key === 'Enter') {
      const o = search.options[active === -1 ? 0 : active]
      if (!o) return
      e.preventDefault()
      pick(o.to)
    } else if (e.key === 'Escape') {
      e.preventDefault()
      e.stopPropagation()
      if (value !== '') setValue('')
      else onEscape()
    }
  }

  return { value, setValue, search, listId, active, activeId: active >= 0 ? search.options[active]?.id : undefined, pick, onKeyDown }
}
