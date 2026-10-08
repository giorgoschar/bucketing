import type { ReactNode } from 'react'

function Icon({ children, strokeWidth = 1.9 }: { children: ReactNode; strokeWidth?: number }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round"
      strokeLinejoin="round" aria-hidden="true" focusable="false" className="ui-icon">
      {children}
    </svg>
  )
}

export const CheckIcon = () => <Icon strokeWidth={2.4}><path d="M20 6 9 17l-5-5" /></Icon>
export const ChevronLeftIcon = () => <Icon><path d="m15 18-6-6 6-6" /></Icon>
export const ChevronRightIcon = () => <Icon><path d="m9 18 6-6-6-6" /></Icon>
export const ChevronDownIcon = () => <Icon><path d="m6 9 6 6 6-6" /></Icon>
export const AlertIcon = () => (
  <Icon><circle cx="12" cy="12" r="10" /><line x1="12" x2="12" y1="8" y2="12" /><line x1="12" x2="12.01" y1="16" y2="16" /></Icon>
)
export const ArrowInIcon = () => <Icon><path d="M17 7 7 17" /><path d="M17 17H7V7" /></Icon>
export const ArrowOutIcon = () => <Icon><path d="M7 7h10v10" /><path d="M7 17 17 7" /></Icon>
export const ClockIcon = () => <Icon><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></Icon>
export const CloudOffIcon = () => (
  <Icon>
    <path d="m2 2 20 20" /><path d="M5.782 5.782A7 7 0 0 0 9 19h8.5a4.5 4.5 0 0 0 1.307-.193" />
    <path d="M21.532 16.5A4.5 4.5 0 0 0 17.5 10h-1.79A7.008 7.008 0 0 0 10 5.07" />
  </Icon>
)
export const PauseIcon = () => (
  <Icon><rect x="14" y="4" width="4" height="16" rx="1" /><rect x="6" y="4" width="4" height="16" rx="1" /></Icon>
)
export const PlusIcon = () => <Icon strokeWidth={2.2}><path d="M5 12h14" /><path d="M12 5v14" /></Icon>
export const XIcon = () => <Icon strokeWidth={2}><path d="M18 6 6 18" /><path d="m6 6 12 12" /></Icon>
export const LinkIcon = () => (
  <Icon>
    <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
    <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
  </Icon>
)

// Plan › Cash (lucide shapes: lock, landmark, coins, wallet, eye, eye-off).
export const LockIcon = () => (
  <Icon><rect width="18" height="11" x="3" y="11" rx="2" ry="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" /></Icon>
)
export const LandmarkIcon = () => (
  <Icon>
    <line x1="3" x2="21" y1="22" y2="22" /><line x1="6" x2="6" y1="18" y2="11" /><line x1="10" x2="10" y1="18" y2="11" />
    <line x1="14" x2="14" y1="18" y2="11" /><line x1="18" x2="18" y1="18" y2="11" /><polygon points="12 2 20 7 4 7" />
  </Icon>
)
export const CoinsIcon = () => (
  <Icon>
    <circle cx="8" cy="8" r="6" /><path d="M18.09 10.37A6 6 0 1 1 10.34 18" /><path d="M7 6h1v4" />
    <path d="m16.71 13.88.7.71-2.82 2.82" />
  </Icon>
)
export const WalletIcon = () => (
  <Icon>
    <path d="M19 7V4a1 1 0 0 0-1-1H5a2 2 0 0 0 0 4h15a1 1 0 0 1 1 1v4h-3a2 2 0 0 0 0 4h3a1 1 0 0 0 1-1v-2a1 1 0 0 0-1-1" />
    <path d="M3 5v14a2 2 0 0 0 2 2h15a1 1 0 0 0 1-1v-4" />
  </Icon>
)
export const EyeIcon = () => (
  <Icon><path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0" /><circle cx="12" cy="12" r="3" /></Icon>
)
export const EyeOffIcon = () => (
  <Icon>
    <path d="M10.733 5.076a10.744 10.744 0 0 1 11.205 6.575 1 1 0 0 1 0 .696 10.747 10.747 0 0 1-1.444 2.49" />
    <path d="M14.084 14.158a3 3 0 0 1-4.242-4.242" />
    <path d="M17.479 17.499a10.75 10.75 0 0 1-15.417-5.151 1 1 0 0 1 0-.696 10.75 10.75 0 0 1 4.446-5.143" />
    <path d="m2 2 20 20" />
  </Icon>
)
