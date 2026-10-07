import { api } from '../../api/client'
import { settingsKeys } from '../../data/keys'
import { useOnlineAction } from '../../data/onlineAction'
import type { RawResult } from '../../data/rawJson'
import { useSession } from '../../session/SessionProvider'
import type { TokenItem } from './hooks'

/** Server timestamps are naive UTC ("2026-10-07T10:00:00"): read them as UTC. */
const utc = (iso: string) => Date.parse(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`)

export function lastUsed(iso: string | null, now = Date.now()): string {
  if (!iso) return 'Never used'
  const mins = Math.max(0, Math.floor((now - utc(iso)) / 60_000))
  if (mins < 1) return 'Last used just now'
  if (mins < 60) return `Last used ${mins}m ago`
  if (mins < 48 * 60) return `Last used ${Math.round(mins / 60)}h ago`
  return `Last used ${Math.round(mins / 1440)}d ago`
}

export function useTokenActions() {
  const act = useOnlineAction()
  const hh = useSession().me?.household_id ?? ''
  return {
    // The response carries the plaintext token: returned to the screen, never cached. Invalidating the
    // list refetches it, and the list endpoint never includes the plaintext.
    create: (body: { name: string; default_bucket_id: string | null }) =>
      act(() => api.POST('/api/v1/settings/tokens', { body }) as Promise<RawResult<TokenItem & { token: string }>>, { invalidates: [settingsKeys.tokens(hh)] }),
    revoke: (id: string) =>
      act(() => api.DELETE('/api/v1/settings/tokens/{token_id}', { params: { path: { token_id: id } } }), { invalidates: [settingsKeys.tokens(hh)], success: 'Token revoked' }),
  }
}
