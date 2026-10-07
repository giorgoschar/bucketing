import { createBrowserRouter, Navigate } from 'react-router'
import { AppShell } from './shell/AppShell'
import { FullScreenShell } from './shell/FullScreenShell'
import { Home } from './screens/Home'
import { Activity } from './screens/Activity'
import { ActivityDetail } from './features/activity/Detail'
import { Insights } from './screens/Insights'
import { Compose, Items, Plan } from './screens/lazy'

export const router = createBrowserRouter(
  [
    {
      path: '/',
      element: <AppShell />,
      children: [
        { index: true, element: <Home /> },
        { path: 'activity', element: <Activity /> },
        { path: 'activity/:id', element: <ActivityDetail /> },
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
