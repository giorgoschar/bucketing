import { type FormEvent, type ReactNode, useId, useState } from 'react'
import { Link } from 'react-router'
import { useOnline } from '../../../data/online'
import { usePendingIds } from '../../../data/pending'
import { Check } from '../../../ui/Check'
import { EmptyState } from '../../../ui/EmptyState'
import { formatMoney } from '../../../ui/format'
import { ClockIcon, CloudOffIcon, PlusIcon, XIcon } from '../../../ui/icons'
import { Money } from '../../../ui/Money'
import { QueryView } from '../../../ui/QueryView'
import { Sheet } from '../../../ui/Sheet'
import { SwipeRow } from '../../../ui/SwipeRow'
import {
  formatQty, PANTRY_OFFLINE, savesVsOneStore, syncingText, useApplyTicked, useQueuedChanges, useShopping, useShoppingActions,
} from './shoppingHooks'
import type { ShoppingItem, ShoppingLine, ShoppingOut } from './shoppingTypes'
import './shopping.css'

/** A one-off line added offline has this id until the queue sends it and the list refetches. */
const TEMP = 'tmp-'

const itemTitle = (i: ShoppingItem) => `${i.name} × ${formatQty(i.need_qty)}${i.unit ? ` ${i.unit}` : ''}`
const lineTitle = (l: ShoppingLine) => (l.quantity == null ? l.name : `${l.name} × ${formatQty(l.quantity)}`)

function reasonText(i: ShoppingItem): string {
  if (i.reason === 'runout') {
    // The estimate is fractional (0.1 d): a whole day, rounded up.
    return i.runout_days_estimate == null ? 'Running out soon' : `Runs out in ~${Math.max(1, Math.ceil(i.runout_days_estimate))} d`
  }
  return i.quantity == null ? 'Low' : `Low · ${formatQty(i.quantity)} left`
}

/** Plan › Pantry › Shopping list (spec §4.5). */
export function ShoppingList() {
  const shopping = useShopping()
  const online = useOnline()
  return (
    <>
      <header className="topbar backheader">
        {/* Back is the Pantry segment itself: BackHeader takes a bare pathname, so the link is built here. */}
        <Link className="backheader__back" to={{ pathname: '/plan', search: '?view=pantry' }} aria-label="Back">
          <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true"><path d="M15 18l-6-6 6-6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
        </Link>
        <h1 className="topbar__title backheader__title">Shopping list</h1>
      </header>
      <section className="screen shop">
        {shopping.stale && shopping.data && (
          <p className="ui-banner" role="status">
            <CloudOffIcon />{online ? 'Couldn’t refresh · showing the saved list' : 'Offline · showing the saved list'}
          </p>
        )}
        <QueryView result={shopping} showBanner={false} noDataText="No saved shopping list yet. Connect once to load it.">
          {(s) => <ShoppingBody s={s} online={online} />}
        </QueryView>
      </section>
    </>
  )
}

function ShoppingBody({ s, online }: { s: ShoppingOut; online: boolean }) {
  const pending = usePendingIds()
  const actions = useShoppingActions()
  const [adding, setAdding] = useState(false)
  const byId = new Map(s.items.map((i) => [i.id, i]))
  const stores = s.groups.filter((g) => g.retailer !== null).length
  const saves = savesVsOneStore(s)
  const empty = s.items.length === 0 && s.lines.length === 0
  return (
    <div className="shop__body" data-footer={s.ticked_count > 0 || undefined}>
      {empty ? (
        <EmptyState title="Nothing to buy" body="Items running low in your pantry show up here." />
      ) : s.items.length > 0 && (
        <section className="ui-card shop-sum" aria-label="Shopping total">
          <div className="shop-sum__fig">
            <p className="shop-sum__count">
              {s.items.length === 1 ? '1 item' : `${s.items.length} items`} · {stores === 1 ? '1 store' : `${stores} stores`}
            </p>
            <Money amount={s.total} className="shop-sum__total" />
          </div>
          {saves !== null && (
            <span className="shop-saves"><TrendDownIcon />{`saves ${formatMoney(saves)} vs one store`}</span>
          )}
        </section>
      )}

      {s.groups.map((g) => {
        const rows = g.item_ids.map((id) => byId.get(id)).filter((i): i is ShoppingItem => i !== undefined)
        if (rows.length === 0) return null
        return (
          <StoreSection key={g.retailer ?? '(none)'} name={g.retailer_name ?? (g.retailer === null ? 'No price' : g.retailer)}
            subtotal={g.retailer === null ? null : g.total}>
            {rows.map((i) => (
              <ItemRow key={i.id} item={i} pending={pending.has(i.id)} onToggle={() => void actions.toggle(i)} />
            ))}
          </StoreSection>
        )
      })}

      <ExtraLines lines={s.lines} pending={pending} onAdd={() => setAdding(true)}
        onCheck={(l) => void actions.checkLine(l, !l.checked)} onDelete={(l) => void actions.deleteLine(l)} />

      <p className="shop-note">
        Ticked items go into your pantry when you confirm. Nothing here changes your expenses.
      </p>

      {s.ticked_count > 0 && <TickedBar count={s.ticked_count} online={online} />}
      <AddLineSheet open={adding} onClose={() => setAdding(false)}
        onAdd={(name, quantity) => {
          setAdding(false)
          void actions.addLine({ name, quantity, tempId: `${TEMP}${crypto.randomUUID()}` })
        }} />
    </div>
  )
}

function StoreSection({ name, subtotal, children }: { name: string; subtotal: number | null; children: ReactNode }) {
  const id = useId()
  return (
    <section className="shop-store" aria-labelledby={id}>
      <div className="shop-store__head">
        <h2 id={id} className="shop-store__name">{subtotal !== null && <StoreIcon />}{name}</h2>
        {subtotal !== null && <Money amount={subtotal} className="shop-store__sub" />}
      </div>
      <div className="ui-list">{children}</div>
    </section>
  )
}

const waiting = <span className="shop-wait"><ClockIcon />Waiting to sync</span>

function ItemRow({ item, pending, onToggle }: { item: ShoppingItem; pending: boolean; onToggle: () => void }) {
  // A tick queued offline has no id yet, so it can't be taken back until it syncs.
  const locked = item.ticked && !item.tick_id
  const each = item.price !== null && item.need_qty !== 1 ? ` · ${formatMoney(item.price)} each` : ''
  const subId = useId()
  const priceId = useId()
  const priced = item.line_total !== null
  // The name stays short ("Milk × 2"); the reason, sync state and price are its description (screen readers).
  return (
    <button type="button" role="checkbox" aria-checked={item.ticked} aria-label={itemTitle(item)}
      aria-describedby={priced ? `${subId} ${priceId}` : subId}
      className="ui-row shop-row" data-on={item.ticked || undefined} disabled={locked} onClick={onToggle}>
      <Check checked={item.ticked} />
      <span className="ui-row__main">
        <span className="shop-row__title">{itemTitle(item)}</span>
        <span id={subId} className="shop-row__sub">
          {item.advice === 'buy_now' && <><span className="shop-drop"><TrendDownIcon />Price drop</span>{' '}</>}
          <span>{reasonText(item)}{each}</span>
          {pending && <>{' '}{waiting}</>}
        </span>
      </span>
      {priced && <span id={priceId} className="ui-row__end"><Money amount={item.line_total} className="shop-row__price" /></span>}
    </button>
  )
}

interface ExtraProps {
  lines: ShoppingLine[]
  pending: ReadonlySet<string>
  onAdd: () => void
  onCheck: (l: ShoppingLine) => void
  onDelete: (l: ShoppingLine) => void
}

function ExtraLines({ lines, pending, onAdd, onCheck, onDelete }: ExtraProps) {
  const id = useId()
  const add = <button type="button" className="btn btn--sm btn--ghost shop-add" onClick={onAdd}><PlusIcon />Add item</button>
  if (lines.length === 0) return add
  return (
    <section className="shop-store" aria-labelledby={id}>
      <div className="shop-store__head"><h2 id={id} className="shop-store__name">Extra items</h2></div>
      <div className="ui-list">
        {lines.map((l) => {
          const unsynced = l.id.startsWith(TEMP)
          const subId = `shop-line-${l.id}`
          const syncing = unsynced || pending.has(l.id)
          return (
            <SwipeRow key={l.id} disabled={unsynced} onDelete={() => onDelete(l)}>
              <div className="shop-line">
                <button type="button" role="checkbox" aria-checked={l.checked} aria-label={lineTitle(l)}
                  aria-describedby={syncing ? subId : undefined} className="ui-row shop-row" data-on={l.checked || undefined} disabled={unsynced} onClick={() => onCheck(l)}>
                  <Check checked={l.checked} />
                  <span className="ui-row__main">
                    <span className="shop-row__title">{lineTitle(l)}</span>
                    {syncing && <span id={subId} className="shop-row__sub">{waiting}</span>}
                  </span>
                </button>
                <button type="button" className="ui-iconbtn ui-iconbtn--bare shop-line__del" aria-label={`Delete ${l.name}`}
                  disabled={unsynced} onClick={() => onDelete(l)}>
                  <XIcon />
                </button>
              </div>
            </SwipeRow>
          )
        })}
      </div>
      {add}
    </section>
  )
}

function TickedBar({ count, online }: { count: number; online: boolean }) {
  const apply = useApplyTicked()
  const queued = useQueuedChanges()
  const [busy, setBusy] = useState(false)
  const run = async () => {
    setBusy(true)
    try {
      await apply()
    } finally {
      setBusy(false)
    }
  }
  return (
    <section className="shop-bar" aria-label="Ticked items">
      <span className="shop-bar__sum">
        <span><span className="ui-num">{count}</span> ticked</span>
        {!online ? <span className="shop-bar__why">{PANTRY_OFFLINE}</span>
          : queued > 0 && <span className="shop-bar__why">{syncingText(queued)}</span>}
      </span>
      <button type="button" className="shop-bar__btn" disabled={!online || queued > 0 || busy} onClick={() => void run()}>
        Add to pantry
      </button>
    </section>
  )
}

/** A positive quantity, "1,5" or "1.5"; '' is no quantity; NaN is invalid. */
function parseQty(raw: string): number | null {
  const t = raw.trim().replace(',', '.')
  if (!t) return null
  const n = Number(t)
  return Number.isFinite(n) && n > 0 ? n : Number.NaN
}

function AddLineSheet({ open, onClose, onAdd }: { open: boolean; onClose: () => void; onAdd: (name: string, quantity: number | null) => void }) {
  const [name, setName] = useState('')
  const [qty, setQty] = useState('')
  const nameId = useId()
  const qtyId = useId()
  const errId = useId()
  const quantity = parseQty(qty)
  const badQty = Number.isNaN(quantity)
  const ok = name.trim().length > 0 && name.trim().length <= 200 && !badQty
  const close = () => {
    setName('')
    setQty('')
    onClose()
  }
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!ok) return
    onAdd(name.trim(), quantity)
    setName('')
    setQty('')
  }
  return (
    <Sheet open={open} onClose={close} title="Add item">
      <form className="shop-form" onSubmit={submit}>
        <div className="ui-field">
          <label className="ui-field__label" htmlFor={nameId}>Item</label>
          <input id={nameId} className="ui-input" value={name} maxLength={200} autoComplete="off" enterKeyHint="done"
            onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="ui-field">
          <label className="ui-field__label" htmlFor={qtyId}>Quantity (optional)</label>
          <input id={qtyId} className="ui-input" value={qty} inputMode="decimal" autoComplete="off" enterKeyHint="done"
            aria-invalid={badQty || undefined} aria-describedby={badQty ? errId : undefined}
            onChange={(e) => setQty(e.target.value)} />
          {badQty && <p id={errId} className="ui-field__error">Enter a quantity above 0</p>}
        </div>
        <button type="submit" className="btn btn--primary btn--lg btn--block" disabled={!ok}>Add</button>
      </form>
    </Sheet>
  )
}

function StoreIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.9} strokeLinecap="round" strokeLinejoin="round"
      aria-hidden="true" focusable="false" className="ui-icon shop-store__ico">
      <path d="M3 9 4.5 4h15L21 9" /><path d="M3 9h18v1a3 3 0 0 1-6 0 3 3 0 0 1-6 0 3 3 0 0 1-6 0Z" /><path d="M5 13v7h14v-7" />
    </svg>
  )
}

function TrendDownIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round"
      aria-hidden="true" focusable="false" className="ui-icon">
      <path d="m22 17-8.5-8.5-5 5L2 7" /><path d="M16 17h6v-6" />
    </svg>
  )
}
