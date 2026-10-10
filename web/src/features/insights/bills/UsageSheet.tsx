import { useState } from 'react'
import { useOnline } from '../../../data/online'
import '../../plan/entry.css'
import { Sheet } from '../../../ui/Sheet'
import { formatShortDate } from '../../../ui/format'
import { useSetUsage } from './hooks'
import { parseUsage } from './usage'

export interface UsageSheetTarget { entryId: string; dueDate: string; usage: number | null }

/** Edit usage on one past entry (spec §5.3, §3.3). Online only. */
export function UsageSheet({ itemId, unit, target, onClose }: { itemId: string; unit: string; target: UsageSheetTarget | null; onClose: () => void }) {
  return (
    <Sheet open={target !== null} onClose={onClose} title="Edit usage">
      {target && <Body key={target.entryId} itemId={itemId} unit={unit} target={target} onClose={onClose} />}
    </Sheet>
  )
}

function Body({ itemId, unit, target, onClose }: { itemId: string; unit: string; target: UsageSheetTarget; onClose: () => void }) {
  const online = useOnline()
  const save = useSetUsage(itemId)
  const [text, setText] = useState(target.usage === null ? '' : String(target.usage))
  const [problem, setProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const parsed = parseUsage(text)

  const submit = async () => {
    if (parsed === undefined || !online) return
    setBusy(true)
    setProblem(null)
    const r = await save(target.entryId, parsed)
    setBusy(false)
    if (r.ok) onClose()
    else if (r.kind === 'rejected') setProblem(r.message)
  }

  return (
    <form className="entry__form" onSubmit={(e) => { e.preventDefault(); void submit() }}>
      <p className="entry__due">{formatShortDate(target.dueDate)}</p>
      <label className="ui-field">
        <span className="ui-field__label">{`Usage (${unit})`}</span>
        <input className="ui-input ui-num" inputMode="decimal" autoComplete="off" value={text} aria-invalid={parsed === undefined}
          onChange={(e) => setText(e.target.value)} />
      </label>
      {parsed === undefined && <p className="ui-field__error">Enter a number like 412.5, or leave it empty to clear it.</p>}
      {problem && <p className="entry__problem" role="alert">{problem}</p>}
      {!online && <p className="billhist__offline">Connect to change usage</p>}
      <button type="submit" className="btn btn--primary btn--block btn--lg" disabled={parsed === undefined || !online || busy}>Save usage</button>
    </form>
  )
}
