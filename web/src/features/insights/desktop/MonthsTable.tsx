import { QueryView } from '../../../ui/QueryView'
import { eur, signedEur } from '../format'
import type { InsightFilters } from '../types'
import { useInsights } from '../hooks'
import type { WidgetCtx } from '../Insights'
import { Card } from '../widgets/Card'

/** The last 12 months, In / Out / Net (spec §5.4). Asks for `months=12`; the overview above keeps its 6. */
export function MonthsTable({ period, lens, filters }: { period: WidgetCtx['period']; lens: WidgetCtx['lens']; filters: InsightFilters }) {
  const twelve = useInsights(period, lens, filters, 12)
  return (
    <Card title="Last 12 months">
      <QueryView result={twelve} showBanner={false} noDataText="No saved months yet. Connect once to load them.">
        {(d) => (
          <div className="insights__tablewrap">
            <table className="insights__table">
              <caption className="insights__cap">Last 12 months</caption>
              <thead>
                <tr><th scope="col">Month</th><th scope="col">In</th><th scope="col">Out</th><th scope="col">Net</th></tr>
              </thead>
              <tbody>
                {d.monthly_in_out.map((m) => (
                  <tr key={`${m.year}-${m.month}`}>
                    <th scope="row">{m.label} <span className="insights__year">{m.year}</span></th>
                    <td className="ui-num">{eur(m.in)}</td>
                    <td className="ui-num">{eur(m.out)}</td>
                    <td className="ui-num">{signedEur(m.net)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </QueryView>
    </Card>
  )
}
