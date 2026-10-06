/** Messages for the backend's `auth_error` codes and the passkey-link result, shared by SignIn and the shell. */
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

export const LINKED_MESSAGE = 'Passkey linked. You can sign in with Face ID now.'
export const LOGOUT_FAILED_MESSAGE = 'Couldn’t end the session on the server. Try again.'

export function authErrorMessage(code: string): string {
  return Object.hasOwn(MESSAGES, code) ? MESSAGES[code] : 'Sign-in failed. Try again.'
}

/** The one-shot result the auth callbacks append to /app/ (`?auth_error=<code>` or `?linked=1`). */
export interface AuthResult { error: string | null; linked: boolean }

export function readAuthResult(search: string): AuthResult {
  const params = new URLSearchParams(search)
  return { error: params.get('auth_error'), linked: params.has('linked') }
}
