/** Units the item form offers (spec §5.1); anything else is "Other" with free text. */
export const USAGE_UNITS = ['kWh', 'm³', 'L', 'GB'] as const
export const USAGE_UNIT_MAX = 12

/**
 * A usage figure as typed: blank → null, a decimal comma or point accepted, up to 3 decimals, up to 9 digits
 * before the point (the server's Numeric(12, 3)). Anything else → undefined.
 */
export function parseUsage(input: string): number | null | undefined {
  const s = input.replace(/\s/g, '').replace(',', '.')
  if (s === '') return null
  if (!/^(\d{1,9}(\.\d{0,3})?|\.\d{1,3})$/.test(s)) return undefined
  return Number(s)
}
