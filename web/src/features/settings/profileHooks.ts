import { api } from '../../api/client'
import { settingsKeys } from '../../data/keys'
import { useOnlineAction } from '../../data/onlineAction'
import { useSession } from '../../session/SessionProvider'

/** Profile & security writes: online only, never queued. The 2FA responses carry secrets, so they are
 *  returned to the calling component and never written to the query cache or the device store. */
export function useProfileActions() {
  const act = useOnlineAction()
  const hh = useSession().me?.household_id ?? ''
  const security = [settingsKeys.security(hh), settingsKeys.profile(hh)]
  return {
    saveProfile: (body: { display_name: string; email: string | null; avatar_color: string }) =>
      act(() => api.PUT('/api/v1/settings/profile', { body }), { invalidates: [settingsKeys.profile(hh), settingsKeys.household(hh)], success: 'Profile saved' }),
    changePassword: (body: { current_password: string; new_password: string }) =>
      act(() => api.POST('/api/v1/settings/profile/password', { body })),
    totpSetup: () => act(() => api.POST('/api/v1/settings/security/totp/setup')),
    totpEnable: (code: string) => act(() => api.POST('/api/v1/settings/security/totp/enable', { body: { code } }), { invalidates: security }),
    totpDisable: (body: { current_password: string; code: string }) =>
      act(() => api.POST('/api/v1/settings/security/totp/disable', { body }), { invalidates: security }),
  }
}
