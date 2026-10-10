import { lazy, Suspense, useEffect, useState } from 'react'
import { Navigate, Outlet, useLocation, useNavigate } from 'react-router'
import { clearPending } from '../data/pending'
import { installQueueBridge } from '../data/queueBridge'
import { startReplayTriggers } from '../offline/queue'
import { queryClient } from '../queryClient'
import { authErrorMessage, LINKED_MESSAGE, readAuthResult } from '../session/authMessages'
import { useSession } from '../session/SessionProvider'
import { SignIn } from '../session/SignIn'
import { Toaster } from '../ui/Toast'
import { useIsDesktop } from '../ui/useIsDesktop'
import { TickedPrompt } from '../features/plan/pantry/TickedPrompt'
import { resetTickedPrompt } from '../features/plan/pantry/tickedOffer'
import { fullScreenAddress, panelOf, rememberScreen, resetScreen } from './addPanel'
import { CloseIcon } from './icons'
import { TabBar } from './TabBar'
import './shell.css'

// Desktop only: the phone never loads the sidebar's code.
const Sidebar = lazy(() => import('./Sidebar').then((m) => ({ default: m.Sidebar })))
const AddPanel = lazy(() => import('./AddSidePanel'))

export function AppShell() {
  const { status } = useSession()
  const desktop = useIsDesktop()
  const location = useLocation()
  const navigate = useNavigate()
  // The auth callbacks land here with ?auth_error=… or ?linked=1 whether or not a session exists.
  // Read it once, then drop it from the URL so a reload doesn't repeat it.
  const [result, setResult] = useState(() => readAuthResult(location.search))
  const hasParams = location.search.includes('auth_error') || location.search.includes('linked')

  useEffect(() => {
    if (!hasParams) return
    const params = new URLSearchParams(location.search)
    params.delete('auth_error')
    params.delete('linked')
    const rest = params.toString()
    navigate({ search: rest ? `?${rest}` : '' }, { replace: true })
  }, [hasParams, location.search, navigate])

  // Where a later /new link should open its panel on a desktop (addPanel.ts).
  useEffect(() => { rememberScreen(location.pathname, location.search) }, [location.pathname, location.search])

  // Replay queued offline writes on open, `online` and returning to the tab (iOS has no Background Sync).
  // The bridge first, so the first drain already refreshes the screens and clears the pending markers.
  useEffect(() => {
    if (status !== 'signedIn') {
      // Signed out: this account's markers must not outlive it. Not on unmount: /new sits outside AppShell,
      // and opening the composer must not wipe the "Waiting to sync" markers.
      clearPending()
      resetTickedPrompt() // a pantry offer is this account's too
      resetScreen() // and so is the screen a /new link would open over
      return
    }
    const stopBridge = installQueueBridge(queryClient)
    const stopReplay = startReplayTriggers()
    return () => {
      stopReplay()
      stopBridge()
    }
  }, [status])

  if (status === 'loading') return <div className="boot" aria-busy="true" />
  if (status === 'signedOut') return <SignIn result={result} />

  // ?add=1 / ?edit=<id> is the desktop panel. The phone has no panel: the same address is the full-screen composer.
  const panel = panelOf(new URLSearchParams(location.search))
  if (panel && !desktop) return <Navigate replace to={fullScreenAddress(new URLSearchParams(location.search))!} />

  const dismiss = () => setResult({ error: null, linked: false })
  const banner = result.error
    ? { role: 'alert', tone: 'error', text: authErrorMessage(result.error) }
    : result.linked
      ? { role: 'status', tone: 'ok', text: LINKED_MESSAGE }
      : null

  return (
    <div className="shell">
      {desktop && <Suspense fallback={null}><Sidebar /></Suspense>}
      <main className="shell__main">
        {banner && (
          <div role={banner.role} className={`notice notice--${banner.tone} shell__banner`}>
            <span className="notice__text">{banner.text}</span>
            <button type="button" className="notice__close" aria-label="Dismiss" onClick={dismiss}>
              <CloseIcon />
            </button>
          </div>
        )}
        {/* Plan and Items are code-split (router.tsx): a skeleton while their code loads, tab bar still there. */}
        <Suspense fallback={<div className="ui-skeleton" role="status" aria-busy="true" aria-label="Loading" />}>
          <Outlet />
        </Suspense>
      </main>
      {!desktop && <TabBar />}
      {desktop && panel && <Suspense fallback={null}><AddPanel /></Suspense>}
      <Toaster />
      {/* Pantry spec §4.6: the composer's post-save offer shows here, where the composer returns. */}
      <TickedPrompt />
    </div>
  )
}
