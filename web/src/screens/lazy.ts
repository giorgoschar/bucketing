import { lazy } from 'react'

// Code-split so the main bundle stays under 500 kB: the composer (with the scan screen and its QR decoder)
// loads on the first ＋, Plan and its items list on the first visit. Home stays in the main bundle.
export const Compose = lazy(() => import('./Compose').then((m) => ({ default: m.Compose })))
export const Plan = lazy(() => import('./Plan').then((m) => ({ default: m.Plan })))
export const Items = lazy(() => import('../features/plan/items/Items').then((m) => ({ default: m.Items })))

// Phase 2 P3: the Activity detail, the Insights drill-downs and every Settings screen load on first visit
// so the main bundle stays under 500 kB. The tab roots (Home, Activity, Insights) stay in the main bundle.
export const ActivityDetail = lazy(() => import('../features/activity/Detail').then((m) => ({ default: m.Detail })))
export const CategoryScreen = lazy(() => import('../features/insights/CategoryScreen').then((m) => ({ default: m.CategoryScreen })))
export const FuelScreen = lazy(() => import('../features/insights/FuelScreen').then((m) => ({ default: m.FuelScreen })))
export const Settings = lazy(() => import('../features/settings/Settings').then((m) => ({ default: m.Settings })))
export const Profile = lazy(() => import('../features/settings/Profile').then((m) => ({ default: m.Profile })))
export const Household = lazy(() => import('../features/settings/Household').then((m) => ({ default: m.Household })))
export const Categories = lazy(() => import('../features/settings/Categories').then((m) => ({ default: m.Categories })))
export const Automations = lazy(() => import('../features/settings/Automations').then((m) => ({ default: m.Automations })))
export const Notifications = lazy(() => import('../features/settings/Notifications').then((m) => ({ default: m.Notifications })))
