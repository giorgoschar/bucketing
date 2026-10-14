import { Link } from 'react-router'
import { BellIcon } from '../../shell/icons'
import { useNotifications } from './hooks'

/** The bell: top bar on a phone, sidebar on desktop. Shows the unread count from the saved copy when offline. */
export function NotificationBell({ sidebar = false }: { sidebar?: boolean }) {
  const unread = useNotifications().data?.unread ?? 0
  const count = unread > 99 ? '99+' : String(unread)
  return (
    <Link to="/notifications" className="bell" aria-label={unread ? `Notifications, ${unread} unread` : 'Notifications'}>
      <BellIcon />
      {sidebar && <span aria-hidden="true">Notifications</span>}
      {unread > 0 && <span className="bell__count" aria-hidden="true">{count}</span>}
    </Link>
  )
}
