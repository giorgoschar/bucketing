import { useQueryClient } from '@tanstack/react-query'
import { type CSSProperties, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { ApiError } from '../../../data/http'
import { keys } from '../../../data/keys'
import { useOnline } from '../../../data/online'
import { usePendingIds } from '../../../data/pending'
import { barPct, scaleMax } from '../../../ui/charts/scale'
import { formatMoney } from '../../../ui/format'
import { CloudOffIcon } from '../../../ui/icons'
import { QueryView } from '../../../ui/QueryView'
import { Sheet } from '../../../ui/Sheet'
import { useToast } from '../../../ui/Toast'
import { ToggleRow } from '../../../ui/ToggleRow'
import { OFFLINE_WRITE } from './BarcodeSheet'
import { useAdjustStock, usePantryReplaySync, useStockDetail, useStockWrites } from './hooks'
import { ArchiveIcon, RefreshIcon } from './icons'
import { Initial } from './PantryRow'
import { PriceChart } from './PriceChart'
import { dayMonth } from './priceScale'
import { Stepper } from './Stepper'
import { formatQty, type PriceToday, sizeLabel, type StockDetail } from './types'
import '../../../ui/controls.css'
import './pantry.css'

const LIST = '/plan?view=pantry'

/** Plan › Pantry › product (pantry spec §4.4). Lazy-loaded at /plan/pantry/:id. */
export function Detail({ id: given }: { id?: string } = {}) {
  const params = useParams()
  const id = given ?? params.id ?? ''
  const detail = useStockDetail(id)
  usePantryReplaySync()
  // A 404 (archived meanwhile, an old notification link, another household's id) is not a retryable failure.
  const error = useQueryClient().getQueryState(keys.stockItem(id))?.error
  const gone = detail.data === undefined && error instanceof ApiError && error.status === 404
  const online = useOnline()
  return (
    <>
      <header className="topbar backheader">
        <Link className="backheader__back" to={LIST} aria-label="Back">
          <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true"><path d="M15 18l-6-6 6-6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
        </Link>
        <span className="backheader__title" />
        <div className="backheader__action" />
      </header>
      <section className="screen pantry-detail">
        {detail.stale && (
          <p className="ui-banner" role="status">
            <CloudOffIcon />{online ? 'Couldn’t refresh · showing saved product' : 'Offline · showing saved product'}
          </p>
        )}
        {gone ? (
          <div className="ui-empty">
            <p className="ui-empty__title">This item isn’t in your pantry any more</p>
            <p className="ui-empty__body">It was archived, or it belongs to another household.</p>
            <Link className="btn btn--primary" to={LIST}>Back to Pantry</Link>
          </div>
        ) : (
          <QueryView result={detail} showBanner={false} noDataText="No saved copy of this product yet. Connect to load it.">
            {(d) => <Body d={d} online={online} />}
          </QueryView>
        )}
      </section>
    </>
  )
}

function Body({ d, online }: { d: StockDetail; online: boolean }) {
  const size = sizeLabel(d)
  const sub = [d.brand, size].filter(Boolean).join(' · ')
  return (
    <>
      <div className="pantry-detail__who">
        <Initial name={d.name} size="lg" />
        <div className="pantry-detail__id">
          <h1 className="pantry-detail__name">{d.name}</h1>
          {sub && <p className="pantry-detail__sub">{sub}</p>}
        </div>
      </div>
      <StockCard d={d} online={online} />
      <PricesCard d={d} online={online} />
      <section className="ui-card pantry-card" aria-label="Lowest price, 6 months">
        <PriceChart history={d.history} title="Lowest price, 6 months" />
      </section>
      <TrackAndArchive d={d} online={online} />
    </>
  )
}

function StockCard({ d, online }: { d: StockDetail; online: boolean }) {
  const { adjust } = useAdjustStock(d)
  const pending = usePendingIds().has(d.id)
  const writes = useStockWrites(d.id)
  const [min, setMin] = useState<number | null>(null)
  const shownMin = min ?? d.min_quantity
  const below = shownMin - d.quantity
  const stepMin = async (delta: number) => {
    const next = Math.max(0, shownMin + delta)
    setMin(next)
    await writes.settings({ min_quantity: next })
    setMin(null)
  }
  return (
    <section className="ui-card pantry-card" aria-label="Stock">
      <div className="pantry-card__row">
        <div className="pantry-card__label">
          <b>In stock</b>
          {below > 1e-9 && <span className="pantry-card__warn">{formatQty(below)} below your minimum</span>}
          {Math.abs(below) <= 1e-9 && <span className="pantry-card__warn">At your minimum</span>}
          {pending && <span className="pantry-row__pending">Waiting to sync</span>}
        </div>
        <Stepper name={d.name} value={d.quantity} size="lg" onStep={(delta) => void adjust(delta)} />
      </div>
      <div className="pantry-card__rule" />
      <div className="pantry-card__row">
        <span className="pantry-card__label">Keep at least</span>
        <Stepper name={`minimum for ${d.name}`} label="Keep at least" value={shownMin} disabled={!online || min !== null}
          onStep={(delta) => void stepMin(delta)} />
      </div>
      {d.runout_days != null && (
        <>
          <div className="pantry-card__rule" />
          <div className="pantry-card__row">
            <span className="pantry-card__label">Lasts about</span>
            <b className="pantry-card__value">{d.runout_days} {d.runout_days === 1 ? 'day' : 'days'}</b>
          </div>
        </>
      )}
    </section>
  )
}

const byUnitPrice = (a: PriceToday, b: PriceToday) =>
  (a.unit_price ?? Infinity) - (b.unit_price ?? Infinity) || (a.price ?? Infinity) - (b.price ?? Infinity)

function PricesCard({ d, online }: { d: StockDetail; online: boolean }) {
  const writes = useStockWrites(d.id)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const rows = d.prices_today.filter((p) => p.price != null).slice().sort(byUnitPrice)
  const max = scaleMax(rows.map((r) => r.price as number))
  const refresh = async () => {
    setBusy(true)
    setProblem(null)
    const out = await writes.refresh()
    setBusy(false)
    if (out.ok) return
    if (out.status != null && out.status >= 500) setProblem('Prices unavailable right now. Try again later.')
    else if (out.kind !== 'auth') setProblem(out.message)
  }
  return (
    <section className="ui-card pantry-card" aria-labelledby="pantry-prices-title">
      <div className="pantry-card__head">
        <h2 id="pantry-prices-title" className="pantry-card__title">Prices today</h2>
        {d.prices_as_of && <span className="pantry-card__meta">PosoKanei · {dayMonth(d.prices_as_of)}</span>}
      </div>
      {rows.length ? (
        <ul className="pantry-cmp" aria-label="Prices today">
          {rows.map((r, i) => (
            <li key={r.retailer} className={`pantry-cmp__row${i === 0 ? ' pantry-cmp__row--best' : ''}`}>
              <span className="pantry-cmp__store">
                {r.retailer_name}{r.is_discount && <> <span className="ui-badge ui-badge--acc pantry-cmp__offer">Offer</span></>}
              </span>
              <span className="pantry-cmp__track" aria-hidden="true">
                <span className="pantry-cmp__fill" style={{ width: `${barPct(r.price as number, max)}%` } as CSSProperties} />
              </span>
              <span className="pantry-cmp__price ui-num">{formatMoney(r.price as number)}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="pantry-chart__empty">No prices for today yet.</p>
      )}
      {problem && <p className="pantry-card__problem" role="alert">{problem}</p>}
      <button type="button" className="btn btn--block pantry-card__btn" disabled={!online || busy} onClick={() => void refresh()}>
        <RefreshIcon />{busy ? 'Refreshing…' : 'Refresh prices'}
      </button>
    </section>
  )
}

function TrackAndArchive({ d, online }: { d: StockDetail; online: boolean }) {
  const writes = useStockWrites(d.id)
  const navigate = useNavigate()
  const toast = useToast()
  const [track, setTrack] = useState<boolean | null>(null)
  const [confirm, setConfirm] = useState(false)
  const [archiving, setArchiving] = useState(false)
  const checked = track ?? d.track_price
  return (
    <>
      <div className="ui-card pantry-card pantry-card--tight">
        <ToggleRow label="Track price" hint="Get a notification when it drops" checked={checked}
          disabled={!online || track !== null}
          onChange={async (next) => {
            setTrack(next)
            await writes.settings({ track_price: next })
            setTrack(null)
          }} />
      </div>
      {!online && <p className="pantry-offline">{OFFLINE_WRITE}</p>}
      <button type="button" className="btn btn--block pantry-archive" disabled={!online} onClick={() => setConfirm(true)}>
        <ArchiveIcon />Archive product
      </button>
      <Sheet open={confirm} onClose={() => setConfirm(false)} title={`Archive ${d.name}?`}>
        <div className="pantry-confirm">
          <p className="pantry-confirm__text">It leaves your pantry and the shopping list. Its price history is kept.</p>
          <div className="pantry-confirm__acts">
            <button type="button" className="btn" onClick={() => setConfirm(false)}>Cancel</button>
            <button type="button" className="btn btn--danger" disabled={!online || archiving} onClick={async () => {
              setArchiving(true)
              const out = await writes.archive()
              setArchiving(false)
              if (!out.ok) return
              setConfirm(false)
              toast.show(`Archived ${d.name}`)
              navigate(LIST)
            }}>Archive</button>
          </div>
        </div>
      </Sheet>
    </>
  )
}
