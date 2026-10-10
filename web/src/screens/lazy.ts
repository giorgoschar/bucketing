import { lazy } from 'react'

// Code-split so the main bundle stays under 500 kB: the composer (with the scan screen and its QR decoder)
// loads on the first ＋, Plan and its items list on the first visit. Home stays in the main bundle.
export const Compose = lazy(() => import('./Compose').then((m) => ({ default: m.Compose })))
export const Plan = lazy(() => import('./Plan').then((m) => ({ default: m.Plan })))
export const Items = lazy(() => import('../features/plan/items/Items').then((m) => ({ default: m.Items })))
// Plan › Pantry › product (pantry spec §4.4).
export const PantryDetail = lazy(() => import('../features/plan/pantry/Detail').then((m) => ({ default: m.Detail })))

// Phase 2 P3: the Insights drill-downs and every Settings screen load on first visit so the main bundle stays
// small. Home and Insights stay in the main bundle; Activity (list and detail) is lazy since Phase A, below.
// The Activity list and its detail are one element for both routes, so opening a row keeps the table mounted.
export const ActivityRoute = lazy(() => import('../features/activity/ActivityRoute').then((m) => ({ default: m.ActivityRoute })))
export const CategoryScreen = lazy(() => import('../features/insights/CategoryScreen').then((m) => ({ default: m.CategoryScreen })))
export const FuelScreen = lazy(() => import('../features/insights/FuelScreen').then((m) => ({ default: m.FuelScreen })))
// Phase A: Insights › Bills (the list, and each bill's history).
export const BillsList = lazy(() => import('../features/insights/bills/BillsList').then((m) => ({ default: m.BillsList })))
export const BillHistory = lazy(() => import('../features/insights/bills/BillHistory').then((m) => ({ default: m.BillHistory })))
// Phase B: Insights › Statements (the list, and each past month's statement).
export const StatementsList = lazy(() => import('../features/insights/statements/StatementsList').then((m) => ({ default: m.StatementsList })))
export const Settings = lazy(() => import('../features/settings/Settings').then((m) => ({ default: m.Settings })))
export const Profile = lazy(() => import('../features/settings/Profile').then((m) => ({ default: m.Profile })))
export const Household = lazy(() => import('../features/settings/Household').then((m) => ({ default: m.Household })))
export const Categories = lazy(() => import('../features/settings/Categories').then((m) => ({ default: m.Categories })))
export const Automations = lazy(() => import('../features/settings/Automations').then((m) => ({ default: m.Automations })))
export const Appearance = lazy(() => import('../features/settings/Appearance').then((m) => ({ default: m.Appearance })))
export const Notifications = lazy(() => import('../features/settings/Notifications').then((m) => ({ default: m.Notifications })))

// Plan › Pantry › Shopping list (pantry spec §4.5): loads on first visit.
export const ShoppingList = lazy(() => import('../features/plan/pantry/ShoppingList').then((m) => ({ default: m.ShoppingList })))
