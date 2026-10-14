import { useState } from 'react'
import { Badge } from '../../ui/Badge'
import { Sheet } from '../../ui/Sheet'
import { type HouseholdMember } from './hooks'
import { useHouseholdActions, useHouseholds } from './householdHooks'

const nameOf = (m: HouseholdMember) => m.display_name || m.username || 'Member'

/** Your households: switch (only when there is more than one) and start a new one. */
export function Households() {
  const actions = useHouseholdActions()
  const list = useHouseholds().data ?? []
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const create = async () => {
    if (!name.trim()) return
    setBusy(true)
    await actions.create(name.trim())
    setBusy(false)
  }
  const switchTo = async (id: string) => {
    setBusy(true)
    await actions.switchTo(id)
    setBusy(false)
  }
  return (
    <section className="ui-card settings__card" aria-labelledby="hh-h">
      <h2 id="hh-h" className="settings__h">Households</h2>
      {list.length > 1 && (
        <ul className="ui-list">
          {list.map((h) => (
            <li key={h.id} className="ui-row">
              <span className="ui-row__main"><span className="ui-row__title">{h.name}</span></span>
              {h.active ? (
                <Badge tone="acc">Current</Badge>
              ) : (
                <button type="button" className="btn btn--sm" disabled={busy} aria-label={`Switch to ${h.name}`} onClick={() => void switchTo(h.id)}>Switch</button>
              )}
            </li>
          ))}
        </ul>
      )}
      {creating ? (
        <div className="settings__form">
          <label className="ui-field">
            <span className="ui-field__label">Household name</span>
            <input className="ui-input" value={name} maxLength={100} autoFocus onChange={(e) => setName(e.target.value)} />
          </label>
          <div className="settings__btnrow">
            <button type="button" className="btn" onClick={() => setCreating(false)}>Cancel</button>
            <button type="button" className="btn btn--primary" disabled={busy || !name.trim()} onClick={() => void create()}>Create household</button>
          </div>
        </div>
      ) : (
        <button type="button" className="btn" onClick={() => setCreating(true)}>New household</button>
      )}
    </section>
  )
}

/** Leave this household, asked in the page. An owner with other members must hand over first; the last
 *  member must type the name, because leaving archives the household for everyone. */
export function LeaveCard({ householdName, owner, others }: { householdName: string; owner: boolean; others: number }) {
  const actions = useHouseholdActions()
  const [open, setOpen] = useState(false)
  const [typed, setTyped] = useState('')
  const [busy, setBusy] = useState(false)
  const last = others === 0
  const blocked = owner && !last
  const leave = async () => {
    setBusy(true)
    await actions.leave(last ? typed : '')
    setBusy(false)
  }
  const close = () => { setOpen(false); setTyped('') }
  return (
    <>
      <section className="ui-card settings__card" aria-label="Leave household">
        <button type="button" className="btn btn--danger" onClick={() => setOpen(true)}>Leave household</button>
      </section>
      <Sheet open={open} onClose={close} title="Leave household">
        <div className="settings__form">
          {blocked ? (
            <p className="settings__help">You are the owner. Make someone else the owner, or remove the other members, before you leave.</p>
          ) : last ? (
            <>
              <p className="settings__help">You are the last member. Leaving archives this household for everyone.</p>
              <label className="ui-field">
                <span className="ui-field__label">Type the household name</span>
                <input className="ui-input" value={typed} autoComplete="off" onChange={(e) => setTyped(e.target.value)} />
              </label>
            </>
          ) : (
            <p className="settings__help">You lose access to this household&apos;s data. Someone has to invite you to come back.</p>
          )}
          <div className="settings__btnrow">
            <button type="button" className="btn" onClick={close}>{blocked ? 'Close' : 'Cancel'}</button>
            {!blocked && (
              <button type="button" className="btn btn--danger" disabled={busy || (last && typed.trim() !== householdName)} onClick={() => void leave()}>
                Leave {householdName}
              </button>
            )}
          </div>
        </div>
      </Sheet>
    </>
  )
}

export type MemberStep = { kind: 'transfer' | 'reset' | 'remove'; member: HouseholdMember }

/** The owner's action menu for one member, and the in-page confirmation each action asks for. */
export function MemberSheets({ menuFor, onMenu, step, onStep }: {
  menuFor: HouseholdMember | null
  onMenu: (m: HouseholdMember | null) => void
  step: MemberStep | null
  onStep: (s: MemberStep | null) => void
}) {
  const actions = useHouseholdActions()
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const m = step?.member
  const close = () => { onStep(null); setCode('') }
  const run = async () => {
    if (!step) return
    setBusy(true)
    const out = step.kind === 'transfer' ? await actions.transferOwnership(step.member.user_id)
      : step.kind === 'reset' ? await actions.resetTwoFactor(step.member.user_id, code.trim())
        : await actions.removeMember(step.member.user_id)
    setBusy(false)
    if (out.ok) close()
  }
  const pick = (kind: MemberStep['kind']) => { if (menuFor) onStep({ kind, member: menuFor }); onMenu(null) }
  return (
    <>
      <Sheet open={menuFor !== null} onClose={() => onMenu(null)} title={menuFor ? nameOf(menuFor) : 'Member'}>
        <div className="settings__form">
          <button type="button" className="btn btn--block" onClick={() => pick('transfer')}>Make owner</button>
          <button type="button" className="btn btn--block" onClick={() => pick('reset')}>Reset 2FA</button>
          <button type="button" className="btn btn--danger btn--block" onClick={() => pick('remove')}>Remove from household</button>
        </div>
      </Sheet>
      <Sheet open={step !== null} onClose={close} title={step?.kind === 'transfer' ? 'Make owner' : step?.kind === 'reset' ? 'Reset 2FA' : 'Remove member'}>
        {step && m && (
          <div className="settings__form">
            {step.kind === 'transfer' && <p className="settings__help">{nameOf(m)} will become the owner. You become a member and can no longer manage the household.</p>}
            {step.kind === 'remove' && <p className="settings__help">{nameOf(m)} loses access to this household&apos;s data.</p>}
            {step.kind === 'reset' && (
              <>
                <p className="settings__help">{nameOf(m)} loses their authenticator and passkey, is signed out everywhere, and sets 2FA up again at next sign-in.</p>
                <label className="ui-field">
                  <span className="ui-field__label">Your authenticator code</span>
                  <input className="ui-input" inputMode="numeric" autoComplete="one-time-code" maxLength={8} value={code} onChange={(e) => setCode(e.target.value)} />
                </label>
              </>
            )}
            <div className="settings__btnrow">
              <button type="button" className="btn" onClick={close}>Cancel</button>
              <button type="button" className={`btn ${step.kind === 'transfer' ? 'btn--primary' : 'btn--danger'}`} disabled={busy || (step.kind === 'reset' && code.trim().length < 6)} onClick={() => void run()}>
                {step.kind === 'transfer' ? `Make ${nameOf(m)} the owner` : step.kind === 'reset' ? `Reset ${nameOf(m)}’s 2FA` : `Remove ${nameOf(m)}`}
              </button>
            </div>
          </div>
        )}
      </Sheet>
    </>
  )
}
