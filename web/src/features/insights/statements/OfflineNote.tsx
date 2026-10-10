import { useOnline } from '../../../data/online'
import { CloudOffIcon } from '../../../ui/icons'

/** Shown above a saved statement (or the list) that could not be refreshed (spec §4.8). */
export function OfflineNote() {
  const online = useOnline()
  return (
    <p className="ui-banner" role="status">
      <CloudOffIcon />{online ? 'Couldn’t refresh · showing saved statement' : 'Offline · showing saved statement'}
    </p>
  )
}
