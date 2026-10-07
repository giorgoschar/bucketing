import { type CSSProperties, useState } from 'react'
import { BackHeader } from '../../ui/BackHeader'
import { Badge } from '../../ui/Badge'
import { PlusIcon } from '../../ui/icons'
import { QueryView } from '../../ui/QueryView'
import { Sheet } from '../../ui/Sheet'
import { type CategoryBody, deleteMessage, ruleChip, useCategoryActions } from './categoryHooks'
import { type CategoryItem, type Rule, useCategories, useRules } from './hooks'
import { SWATCHES, swatchName } from './palette'
import { RuleSheet } from './RuleSheet'
import './settings.css'

const LOCKED_NOTE = 'The composer needs this one to ask for litres.'

function Editor({ initial, onSave, onCancel, onDelete }: {
  initial: CategoryBody; onSave(b: CategoryBody): Promise<unknown>; onCancel(): void; onDelete?(): void
}) {
  const [body, setBody] = useState(initial)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const save = async () => {
    const name = body.name.trim()
    if (!name) return setError('Enter a name.')
    setError(null)
    setBusy(true)
    await onSave({ ...body, name })
    setBusy(false)
  }
  return (
    <div className="settings__editor settings__form">
      <label className="ui-field">
        <span className="ui-field__label">Category name</span>
        <input className="ui-input" value={body.name} maxLength={50} aria-invalid={error ? true : undefined}
          onChange={(e) => setBody({ ...body, name: e.target.value })} />
      </label>
      {error && <p className="ui-field__error" role="alert">{error}</p>}
      <div className="ui-field">
        <span className="ui-field__label">Colour</span>
        <div className="settings__swatches" role="radiogroup" aria-label="Colour">
          {SWATCHES.map((hex) => (
            <button key={hex} type="button" role="radio" aria-checked={body.color.toLowerCase() === hex} aria-label={swatchName(hex)}
              className="settings__swatch" style={{ '--tint': hex } as CSSProperties} onClick={() => setBody({ ...body, color: hex })} />
          ))}
        </div>
      </div>
      <label className="ui-field">
        <span className="ui-field__label">Icon</span>
        <input className="ui-input settings__icon-input" value={body.icon} maxLength={10} onChange={(e) => setBody({ ...body, icon: e.target.value })} />
      </label>
      <div className="settings__btnrow">
        {onDelete && <button type="button" className="btn btn--danger" onClick={onDelete}>Delete</button>}
        <button type="button" className="btn" onClick={onCancel}>Cancel</button>
        <button type="button" className="btn btn--primary" disabled={busy} onClick={() => void save()}>Save</button>
      </div>
    </div>
  )
}

export function Categories() {
  const categories = useCategories()
  const rules = useRules().data ?? []
  const actions = useCategoryActions()
  const [open, setOpen] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [rule, setRule] = useState<{ rule: Rule | null; categoryId: string } | null>(null)
  const [confirm, setConfirm] = useState<CategoryItem | null>(null)
  const [busy, setBusy] = useState(false)
  const byCategory = (id: string) => rules.filter((r) => r.category_id === id)

  const removeConfirmed = async () => {
    if (!confirm) return
    setBusy(true)
    const out = await actions.remove(confirm.id)
    setBusy(false)
    if (out.ok) { setConfirm(null); setOpen(null) }
  }

  return (
    <>
      <BackHeader title="Categories & rules" back="/settings"
        action={<button type="button" className="ui-iconbtn ui-iconbtn--bare" aria-label="Add category" onClick={() => setAdding(true)}><PlusIcon /></button>} />
      <section className="screen settings">
        {adding && (
          <section className="ui-card settings__card" aria-label="New category">
            <Editor initial={{ name: '', color: SWATCHES[0], icon: '📦' }} onCancel={() => setAdding(false)}
              onSave={async (b) => { if ((await actions.create(b)).ok) setAdding(false) }} />
          </section>
        )}
        <QueryView result={categories} noDataText="No saved data yet. Connect once to load Settings.">
          {(list) => (
            <ul className="ui-list settings__cats">
              {list.map((c) => {
                const mine = byCategory(c.id)
                const expanded = open === c.id
                return (
                  <li key={c.id} data-testid={`cat-${c.id}`} className="settings__cat">
                    <button type="button" className="ui-row" aria-expanded={expanded} onClick={() => setOpen(expanded ? null : c.id)}>
                      <span className="settings__catico" style={{ '--tint': c.color ?? 'var(--c6)' } as CSSProperties} aria-hidden="true">{c.icon ?? '📦'}</span>
                      <span className="ui-row__main"><span className="ui-row__title">{c.name}</span></span>
                      {c.locked && <Badge>System</Badge>}
                    </button>
                    {mine.length > 0 && (
                      <div className="settings__rules" role="group" aria-label={`Rules for ${c.name}`}>
                        {mine.map((r) => (
                          <button key={r.id} type="button" className="settings__rule" onClick={() => setRule({ rule: r, categoryId: c.id })}>
                            {ruleChip(r)}
                          </button>
                        ))}
                      </div>
                    )}
                    {expanded && (c.locked ? (
                      <p className="settings__help settings__locked">{LOCKED_NOTE}</p>
                    ) : (
                      <div className="settings__expand">
                        <Editor initial={{ name: c.name, color: c.color ?? SWATCHES[0], icon: c.icon ?? '📦' }} onCancel={() => setOpen(null)}
                          onSave={async (b) => { if ((await actions.update(c.id, b)).ok) setOpen(null) }}
                          onDelete={c.is_default ? undefined : () => setConfirm(c)} />
                        <button type="button" className="btn btn--sm settings__addrule" onClick={() => setRule({ rule: null, categoryId: c.id })}>＋ Rule</button>
                      </div>
                    ))}
                  </li>
                )
              })}
            </ul>
          )}
        </QueryView>
      </section>

      <RuleSheet open={rule !== null} onClose={() => setRule(null)} rule={rule?.rule ?? null} categoryId={rule?.categoryId ?? ''} categories={categories.data ?? []} />
      <Sheet open={confirm !== null} onClose={() => setConfirm(null)} title={confirm ? `Delete ${confirm.name}?` : 'Delete'}>
        <div className="settings__form">
          <p className="settings__help">{confirm ? deleteMessage(confirm) : ''}</p>
          <div className="settings__btnrow">
            <button type="button" className="btn" onClick={() => setConfirm(null)}>Cancel</button>
            <button type="button" className="btn btn--danger" disabled={busy} onClick={() => void removeConfirmed()}>Delete category</button>
          </div>
        </div>
      </Sheet>
    </>
  )
}
