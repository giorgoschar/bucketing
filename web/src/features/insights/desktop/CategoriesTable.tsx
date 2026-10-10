import { Link } from 'react-router'
import { eur } from '../format'
import { useCategoriesVsUsual } from '../hooks'
import type { WidgetCtx } from '../Insights'
import { HOUSEHOLD, insightsSearch } from '../lens'
import { singleMonth } from '../overview'
import { CASH_NOT_LOGGED, UNCATEGORISED, type CategoryUsual } from '../types'
import { Card } from '../widgets/Card'

/** Every category in the period: amount, share of spending, and against its usual (spec §5.4). */
export function CategoriesTable({ data, period, lens }: Pick<WidgetCtx, 'data' | 'period' | 'lens'>) {
  const month = singleMonth(period, data)
  // The usual is the household's, for one calendar month; any other view says "—".
  return month && lens === HOUSEHOLD
    ? <WithUsual month={month} data={data} period={period} lens={lens} />
    : <Table data={data} period={period} lens={lens} usual={undefined} />
}

function WithUsual({ month, ...rest }: { month: string } & Pick<WidgetCtx, 'data' | 'period' | 'lens'>) {
  return <Table {...rest} usual={useCategoriesVsUsual(month).data} />
}

function Table({ data, period, lens, usual }: Pick<WidgetCtx, 'data' | 'period' | 'lens'> & { usual: CategoryUsual[] | undefined }) {
  const against = (id: string | null, name: string): string => {
    const u = usual?.find((c) => (id === null ? c.category_id === null && c.name === name : c.category_id === id))
    if (!u || u.usual === null) return '—'
    const diff = Math.round((u.this_month - u.usual) * 100) / 100
    if (diff === 0) return 'Same as usual'
    return `${eur(Math.abs(diff))} ${diff > 0 ? 'above' : 'below'} usual`
  }
  return (
    <Card title="Categories">
      <div className="insights__tablewrap">
        <table className="insights__table">
          <caption className="insights__cap">Categories</caption>
          <thead>
            <tr><th scope="col">Category</th><th scope="col">Amount</th><th scope="col">Share</th><th scope="col">Against usual</th></tr>
          </thead>
          <tbody>
            {data.categories.map((c) => {
              const id = c.category_id === null ? UNCATEGORISED : c.category_id
              const isCash = c.category_id === CASH_NOT_LOGGED
              return (
                <tr key={id}>
                  <th scope="row">
                    {isCash ? <span><span aria-hidden="true">{c.icon}</span> {c.name}</span> : (
                      <Link to={`/insights/category/${encodeURIComponent(id)}${insightsSearch(period, lens)}`}>
                        <span aria-hidden="true">{c.icon}</span> {c.name}
                      </Link>
                    )}
                  </th>
                  <td className="ui-num">{eur(c.amount)}</td>
                  <td className="ui-num">{Math.round(c.pct)}%</td>
                  <td>{isCash ? '—' : against(c.category_id, c.name)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </Card>
  )
}
