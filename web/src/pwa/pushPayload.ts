import { appRoute } from './appRoute'

export interface PushNotice { title: string; options: NotificationOptions & { data: { url: string } } }

/** The server sends {title, body, link} (app/services/notifications.py). */
export function noticeFromPush(text: string | null): PushNotice {
  let p: { title?: unknown; body?: unknown; link?: unknown } = {}
  if (text) {
    try {
      const parsed: unknown = JSON.parse(text)
      p = typeof parsed === 'object' && parsed !== null ? parsed : {}
    } catch {
      p = { body: text }
    }
  }
  return {
    title: typeof p.title === 'string' && p.title ? p.title : 'Tameio',
    options: {
      body: typeof p.body === 'string' ? p.body : '',
      icon: '/app/icons/icon-192.png',
      badge: '/app/icons/icon-192.png',
      data: { url: appRoute(typeof p.link === 'string' ? p.link : '/') },
    },
  }
}
