import { createBrowserRouter, Navigate } from 'react-router'
import { AppShell } from './shell/AppShell'
import { FullScreenShell } from './shell/FullScreenShell'
import { Home } from './screens/Home'
import { Activity } from './screens/Activity'
import { Compose } from './screens/Compose'
import { Plan } from './screens/Plan'
import { Items } from './features/plan/items/Items'
import { Insights } from './screens/Insights'
import { CategoryScreen } from './features/insights/CategoryScreen'
import { FuelScreen } from './features/insights/FuelScreen'
import { Settings } from './features/settings/Settings'
import { Profile } from './features/settings/Profile'
import { Household } from './features/settings/Household'
import { Categories } from './features/settings/Categories'
import { Automations } from './features/settings/Automations'
import { Notifications } from './features/settings/Notifications'

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
        { path: 'insights/category/:id', element: <CategoryScreen /> },
        { path: 'insights/fuel', element: <FuelScreen /> },
        { path: 'settings', element: <Settings /> },
        { path: 'settings/profile', element: <Profile /> },
        { path: 'settings/household', element: <Household /> },
        { path: 'settings/categories', element: <Categories /> },
        { path: 'settings/automations', element: <Automations /> },
        { path: 'settings/notifications', element: <Notifications /> },
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
