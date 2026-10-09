import { useState } from 'react'
import { Link } from 'react-router'
import { memberName, useBuckets, useCategories, useHousehold } from '../../../data/reads'
import type { EntryOut } from '../../../data/types'
import type { ItemWithUsage } from '../../insights/bills/types'
import { USAGE_UNITS, USAGE_UNIT_MAX } from '../../insights/bills/usage'
import { useSession } from '../../../session/SessionProvider'
import { formatShortDate, todayISO } from '../../../ui/format'
import { PauseIcon } from '../../../ui/icons'
import { List, ListRow } from '../../../ui/ListRow'
import { Money } from '../../../ui/Money'
import { Segmented } from '../../../ui/Segmented'
import { Sheet } from '../../../ui/Sheet'
import { PAYMENT_METHODS } from '../paymentMethods'
import { emptyItemForm, formToBody, itemToForm, sharesNeedScaling, validateItemForm, type ItemForm } from './form'
import { useItemActions } from './hooks'
import { RulePicker } from './RulePicker'
import './items.css'

export interface ItemSheetProps {
  open: boolean
  /** null: a new item. */
  item: ItemWithUsage | null
  onClose: () => void
  onOpenEntry?: (entry: EntryOut) => void
}

const DIRECTIONS = [{ value: 'out', label: 'Out' }, { value: 'in', label: 'In' }] as const

export function ItemSheet({ open, item, onClose, onOpenEntry }: ItemSheetProps) {
  return (
    <Sheet open={open} onClose={onClose} title={item ? 'Edit item' : 'New item'}>
      {open && <ItemBody key={item?.id ?? 'new'} item={item} onClose={onClose} onOpenEntry={onOpenEntry} />}
    </Sheet>
  )
}

function ItemBody({ item, onClose, onOpenEntry }: Omit<ItemSheetProps, 'open'>) {
  const { me } = useSession()
  const [form, setForm] = useState<ItemForm>(() => (item ? itemToForm(item) : emptyItemForm(todayISO(), me?.id ?? null)))
  const set = <K extends keyof ItemForm>(key: K, value: ItemForm[K]) => setForm((f) => ({ ...f, [key]: value }))
  const [problem, setProblem] = useState<string | null>(null)
  const [deleteBlocked, setDeleteBlocked] = useState<string | null>(null)
  const allBuckets = useBuckets().data ?? []
  const buckets = allBuckets.filter((b) => b.kind === 'monthly' && b.status === 'active')
  // The item's own budget stays selectable when it is no longer offered (archived or an event), so saving keeps it.
  const current = form.bucket_id ? allBuckets.find((b) => b.id === form.bucket_id) : undefined
  const extra = current && !buckets.some((b) => b.id === current.id) ? current : undefined
  const categories = useCategories().data ?? []
  const members = useHousehold().data?.members ?? []
  const actions = useItemActions()
  const out = form.direction === 'out'
  // The server refuses a direction or currency change once an item has payments (409). Unknown counts as locked.
  const locked = item !== null && item.has_history !== false
  const next = item?.next_entry ?? null

  const save = async () => {
    const msg = validateItemForm(form)
    if (msg) {
      setProblem(msg)
      return
    }
    setProblem(null)
    const body = formToBody(form)
    const r = item
      ? await actions.update({ id: item.id, body })
      : await actions.create({ body, tempId: `pending-${crypto.randomUUID()}` })
    if (r.status === 'rejected') setProblem(r.detail)
    else onClose()
  }

  const remove = async () => {
    if (!item) return
    const r = await actions.remove({ id: item.id })
    if (r.status === 'rejected') setDeleteBlocked(r.detail)
    else onClose()
  }

  const pause = async () => {
    if (!item) return
    const r = await actions.update({ id: item.id, body: formToBody({ ...itemToForm(item), is_active: false }) })
    if (r.status !== 'rejected') onClose()
  }

  return (
    <form className="items-form" noValidate onSubmit={(e) => { e.preventDefault(); void save() }}>
      {problem && <p className="items-form__problem" role="alert">{problem}</p>}

      <label className="ui-field">
        <span className="ui-field__label">Name</span>
        <input className="ui-input" value={form.name} maxLength={100} autoComplete="off"
          onChange={(e) => set('name', e.target.value)} />
      </label>

      <div className="ui-field">
        <span className="ui-field__label" aria-hidden="true">Direction</span>
        <Segmented label="Direction" options={DIRECTIONS} value={form.direction} disabled={locked}
          onChange={(d) => set('direction', d)} />
        {locked && <p className="items-form__hint">This item has payments, so its direction and currency can't change.</p>}
      </div>

      <div className="items-form__row">
        <label className="ui-field">
          <span className="ui-field__label">Amount</span>
          <input className="ui-input ui-num" inputMode="decimal" autoComplete="off" placeholder="Variable"
            value={form.amount} onChange={(e) => set('amount', e.target.value)} />
        </label>
        <label className="ui-field">
          <span className="ui-field__label">Currency</span>
          <input className="ui-input" value={form.currency} maxLength={3} disabled={locked} autoCapitalize="characters" autoComplete="off"
            onChange={(e) => set('currency', e.target.value.toUpperCase())} />
        </label>
      </div>
      <p className="items-form__hint">Leave the amount blank if it changes every time.</p>
      {sharesNeedScaling(form) && <p className="items-form__hint">Shares are scaled to the new amount</p>}

      <RulePicker value={form.rule} startDate={form.start_date} endDate={form.end_date} onChange={(rule) => set('rule', rule)} />

      <div className="items-form__row items-form__row--even">
        <label className="ui-field">
          <span className="ui-field__label">Starts</span>
          <input type="date" className="ui-input" value={form.start_date} onChange={(e) => set('start_date', e.target.value)} />
        </label>
        <label className="ui-field">
          <span className="ui-field__label">Ends (optional)</span>
          <input type="date" className="ui-input" value={form.end_date} onChange={(e) => set('end_date', e.target.value)} />
        </label>
      </div>

      {out && (
        <label className="ui-field">
          <span className="ui-field__label">Budget</span>
          <select className="ui-input" value={form.bucket_id} onChange={(e) => set('bucket_id', e.target.value)}>
            <option value="">No budget (a Fixed cost)</option>
            {extra && (
              <option value={extra.id}>{`${extra.name} (${extra.status === 'archived' ? 'archived' : 'not monthly'})`}</option>
            )}
            {buckets.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
        </label>
      )}

      {out && (
        <div className="ui-field">
          <span className="ui-field__label" aria-hidden="true">Payment method</span>
          <Segmented label="Payment method" options={PAYMENT_METHODS} value={form.payment_method}
            onChange={(m) => set('payment_method', m)} />
        </div>
      )}

      <label className="ui-field">
        <span className="ui-field__label">Category</span>
        <select className="ui-input" value={form.category_id} onChange={(e) => set('category_id', e.target.value)}>
          <option value="">No category</option>
          {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </label>

      {form.keep.payer_mode !== 'own_share' && (
        <label className="ui-field">
          <span className="ui-field__label">{out ? 'Paid by' : 'Received by'}</span>
          <select className="ui-input" value={form.paid_by_default} onChange={(e) => set('paid_by_default', e.target.value)}>
            <option value="">Not set</option>
            {members.map((m) => <option key={m.user_id} value={m.user_id}>{memberName(m)}</option>)}
          </select>
        </label>
      )}

      {out && (
        <label className="ui-check">
          <span>Pay automatically on the due date</span>
          <input type="checkbox" checked={form.is_auto_pay} onChange={(e) => set('is_auto_pay', e.target.checked)} />
        </label>
      )}

      {out && (
        <>
          <label className="ui-field">
            <span className="ui-field__label">Track usage</span>
            <select className="ui-input" value={form.usageChoice}
              onChange={(e) => set('usageChoice', e.target.value as ItemForm['usageChoice'])}>
              <option value="off">Off</option>
              {USAGE_UNITS.map((u) => <option key={u} value={u}>{u}</option>)}
              <option value="other">Other</option>
            </select>
          </label>
          {form.usageChoice === 'other' && (
            <label className="ui-field">
              <span className="ui-field__label">Usage unit</span>
              <input className="ui-input" value={form.usageOther} maxLength={USAGE_UNIT_MAX} autoComplete="off"
                onChange={(e) => set('usageOther', e.target.value)} />
            </label>
          )}
        </>
      )}

      <label className="ui-field">
        <span className="ui-field__label">Notes</span>
        <textarea className="ui-input" value={form.notes} onChange={(e) => set('notes', e.target.value)} />
      </label>

      <label className="ui-check">
        <span>Active</span>
        <input type="checkbox" checked={form.is_active} onChange={(e) => set('is_active', e.target.checked)} />
      </label>
      {!form.is_active && <p className="items-form__hint">Paused items create no new entries.</p>}

      {next && onOpenEntry && (
        <List>
          <ListRow onClick={() => onOpenEntry(next)} title={`Next: ${formatShortDate(next.due_date)}`}
            subtitle="Pay, skip or set the amount"
            trailing={<Money amount={next.amount} currency={next.currency} estimated={next.estimated} nullText="variable" />} />
        </List>
      )}

      <button type="submit" className="btn btn--primary btn--block btn--lg" disabled={actions.busy}>
        {item ? 'Save' : 'Add item'}
      </button>
      {item && (
        // All time, by bill: "All" there selects by bill (2c spec §4.5).
        <Link className="btn btn--ghost btn--block" to={`/activity?recurring_bill_id=${encodeURIComponent(item.id)}`}>
          See payments
        </Link>
      )}
      {item && !locked && !deleteBlocked && (
        <button type="button" className="btn btn--danger btn--block" disabled={actions.busy} onClick={() => void remove()}>
          Delete item
        </button>
      )}
      {deleteBlocked && (
        <>
          <p className="items-form__problem" role="alert">{deleteBlocked}</p>
          <button type="button" className="btn btn--block" disabled={actions.busy} onClick={() => void pause()}>
            <PauseIcon />Pause instead
          </button>
        </>
      )}
    </form>
  )
}
