const KEY = 'tameio.signin.notice'

/** A one-line message the sign-in screen shows once (e.g. after a password change). Not sensitive. */
export function setSignInNotice(text: string): void {
  try { sessionStorage.setItem(KEY, text) } catch { /* storage unavailable: no notice */ }
}

export function takeSignInNotice(): string | null {
  try {
    const text = sessionStorage.getItem(KEY)
    sessionStorage.removeItem(KEY)
    return text
  } catch {
    return null
  }
}
