import { useState } from 'react'
import { useSession } from '../../session/SessionProvider'
import { BackHeader } from '../../ui/BackHeader'
import { Badge } from '../../ui/Badge'
import { QueryView } from '../../ui/QueryView'
import { Sheet } from '../../ui/Sheet'
import { type HouseholdInfo, type HouseholdMember, useHousehold } from './hooks'
import { inviteUrl, useHouseholdActions } from './householdHooks'
import './settings.css'

const nameOf = (m: HouseholdMember) => m.display_name || m.username || 'Member'
const HEX = /^#[0-9a-f]{6}$/i

const MoreIcon = () => (
  <svg viewBox="0 0 24 24" className="ui-icon" aria-hidden="true" focusable="false" fill="currentColor">
    <circle cx="5" cy="12" r="1.8" /><circle cx="12" cy="12" r="1.8" /><circle cx="19" cy="12" r="1.8" />
  </svg>
)

function NameCard({ h, owner }: { h: HouseholdInfo; owner: boolean }) {
  const actions = useHouseholdActions()
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const save = async () => {
    const trimmed = name.trim()
    if (!trimmed) return
    setBusy(true)
    const out = await actions.rename(trimmed, h.default_currency)
    setBusy(false)
    if (out.ok) setEditing(false)
  }
  return (
    <section className="ui-card settings__card" aria-label="Household">
      {editing ? (
        <div className="settings__form">
          <label className="ui-field">
            <span className="ui-field__label">Household name</span>
            <input className="ui-input" value={name} maxLength={100} autoFocus onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') void save() }} />
          </label>
          <div className="settings__btnrow">
            <button type="button" className="btn" onClick={() => setEditing(false)}>Cancel</button>
            <button type="button" className="btn btn--primary" disabled={busy} onClick={() => void save()}>Save</button>
          </div>
        </div>
      ) : (
        <div className="settings__line">
          <span className="settings__name">{h.name}</span>
          {owner && <button type="button" className="btn btn--sm btn--ghost" aria-label="Edit name" onClick={() => { setName(h.name); setEditing(true) }}>Edit</button>}
        </div>
      )}
      <div className="settings__line">
        <span className="settings__state">Currency</span>
        <span className="settings__state">{h.default_currency} · Fixed</span>
      </div>
    </section>
  )
}

export function Household() {
  const me = useSession().me
  const household = useHousehold()
  const actions = useHouseholdActions()
  const [menuFor, setMenuFor] = useState<HouseholdMember | null>(null)
  const [confirm, setConfirm] = useState<HouseholdMember | null>(null)
  const [link, setLink] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const newLink = async () => {
    setBusy(true)
    const out = await actions.invite()
    setBusy(false)
    if (out.ok) setLink(inviteUrl(out.data.token))
  }
  const remove = async () => {
    if (!confirm) return
    setBusy(true)
    const out = await actions.removeMember(confirm.user_id)
    setBusy(false)
    if (out.ok) setConfirm(null)
  }

  return (
    <>
      <BackHeader title="Household" back="/settings" />
      <section className="screen settings">
        <QueryView result={household} noDataText="No saved data yet. Connect once to load Settings.">
          {(h) => {
            const owner = h.members.some((m) => m.user_id === me?.id && m.role === 'owner')
            return (
              <>
                <NameCard h={h} owner={owner} />

                <section aria-labelledby="members-h">
                  <h2 id="members-h" className="settings__group">Members</h2>
                  <ul className="ui-list settings__members">
                    {h.members.map((m) => {
                      const tint = m.avatar_color && HEX.test(m.avatar_color) ? m.avatar_color : undefined
                      return (
                        <li key={m.user_id} className="ui-row">
                          <span className={tint ? 'avatar' : 'avatar avatar--fallback'} style={tint ? { background: tint } : undefined} aria-hidden="true">
                            {nameOf(m).slice(0, 1).toUpperCase()}
                          </span>
                          <span className="ui-row__main"><span className="ui-row__title">{m.user_id === me?.id ? `${nameOf(m)} (you)` : nameOf(m)}</span></span>
                          <Badge tone={m.role === 'owner' ? 'acc' : 'neutral'}>{m.role === 'owner' ? 'Owner' : 'Member'}</Badge>
                          {owner && m.user_id !== me?.id && (
                            <button type="button" className="ui-iconbtn ui-iconbtn--bare" aria-label={`Actions for ${nameOf(m)}`} onClick={() => setMenuFor(m)}>
                              <MoreIcon />
                            </button>
                          )}
                        </li>
                      )
                    })}
                  </ul>
                </section>

                {owner && (
                  <section className="ui-card settings__card" aria-labelledby="invite-h">
                    <h2 id="invite-h" className="settings__h">Invite</h2>
                    {link ? (
                      <>
                        <p className="settings__secret">{link}</p>
                        <p className="settings__help">Expires in 7 days · single use</p>
                        <div className="settings__btnrow">
                          <button type="button" className="btn" onClick={() => void navigator.clipboard?.writeText(link).catch(() => {})}>Copy</button>
                          <button type="button" className="btn" disabled={busy} onClick={() => void newLink()}>New link</button>
                        </div>
                      </>
                    ) : (
                      <>
                        <p className="settings__help">A link someone opens to join this household. It works once.</p>
                        <button type="button" className="btn btn--primary" disabled={busy} onClick={() => void newLink()}>New link</button>
                      </>
                    )}
                  </section>
                )}
              </>
            )
          }}
        </QueryView>
      </section>

      <Sheet open={menuFor !== null} onClose={() => setMenuFor(null)} title={menuFor ? nameOf(menuFor) : 'Member'}>
        <button type="button" className="btn btn--danger btn--block" onClick={() => { setConfirm(menuFor); setMenuFor(null) }}>Remove from household</button>
      </Sheet>
      <Sheet open={confirm !== null} onClose={() => setConfirm(null)} title="Remove member">
        <div className="settings__form">
          <p className="settings__help">{confirm ? `${nameOf(confirm)} loses access to this household's data.` : ''}</p>
          <div className="settings__btnrow">
            <button type="button" className="btn" onClick={() => setConfirm(null)}>Cancel</button>
            <button type="button" className="btn btn--danger" disabled={busy} onClick={() => void remove()}>
              {confirm ? `Remove ${nameOf(confirm)}` : 'Remove'}
            </button>
          </div>
        </div>
      </Sheet>
    </>
  )
}
