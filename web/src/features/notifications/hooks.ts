import { useQueryClient } from '@tanstack/react-query'
import { api } from '../../api/client'
import { useCachedQuery } from '../../data/cachedQuery'
import { unwrap } from '../../data/http'
import { keys } from '../../data/keys'
import { isOnline } from '../../data/online'

export interface AppNotification {
  id: string
  type: string
  title: string
  body: string | null
  link: string | null
  is_read: boolean
  created_at: string | null
}
export interface NotificationList { unread: number; has_more: boolean; offset: number; items: AppNotification[] }

/** GET /notifications, newest 50. The route's response is untyped in OpenAPI, so the shape is here. */
export function useNotifications() {
  return useCachedQuery(keys.notifications(), (signal) =>
    unwrap(api.GET('/api/v1/notifications', { signal })).then((d) => d as NotificationList))
}

/** Marking read is best effort: offline it changes nothing (the list is read only from the cache). The cache
 *  is patched at once; a failed call is put right by the refetch. */
export function useMarkRead() {
  const qc = useQueryClient()
  const patch = (fn: (l: NotificationList) => NotificationList) =>
    qc.setQueryData<NotificationList>(keys.notifications(), (l) => (l ? fn(l) : l))
  const settle = () => qc.invalidateQueries({ queryKey: keys.notifications() })
  return {
    one: async (n: AppNotification) => {
      if (n.is_read || !isOnline()) return
      patch((l) => ({ ...l, unread: Math.max(0, l.unread - 1), items: l.items.map((i) => (i.id === n.id ? { ...i, is_read: true } : i)) }))
      await api.POST('/api/v1/notifications/{notification_id}/read', { params: { path: { notification_id: n.id } } }).catch(() => {})
      void settle()
    },
    all: async () => {
      if (!isOnline()) return
      patch((l) => ({ ...l, unread: 0, items: l.items.map((i) => ({ ...i, is_read: true })) }))
      await api.POST('/api/v1/notifications/read-all').catch(() => {})
      void settle()
    },
  }
}
