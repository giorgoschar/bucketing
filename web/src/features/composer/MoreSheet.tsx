import { type Dispatch, type ReactNode, useState } from 'react'
import { ToggleRow } from '../../ui/ToggleRow'
import { type Member, Sheet } from './bridge'
import type { Validation } from './model'
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
  return (
    <Sheet open={open} onClose={onClose} title="More"
      footer={<button type="button" className="btn btn--primary btn--lg btn--block" onClick={onClose}>Done</button>}>
      {!income && (
        <Section title="Date">
          <DateChips value={s.date} today={ctx.today} onPick={(d) => dispatch({ type: 'setDate', value: d })} />
          {ctx.problems.date && <p className="ck-more__error">{ctx.problems.date}</p>}
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
