import { useId, useState } from 'react'
import { Sheet } from '../../ui/Sheet'
import { useCategoryActions } from './categoryHooks'
import type { CategoryItem, Rule } from './hooks'

export const RULE_HELP = 'Matches any merchant containing this text, ignoring case and accents. Minimum 2 characters.'

/** New rule (from "＋ Rule") or an existing one (tap on its chip). The pattern shows as stored.
 *  Server 400/409 appear on the field; offline and 429 are toasted by the action. */
export function RuleSheet({ open, onClose, rule, categoryId, categories }: {
  open: boolean; onClose(): void; rule: Rule | null; categoryId: string; categories: CategoryItem[]
}) {
  const actions = useCategoryActions()
  const fresh = () => ({ pattern: rule?.pattern ?? '', cat: rule?.category_id ?? categoryId, error: null as string | null })
  const [draft, setDraft] = useState(fresh)
  const opening = `${open}|${rule?.id ?? ''}|${categoryId}`
  const [seen, setSeen] = useState(opening)
  if (seen !== opening) {
    setSeen(opening)
    if (open) setDraft(fresh())
  }
  const [busy, setBusy] = useState(false)
  const helpId = useId()
  const errId = useId()

  const save = async () => {
    if (draft.pattern.trim().length < 2) return setDraft((d) => ({ ...d, error: 'Enter at least 2 characters.' }))
    setBusy(true)
    const out = await actions.saveRule({ id: rule?.id, pattern: draft.pattern.trim(), category_id: draft.cat })
    setBusy(false)
    if (out.ok) onClose()
    else if (out.kind === 'rejected') setDraft((d) => ({ ...d, error: out.message }))
  }
  const remove = async () => {
    if (!rule) return
    setBusy(true)
    const out = await actions.deleteRule(rule.id)
    setBusy(false)
    if (out.ok) onClose()
  }

  return (
    <Sheet open={open} onClose={onClose} title={rule ? 'Edit rule' : 'New rule'}>
      <div className="settings__form">
        <label className="ui-field">
          <span className="ui-field__label">Merchant contains</span>
          <input className="ui-input" value={draft.pattern} autoCapitalize="none" autoCorrect="off" spellCheck={false}
            aria-describedby={draft.error ? `${errId} ${helpId}` : helpId} aria-invalid={draft.error ? true : undefined}
            onChange={(e) => setDraft((d) => ({ ...d, pattern: e.target.value, error: null }))} />
        </label>
        {draft.error && <p id={errId} className="ui-field__error" role="alert">{draft.error}</p>}
        <p id={helpId} className="settings__help">{RULE_HELP}</p>
        <label className="ui-field">
          <span className="ui-field__label">Category</span>
          <select className="ui-input" value={draft.cat} onChange={(e) => setDraft((d) => ({ ...d, cat: e.target.value }))}>
            {categories.map((c) => <option key={c.id} value={c.id}>{c.icon ? `${c.icon} ` : ''}{c.name}</option>)}
          </select>
        </label>
        <div className="settings__btnrow">
          {rule && <button type="button" className="btn btn--danger" disabled={busy} onClick={() => void remove()}>Delete rule</button>}
          <button type="button" className="btn btn--primary" disabled={busy} onClick={() => void save()}>Save rule</button>
        </div>
      </div>
    </Sheet>
  )
}
