import { forwardRef, useImperativeHandle, useRef } from 'react'
import { Link, useInRouterContext } from 'react-router'
import { useSession } from '../session/SessionProvider'
import { avatarLook } from './avatar'
import { LogOutIcon } from './icons'

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  const letters = parts.length > 1 ? parts[0][0] + parts[parts.length - 1][0] : (parts[0] ?? '?').slice(0, 1)
  return letters.toUpperCase()
}

/** The signed-in member's avatar: initials on their own colour. */
export function MyAvatar() {
  const { me } = useSession()
  const name = me?.display_name || me?.username || ''
  // avatar_color is the user's own pick from the server's palette (with an initial that reads on it); else a token.
  const look = avatarLook(me?.avatar_color)
  return <span className={look.className} style={look.style}>{initials(name)}</span>
}

export type AccountDialogHandle = { open: () => void }

/** The account sheet (name, Settings, Sign out). The top bar's avatar opens it on the phone, the sidebar's on desktop. */
export const AccountDialog = forwardRef<AccountDialogHandle>(function AccountDialog(_props, ref) {
  const { me, signOut } = useSession()
  // Screens always render inside the router; the fallback keeps it usable on its own (unit tests).
  const inRouter = useInRouterContext()
  const sheet = useRef<HTMLDialogElement>(null)
  const cancel = useRef<HTMLButtonElement>(null)
  const name = me?.display_name || me?.username || ''
  const large = avatarLook(me?.avatar_color, 'avatar--lg')

  const close = () => sheet.current?.close()
  useImperativeHandle(ref, () => ({
    open() {
      sheet.current?.showModal()
      cancel.current?.focus() // start on the safe choice, not the destructive one
    },
  }))

  return (
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
          <span className={large.className} style={large.style}>{initials(name)}</span>
          <div>
            <div className="sheet__name">{name}</div>
            {me?.email && <div className="sheet__sub">{me.email}</div>}
          </div>
        </div>
        {inRouter ? (
          <Link to="/settings" className="btn btn--block" onClick={close}>Settings</Link>
        ) : (
          <a href="/app/settings" className="btn btn--block">Settings</a>
        )}
        <button type="button" className="btn btn--danger btn--block" onClick={() => { close(); void signOut() }}>
          <LogOutIcon />
          Sign out
        </button>
        <button type="button" ref={cancel} className="btn btn--block" onClick={close}>Cancel</button>
      </div>
    </dialog>
  )
})
