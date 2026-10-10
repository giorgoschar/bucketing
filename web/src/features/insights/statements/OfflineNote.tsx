import { CloudOffIcon } from '../../../ui/icons'

/** Shown above a saved statement (or the list) that could not be refreshed (spec §4.8). */
export function OfflineNote() {
  return (
    <p className="ui-banner" role="status">
      <CloudOffIcon />Offline · showing saved statement
    </p>
  )
}
