import { useState } from 'react'
import { Badge } from '../../ui/Badge'
import { BackHeader } from '../../ui/BackHeader'
import { QueryView } from '../../ui/QueryView'
import { Sheet } from '../../ui/Sheet'
import { type TokenItem, useBuckets, useTokens } from './hooks'
import { RecentAttempts } from './RecentAttempts'
import { lastUsed, useTokenActions } from './tokenHooks'
import './settings.css'

const STEPS = [
  { title: 'Create a token below', body: 'Copy it. Tameio shows it only once.' },
  { title: 'Add the Tameio Shortcut', body: 'Paste the token when the Shortcut asks for it.' },
  { title: 'Turn on the Wallet automation', body: 'Shortcuts › Automation › Wallet › “When I tap any card” › Run Tameio.' },
]

const ASK_STEPS = [
  'If needs_category (from the Tameio reply) is true…',
  'Choose from List over category_names.',
  'Get Contents of URL: a second POST to …/ingest/apple-pay/<id>/classify, with the same token, and the JSON {"category": <Chosen Item>}.',
]

export function Automations() {
  const tokens = useTokens()
  const buckets = useBuckets().data ?? []
  const actions = useTokenActions()
  const [name, setName] = useState('')
  const [bucket, setBucket] = useState('')
  const [classify, setClassify] = useState(false)
  const [nameError, setNameError] = useState<string | null>(null)
  // The plaintext token: this component's state only, gone when the screen is left.
  const [fresh, setFresh] = useState<string | null>(null)
  const [revoking, setRevoking] = useState<TokenItem | null>(null)
  const [busy, setBusy] = useState(false)
  const bucketName = (id: string | null) => buckets.find((b) => b.id === id)?.name ?? 'No default budget'

  const create = async () => {
    const trimmed = name.trim()
    if (trimmed.length < 1 || trimmed.length > 60) return setNameError('Use 1 to 60 characters.')
    setNameError(null)
    setBusy(true)
    const out = await actions.create({ name: trimmed, default_bucket_id: bucket || null, ...(classify ? { allow_classify: true } : {}) })
    setBusy(false)
    if (out.ok) { setFresh(out.data.token); setName(''); setBucket(''); setClassify(false) }
  }
  const revoke = async () => {
    if (!revoking) return
    setBusy(true)
    const out = await actions.revoke(revoking.id)
    setBusy(false)
    if (out.ok) setRevoking(null)
  }

  return (
    <>
      <BackHeader title="Apple Pay" back="/settings" />
      <section className="screen settings">
        <section className="ui-card settings__card" aria-labelledby="steps-h">
          <h2 id="steps-h" className="settings__h">Log Apple Pay purchases on their own</h2>
          <ol className="settings__steps">
            {STEPS.map((s, i) => (
              <li key={s.title} aria-label={`Step ${i + 1}: ${s.title}`}>
                <span className="settings__stepn" aria-hidden="true">{i + 1}</span>
                <span><b>{s.title}</b><span className="settings__help">{s.body}</span></span>
              </li>
            ))}
          </ol>
        </section>

        {fresh && (
          <div className="ui-card settings__card settings__fresh" role="alert">
            <p className="settings__h">Copy your new token now</p>
            <p className="settings__help">You won't see it again after you leave this screen.</p>
            <p className="settings__secret">{fresh}</p>
            <button type="button" className="btn btn--primary" onClick={() => void navigator.clipboard?.writeText(fresh).catch(() => {})}>Copy token</button>
          </div>
        )}

        <QueryView result={tokens} noDataText="No saved data yet. Connect once to load Settings.">
          {(list) => list.length > 0 && (
            <section aria-labelledby="tokens-h">
              <h2 id="tokens-h" className="settings__group">Tokens</h2>
              <ul className="ui-list settings__tokens" aria-label="Tokens">
                {list.map((t) => (
                  <li key={t.id} className="ui-row">
                    <span className="ui-row__main">
                      <span className="ui-row__title">{t.name}</span>
                      {t.can_classify && <span><Badge tone="acc">Can ask for a category</Badge></span>}
                      <span className="ui-row__sub">{`${t.prefix} · ${bucketName(t.default_bucket_id)} · ${lastUsed(t.last_used_at)}`}</span>
                    </span>
                    <button type="button" className="btn btn--sm btn--danger" aria-label={`Revoke ${t.name}`} onClick={() => setRevoking(t)}>Revoke</button>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </QueryView>

        <RecentAttempts />

        <section className="ui-card settings__card" aria-labelledby="new-token">
          <h2 id="new-token" className="settings__h">New token</h2>
          <div className="settings__form">
            <label className="ui-field">
              <span className="ui-field__label">Token name</span>
              <input className="ui-input" value={name} placeholder="Giorgos iPhone" aria-invalid={nameError ? true : undefined}
                onChange={(e) => setName(e.target.value)} />
            </label>
            {nameError && <p className="ui-field__error" role="alert">{nameError}</p>}
            <label className="ui-field">
              <span className="ui-field__label">Default budget</span>
              <select className="ui-input" value={bucket} onChange={(e) => setBucket(e.target.value)}>
                <option value="">None</option>
                {buckets.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
              </select>
            </label>
            <label className="ui-check">
              <span>Let the Shortcut ask for a category (shares your category and budget names with the Shortcut)</span>
              <input type="checkbox" checked={classify} onChange={(e) => setClassify(e.target.checked)} />
            </label>
            <button type="button" className="btn btn--primary" disabled={busy} onClick={() => void create()}>Create token</button>
          </div>
        </section>

        <section className="ui-card settings__card" aria-labelledby="ask-h" role="region">
          <h2 id="ask-h" className="settings__h">Ask for a category</h2>
          <p className="settings__help">For a token that is allowed to ask. After the purchase is saved, the Shortcut can offer your categories:</p>
          <ol className="settings__steps">
            {ASK_STEPS.map((t, i) => (
              <li key={i}>
                <span className="settings__stepn" aria-hidden="true">{i + 1}</span>
                <span className="settings__help">{t}</span>
              </li>
            ))}
          </ol>
          <p className="settings__help">To stop being asked about a merchant, add a rule in Settings › Categories &amp; rules.</p>
        </section>

        <p className="settings__help">Purchases arrive tagged Apple Pay with no payer. You pick who paid from Home.</p>
      </section>

      <Sheet open={revoking !== null} onClose={() => setRevoking(null)} title="Revoke token">
        <div className="settings__form">
          <p className="settings__help">{revoking ? `The Shortcut using “${revoking.name}” stops working.` : ''}</p>
          <div className="settings__btnrow">
            <button type="button" className="btn" onClick={() => setRevoking(null)}>Cancel</button>
            <button type="button" className="btn btn--danger" disabled={busy} onClick={() => void revoke()}>Revoke token</button>
          </div>
        </div>
      </Sheet>
    </>
  )
}
