import { useState } from 'react'
import { usePushState } from '../../pwa/pushClient'
import { BackHeader } from '../../ui/BackHeader'
import { Toggle } from '../../ui/Toggle'
import { useToast } from '../../ui/Toast'
import { useNotificationPrefs } from './hooks'
import { disabledAfter, useNotificationActions } from './notificationHooks'
import './settings.css'

/** The groups the screen knows, in the order it shows them. Any other group the server sends follows them. */
const KNOWN_GROUPS = ['Bills', 'Budgets', 'Pantry', 'Insights', 'Apple Pay']

function groupsOf(present: string[]): string[] {
  const known = KNOWN_GROUPS.filter((g) => present.includes(g))
  return [...known, ...Array.from(new Set(present.filter((g) => !KNOWN_GROUPS.includes(g))))]
}

export function Notifications() {
  const { state, refresh } = usePushState()
  const prefs = useNotificationPrefs().data
  const actions = useNotificationActions()
  const toast = useToast()
  const [busy, setBusy] = useState<string | null>(null)

  const run = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key)
    try { await fn() } finally { setBusy(null); refresh() }
  }
  const sendTest = () => run('test', async () => {
    const out = await actions.test()
    if (!out.ok) return
    const res = out.data as { sent?: boolean; error?: string | null } | undefined
    if (res?.sent) toast.show('Test sent. It should arrive in a few seconds.')
    else toast.show(res?.error || 'The test was not sent.', { tone: 'error' })
  })
  const pushNote =
    state === 'denied' ? 'Allowed in iOS Settings'
    : state === 'not-installed' ? 'Add Tameio to your Home Screen to get push alerts.'
    : state === 'unsupported' ? "This browser can't receive push alerts."
    : null
  const blocked = state === 'denied' || state === 'not-installed' || state === 'unsupported'

  return (
    <>
      <BackHeader title="Notifications" back="/settings" />
      <section className="screen settings">
        <section className="ui-card settings__card" aria-label="Push">
          <div className="settings__line">
            <span className="settings__label">
              <span className="settings__labeltitle">Push on this device</span>
              {pushNote && <span className="settings__help">{pushNote}</span>}
            </span>
            <Toggle label="Push on this device" checked={state === 'on'} busy={busy === 'push' || state === null} disabled={blocked}
              onChange={(on) => void run('push', on ? actions.pushOn : actions.pushOff)} />
          </div>
          {state === 'on' && (
            <button type="button" className="btn btn--sm settings__test" disabled={busy === 'test'} onClick={() => void sendTest()}>Send test</button>
          )}
        </section>

        {prefs && groupsOf(prefs.types.map((t) => t.group)).map((group) => {
          const types = prefs.types.filter((t) => t.group === group)
          if (!types.length) return null
          const id = `alerts-${group.replace(/\s+/g, '-').toLowerCase()}`
          return (
            <section key={group} aria-labelledby={id}>
              <h2 id={id} className="settings__group">{group}</h2>
              <div className="ui-list">
                {types.map((t) => (
                  <div key={t.type} className="ui-row settings__toggle-row">
                    <span className="ui-row__main"><span className="ui-row__title">{t.label}</span></span>
                    <Toggle label={t.label} checked={t.enabled} busy={busy === t.type}
                      onChange={(on) => void run(t.type, () => actions.setDisabled(disabledAfter(prefs, t.type, on)))} />
                  </div>
                ))}
              </div>
            </section>
          )
        })}
        {prefs && <p className="settings__help">Off stops both the in-app notification and the push, for you in this household.</p>}
      </section>
    </>
  )
}
