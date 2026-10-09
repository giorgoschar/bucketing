import { useRef, type ReactNode } from 'react'
import { AccountDialog, type AccountDialogHandle, MyAvatar } from './AccountDialog'

/** `actions` (icon buttons for the screen) render before the account button. */
export function TopBar({ title, actions }: { title: string; actions?: ReactNode }) {
  const account = useRef<AccountDialogHandle>(null)
  return (
    <header className="topbar">
      <h1 className="topbar__title">{title}</h1>
      <div className="topbar__end">
        {actions}
        <button
          type="button"
          className="topbar__account"
          aria-label="Account"
          aria-haspopup="dialog"
          onClick={() => account.current?.open()}
        >
          <MyAvatar />
        </button>
      </div>
      <AccountDialog ref={account} />
    </header>
  )
}
