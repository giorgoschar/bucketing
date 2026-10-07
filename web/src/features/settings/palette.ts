/** The 8 swatches for avatars and categories (a subset of the server's AVATAR_COLORS). */
export const SWATCHES = ['#6366f1', '#8b5cf6', '#ec4899', '#ef4444', '#f97316', '#f59e0b', '#10b981', '#06b6d4'] as const
const NAMES = ['Indigo', 'Violet', 'Pink', 'Red', 'Orange', 'Amber', 'Green', 'Cyan']
/** Accessible name for a swatch button: colour is never the only signal. */
export const swatchName = (hex: string) => NAMES[SWATCHES.indexOf(hex.toLowerCase() as (typeof SWATCHES)[number])] ?? hex
