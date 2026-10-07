import { lazy } from 'react'
import { createBrowserRouter, Navigate } from 'react-router'
import { AppShell } from './shell/AppShell'
import { FullScreenShell } from './shell/FullScreenShell'
import { Home } from './screens/Home'
import { Activity } from './screens/Activity'
import { Insights } from './screens/Insights'

// Code-split so the main bundle stays under 500 kB: the composer (with the scan screen and its QR decoder)
// loads on the first ＋, Plan and its items list on the first visit. Home stays in the main bundle.
const Compose = lazy(() => import('./screens/Compose').then((m) => ({ default: m.Compose })))
const Plan = lazy(() => import('./screens/Plan').then((m) => ({ default: m.Plan })))
const Items = lazy(() => import('./features/plan/items/Items').then((m) => ({ default: m.Items })))

export const router = createBrowserRouter(
  [
    {
      path: '/',
      element: <AppShell />,
      children: [
        { index: true, element: <Home /> },
        { path: 'activity', element: <Activity /> },
        { path: 'plan', element: <Plan /> },
        { path: 'plan/items', element: <Items /> },
        { path: 'insights', element: <Insights /> },
        { path: '*', element: <Navigate to="/" replace /> },
      ],
    },
    // The composer sits outside AppShell so no tab bar shows while composing (2b spec §3).
    {
      element: <FullScreenShell />,
      children: [
        { path: '/new', element: <Compose /> },
        { path: '/edit/:id', element: <Compose /> },
      ],
    },
  ],
  { basename: '/app' },
)
