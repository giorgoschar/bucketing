import { useRef } from 'react'
import { useSession } from '../session/SessionProvider'
import { LogOutIcon } from './icons'

const HEX = /^#[0-9a-f]{6}$/i

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  const letters = parts.length > 1 ? parts[0][0] + parts[parts.length - 1][0] : (parts[0] ?? '?').slice(0, 1)
  return letters.toUpperCase()
}

export function TopBar({ title }: { title: string }) {
  const { me, signOut } = useSession()
  const sheet = useRef<HTMLDialogElement>(null)
  const cancel = useRef<HTMLButtonElement>(null)
  const name = me?.display_name || me?.username || ''
  // avatar_color is the user's own pick from the server's palette; fall back to a token.
  const tint = me?.avatar_color && HEX.test(me.avatar_color) ? me.avatar_color : undefined

  const close = () => sheet.current?.close()
  const open = () => {
    sheet.current?.showModal()
    cancel.current?.focus() // start on the safe choice, not the destructive one
  }
  const avatarClass = tint ? 'avatar' : 'avatar avatar--fallback'

  return (
    <header className="topbar">
      <h1 className="topbar__title">{title}</h1>
      <button
        type="button"
        className="topbar__account"
        aria-label="Account"
        aria-haspopup="dialog"
        onClick={open}
      >
        <span className={avatarClass} style={tint ? { background: tint } : undefined}>{initials(name)}</span>
      </button>
      <dialog
        ref={sheet}
        className="sheet"
        aria-label="Account"
        // The dialog has no padding and .sheet__body fills it, so a click that lands on the dialog
        // itself is a click on the ::backdrop outside the content.
        onClick={(e) => { if (e.target === e.currentTarget) close() }}
      >
        <div className="sheet__body">
          <div className="sheet__grab" aria-hidden="true" />
          <div className="sheet__who">
            <span className={`${avatarClass} avatar--lg`} style={tint ? { background: tint } : undefined}>{initials(name)}</span>
            <div>
              <div className="sheet__name">{name}</div>
              {me?.email && <div className="sheet__sub">{me.email}</div>}
            </div>
          </div>
          <button type="button" className="btn btn--danger btn--block" onClick={() => { close(); void signOut() }}>
            <LogOutIcon />
            Sign out
          </button>
          <button type="button" ref={cancel} className="btn btn--block" onClick={close}>Cancel</button>
        </div>
      </dialog>
    </header>
  )
}
