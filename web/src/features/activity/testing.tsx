import type { ReactElement } from 'react'
import { Route, Routes, useLocation } from 'react-router'
import { renderWithProviders } from '../../test/render'

function Where() {
  const loc = useLocation()
  return <output data-testid="location">{loc.pathname + loc.search}</output>
}

/** 2a's renderWithProviders (query client, memory router, Toaster, signed-in identity) renders `ui` at every path.
 * This mounts it at `path` so a screen can read `:id`, and adds the location readout the tests assert on. */
export function renderActivity(ui: ReactElement, { route = '/activity', path = '/activity' } = {}) {
  return renderWithProviders(
    <>
      <Routes>
        <Route path={path} element={ui} />
      </Routes>
      <Where />
    </>,
    { route },
  )
}
