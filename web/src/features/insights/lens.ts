import { useCallback } from 'react'
import { useSearchParams } from 'react-router'
import { type Period, writePeriod } from './period'

export type Lens = string
export const HOUSEHOLD = 'household'
export const LENS_STORAGE_KEY = 'tameio.insights.lens'

export interface LensMember { user_id: string; display_name: string | null; username: string | null }

const firstName = (m: LensMember) => (m.display_name || m.username || '?').trim().split(/\s+/)[0]

/** "Household", "Me", then each other member by first name (full name when two share one). */
export function lensOptions(members: LensMember[], meId: string): { value: string; label: string }[] {
  const others = members.filter((m) => m.user_id !== meId)
  const counts = new Map<string, number>()
  for (const m of others) counts.set(firstName(m), (counts.get(firstName(m)) ?? 0) + 1)
  const labelled = others
    .map((m) => ({ value: m.user_id, label: (counts.get(firstName(m)) ?? 0) > 1 ? (m.display_name || m.username || '?') : firstName(m) }))
    .sort((a, b) => a.label.localeCompare(b.label))
  return [{ value: HOUSEHOLD, label: 'Household' }, { value: meId, label: 'Me' }, ...labelled]
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/** A lens for someone no longer in the household (old link, stale storage) falls back to Household.
 *  Until members load only `household`, `me` or a UUID-shaped id is accepted; after, only real members. */
export function resolveLens(raw: string | null, members?: LensMember[]): Lens {
  if (!raw || raw === HOUSEHOLD) return HOUSEHOLD
  if (!members) return raw === 'me' || UUID.test(raw) ? raw : HOUSEHOLD
  return members.some((m) => m.user_id === raw) ? raw : HOUSEHOLD
}

export function lensQuery(lens: Lens): { paid_by?: string } {
  return lens === HOUSEHOLD ? {} : { paid_by: lens }
}

/** Search string carrying the view into a drill-down link. */
export function insightsSearch(period: Period, lens: Lens): string {
  const params = writePeriod(new URLSearchParams(), period)
  params.set('lens', lens) // household is written too, so a stored member lens cannot override it
  return `?${params.toString()}`
}

function readStored(): string | null {
  try {
    return localStorage.getItem(LENS_STORAGE_KEY)
  } catch {
    return null
  }
}

export function useLens(members?: LensMember[]): [Lens, (next: Lens) => void] {
  const [params, setParams] = useSearchParams()
  const lens = resolveLens(params.get('lens') ?? readStored(), members)
  const set = useCallback(
    (next: Lens) => {
      setParams(
        (prev) => {
          const p = new URLSearchParams(prev)
          if (next === HOUSEHOLD) p.delete('lens')
          else p.set('lens', next)
          return p
        },
        { replace: true },
      )
      try {
        localStorage.setItem(LENS_STORAGE_KEY, next)
      } catch {
        // storage unavailable: the URL still carries it
      }
    },
    [setParams],
  )
  return [lens, set]
}
