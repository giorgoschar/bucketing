import { Route, Routes, useLocation } from 'react-router'
import { renderWithProviders } from '../../test/render'
import { fakeApi, type Routes as ApiRoutes } from '../../test/fakeApi'
import { Activity } from './Activity'
import { ActivityIdRoute } from './ActivityIdRoute'
import { makeTxn, pageOf, refRoutes } from './testing'
import type { Txn } from './hooks'

function Where() {
  const loc = useLocation()
  return <output data-testid="location">{loc.pathname + loc.search}</output>
}

export const FEED = 'GET /api/v1/transactions' as const

/** Activity and /activity/:id the way router.tsx mounts them, with the reads the pane needs. */
export function renderDesktopActivity(rows: Txn[], { route = '/activity', extra = {}, total }: {
  route?: string; extra?: ApiRoutes; total?: number
} = {}) {
  const fake = fakeApi({
    ...refRoutes(),
    [FEED]: () => pageOf(rows, { total: total ?? rows.length }),
    'GET /api/v1/transactions/{txn_id}': (req) => rows.find((r) => r.id === req.params.txn_id) ?? makeTxn({ id: req.params.txn_id }),
    'GET /api/v1/transactions/{txn_id}/history': () => ({ events: [] }) as never,
    'GET /api/v1/recurring/entries': () => [],
    ...extra,
  })
  const view = renderWithProviders(
    <>
      <Routes>
        <Route path="/activity" element={<Activity />} />
        <Route path="/activity/:id" element={<ActivityIdRoute />} />
      </Routes>
      <Where />
    </>,
    { route },
  )
  return { fake, ...view }
}
