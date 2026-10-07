import { useState } from 'react'
import { ScanFaceIcon, WalletIcon } from '../shell/icons'
import { authErrorMessage, LINKED_MESSAGE, LOGOUT_FAILED_MESSAGE, type AuthResult } from './authMessages'
import { takeSignInNotice } from './notice'
import { useSession } from './SessionProvider'

export function SignIn({ result }: { result: AuthResult }) {
  const { logoutFailed, retryLogout } = useSession()
  const [notice] = useState(takeSignInNotice)
  return (
    <main className="signin">
      <div className="signin__brand">
        <div className="signin__mark" aria-hidden="true"><WalletIcon /></div>
        <div>
          <h1 className="signin__title">Tameio</h1>
          <p className="signin__lede">Household money, private by default.</p>
        </div>
      </div>
      <div className="signin__actions">
        {logoutFailed && (
          <div role="alert" className="notice notice--error">
            <span className="notice__text">{LOGOUT_FAILED_MESSAGE}</span>
            <button type="button" className="notice__action" onClick={() => void retryLogout()}>Retry</button>
          </div>
        )}
        {result.error && <p role="alert" className="notice notice--error">{authErrorMessage(result.error)}</p>}
        {notice && <p role="status" className="notice notice--ok">{notice}</p>}
        {result.linked && <p role="status" className="notice notice--ok">{LINKED_MESSAGE}</p>}
        {/* A top-level navigation: it stays inside the PWA scope until the hop to Pocket ID. */}
        <a className="btn btn--primary btn--lg btn--block" href="/app/auth/login">
          <ScanFaceIcon />
          Sign in with Face ID
        </a>
        <p className="signin__hint">No account? Ask a household member for an invite link.</p>
      </div>
    </main>
  )
}
