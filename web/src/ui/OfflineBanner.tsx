import { formatShortDate, formatTime, toISODate } from './format'
import { CloudOffIcon } from './icons'

/** "Offline · updated 14:02" (today) or "Offline · updated 5 Oct 09:30" (an earlier day). */
export function OfflineBanner({ updatedAt, now = Date.now() }: { updatedAt: number; now?: number }) {
  let when: string
  if (updatedAt === 0) when = 'never'
  else if (toISODate(new Date(updatedAt)) === toISODate(new Date(now))) when = formatTime(updatedAt)
  else when = `${formatShortDate(toISODate(new Date(updatedAt)))} ${formatTime(updatedAt)}`
  return (
    <p className="ui-banner" role="status">
      <CloudOffIcon />
      Offline · updated {when}
    </p>
  )
}
