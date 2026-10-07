import { api } from '../../api/client'
import { settingsKeys } from '../../data/keys'
import { useOnlineAction } from '../../data/onlineAction'
import { disablePush, enablePush, sendTestPush } from '../../pwa/pushClient'
import { useSession } from '../../session/SessionProvider'
import type { NotificationPrefs } from './hooks'

export const disabledAfter = (prefs: NotificationPrefs, type: string, enabled: boolean) =>
  prefs.types.filter((t) => (t.type === type ? !enabled : !t.enabled)).map((t) => t.type)

/** All online only. The push routes are the cookie + CSRF ones outside OpenAPI (/push/*, via pushClient).
 *  enablePush asks iOS for permission first, so it must start in the tap's call chain (it does:
 *  useOnlineAction checks navigator.onLine synchronously and then calls it). */
export function useNotificationActions() {
  const act = useOnlineAction()
  const hh = useSession().me?.household_id ?? ''
  const prefsKey = [settingsKeys.notifications(hh)]
  return {
    setDisabled: (disabled: string[]) =>
      act(() => api.PUT('/api/v1/settings/notifications', { body: { disabled } }), { invalidates: prefsKey }),
    pushOn: () => act(() => enablePush(), { invalidates: prefsKey, success: 'Push is on for this device' }),
    pushOff: () => act(() => disablePush(), { invalidates: prefsKey, success: 'Push is off for this device' }),
    test: () => act(() => sendTestPush()),
  }
}
