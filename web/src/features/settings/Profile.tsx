import { useState } from 'react'
import { useSession } from '../../session/SessionProvider'
import { setSignInNotice } from '../../session/notice'
import { BackHeader } from '../../ui/BackHeader'
import { QueryView } from '../../ui/QueryView'
import { Sheet } from '../../ui/Sheet'
import { type Profile as ProfileData, useProfile, useSecurity } from './hooks'
import { SWATCHES, swatchName } from './palette'
import { Passkey } from './Passkey'
import { useProfileActions } from './profileHooks'
import { TwoFactor } from './TwoFactor'
import './settings.css'

function ProfileForm({ profile }: { profile: ProfileData }) {
  const actions = useProfileActions()
  const [name, setName] = useState(profile.display_name)
  const [email, setEmail] = useState(profile.email ?? '')
  const [color, setColor] = useState<string>(profile.avatar_color?.toLowerCase() ?? SWATCHES[0])
  const [nameError, setNameError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const save = async () => {
    const trimmed = name.trim()
    if (trimmed.length < 1 || trimmed.length > 100) return setNameError('Use 1 to 100 characters.')
    setNameError(null)
    setBusy(true)
    await actions.saveProfile({ display_name: trimmed, email: email.trim() || null, avatar_color: color })
    setBusy(false)
  }

  return (
    <section className="ui-card settings__card" aria-labelledby="profile-h">
      <h2 id="profile-h" className="settings__h">Profile</h2>
      <div className="settings__form">
        <label className="ui-field">
          <span className="ui-field__label">Name</span>
          <input className="ui-input" value={name} maxLength={100} autoComplete="name" aria-invalid={nameError ? true : undefined}
            onChange={(e) => setName(e.target.value)} />
        </label>
        {nameError && <p className="ui-field__error" role="alert">{nameError}</p>}
        <label className="ui-field">
          <span className="ui-field__label">Email (optional)</span>
          <input className="ui-input" type="email" value={email} autoComplete="email" autoCapitalize="none" onChange={(e) => setEmail(e.target.value)} />
        </label>
        <div className="ui-field">
          <span className="ui-field__label" id="swatch-l">Avatar colour</span>
          <div className="settings__swatches" role="radiogroup" aria-labelledby="swatch-l">
            {SWATCHES.map((hex) => (
              <button key={hex} type="button" role="radio" aria-checked={color === hex} aria-label={swatchName(hex)}
                className="settings__swatch" style={{ '--tint': hex } as React.CSSProperties} onClick={() => setColor(hex)} />
            ))}
          </div>
        </div>
        <button type="button" className="btn btn--primary" disabled={busy} onClick={() => void save()}>Save profile</button>
      </div>
    </section>
  )
}

export function Profile() {
  const { signOut } = useSession()
  const profile = useProfile()
  const security = useSecurity()
  const actions = useProfileActions()
  const [pwOpen, setPwOpen] = useState(false)
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [pwError, setPwError] = useState<string | null>(null)

  const closePw = () => { setPwOpen(false); setCurrent(''); setNext(''); setPwError(null) }
  const changePassword = async () => {
    if (next.length < 12) return setPwError('Use at least 12 characters.')
    setPwError(null)
    const out = await actions.changePassword({ current_password: current, new_password: next })
    if (!out.ok) return
    setSignInNotice('Password changed. Sign in again.')
    await signOut() // the server ended every session
  }

  return (
    <>
      <BackHeader title="Profile & security" back="/settings" />
      <section className="screen settings">
        <QueryView result={profile} noDataText="No saved data yet. Connect once to load Settings.">
          {(p) => <ProfileForm key={profile.dataUpdatedAt} profile={p} />}
        </QueryView>

        <section className="ui-card settings__card" aria-labelledby="pw-h">
          <h2 id="pw-h" className="settings__h">Password</h2>
          <div className="settings__line">
            <span className="settings__state">Used with 2FA to sign in</span>
            <button type="button" className="btn btn--sm" onClick={() => setPwOpen(true)}>Change password</button>
          </div>
        </section>
        <Sheet open={pwOpen} onClose={closePw} title="Change password">
          <div className="settings__form">
            <p className="notice settings__notice">You'll be signed out everywhere and your Apple Pay tokens will stop working.</p>
            <label className="ui-field">
              <span className="ui-field__label">Current password</span>
              <input className="ui-input" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
            </label>
            <label className="ui-field">
              <span className="ui-field__label">New password</span>
              <input className="ui-input" type="password" autoComplete="new-password" minLength={12} value={next}
                aria-invalid={pwError ? true : undefined} onChange={(e) => setNext(e.target.value)} />
            </label>
            {pwError && <p className="ui-field__error" role="alert">{pwError}</p>}
            <div className="settings__btnrow">
              <button type="button" className="btn" onClick={closePw}>Cancel</button>
              <button type="button" className="btn btn--danger" onClick={() => void changePassword()}>Change and sign out</button>
            </div>
          </div>
        </Sheet>

        {security.data && <TwoFactor security={security.data} />}
        {security.data && <Passkey security={security.data} />}

        <button type="button" className="btn btn--danger btn--block" onClick={() => void signOut()}>Sign out</button>
      </section>
    </>
  )
}
