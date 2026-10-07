import { useEffect, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router'
import { clearPending } from '../data/pending'
import { installQueueBridge } from '../data/queueBridge'
import { startReplayTriggers } from '../offline/queue'
import { queryClient } from '../queryClient'
import { authErrorMessage, LINKED_MESSAGE, readAuthResult } from '../session/authMessages'
import { useSession } from '../session/SessionProvider'
import { SignIn } from '../session/SignIn'
import { Toaster } from '../ui/Toast'
import { CloseIcon } from './icons'
import { TabBar } from './TabBar'
import './shell.css'

export function AppShell() {
  const { status } = useSession()
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

  // Replay queued offline writes on open, `online` and returning to the tab (iOS has no Background Sync).
  // The bridge first, so the first drain already refreshes the screens and clears the pending markers.
  useEffect(() => {
    if (status !== 'signedIn') return
    const stopBridge = installQueueBridge(queryClient)
    const stopReplay = startReplayTriggers()
    return () => {
      stopReplay()
      stopBridge()
      clearPending() // signed out or switched: this account's markers must not outlive it
    }
  }, [status])

  if (status === 'loading') return <div className="boot" aria-busy="true" />
  if (status === 'signedOut') return <SignIn result={result} />

  const dismiss = () => setResult({ error: null, linked: false })
  const banner = result.error
    ? { role: 'alert', tone: 'error', text: authErrorMessage(result.error) }
    : result.linked
      ? { role: 'status', tone: 'ok', text: LINKED_MESSAGE }
      : null

  return (
    <div className="shell">
      <main className="shell__main">
        {banner && (
          <div role={banner.role} className={`notice notice--${banner.tone} shell__banner`}>
            <span className="notice__text">{banner.text}</span>
            <button type="button" className="notice__close" aria-label="Dismiss" onClick={dismiss}>
              <CloseIcon />
            </button>
          </div>
        )}
        <Outlet />
      </main>
      <TabBar />
      <Toaster />
    </div>
  )
}
