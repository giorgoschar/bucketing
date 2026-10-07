import { useEffect, useRef, type FormEvent } from 'react'
import { useSearchParams } from 'react-router'
import { readCsrf } from '../../api/client'
import { isOnline } from '../../data/online'
import { OFFLINE_MESSAGE } from '../../data/onlineAction'
import { useToast } from '../../ui/Toast'
import type { Security } from './hooks'

export const PASSKEY_MESSAGES = {
  linked: 'Passkey linked.',
  unlinked: 'Passkey unlinked.',
  // Never says which factor was wrong.
  error: "Couldn't link the passkey. Check your password and code.",
} as const
type Outcome = keyof typeof PASSKEY_MESSAGES

/** Native form posts: the server redirects to the identity provider, then back to
 *  /app/settings/profile?passkey=linked|unlinked|error. */
export function Passkey({ security }: { security: Security }) {
  const toast = useToast()
  const [params, setParams] = useSearchParams()
  const shown = useRef(false)
  const outcome = params.get('passkey')

  useEffect(() => {
    if (!outcome || shown.current) return
    shown.current = true
    if (outcome in PASSKEY_MESSAGES) {
      toast.show(PASSKEY_MESSAGES[outcome as Outcome], ...(outcome === 'error' ? [{ tone: 'error' as const }] : []))
    }
    setParams((p) => { const n = new URLSearchParams(p); n.delete('passkey'); return n }, { replace: true })
  }, [outcome, setParams, toast])

  if (!security.passkey_available) return null
  // A native post cannot be queued either: offline it would only show the browser's error page.
  const guard = (e: FormEvent) => { if (!isOnline()) { e.preventDefault(); toast.show(OFFLINE_MESSAGE, { tone: 'error' }) } }
  const hidden = (
    <>
      <input type="hidden" name="_csrf_token" value={readCsrf()} />
      <input type="hidden" name="return_to" value="app" />
    </>
  )

  return (
    <section className="ui-card settings__card" aria-labelledby="passkey-h">
      <h2 id="passkey-h" className="settings__h">Passkey</h2>
      {!security.password_session ? (
        <p className="settings__help">Sign in with your password and 2FA to change this.</p>
      ) : security.passkey_linked ? (
        <form method="post" action="/app/auth/unlink" onSubmit={guard} className="settings__line">
          {hidden}
          <span className="settings__state"><span className="settings__on">Linked</span> · Face ID signs you in</span>
          <button type="submit" className="btn btn--sm">Unlink</button>
        </form>
      ) : (
        <form method="post" action="/app/auth/link" onSubmit={guard} className="settings__form">
          {hidden}
          <p className="settings__help">Sign in with Face ID next time. You confirm with your password and code first.</p>
          <label className="ui-field">
            <span className="ui-field__label">Password</span>
            <input className="ui-input" type="password" name="password" autoComplete="current-password" required />
          </label>
          <label className="ui-field">
            <span className="ui-field__label">Authenticator code</span>
            <input className="ui-input settings__code" name="totp_code" autoComplete="one-time-code" inputMode="numeric" maxLength={6} required />
          </label>
          <button type="submit" className="btn btn--primary">Link passkey</button>
        </form>
      )}
    </section>
  )
}
