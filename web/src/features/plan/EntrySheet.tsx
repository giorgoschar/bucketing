import { useState } from 'react'
import type { ActionResult } from '../../data/action'
import { usePendingIds } from '../../data/pending'
import { memberName, useHousehold, useRecurringItems } from '../../data/reads'
import type { EntryDoneIn, EntryOut, PaymentMethod } from '../../data/types'
import { useSession } from '../../session/SessionProvider'
import { Badge } from '../../ui/Badge'
import { AlertIcon, CheckIcon, ClockIcon } from '../../ui/icons'
import { Money } from '../../ui/Money'
import { Segmented } from '../../ui/Segmented'
import { Sheet } from '../../ui/Sheet'
import { formatDayHeader, formatMoney, parseAmount } from '../../ui/format'
import { useEntryActions, type EntryActions } from './hooks'
import './entry.css'

export type EntryIntent = 'default' | 'amount'
export interface EntrySheetProps { entry: EntryOut | null; intent?: EntryIntent; onClose: () => void }

const METHODS: readonly { value: PaymentMethod; label: string }[] = [
  { value: 'card', label: 'Card' },
  { value: 'cash', label: 'Cash' },
  { value: 'apple_pay', label: 'Apple Pay' },
  { value: 'transfer', label: 'Transfer' },
  { value: 'other', label: 'Other' },
]

export function EntrySheet({ entry, intent = 'default', onClose }: EntrySheetProps) {
  return (
    <Sheet open={entry !== null} onClose={onClose} title={entry?.name ?? ''}>
      {entry && <EntryBody key={`${entry.id}:${intent}`} entry={entry} intent={intent} onClose={onClose} />}
    </Sheet>
  )
}

type Mode = 'menu' | 'pay' | 'amount' | 'undo'

function EntryBody({ entry, intent, onClose }: { entry: EntryOut; intent: EntryIntent; onClose: () => void }) {
  const expected = entry.status === 'expected'
  const isIn = entry.direction === 'in'
  const [mode, setMode] = useState<Mode>(intent === 'amount' && expected ? 'amount' : 'menu')
  const [problem, setProblem] = useState<string | null>(null)
  const actions = useEntryActions(entry)
  const pending = usePendingIds().has(entry.id)
  const after = (r: ActionResult<unknown>) => {
    if (r.status === 'rejected') setProblem(r.detail)
    else onClose()
  }

  return (
    <div className="entry">
      <div className="entry__summary">
        <Money className="entry__amount ui-figure" amount={entry.amount} currency={entry.currency}
          estimated={entry.estimated} nullText="No amount yet" />
        <p className="entry__due">{isIn ? 'Expected' : 'Due'} {formatDayHeader(entry.due_date)}</p>
        <div className="entry__badges">
          <StatusBadge entry={entry} />
          {pending && <Badge icon={<ClockIcon />}>Waiting to sync</Badge>}
        </div>
      </div>

      {problem && <p className="entry__problem" role="alert">{problem}</p>}

      {expected && mode === 'menu' && (
        <div className="entry__actions">
          <button type="button" className="btn btn--primary btn--block btn--lg" onClick={() => setMode('pay')}>
            {isIn ? 'Received' : 'Paid'}
          </button>
          <button type="button" className="btn btn--block" onClick={() => setMode('amount')}>Set amount</button>
          <button type="button" className="btn btn--ghost btn--block" disabled={actions.busy}
            onClick={async () => after(await actions.skip())}>Skip</button>
        </div>
      )}
      {expected && mode === 'pay' && <PayForm entry={entry} actions={actions} onResult={after} />}
      {expected && mode === 'amount' && <AmountForm entry={entry} actions={actions} onResult={after} />}

      {!expected && mode === 'menu' && (
        <div className="entry__actions">
          <button type="button" className="btn btn--block" disabled={actions.busy}
            onClick={async () => {
              if (entry.status === 'done' && !isIn) setMode('undo')
              else after(await actions.undo(false))
            }}>
            Undo
          </button>
        </div>
      )}
      {mode === 'undo' && (
        <div className="entry__actions">
          <p className="entry__question">Undo this payment. What should happen to the expense?</p>
          {!problem && (
            <button type="button" className="btn btn--block" disabled={actions.busy}
              onClick={async () => after(await actions.undo(false))}>Keep the expense</button>
          )}
          <button type="button" className="btn btn--danger btn--block" disabled={actions.busy}
            onClick={async () => after(await actions.undo(true))}>Delete the expense</button>
        </div>
      )}
    </div>
  )
}

function StatusBadge({ entry }: { entry: EntryOut }) {
  if (entry.status === 'done') return <Badge tone="pos" icon={<CheckIcon />}>{entry.direction === 'in' ? 'Received' : 'Paid'}</Badge>
  if (entry.status === 'skipped') return <Badge>Skipped</Badge>
  if (entry.overdue) return <Badge tone="neg" icon={<AlertIcon />}>Overdue</Badge>
  return <Badge>Expected</Badge>
}

interface FormProps { entry: EntryOut; actions: EntryActions; onResult: (r: ActionResult<unknown>) => void }

function PayForm({ entry, actions, onResult }: FormProps) {
  const isIn = entry.direction === 'in'
  const { me } = useSession()
  const members = useHousehold().data?.members ?? []
  const item = useRecurringItems().data?.find((i) => i.id === entry.item_id)
  const fallbackWho = item?.paid_by_default ?? me?.id ?? members[0]?.user_id ?? null
  const [picked, setPicked] = useState<string | null>(null)
  const who = picked ?? fallbackWho
  const [method, setMethod] = useState<PaymentMethod>(METHODS.find((m) => m.value === entry.payment_method)?.value ?? (isIn ? 'transfer' : 'card'))
  const [text, setText] = useState(entry.amount === null ? '' : entry.amount.toFixed(2))
  const parsed = parseAmount(text)
  const amount = parsed ?? (entry.amount === null ? null : entry.amount.toFixed(2))
  const valid = parsed !== undefined && amount !== null
  const whoLabel = isIn ? 'Received by' : 'Paid by'

  const submit = async () => {
    if (!valid) return
    const body: EntryDoneIn = { amount: parsed ?? null, person: who, payment_method: method }
    onResult(await actions.markDone(body))
  }

  return (
    <form className="entry__form" onSubmit={(e) => { e.preventDefault(); void submit() }}>
      <label className="ui-field">
        <span className="ui-field__label">Amount</span>
        <input className="ui-input ui-num" inputMode="decimal" autoComplete="off" value={text}
          aria-invalid={parsed === undefined} onChange={(e) => setText(e.target.value)} />
      </label>
      {parsed === undefined && <p className="ui-field__error">Enter an amount like 38.90</p>}
      {members.length > 1 && (
        <div className="ui-field">
          <span className="ui-field__label" aria-hidden="true">{whoLabel}</span>
          <Segmented label={whoLabel} value={who ?? ''} onChange={setPicked}
            options={members.map((m) => ({ value: m.user_id, label: memberName(m) }))} />
        </div>
      )}
      <div className="ui-field">
        <span className="ui-field__label" aria-hidden="true">Method</span>
        <Segmented label="Method" options={METHODS} value={method} onChange={setMethod} />
      </div>
      <button type="submit" className="btn btn--primary btn--block btn--lg" disabled={!valid || actions.busy}>
        {`${isIn ? 'Mark received' : 'Mark paid'}${amount !== null ? ` ${formatMoney(Number(amount), { currency: entry.currency })}` : ''}`}
      </button>
    </form>
  )
}

function AmountForm({ entry, actions, onResult }: FormProps) {
  const [text, setText] = useState(entry.amount !== null && !entry.estimated ? entry.amount.toFixed(2) : '')
  const parsed = parseAmount(text)
  const hint = entry.amount !== null && entry.estimated ? `Usually ≈ ${formatMoney(entry.amount, { currency: entry.currency })}` : undefined
  return (
    <form className="entry__form"
      onSubmit={async (e) => { e.preventDefault(); if (parsed) onResult(await actions.setAmount(parsed)) }}>
      <label className="ui-field">
        <span className="ui-field__label">Amount</span>
        <input className="ui-input ui-num" inputMode="decimal" autoComplete="off" value={text} placeholder={hint}
          aria-invalid={parsed === undefined} onChange={(e) => setText(e.target.value)} />
      </label>
      {parsed === undefined && <p className="ui-field__error">Enter an amount like 86.40</p>}
      <button type="submit" className="btn btn--primary btn--block btn--lg" disabled={!parsed || actions.busy}>Save amount</button>
    </form>
  )
}
