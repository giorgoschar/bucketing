import { useState } from 'react'
import { Sheet } from '../../ui/Sheet'
import type { Security } from './hooks'
import { useProfileActions } from './profileHooks'

export const groupSecret = (s: string) => s.replace(/\s+/g, '').match(/.{1,4}/g)?.join(' ') ?? ''
export const REENROL = 'Password sign-in needs 2FA. Set it up again to keep using Tameio.'

const copy = (text: string) => void navigator.clipboard?.writeText(text).catch(() => {})

/** 2FA set up and turn off. The secret and the backup codes live in this component's state only:
 *  never in the query cache, storage or the URL, and gone when it unmounts. */
export function TwoFactor({ security }: { security: Security }) {
  const actions = useProfileActions()
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null)
  const [setupOpen, setSetupOpen] = useState(false)
  const [reason, setReason] = useState<string | null>(null)
  const [code, setCode] = useState('')
  const [codes, setCodes] = useState<string[] | null>(null)
  const [offOpen, setOffOpen] = useState(false)
  const [password, setPassword] = useState('')
  const [offCode, setOffCode] = useState('')
  const [busy, setBusy] = useState(false)

  const openSetup = async (why: string | null = null) => {
    setReason(why); setCode(''); setSetup(null); setSetupOpen(true)
    const out = await actions.totpSetup()
    if (out.ok) setSetup(out.data as { secret: string; otpauth_uri: string })
    else if (!why) setSetupOpen(false) // after Turn off the sheet stays, so the reason is still read
  }
  const closeSetup = () => { setSetupOpen(false); setSetup(null); setCode('') }
  const enable = async () => {
    setBusy(true)
    const out = await actions.totpEnable(code.trim())
    setBusy(false)
    if (out.ok) { closeSetup(); setCodes((out.data as { backup_codes: string[] }).backup_codes) }
  }
  const turnOff = async () => {
    setBusy(true)
    const out = await actions.totpDisable({ current_password: password, code: offCode.trim() })
    setBusy(false)
    if (!out.ok) return
    setOffOpen(false); setPassword(''); setOffCode('')
    // Password sign-in requires 2FA: everything else now answers 403 until it is back on.
    if (security.password_session) void openSetup(REENROL)
  }

  return (
    <section className="ui-card settings__card" aria-labelledby="tfa-h">
      <h2 id="tfa-h" className="settings__h">Two-factor</h2>
      {security.totp_enabled ? (
        <div className="settings__line">
          <span className="settings__state"><span className="settings__on">On</span> · {`${security.backup_codes_remaining} backup codes left`}</span>
          <button type="button" className="btn btn--sm" onClick={() => setOffOpen(true)}>Turn off</button>
        </div>
      ) : (
        <div className="settings__line">
          <span className="settings__state">Off</span>
          <button type="button" className="btn btn--sm btn--primary" onClick={() => void openSetup()}>Set up</button>
        </div>
      )}

      <Sheet open={setupOpen} onClose={closeSetup} title="Set up 2FA" closeOnBackdrop={false}>
        {reason && <p role="status" className="notice settings__notice">{reason}</p>}
        {setup ? (
          <div className="settings__form">
            <p className="settings__help">Add this key to your authenticator app, then enter the code it shows.</p>
            <p className="settings__secret">{groupSecret(setup.secret)}</p>
            <div className="settings__btnrow">
              <button type="button" className="btn btn--sm" onClick={() => copy(setup.secret)}>Copy</button>
              <a className="btn btn--sm" href={setup.otpauth_uri}>Open in authenticator</a>
            </div>
            <label className="ui-field">
              <span className="ui-field__label">6-digit code</span>
              <input className="ui-input settings__code" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
                autoComplete="one-time-code" inputMode="numeric" pattern="[0-9]{6}" maxLength={6} />
            </label>
            <div className="settings__btnrow">
              <button type="button" className="btn" onClick={closeSetup}>Cancel</button>
              <button type="button" className="btn btn--primary" disabled={busy} onClick={() => void enable()}>Turn on</button>
            </div>
          </div>
        ) : <div className="ui-skeleton" role="status" aria-busy="true" aria-label="Loading" />}
      </Sheet>

      <Sheet open={codes !== null} onClose={() => setCodes(null)} title="Backup codes" closeOnBackdrop={false}>
        <div className="settings__form">
          <p className="settings__help">Each code signs you in once if you lose your phone. They are shown only now.</p>
          <ul className="settings__codes">{codes?.map((c) => <li key={c}>{c}</li>)}</ul>
          <div className="settings__btnrow">
            <button type="button" className="btn" onClick={() => copy((codes ?? []).join('\n'))}>Copy all</button>
            <button type="button" className="btn btn--primary" onClick={() => setCodes(null)}>I've saved these</button>
          </div>
        </div>
      </Sheet>

      <Sheet open={offOpen} onClose={() => setOffOpen(false)} title="Turn off 2FA">
        <div className="settings__form">
          <p className="settings__help">Your Apple Pay tokens will stop working and other devices will be signed out.</p>
          <label className="ui-field">
            <span className="ui-field__label">Password</span>
            <input className="ui-input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
          <label className="ui-field">
            <span className="ui-field__label">Authenticator code</span>
            <input className="ui-input settings__code" autoComplete="one-time-code" inputMode="numeric" maxLength={6} value={offCode}
              onChange={(e) => setOffCode(e.target.value.replace(/\D/g, ''))} />
          </label>
          <div className="settings__btnrow">
            <button type="button" className="btn" onClick={() => setOffOpen(false)}>Cancel</button>
            <button type="button" className="btn btn--danger" disabled={busy} onClick={() => void turnOff()}>Turn off 2FA</button>
          </div>
        </div>
      </Sheet>
    </section>
  )
}
