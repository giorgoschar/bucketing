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
