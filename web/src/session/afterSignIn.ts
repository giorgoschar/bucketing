// The OIDC callback always lands on /app/, so an invite link opened signed out would be lost. Keep it
// for this tab only (sessionStorage) and open it once the session exists. Only /join/<token> is kept.
const KEY = 'tameio.after-signin'
const INVITE = /^\/join\/[\w-]+$/

export function rememberInvite(path: string) {
  if (!INVITE.test(path)) return
  try { sessionStorage.setItem(KEY, path) } catch { /* private mode: the link just needs opening again */ }
}

export function takeAfterSignIn(): string | null {
  try {
    const path = sessionStorage.getItem(KEY)
    sessionStorage.removeItem(KEY)
    return path && INVITE.test(path) ? path : null
  } catch {
    return null
  }
}
