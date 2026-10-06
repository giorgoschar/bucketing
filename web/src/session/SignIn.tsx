import { ScanFaceIcon, WalletIcon } from '../shell/icons'

const MESSAGES: Record<string, string> = {
  not_linked: 'This passkey isn’t linked yet. Sign in with your password at /login, then Settings → Link passkey.',
  link_requires_login: 'To link a passkey, first sign in with your password and 2FA.',
  no_household: 'You’re signed in but not in a household yet. Ask for an invite.',
  denied: 'Sign-in was cancelled.',
  state: 'That sign-in link expired. Try again.',
  token: 'Sign-in couldn’t be verified. Try again.',
  provider: 'The sign-in service didn’t respond. Try again in a minute.',
  subject_conflict: 'This passkey is already linked to a different account.',
}

export function SignIn() {
  const params = new URLSearchParams(location.search)
  const code = params.get('auth_error')
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
        {code && <p role="alert" className="signin__error">{MESSAGES[code] ?? 'Sign-in failed. Try again.'}</p>}
        {params.has('linked') && (
          <p role="status" className="signin__ok">Passkey linked. You can sign in with Face ID now.</p>
        )}
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
