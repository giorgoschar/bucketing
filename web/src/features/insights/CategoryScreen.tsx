import { Link, useParams } from 'react-router'
import { BackHeader } from '../../ui/BackHeader'
import { Chips } from '../../ui/Chips'
import { MonthBars } from '../../ui/charts'
import { formatShortDate } from '../../ui/format'
import { QueryView } from '../../ui/QueryView'
import { eur } from './format'
import { useCategoryDetail, useMembers } from './hooks'
import { useLens } from './lens'
import { type Preset, PRESETS, usePeriod } from './period'
import { Card } from './widgets/Card'
import './insights.css'

const CHIPS = PRESETS.filter((p) => p.value !== 'custom')

/** /insights/category/:id: same period chips and lens as Insights (from the URL). */
export function CategoryScreen() {
  const { id = 'uncategorised' } = useParams()
  const members = useMembers().data?.members
  const [period, setPeriod] = usePeriod()
  const [lens] = useLens(members)
  const detail = useCategoryDetail(id, period, lens)
  const name = detail.data ? detail.data.category?.name ?? 'Uncategorised' : 'Category'
  const who = (userId: string | null) => {
    const m = members?.find((x) => x.user_id === userId)
    return m ? (m.display_name || m.username || '').split(' ')[0] : null
  }

  return (
    <>
      <BackHeader title={name} back="/insights" keepSearch />
      <div className="insights__bar">
        <Chips label="Period" options={CHIPS} value={period.preset} onChange={(p: Preset) => setPeriod({ preset: p })} />
      </div>
      <section className="screen insights">
        <QueryView result={detail} noDataText="No saved data for this view. Connect once to load it.">
          {(d) => (
            <>
              <div className="insights__headline insights__headline--split">
                <p className="insights__big"><span className="ui-money ui-figure">{eur(d.total)}</span></p>
                {d.avg_per_month != null && <p className="insights__avg ui-num">Average {eur(d.avg_per_month)}/mo</p>}
              </div>
              <Card title="Six months">
                <MonthBars title={`${name} per month`} months={d.months.map((m) => m.label)} current
                  series={[{ name, values: d.months.map((m) => m.total) }]} format={eur} />
              </Card>
              {d.merchants.length > 0 && (
                <Card title="Top shops">
                  <ul className="insights__rows">
                    {d.merchants.map((m) => (
                      <li key={m.merchant} className="insights__item">
                        <span className="insights__item-main">
                          <span className="insights__item-title">{m.merchant}</span>
                          <span className="insights__note">{m.count} {m.count === 1 ? 'expense' : 'expenses'}</span>
                        </span>
                        <span className="insights__item-value ui-num">{eur(m.total)}</span>
                      </li>
                    ))}
                  </ul>
                </Card>
              )}
              {d.category && (
                <Card title="Auto-filed by" action={<Link to="/settings/categories">Edit rules</Link>}>
                  {d.rules.length ? (
                    <ul className="insights__rules" aria-label="Rules">
                      {d.rules.map((r) => <li key={r.id} className="insights__rule">{`${r.pattern} ${r.match_count}`}</li>)}
                    </ul>
                  ) : <p className="insights__foot">No rules file expenses here yet.</p>}
                </Card>
              )}
              {d.recent.length > 0 && (
                <Card title="Latest" action={<span className="insights__note">{d.count} {d.count === 1 ? 'expense' : 'expenses'}</span>}>
                  <ul className="insights__rows">
                    {d.recent.map((t) => (
                      <li key={t.id} className="insights__item">
                        <span className="insights__item-main">
                          <span className="insights__item-title">{t.merchant || t.notes || name}</span>
                          <span className="insights__note">{[who(t.paid_by), formatShortDate(t.date)].filter(Boolean).join(' · ')}</span>
                        </span>
                        <span className="insights__item-value ui-num">{eur(t.amount)}</span>
                      </li>
                    ))}
                  </ul>
                </Card>
              )}
            </>
          )}
        </QueryView>
      </section>
    </>
  )
}
