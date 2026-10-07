import { api } from '../../api/client'
import { insightsKeys, settingsKeys } from '../../data/keys'
import { runOnline, useOnlineAction } from '../../data/onlineAction'
import type { RawResult } from '../../data/rawJson'
import { useSession } from '../../session/SessionProvider'
import { useToast } from '../../ui/Toast'

export const inviteUrl = (token: string, origin = globalThis.location.origin) => `${origin}/join/${token}`
export const INVITE_RATE_MESSAGE = 'Too many links, wait a minute.'

export function useHouseholdActions() {
  const act = useOnlineAction()
  const toast = useToast()
  const hh = useSession().me?.household_id ?? ''
  const keys = [settingsKeys.household(hh), insightsKeys.all(hh)]
  return {
    rename: (name: string, currency: string) =>
      act(() => api.PUT('/api/v1/settings/household', { body: { name, default_currency: currency } }), { invalidates: keys, success: 'Saved' }),
    removeMember: (userId: string) =>
      act(() => api.DELETE('/api/v1/settings/household/members/{member_user_id}', { params: { path: { member_user_id: userId } } }),
        { invalidates: keys, success: 'Removed' }),
    /** The link is shown once and never stored; 429 has its own wording. */
    invite: async () => {
      const out = await runOnline(
        () => api.POST('/api/v1/settings/household/invite') as Promise<RawResult<{ token: string; expires_at: string }>>,
      )
      if (!out.ok && out.kind !== 'auth') toast.show(out.kind === 'rate' ? INVITE_RATE_MESSAGE : out.message, { tone: 'error' })
      return out // the token goes to component state only, never the cache
    },
  }
}
