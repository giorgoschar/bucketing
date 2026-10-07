import type { CSSProperties } from 'react'
import { Link } from 'react-router'
import { formatMoney } from '../../../ui/format'
import { useAdjustStock } from './hooks'
import { TrendDownIcon } from './icons'
import { Stepper } from './Stepper'
import { formatQty, sizeLabel, type StockItem, tintOf } from './types'

export function Initial({ name, size = 'md' }: { name: string; size?: 'md' | 'lg' }) {
  return (
    <span className={`pantry-tile${size === 'lg' ? ' pantry-tile--lg' : ''}`} style={{ '--tint': tintOf(name) } as CSSProperties}
      aria-hidden="true">
      {name.trim().charAt(0).toUpperCase() || '·'}
    </span>
  )
}

/** "€1.19 · Sklavenitis"; green, with a falling-price mark, when the advice is buy_now. */
export function PriceChip({ item }: { item: StockItem }) {
  const c = item.cheapest
  if (!c || c.price == null) return null
  const buy = item.advice === 'buy_now'
  const text = `${formatMoney(c.price)} · ${c.retailer_name}`
  return (
    <span className={`pantry-price${buy ? ' pantry-price--buy' : ''}`}>
      {buy && <><TrendDownIcon /><span className="ui-sr">Good time to buy: </span></>}
      <span className="ui-num">{text}</span>
    </span>
  )
}

/** One pantry row: the body opens the detail; the − n + stepper is queued offline (spec §4.2). */
export function PantryRow({ item, pending }: { item: StockItem; pending: boolean }) {
  const { adjust } = useAdjustStock(item)
  const size = sizeLabel(item)
  return (
    <li className={`pantry-row${item.low ? ' pantry-row--low' : ''}`} aria-label={item.name}>
      <Link className="pantry-row__body" to={`/plan/pantry/${encodeURIComponent(item.id)}`}>
        <Initial name={item.name} />
        <span className="pantry-row__main">
          <span className="pantry-row__title">
            {item.name}{size && <span className="pantry-row__size"> · {size}</span>}
          </span>
          <span className="pantry-row__sub">
            <span className={item.low ? 'pantry-row__left pantry-row__left--low' : 'pantry-row__left'}>
              {formatQty(item.quantity)} left{item.low && <> · need {formatQty(item.need_qty ?? 1)}</>}
            </span>
            <PriceChip item={item} />
            {pending && <span className="pantry-row__pending">Waiting to sync</span>}
          </span>
        </span>
      </Link>
      <Stepper name={item.name} value={item.quantity} onStep={(d) => void adjust(d)} />
    </li>
  )
}
