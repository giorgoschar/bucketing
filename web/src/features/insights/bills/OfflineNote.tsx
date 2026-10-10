import { useOnline } from '../../../data/online'
import { CloudOffIcon } from '../../../ui/icons'

/** Shown above saved bill data that could not be refreshed (spec §5.7). */
export function OfflineNote() {
  const online = useOnline()
  return (
    <p className="ui-banner" role="status">
      <CloudOffIcon />{online ? 'Couldn’t refresh · showing saved history' : 'Offline · showing saved history'}
    </p>
  )
}
