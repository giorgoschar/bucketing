import { createBrowserRouter, Navigate } from 'react-router'
import { AppShell } from './shell/AppShell'
import { FullScreenShell } from './shell/FullScreenShell'
import { Home } from './screens/Home'
import { Activity } from './screens/Activity'
import { Insights } from './screens/Insights'
import {
  ActivityDetail, Automations, Categories, CategoryScreen, Compose, FuelScreen, Household, Items, Notifications,
  PantryDetail, Plan, Profile, Settings,
} from './screens/lazy'

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
        // Static /plan/pantry/* routes (the shopping list) go above this one.
        { path: 'plan/pantry/:id', element: <PantryDetail /> },
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
