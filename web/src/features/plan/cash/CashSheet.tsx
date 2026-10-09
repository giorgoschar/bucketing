import { type ReactNode, useRef, useState } from 'react'
import { useOnline } from '../../../data/online'
import { useBuckets, useCategories } from '../../../data/reads'
import { todayISO } from '../../../ui/format'
import { EyeOffIcon, LandmarkIcon, LockIcon } from '../../../ui/icons'
import { Segmented } from '../../../ui/Segmented'
import { Sheet } from '../../../ui/Sheet'
import { ToggleRow } from '../../../ui/ToggleRow'
import { centsToString } from '../../composer/amount'
import { AmountField } from './AmountField'
import type { CashSheetMode } from './Cash'
import { CENT_EPS, euros, initial, tint, typedCents, walletSum } from './format'
import { useCashWrite, useWriteId } from './hooks'
import type { CashWalletMemberOut, MovementBody } from './types'

/** The server's OWN_STASH_SHORT (app/services/cash.py); the client pre-checks it with the known stash. */
const OWN_STASH_SHORT = 'Not enough cash in your stash.'

const MODES = [
  { value: 'take', label: 'Take' },
  { value: 'put_back', label: 'Put back' },
  { value: 'still_have', label: 'Still have' },
] as const
const TITLES: Record<CashSheetMode, string> = { take: 'Take cash', put_back: 'Put back', still_have: 'Still have', add: 'Add to stash' }

export interface CashSheetProps {
  mode: CashSheetMode
  onClose: () => void
  /** The viewer's own stash. */
  stash: number
  /** The month's wallets, the viewer first (is_me). */
  members: CashWalletMemberOut[]
  currency: string
  /** The shown month is today's. Put back and Still have write into today's month (and Still have previews
   *  the shown month's wallet), so on another month the sheet offers Take only (final review I1). */
  current?: boolean
}

/** Take / Put back / Still have in one sheet, and Add to stash without the segment row (spec §4.3). */
export function CashSheet({ mode: initialMode, onClose, stash, members, currency, current = true }: CashSheetProps) {
  const [mode, setMode] = useState<CashSheetMode>(initialMode)
  const [text, setText] = useState('')
  const [date, setDate] = useState(todayISO())
  const [note, setNote] = useState('')
  const me = members.find((m) => m.is_me)
  const meId = me?.member_id ?? ''
  /** A member id, or 'bank'. */
  const [from, setFrom] = useState<string>(meId)
  const [spend, setSpend] = useState(false)
  const buckets = (useBuckets().data ?? []).filter((b) => b.status === 'active')
  const categories = useCategories().data ?? []
  const [bucketId, setBucketId] = useState('')
  const [categoryId, setCategoryId] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  /** One id per write (C5): kept across retries of the same body, new when the body changes or after a success. */
  const writeId = useWriteId()
  const amountRef = useRef<HTMLInputElement>(null)
  const { run } = useCashWrite()
  const online = useOnline()

  const cents = typedCents(text)
  const invalid = text.trim() !== '' && cents === null
  const zeroOk = mode === 'still_have'
  const valid = cents !== null && (zeroOk || cents > 0)
  const amount = cents ?? 0
  const e = (c: number) => euros(c / 100, currency)
  const stashCents = Math.round(stash * 100)
  const fromMe = mode === 'take' && from === meId
  const canSpend = mode === 'take' && (from === meId || from === 'bank')
  const spending = canSpend && spend
  const bucket = bucketId || buckets[0]?.id || ''
  const short = fromMe && valid && amount > stashCents
  const ready = online && valid && !short && !busy && (!spending || bucket !== '')

  const label = !valid
    ? 'Enter an amount'
    : mode === 'take' ? `Take ${e(amount)}${spending ? ' and log it' : ''}`
      : mode === 'put_back' ? `Put back ${e(amount)}`
        : mode === 'still_have' ? `Save ${e(amount)} in hand`
          : `Add ${e(amount)}`

  const save = async () => {
    if (!ready) return
    const body: MovementBody = {
      kind: mode === 'add' ? 'stash_in' : mode,
      amount: centsToString(amount),
      // Still have's preview assumes today (final review m4), so it is always dated today.
      movement_date: mode === 'still_have' ? todayISO() : date || null,
      note: note.trim() || null,
    }
    if (mode === 'take') {
      body.stash_owner_id = from === 'bank' ? null : from
      if (spending) {
        body.spend_bucket_id = bucket
        body.category_id = categoryId || null
      }
    }
    setBusy(true)
    setError(null)
    const out = await run(writeId.stamp(body))
    setBusy(false)
    if (out.ok) {
      writeId.done()
      onClose()
    } else if (out.kind === 'rejected') setError(out.message)
  }

  return (
    <Sheet open onClose={onClose} title={TITLES[mode]} initialFocus={amountRef}
      footer={
        <>
          {!online && <p className="cash-offline-hint cash-offline-hint--foot">Connect to change cash</p>}
          <button type="button" className="btn btn--primary btn--block btn--lg" disabled={!ready} onClick={() => void save()}>
            {label}
          </button>
        </>
      }>
      <form className="cash-form" onSubmit={(ev) => { ev.preventDefault(); void save() }}>
        {mode !== 'add' && current && (
          <Segmented label="Cash action" options={MODES} value={mode as Exclude<CashSheetMode, 'add'>}
            onChange={(m) => { setMode(m); setError(null) }} />
        )}
        <AmountField label="Amount" value={text} onChange={(v) => { setText(v); setError(null) }} inputRef={amountRef}
          invalid={invalid} prompt={mode === 'still_have' ? 'How much cash is in your wallet right now?' : undefined} />

        {mode === 'take' && (
          <fieldset className="cash-from">
            <legend className="ui-field__label">From</legend>
            <div className="ui-list">
              <Source checked={from === meId} onPick={() => setFrom(meId)} lead={<span className="ui-ico ui-ico--acc"><LockIcon /></span>}
                title="My stash"
                sub={valid
                  ? <><span className="ui-num">{e(stashCents)}</span> now → <span className="ui-num">{e(stashCents - amount)}</span> after</>
                  : <><span className="ui-num">{e(stashCents)}</span> now</>} />
              {members.filter((m) => !m.is_me).map((m) => (
                <Source key={m.member_id} checked={from === m.member_id} onPick={() => setFrom(m.member_id)}
                  lead={<span className="cash-avatar" style={{ ['--tint' as string]: tint(members.indexOf(m)) }}>{initial(m.name)}</span>}
                  title={`${m.name}'s stash`}
                  sub={<span className="cash-hidden"><EyeOffIcon />Balance hidden</span>} />
              ))}
              <Source checked={from === 'bank'} onPick={() => setFrom('bank')} lead={<span className="ui-ico ui-ico--neutral"><LandmarkIcon /></span>}
                title="Bank or ATM" sub="Not from anyone's stash" />
            </div>
          </fieldset>
        )}

        {short && <p className="ui-field__error" role="alert">{OWN_STASH_SHORT}</p>}

        {mode === 'still_have' && me && <StillPreview member={me} newCents={valid ? amount : null} currency={currency} />}

        <div className="cash-form__row">
          <label className="ui-field">
            <span className="ui-field__label">Date</span>
            {mode === 'still_have' ? (
              <input className="ui-input cash-date--fixed" type="date" value={todayISO()} readOnly aria-readonly="true" />
            ) : (
              <input className="ui-input" type="date" value={date} max={todayISO()} onChange={(ev) => setDate(ev.target.value)} />
            )}
          </label>
          <label className="ui-field">
            <span className="ui-field__label">Note (optional)</span>
            <input className="ui-input" type="text" maxLength={500} enterKeyHint="done" value={note}
              onChange={(ev) => setNote(ev.target.value)} />
          </label>
        </div>

        {canSpend && (
          <div className="cash-spend">
            <ToggleRow label="I spent it on…" hint="Logs the expense now, so nothing is left to log" checked={spend} onChange={setSpend} />
            {spend && (
              <div className="cash-form__row">
                <label className="ui-field">
                  <span className="ui-field__label">Budget</span>
                  <select className="ui-input" value={bucket} onChange={(ev) => setBucketId(ev.target.value)}>
                    {buckets.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
                  </select>
                </label>
                <label className="ui-field">
                  <span className="ui-field__label">Category</span>
                  <select className="ui-input" value={categoryId} onChange={(ev) => setCategoryId(ev.target.value)}>
                    <option value="">No category</option>
                    {categories.map((c) => <option key={c.id} value={c.id}>{c.icon ? `${c.icon} ${c.name}` : c.name}</option>)}
                  </select>
                </label>
              </div>
            )}
            {spend && buckets.length === 0 && <p className="ui-field__error">No budget to log it in. Connect once to load budgets.</p>}
          </div>
        )}

        {error && <p className="ui-field__error" role="alert">{error}</p>}
      </form>
    </Sheet>
  )
}

function Source({ checked, onPick, lead, title, sub }: {
  checked: boolean; onPick: () => void; lead: ReactNode; title: string; sub: ReactNode
}) {
  return (
    <label className={checked ? 'ui-row cash-source cash-source--on' : 'ui-row cash-source'}>
      <span className="ui-row__lead" aria-hidden="true">{lead}</span>
      <span className="ui-row__main">
        <span className="ui-row__title">{title}</span>
        <span className="cash-source__sub">{sub}</span>
      </span>
      <input type="radio" name="cash-from" className="cash-source__radio" checked={checked} onChange={onPick} />
    </label>
  )
}

/** Not yet logged before → after the new still-have (spec §4.3); the server is authoritative on refresh. */
function StillPreview({ member, newCents, currency }: { member: CashWalletMemberOut; newCents: number | null; currency: string }) {
  const { notLogged, inHand } = walletSum(member)
  const before = notLogged
  const after = newCents === null ? null : Math.max(0, notLogged - (newCents / 100 - (inHand ?? 0)))
  const shown = after !== null && Math.abs(after) < CENT_EPS ? 0 : after
  return (
    <p className="cash-preview" data-testid="still-preview">
      Not yet logged <span className="ui-num">{euros(before, currency)}</span>
      {shown !== null && <> → <span className="ui-num">{euros(shown, currency)}</span></>}
    </p>
  )
}
