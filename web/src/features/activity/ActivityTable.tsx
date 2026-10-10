import { type KeyboardEvent, useEffect, useRef, useState } from 'react'
import { useLocation, useMatch, useNavigate } from 'react-router'
import { Badge } from '../../ui/Badge'
import { Check } from '../../ui/Check'
import { Money } from '../../ui/Money'
import type { Sort } from './filters'
import type { TableArgs } from './Feed'
import { METHOD_LABELS } from './format'
import type { RefData, Txn } from './hooks'
import { rowTitle } from './format'

const DATE = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short' })
const DATE_YEAR = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })

function dateText(iso: string | null): string {
  if (!iso) return 'No date'
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  const date = new Date(y, m - 1, d)
  return (y === new Date().getFullYear() ? DATE : DATE_YEAR).format(date)
}

function payerText(t: Txn, ref?: RefData): string {
  if (t.payer_mode === 'own_share') return 'Each own share'
  if (t.missing_payer || !t.paid_by) return 'No payer'
  return ref?.members.find((m) => m.user_id === t.paid_by)?.display_name ?? 'Member'
}

function bucketText(t: Txn, ref?: RefData): string {
  const name = ref?.buckets.find((b) => b.id === t.bucket_id)?.name
  if (name) return name
  return t.recurring_bill_id && t.type === 'expense' ? 'Fixed cost' : '—'
}

const dir = (sort: Sort, col: 'date' | 'amount'): 'ascending' | 'descending' | 'none' =>
  !sort.startsWith(col) ? 'none' : sort.endsWith('asc') ? 'ascending' : 'descending'

/** The first click on a header sorts newest or largest first; the next flips it. Date descending is the default. */
const nextSort = (sort: Sort, col: 'date' | 'amount'): Sort => {
  if (!sort.startsWith(col)) return `${col}_desc`
  return sort.endsWith('desc') ? `${col}_asc` : `${col}_desc`
}

type Props = TableArgs & { sort: Sort; onSort: (next: Sort) => void }

/** Activity on desktop (Phase A spec §4.4): one row per payment, the open one marked. The data, paging and
 *  selection come from Feed and Activity; this only draws them and moves between rows. */
export function ActivityTable({ rows, refData, rowProps, selecting, sort, onSort }: Props) {
  const navigate = useNavigate()
  const location = useLocation()
  const openId = useMatch('/activity/:id')?.params.id
  const [cursor, setCursor] = useState<string | null>(null)
  const stop = cursor ?? openId ?? rows[0]?.id
  const body = useRef<HTMLTableSectionElement>(null)

  // Focus that would fall to the page goes back to the open row, or, when the pane just closed, the row that
  // was open: Up, Down and Esc keep working from where the user was.
  const was = useRef(openId)
  useEffect(() => {
    const id = openId ?? was.current
    was.current = openId
    if (id && document.activeElement === document.body) {
      body.current?.querySelector<HTMLElement>(`tr[data-id="${CSS.escape(id)}"]`)?.focus({ preventScroll: true })
    }
  }, [openId, rows.length])

  // Keep the filters, search and sort in the URL; a second row replaces the first rather than stacking history.
  const open = (id: string) =>
    void navigate({ pathname: `/activity/${encodeURIComponent(id)}`, search: location.search }, { replace: !!openId })

  const onKey = (e: KeyboardEvent<HTMLTableRowElement>, pending: boolean, act: () => void) => {
    if (e.target !== e.currentTarget) return
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      const sibling = e.key === 'ArrowDown' ? e.currentTarget.nextElementSibling : e.currentTarget.previousElementSibling
      if (sibling instanceof HTMLElement) sibling.focus()
    } else if (e.key === 'Enter' || (selecting && e.key === ' ')) {
      e.preventDefault()
      if (!pending) act()
    }
  }

  return (
    <div className="atable-wrap">
      <table className="atable" role="grid" aria-label="Transactions" aria-multiselectable={selecting || undefined}>
        <thead>
          <tr>
            {selecting && <th scope="col" className="atable__check"><span className="ck-visually-hidden">Select</span></th>}
            <th scope="col" aria-sort={dir(sort, 'date')}>
              <button type="button" className="atable__sort" onClick={() => onSort(nextSort(sort, 'date'))}>Date</button>
            </th>
            <th scope="col">What</th>
            <th scope="col">Category</th>
            <th scope="col">Bucket</th>
            <th scope="col">Paid by</th>
            <th scope="col">Method</th>
            <th scope="col" className="atable__num" aria-sort={dir(sort, 'amount')}>
              <button type="button" className="atable__sort" onClick={() => onSort(nextSort(sort, 'amount'))}>Amount</button>
            </th>
          </tr>
        </thead>
        <tbody ref={body}>
          {rows.map((t) => {
            const pending = 'pending' in t
            const extra = pending ? {} : rowProps?.(t) ?? {}
            const act = () => (extra.onOpen ?? open)(t.id)
            const marked = selecting ? !!extra.selected : t.id === openId
            const sign = t.type === 'income' ? 1 : t.type === 'expense' ? -1 : 0
            const fixed = t.type === 'expense' && !!t.recurring_bill_id && !t.bucket_id
            const category = refData?.categories.find((c) => c.id === t.category_id)
            return (
              <tr
                key={t.id}
                data-id={t.id}
                className="atable__row"
                aria-selected={marked}
                aria-disabled={pending || undefined}
                data-pending={pending || undefined}
                tabIndex={t.id === stop ? 0 : -1}
                onFocus={() => setCursor(t.id)}
                onClick={pending ? undefined : act}
                onKeyDown={(e) => onKey(e, pending, act)}
              >
                {selecting && <td className="atable__check"><Check checked={!!extra.selected} /></td>}
                <td className="atable__date">{dateText(t.transaction_date)}</td>
                <td className="atable__what">
                  <span className="atable__title">{rowTitle(t, refData)}</span>
                  {t.payment_method === 'apple_pay' && <Badge>Apple Pay</Badge>}
                  {fixed && <Badge>Fixed</Badge>}
                  {pending && <Badge tone="warn">Waiting to sync</Badge>}
                </td>
                <td>{category ? `${category.icon ?? ''} ${category.name}`.trim() : '—'}</td>
                <td>{bucketText(t, refData)}</td>
                <td>{payerText(t, refData)}</td>
                <td className="atable__method">{METHOD_LABELS[t.payment_method] ?? t.payment_method}</td>
                <td className="atable__num">
                  <Money amount={sign === 0 ? t.amount : sign * t.amount} currency={t.currency ?? 'EUR'} signed={sign !== 0}
                    tone={sign > 0 ? 'auto' : 'none'} />
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
