import { type KeyboardEvent, useCallback, useEffect } from 'react'
import { useLocation, useSearchParams } from 'react-router'
import { type InsightsTab, TABS } from './overview'
import './insights.css'

const FROM_PARAM: Record<string, InsightsTab> = { trends: 'trends', bills: 'bills' }

/** The tab lives in the query string (`?tab=trends`, `?tab=bills`); Overview is the default and writes nothing.
 *  An old `/insights#bills` or `#statements` link opens the Bills & statements tab, and is rewritten to `?tab=bills`
 *  so a lens or period change keeps it. */
export function useInsightsTab(): [InsightsTab, (next: InsightsTab) => void] {
  const [params, setParams] = useSearchParams()
  const { hash } = useLocation()
  const fromHash = hash === '#bills' || hash === '#statements'
  const param = params.get('tab')
  const tab: InsightsTab = param != null ? (FROM_PARAM[param] ?? 'overview') : fromHash ? 'bills' : 'overview'
  useEffect(() => {
    if (param == null && fromHash) setParams((prev) => { const p = new URLSearchParams(prev); p.set('tab', 'bills'); return p }, { replace: true })
  }, [param, fromHash, setParams])
  const set = useCallback((next: InsightsTab) => {
    setParams((prev) => {
      const p = new URLSearchParams(prev)
      if (next === 'overview') p.delete('tab')
      else p.set('tab', next)
      return p
    }, { replace: true })
  }, [setParams])
  return [tab, set]
}

/** Overview, Trends, Bills & statements: a tablist with a roving tab stop; arrow keys move the choice. */
export function InsightsTabs({ value, onChange }: { value: InsightsTab; onChange(tab: InsightsTab): void }) {
  const move = (e: KeyboardEvent<HTMLButtonElement>, i: number) => {
    const step = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0
    if (!step) return
    e.preventDefault()
    const at = (i + step + TABS.length) % TABS.length
    onChange(TABS[at].value)
    ;(e.currentTarget.parentElement?.children[at] as HTMLElement | undefined)?.focus()
  }
  return (
    <div className="ui-seg insights__tabs" role="tablist" aria-label="Insights sections">
      {TABS.map((t, i) => (
        <button key={t.value} type="button" role="tab" id={`insights-tab-${t.value}`} className="ui-seg__opt"
          aria-selected={t.value === value} tabIndex={t.value === value ? 0 : -1}
          onClick={() => onChange(t.value)} onKeyDown={(e) => move(e, i)}>
          {t.label}
        </button>
      ))}
    </div>
  )
}
