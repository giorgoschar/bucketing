import { useNavigate } from 'react-router'
import { appRoute } from '../../pwa/appRoute'
import { BackHeader } from '../../ui/BackHeader'
import { EmptyState } from '../../ui/EmptyState'
import { List, ListRow } from '../../ui/ListRow'
import { QueryView } from '../../ui/QueryView'
import { ago } from '../settings/attemptHooks'
import { type AppNotification, useMarkRead, useNotifications } from './hooks'

/** /notifications: what was sent, newest first. A tap opens the target and marks it read. */
export function NotificationCentre() {
  const result = useNotifications()
  const mark = useMarkRead()
  const navigate = useNavigate()
  const open = (n: AppNotification) => {
    void mark.one(n)
    void navigate(appRoute(n.link).slice('/app'.length) || '/')
  }
  return (
    <>
      <BackHeader title="Notifications" back="/" />
      <section className="screen notes">
        <QueryView result={result} noDataText="No saved notifications yet. Connect once to load them.">
          {({ items, unread }) => items.length === 0 ? (
            <EmptyState title="No notifications yet" />
          ) : (
            <>
              {unread > 0 && (
                <div className="notes__bar"><button type="button" className="btn" onClick={() => void mark.all()}>Mark all read</button></div>
              )}
              <List label="Notifications">
                {items.map((n) => (
                  <ListRow
                    key={n.id}
                    className={n.is_read ? undefined : 'notes__row--unread'}
                    title={n.title}
                    subtitle={[n.body, n.created_at && ago(n.created_at)].filter(Boolean).join(' · ')}
                    trailing={n.is_read ? null : <span className="notes__dot" role="img" aria-label="Unread" />}
                    onClick={() => open(n)}
                  />
                ))}
              </List>
            </>
          )}
        </QueryView>
      </section>
    </>
  )
}
