import { lazy } from 'react'

// Code-split so the main bundle stays under 500 kB: the composer (with the scan screen and its QR decoder)
// loads on the first ＋, Plan and its items list on the first visit. Home stays in the main bundle.
export const Compose = lazy(() => import('./Compose').then((m) => ({ default: m.Compose })))
export const Plan = lazy(() => import('./Plan').then((m) => ({ default: m.Plan })))
export const Items = lazy(() => import('../features/plan/items/Items').then((m) => ({ default: m.Items })))
