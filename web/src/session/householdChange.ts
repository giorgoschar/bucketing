import { queryClient } from '../queryClient'

/** The active household changed (switch, create, join, leave). Nothing cached may outlive it, and the session's
 *  profile names the old household, so drop every cached query and reload the app on the new one. */
export function afterHouseholdChange(to = '/app/') {
  queryClient.clear()
  globalThis.location.assign(to)
}
