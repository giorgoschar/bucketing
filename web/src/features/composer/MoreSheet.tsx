import { type Dispatch, type ReactNode, useState } from 'react'
import { ToggleRow } from '../../ui/ToggleRow'
import { type Member, Sheet } from './bridge'
import { convertCents, formatLitres, litresMilli, parseFuelPrice, parseRate, toCents } from './amount'
import { formatCents } from './currencies'
import { isFuel, type Validation } from './model'
import { memberName } from './pickers/labels'
import { DateChips } from './pickers/DateSheet'
import { RECEIPT_ACCEPT, receiptProblem } from './receipt'
import type { Action, ComposerState } from './state'

export interface MoreCtx {
  today: string
  online: boolean
  householdCurrency: string
  fuelCategoryId: string | null
  members: Member[]
  meId: string
  problems: Validation['problems']
  onOpenSplit?: () => void
}

export interface MoreSheetProps {
  open: boolean
  onClose: () => void
  s: ComposerState
  dispatch: Dispatch<Action>
  ctx: MoreCtx
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="ck-more__section">
      <h3 className="ck-more__title">{title}</h3>
      {children}
    </section>
  )
}

/** The rest of the old edit form, in one scroll (mock screen 3). C4-3 adds fuel, currency and split. */
export function MoreSheet({ open, onClose, s, dispatch, ctx }: MoreSheetProps) {
  const income = s.type === 'income'
  const cents = toCents(s.amount)
  const price = parseFuelPrice(s.fuelPrice)
  const rate = parseRate(s.rate)
  const others = ctx.members.filter((m) => m.user_id !== (s.paidBy ?? ctx.meId)).map((m) => memberName(m)).join(', ')
  const canSplit = !income && ctx.members.length > 1 && !s.ownShare
  return (
    <Sheet open={open} onClose={onClose} title="More"
      footer={<button type="button" className="btn btn--primary btn--lg btn--block" onClick={onClose}>Done</button>}>
      {!income && (
        <Section title="Date">
          <DateChips value={s.date} today={ctx.today} onPick={(d) => dispatch({ type: 'setDate', value: d })} />
          {ctx.problems.date && <p className="ck-more__error">{ctx.problems.date}</p>}
        </Section>
      )}
      {isFuel(s, ctx) && (
        <Section title="Fuel">
          <input className="ui-input ck-more__num" aria-label="Price per litre" inputMode="decimal" autoComplete="off"
            placeholder="Price per litre" value={s.fuelPrice}
            onChange={(e) => dispatch({ type: 'setFuelPrice', value: e.target.value })} />
          {ctx.problems.fuel && <p className="ck-more__error">{ctx.problems.fuel}</p>}
          {price !== null && cents > 0 && (
            <p className="ck-more__note ck-more__figure">{`Litres: ${formatLitres(litresMilli(cents, price))} L`}</p>
          )}
        </Section>
      )}
      {s.currency !== ctx.householdCurrency && (
        <Section title="Currency and rate">
          <p className="ck-more__figure ck-more__fx">
            {`${formatCents(cents, s.currency)} → ${rate !== null ? formatCents(convertCents(cents, rate), ctx.householdCurrency) : 'set a rate'}`}
          </p>
          <input className="ui-input ck-more__num" aria-label="Rate" inputMode="decimal" autoComplete="off" placeholder="Rate"
            value={s.rate} onChange={(e) => dispatch({ type: 'setRate', value: e.target.value })} />
          <p className="ck-more__note">{`Units of ${ctx.householdCurrency} per 1 ${s.currency}`}</p>
          {ctx.problems.rate && <p className="ck-more__error">{ctx.problems.rate}</p>}
        </Section>
      )}
      <Section title="Notes">
        <textarea className="ui-input ck-more__notes" aria-label="Notes" rows={3} maxLength={500} value={s.notes}
          placeholder="Add a note" onChange={(e) => dispatch({ type: 'setNotes', value: e.target.value })} />
        <span className="ck-more__count" aria-hidden="true">{`${s.notes.length}/500`}</span>
      </Section>
      <Section title="Receipt">
        <ReceiptField s={s} dispatch={dispatch} online={ctx.online} />
      </Section>
      {canSplit && (
        <Section title="Split">
          <ToggleRow label={`Split with ${others}`} hint={s.splitOn ? undefined : 'Off · all of it is your share'}
            checked={s.splitOn}
            onChange={(on) => (on ? ctx.onOpenSplit?.() : dispatch({ type: 'setSplit', on: false, mode: s.splitMode, splits: [] }))} />
          {s.splitOn && (
            <button type="button" className="ck-more__shares" onClick={() => ctx.onOpenSplit?.()}>
              {s.splits.map((x) => `${memberName(ctx.members.find((m) => m.user_id === x.user_id))} ${formatCents(toCents(x.amount), s.currency)}`).join(' · ')}
            </button>
          )}
          {ctx.problems.split && <p className="ck-more__error">{ctx.problems.split}</p>}
        </Section>
      )}
      <Section title="Forecast">
        <ToggleRow label="Count in forecast" hint="Turn off for one-offs" checked={s.countInForecast}
          onChange={(on) => dispatch({ type: 'setForecast', on })} />
      </Section>
    </Sheet>
  )
}

function ReceiptField({ s, dispatch, online }: { s: ComposerState; dispatch: Dispatch<Action>; online: boolean }) {
  const [problem, setProblem] = useState<string | null>(null)
  const input = (label: string) => (
    <label className={online ? 'btn btn--sm ck-file' : 'btn btn--sm ck-file ck-file--off'}>
      <input type="file" accept={RECEIPT_ACCEPT} aria-label="Attach receipt" disabled={!online}
        onChange={(e) => {
          const file = e.target.files?.[0]
          e.target.value = ''
          if (!file) return
          const p = receiptProblem(file)
          setProblem(p)
          if (!p) dispatch({ type: 'setReceipt', file })
        }} />
      {label}
    </label>
  )
  return (
    <div className="ck-receipt">
      {s.receipt ? (
        <div className="ck-receipt__row">
          <span className="ck-receipt__name">{s.receipt.name}</span>
          <button type="button" className="btn btn--sm btn--ghost" onClick={() => dispatch({ type: 'setReceipt', file: null })}>
            Remove
          </button>
        </div>
      ) : s.storedReceiptPath ? (
        <div className="ck-receipt__row">
          <span className="ck-receipt__name">Receipt attached</span>
          <a className="btn btn--sm btn--ghost" href={`/transactions/files/${s.storedReceiptPath}`} target="_blank" rel="noopener">
            View
          </a>
          {input('Replace')}
        </div>
      ) : (
        input('Attach receipt')
      )}
      {!online && <p className="ck-more__note">Add the receipt later when you're online (Edit)</p>}
      {problem && <p className="ck-more__error" role="alert">{problem}</p>}
    </div>
  )
}
