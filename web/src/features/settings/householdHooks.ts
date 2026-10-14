import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/client'
import { insightsKeys, settingsKeys } from '../../data/keys'
import { unwrap } from '../../data/http'
import { type OnlineOutcome, runOnline, useOnlineAction } from '../../data/onlineAction'
import type { RawResult } from '../../data/rawJson'
import { useSession } from '../../session/SessionProvider'
import { afterHouseholdChange } from '../../session/householdChange'
import { queuedBlock } from '../../offline/queuedChanges'
import { useToast } from '../../ui/Toast'

export interface HouseholdRow { id: string; name: string; role: 'owner' | 'member'; active: boolean }

/** Every household the caller belongs to. Live: a switch decision should not rest on a stale cache. */
export function useHouseholds() {
  const hh = useSession().me?.household_id ?? ''
  return useQuery({
    queryKey: ['settings', 'households', hh],
    queryFn: async ({ signal }) => (await unwrap(api.GET('/api/v1/settings/households', { signal }))) as unknown as HouseholdRow[],
    gcTime: 0,
  })
}

export const inviteUrl = (token: string, origin = globalThis.location.origin) => `${origin}/app/join/${token}`
export const INVITE_RATE_MESSAGE = 'Too many links, wait a minute.'

export function useHouseholdActions() {
  const act = useOnlineAction()
  const toast = useToast()
  const hh = useSession().me?.household_id ?? ''
  /** Household changes wipe the offline queue: refuse while writes wait, and say why. */
  const guarded = async <T,>(run: () => Promise<OnlineOutcome<T>>): Promise<OnlineOutcome<T>> => {
    const message = await queuedBlock()
    if (!message) return run()
    toast.show(message, { tone: 'error' })
    return { ok: false, status: null, kind: 'rejected', message }
  }
  const keys = [settingsKeys.household(hh), insightsKeys.all(hh)]
  return {
    rename: (name: string, currency: string) =>
      act(() => api.PUT('/api/v1/settings/household', { body: { name, default_currency: currency } }), { invalidates: keys, success: 'Saved' }),
    removeMember: (userId: string) =>
      act(() => api.DELETE('/api/v1/settings/household/members/{member_user_id}', { params: { path: { member_user_id: userId } } }),
        { invalidates: keys, success: 'Removed' }),
    /** Switch, create and leave change which household every screen shows: they reload the app on it. */
    switchTo: async (id: string) => {
      const out = await guarded(() => act(() => api.POST('/api/v1/settings/households/switch', { body: { household_id: id } })))
      if (out.ok) afterHouseholdChange()
      return out
    },
    create: async (name: string) => {
      const out = await guarded(() => act(() => api.POST('/api/v1/settings/households', { body: { name, default_currency: 'EUR' } })))
      if (out.ok) afterHouseholdChange()
      return out
    },
    leave: async (confirmName: string) => {
      const out = await guarded(() => act(() => api.POST('/api/v1/settings/household/leave', { body: { confirm_name: confirmName } })))
      // Nowhere left to go: the old app's /setup starts a new household.
      if (out.ok) afterHouseholdChange((out.data as { household_id: string | null }).household_id ? '/app/' : '/setup')
      return out
    },
    transferOwnership: (userId: string) =>
      act(() => api.POST('/api/v1/settings/household/transfer-ownership/{member_id}', { params: { path: { member_id: userId } } }),
        { invalidates: keys, success: 'Ownership transferred' }),
    resetTwoFactor: (userId: string, ownerCode: string) =>
      act(() => api.POST('/api/v1/settings/household/members/{member_id}/reset-2fa', { params: { path: { member_id: userId } }, body: { owner_code: ownerCode } }),
        { success: '2FA reset. They sign in again.' }),
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
