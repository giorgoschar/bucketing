import { createBrowserRouter, Navigate } from 'react-router'
import { AppShell } from './shell/AppShell'
import { Home } from './screens/Home'
import { Activity } from './screens/Activity'
import { Compose } from './screens/Compose'
import { Plan } from './screens/Plan'
import { Items } from './features/plan/items/Items'
import { Insights } from './screens/Insights'

export const router = createBrowserRouter(
  [
    {
      path: '/',
      element: <AppShell />,
      children: [
        { index: true, element: <Home /> },
        { path: 'activity', element: <Activity /> },
        { path: 'new', element: <Compose /> },
        { path: 'plan', element: <Plan /> },
        { path: 'plan/items', element: <Items /> },
        { path: 'insights', element: <Insights /> },
        { path: '*', element: <Navigate to="/" replace /> },
      ],
    },
  ],
  { basename: '/app' },
)
