import { Link, useSearchParams } from 'react-router'
import { OWN_PANEL_KEYS } from '../../shell/addPanel'
import { TopBar } from '../../shell/TopBar'
import { Segmented } from '../../ui/Segmented'
import { Budgets } from './Budgets'
import { Month } from './Month'
import { Upcoming } from './Upcoming'
import { Cash } from './cash/Cash'
import { Pantry } from './pantry/Pantry'
import './plan.css'

const VIEWS = [
  { value: 'upcoming', label: 'Upcoming' },
  { value: 'month', label: 'Month' },
  { value: 'budgets', label: 'Budgets' },
  { value: 'cash', label: 'Cash' },
  { value: 'pantry', label: 'Pantry' },
] as const
type View = (typeof VIEWS)[number]['value']

export function Plan() {
  const [params, setParams] = useSearchParams()
  // Year folded into Month (cash spec §4.1): old ?view=year links open Month at the Year scale.
  const asked = params.get('view') === 'year' ? 'month' : params.get('view')
  const view: View = VIEWS.find((v) => v.value === asked)?.value ?? 'upcoming'
  // Only the Add panel's own parameters survive a switch: the other views' parameters belong to the view left.
  const choose = (v: View) => setParams((p) => {
    const next = new URLSearchParams()
    for (const k of OWN_PANEL_KEYS) { const x = p.get(k); if (x !== null) next.set(k, x) }
    if (v !== 'upcoming') next.set('view', v)
    return next
  }, { replace: true })
  return (
    <>
      <TopBar title="Plan" actions={<Link to="/plan/items" className="btn btn--sm">Items</Link>} />
      <section className="screen plan">
        <div className="plan__seg">
          <Segmented label="Plan view" options={VIEWS} value={view} onChange={choose} />
        </div>
        {view === 'upcoming' && <Upcoming />}
        {view === 'month' && <Month />}
        {view === 'budgets' && <Budgets />}
        {view === 'cash' && <Cash />}
        {view === 'pantry' && <Pantry />}
      </section>
    </>
  )
}
