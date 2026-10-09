import { Suspense, useEffect } from 'react'
import { Navigate, Outlet, useLocation } from 'react-router'
import { installQueueBridge } from '../data/queueBridge'
import { startReplayTriggers } from '../offline/queue'
import { queryClient } from '../queryClient'
import { useSession } from '../session/SessionProvider'
import { SignIn } from '../session/SignIn'
import { Toaster } from '../ui/Toast'
import { useIsDesktop } from '../ui/useIsDesktop'
import { panelAddress } from './addPanel'
import './shell.css'

/**
 * Layout for full-screen flows (the composer): the same sign-in gate, queue bridge and offline replay
 * as AppShell, without the tab bar. Auth-callback banners stay AppShell's job (callbacks land on /).
 */
export function FullScreenShell() {
  const { status } = useSession()
  const desktop = useIsDesktop()
  const { pathname, search } = useLocation()
  useEffect(() => {
    if (status !== 'signedIn') return
    const stopBridge = installQueueBridge(queryClient)
    const stopReplay = startReplayTriggers()
    return () => {
      stopReplay()
      stopBridge()
    }
  }, [status])
  if (status === 'loading') return <div className="boot" aria-busy="true" />
  if (status === 'signedOut') return <SignIn result={{ error: null, linked: false }} />
  // On a desktop the composer is a side panel over a screen (addPanel.ts), not a route.
  if (desktop) return <Navigate replace to={panelAddress(pathname, search)} />
  return (
    <>
      {/* The composer is code-split (router.tsx): the boot screen covers its first load. */}
      <Suspense fallback={<div className="boot" aria-busy="true" />}>
        <Outlet />
      </Suspense>
      <Toaster />
    </>
  )
}
