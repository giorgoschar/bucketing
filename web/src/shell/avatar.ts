import type { CSSProperties } from 'react'

const HEX = /^#[0-9a-f]{6}$/i
const WHITE = '#FFFFFF'
const INK = '#0B0E17'
const BLACK = '#000000'

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
  const f = (v: number) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4)
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
}

/** WCAG contrast ratio of two #rrggbb colours. */
export function contrast(a: string, b: string): number {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p)
  return (x + 0.05) / (y + 0.05)
}

/** The initial's colour on an avatar tint: white where it reads at 4.5:1, else the app's ink, else black.
 *  The tint is the user's pick (the same in both themes), so the ink is chosen from it, not from the theme:
 *  the old fixed light ink gave 4.10:1 on indigo in dark mode. */
export function avatarInk(tint: string): string {
  if (contrast(WHITE, tint) >= 4.5) return WHITE
  if (contrast(INK, tint) >= 4.5) return INK
  return BLACK
}

/** className and style for an `.avatar`: the user's colour with a readable initial, or the token fallback. */
export function avatarLook(color: string | null | undefined, extra = ''): { className: string; style?: CSSProperties } {
  const tint = color && HEX.test(color) ? color : undefined
  const className = ['avatar', tint ? '' : 'avatar--fallback', extra].filter(Boolean).join(' ')
  return tint ? { className, style: { background: tint, color: avatarInk(tint) } } : { className }
}
