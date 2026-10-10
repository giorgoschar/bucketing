import { createBrowserRouter, Navigate, type RouteObject } from 'react-router'
import { AppShell } from './shell/AppShell'
import { ScreenError } from './shell/ScreenError'
import { FullScreenShell } from './shell/FullScreenShell'
import { Home } from './screens/Home'
import { Insights } from './screens/Insights'
import {
  ActivityRoute, Appearance, Automations, BillHistory, BillsList, Categories, CategoryScreen, Compose, FuelScreen, Household, Items, Notifications,
  PantryDetail, Plan, Profile, Settings, ShoppingList, Statement, StatementsList,
} from './screens/lazy'

/** Each screen gets the error screen (a lazy chunk that 404s after a deploy, P3 M2). On the screen route,
 *  not the shell, so it renders in the shell's Outlet and the tab bar stays. */
const guarded = (routes: RouteObject[]): RouteObject[] => routes.map((r) => ({ ...r, errorElement: <ScreenError /> }))

export const router = createBrowserRouter(
  [
    {
      path: '/',
      element: <AppShell />,
      children: guarded([
        { index: true, element: <Home /> },
        { path: 'activity', element: <ActivityRoute /> },
        { path: 'activity/:id', element: <ActivityRoute /> },
        { path: 'plan', element: <Plan /> },
        { path: 'plan/items', element: <Items /> },
        // Static pantry routes before any 'plan/pantry/:id'.
        { path: 'plan/pantry/list', element: <ShoppingList /> },
        { path: 'plan/pantry/:id', element: <PantryDetail /> },
        { path: 'insights', element: <Insights /> },
        { path: 'insights/category/:id', element: <CategoryScreen /> },
        { path: 'insights/fuel', element: <FuelScreen /> },
        { path: 'insights/bills', element: <BillsList /> },
        { path: 'insights/bills/:id', element: <BillHistory /> },
        { path: 'insights/statements', element: <StatementsList /> },
        { path: 'insights/statements/:month', element: <Statement /> },
        { path: 'settings', element: <Settings /> },
        { path: 'settings/profile', element: <Profile /> },
        { path: 'settings/household', element: <Household /> },
        { path: 'settings/categories', element: <Categories /> },
        { path: 'settings/automations', element: <Automations /> },
        { path: 'settings/notifications', element: <Notifications /> },
        { path: 'settings/appearance', element: <Appearance /> },
        { path: '*', element: <Navigate to="/" replace /> },
      ]),
    },
    // The composer sits outside AppShell so no tab bar shows while composing (2b spec §3).
    {
      element: <FullScreenShell />,
      children: guarded([
        { path: '/new', element: <Compose /> },
        { path: '/edit/:id', element: <Compose /> },
      ]),
    },
  ],
  { basename: '/app' },
)
