import type { YearOut } from '../../data/types'
import { formatMonthShort } from '../../ui/format'
import { Money } from '../../ui/Money'
import { QueryView } from '../../ui/QueryView'
import { usePlanYear } from './hooks'
import './plan.css'

export function Year() {
  const year = usePlanYear()
  return (
    <QueryView result={year} noDataText="No saved data yet. Connect once to load Plan.">
      {(y) => <YearBars year={y} />}
    </QueryView>
  )
}

function YearBars({ year }: { year: YearOut }) {
  const max = Math.max(0, ...year.months.flatMap((m) => [m.income, m.out]))
  const width = (v: number) => `${max > 0 ? Math.min(100, Math.max(0, (v / max) * 100)) : 0}%`
  return (
    <div className="plan-year">
      <ul className="plan-year__rows">
        {year.months.map((m) => (
          <li key={m.month} className="plan-year__row">
            <span className="plan-year__month">{formatMonthShort(m.month)}</span>
            <div className="plan-year__bars" aria-hidden="true">
              <span className="plan-year__bar plan-year__bar--in" style={{ width: width(m.income) }} />
              <span className="plan-year__bar plan-year__bar--out" style={{ width: width(m.out) }} />
            </div>
            <span className="plan-year__vals">
              <span>In <Money amount={m.income} whole estimated={m.estimated} /></span>
              <span>Out <Money amount={m.out} whole estimated={m.estimated} /></span>
              <span>Net <Money amount={m.income - m.out} whole signed tone="auto" estimated={m.estimated} /></span>
            </span>
          </li>
        ))}
      </ul>
      <p className="plan-year__foot">
        Yearly and quarterly bills average <Money amount={year.infrequent_monthly_average} />/month
      </p>
    </div>
  )
}
