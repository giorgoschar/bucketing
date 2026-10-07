import { useSearchParams } from 'react-router'
import { BackHeader } from '../../ui/BackHeader'
import { Chips } from '../../ui/Chips'
import { LineChart, MonthBars } from '../../ui/charts'
import { formatShortDate } from '../../ui/format'
import { QueryView } from '../../ui/QueryView'
import { eur } from './format'
import { useInsights, useMembers } from './hooks'
import { useLens } from './lens'
import { usePeriod } from './period'
import { type FuelData, NO_FILTERS } from './types'
import { Card } from './widgets/Card'
import './insights.css'

const ALL = 'all'
const perLitre = (n: number) => `€${n.toFixed(3)}`
const litres = (n: number) => `${Math.round(n * 10) / 10} L`

function view(fuel: FuelData, car: string) {
  const one = fuel.cars.find((c) => c.bucket_id === car)
  const refuels = one ? one.refuels : fuel.cars.flatMap((c) => c.refuels).sort((a, b) => a.date.localeCompare(b.date))
  return {
    months: one ? one.months : fuel.months,
    refuels,
    litres: one ? one.litres : fuel.litres,
    spend: one ? one.spend : fuel.spend,
    avg: one ? one.avg_price_per_litre : fuel.avg_price_per_litre,
  }
}

/** /insights/fuel: data is `fuel` from GET /insights (no new endpoint), so it shares the
 *  overview's cache entry for the same period and lens and opens offline whenever Insights did. */
export function FuelScreen() {
  const members = useMembers().data?.members
  const [period] = usePeriod()
  const [lens] = useLens(members)
  const [params, setParams] = useSearchParams()
  const insights = useInsights(period, lens, NO_FILTERS)
  const pick = (c: string) =>
    setParams((p) => {
      const n = new URLSearchParams(p)
      if (c === ALL) n.delete('car')
      else n.set('car', c)
      return n
    }, { replace: true })

  return (
    <>
      <BackHeader title="Fuel" back="/insights" keepSearch />
      <section className="screen insights">
        <QueryView result={insights} noDataText="No saved data for this view. Connect once to load it.">
          {(data) => {
            const fuel = data.fuel
            if (!fuel) return <p className="screen__note">No fill-ups with litres in this period.</p>
            const wanted = params.get('car')
            const car = wanted && fuel.cars.some((c) => c.bucket_id === wanted) ? wanted : ALL
            const v = view(fuel, car)
            const last = v.refuels.at(-1)
            const six = v.refuels.slice(-6)
            const short = (label: string) => label.slice(0, 3)
            return (
              <>
                {fuel.cars.length > 1 && (
                  <Chips label="Car" value={car} onChange={pick}
                    options={[...fuel.cars.map((c) => ({ value: c.bucket_id, label: c.name })), { value: ALL, label: 'All cars' }]} />
                )}
                {last && (
                  <Card title="Last fill">
                    <p className="insights__lead ui-num">{eur(last.spend)}</p>
                    <p className="insights__note ui-num">{`${formatShortDate(last.date)} · ${litres(last.litres)}`} · {perLitre(last.price_per_litre)}/L</p>
                  </Card>
                )}
                {six.length > 1 && (
                  <Card title="Price per litre">
                    <LineChart title="Price per litre, last fills" format={perLitre} average={v.avg}
                      points={six.map((r) => ({ label: formatShortDate(r.date), value: r.price_per_litre }))} />
                  </Card>
                )}
                {v.months.length > 0 && (
                  <div className="insights__pair">
                    <Card title="Litres a month">
                      <MonthBars title="Litres per month" width={140} height={100} months={v.months.map((m) => short(m.label))}
                        series={[{ name: 'Litres', values: v.months.map((m) => m.litres) }]} format={litres} />
                    </Card>
                    <Card title="Spend a month">
                      <MonthBars title="Fuel spend per month" width={140} height={100} months={v.months.map((m) => short(m.label))}
                        series={[{ name: 'Spend', values: v.months.map((m) => m.spend) }]} format={eur} />
                    </Card>
                  </div>
                )}
                <dl className="insights__trio ui-card">
                  <div><dt>Average price</dt><dd className="ui-num">{v.avg != null ? `${perLitre(v.avg)}/L` : '—'}</dd></div>
                  <div><dt>Litres</dt><dd className="ui-num">{litres(v.litres)}</dd></div>
                  <div><dt>Spend</dt><dd className="ui-num">{eur(v.spend)}</dd></div>
                </dl>
                {fuel.unpriced_count > 0 && (
                  <p className="insights__foot">
                    {fuel.unpriced_count === 1 ? '1 fill-up has no price and is left out' : `${fuel.unpriced_count} fill-ups have no price and are left out`}
                  </p>
                )}
              </>
            )
          }}
        </QueryView>
      </section>
    </>
  )
}
