/** Where a notification's server link opens in the app (2d §6.4). The old app's links
 *  (/bills, /transactions/…/edit, …) have no /app/ equivalent of the same path. */
export function appRoute(link: string | null | undefined): string {
  let path: string
  try {
    path = new URL(link || '/', 'https://app.invalid').pathname
  } catch {
    return '/app/'
  }
  const under = (prefix: string) => path === prefix || path.startsWith(`${prefix}/`)
  // Plan › Pantry (pantry spec §4.9): stock_low links to /stock/shopping, price_drop to /stock.
  if (under('/stock/shopping')) return '/app/plan/pantry/list'
  if (under('/stock')) return '/app/plan/pantry'
  if (under('/bills') || under('/buckets')) return '/app/plan'
  if (under('/transactions') || under('/search')) return '/app/activity'
  if (under('/settings')) return '/app/settings'
  return '/app/'
}
