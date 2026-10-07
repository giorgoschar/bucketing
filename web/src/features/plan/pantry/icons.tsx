import type { ReactNode } from 'react'

/** Pantry-only icons, drawn like ui/icons.tsx (24 grid, round caps, currentColor). */
function Icon({ children, strokeWidth = 1.9 }: { children: ReactNode; strokeWidth?: number }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round"
      strokeLinejoin="round" aria-hidden="true" focusable="false" className="ui-icon">
      {children}
    </svg>
  )
}

export const MinusIcon = () => <Icon strokeWidth={2.2}><path d="M5 12h14" /></Icon>
export const SearchIcon = () => <Icon><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></Icon>
export const CartIcon = () => (
  <Icon><circle cx="9" cy="20" r="1.3" /><circle cx="18" cy="20" r="1.3" /><path d="M2.5 3h2.6l2.4 12.2a1.6 1.6 0 0 0 1.6 1.3h8.7a1.6 1.6 0 0 0 1.6-1.2L21 7.5H6" /></Icon>
)
export const TrendDownIcon = () => <Icon><path d="m22 17-8.5-8.5-5 5L2 7" /><path d="M16 17h6v-6" /></Icon>
export const ScanIcon = () => (
  <Icon><path d="M3 7V5a2 2 0 0 1 2-2h2" /><path d="M17 3h2a2 2 0 0 1 2 2v2" /><path d="M21 17v2a2 2 0 0 1-2 2h-2" /><path d="M7 21H5a2 2 0 0 1-2-2v-2" /><path d="M8 7v10M12 7v10M16 7v10" /></Icon>
)
export const PackageIcon = () => (
  <Icon><path d="M21 8 12 3 3 8v8l9 5 9-5Z" /><path d="m3 8 9 5 9-5" /><path d="M12 13v8" /></Icon>
)
export const RefreshIcon = () => (
  <Icon><path d="M21 12a9 9 0 0 1-15.5 6.2L3 16" /><path d="M3 21v-5h5" /><path d="M3 12a9 9 0 0 1 15.5-6.2L21 8" /><path d="M21 3v5h-5" /></Icon>
)
export const ArchiveIcon = () => (
  <Icon><rect x="2.5" y="3.5" width="19" height="5" rx="1.2" /><path d="M4.5 8.5v10a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2v-10" /><path d="M10 12.5h4" /></Icon>
)
export const TagIcon = () => (
  <Icon><path d="M12.6 2.6A2 2 0 0 0 11.2 2H4a2 2 0 0 0-2 2v7.2a2 2 0 0 0 .6 1.4l8.7 8.7a2.4 2.4 0 0 0 3.4 0l6.6-6.6a2.4 2.4 0 0 0 0-3.4Z" /><circle cx="7.5" cy="7.5" r="1.3" /></Icon>
)
