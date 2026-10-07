/** Mirrors settings.currencies on the server. */
export const CURRENCIES = ['EUR', 'USD', 'GBP', 'CHF', 'JPY', 'AUD', 'CAD', 'SEK', 'NOK', 'DKK'] as const

const NAMES: Record<string, string> = {
  EUR: 'euro', USD: 'US dollars', GBP: 'pounds', CHF: 'Swiss francs', JPY: 'yen',
  AUD: 'Australian dollars', CAD: 'Canadian dollars', SEK: 'Swedish kronor', NOK: 'Norwegian kroner', DKK: 'Danish kroner',
}

export const currencyName = (code: string): string => NAMES[code] ?? code

const money = (currency: string) =>
  new Intl.NumberFormat('en-IE', {
    style: 'currency', currency, currencyDisplay: 'narrowSymbol', minimumFractionDigits: 2, maximumFractionDigits: 2,
  })

export function currencySymbol(code: string): string {
  return money(code).formatToParts(0).find((p) => p.type === 'currency')?.value ?? code
}

/** Display only; cents / 100 is exact enough for two printed decimals. */
export const formatCents = (cents: number, currency: string): string => money(currency).format(cents / 100)

/** "4 euro 10", "3 euro": for accessible names. */
export function spokenMoney(cents: number, currency: string): string {
  const rest = cents % 100
  return `${Math.floor(cents / 100)} ${currencyName(currency)}${rest ? ` ${rest}` : ''}`
}
