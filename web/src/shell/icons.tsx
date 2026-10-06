import type { ReactNode, SVGProps } from 'react'

// Lucide icon paths (ISC), inlined so the shell has no icon runtime.
function Icon({ children, ...rest }: SVGProps<SVGSVGElement> & { children: ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {children}
    </svg>
  )
}

export const HouseIcon = () => (
  <Icon>
    <path d="M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8" />
    <path d="M3 10a2 2 0 0 1 .709-1.528l7-5.999a2 2 0 0 1 2.582 0l7 5.999A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
  </Icon>
)

export const ListIcon = () => (
  <Icon>
    <path d="M3 12h.01" /><path d="M3 18h.01" /><path d="M3 6h.01" />
    <path d="M8 12h13" /><path d="M8 18h13" /><path d="M8 6h13" />
  </Icon>
)

export const PlusIcon = () => (
  <Icon strokeWidth={2.2}>
    <path d="M5 12h14" /><path d="M12 5v14" />
  </Icon>
)

export const CalendarRangeIcon = () => (
  <Icon>
    <rect width="18" height="18" x="3" y="4" rx="2" />
    <path d="M16 2v4" /><path d="M3 10h18" /><path d="M8 2v4" />
    <path d="M17 14h-6" /><path d="M13 18H7" /><path d="M7 14h.01" /><path d="M17 18h.01" />
  </Icon>
)

export const ChartPieIcon = () => (
  <Icon>
    <path d="M21 12c.552 0 1.005-.449.95-.998a10 10 0 0 0-8.953-8.951c-.55-.055-.998.398-.998.95v8a1 1 0 0 0 1 1z" />
    <path d="M21.21 15.89A10 10 0 1 1 8 2.83" />
  </Icon>
)

export const ScanFaceIcon = () => (
  <Icon strokeWidth={2}>
    <path d="M3 7V5a2 2 0 0 1 2-2h2" /><path d="M17 3h2a2 2 0 0 1 2 2v2" />
    <path d="M21 17v2a2 2 0 0 1-2 2h-2" /><path d="M7 21H5a2 2 0 0 1-2-2v-2" />
    <path d="M8 14s1.5 2 4 2 4-2 4-2" /><path d="M9 9h.01" /><path d="M15 9h.01" />
  </Icon>
)

export const WalletIcon = () => (
  <Icon strokeWidth={2}>
    <path d="M19 7V4a1 1 0 0 0-1-1H5a2 2 0 0 0 0 4h15a1 1 0 0 1 1 1v4h-3a2 2 0 0 0 0 4h3a1 1 0 0 0 1-1v-2a1 1 0 0 0-1-1" />
    <path d="M3 5v14a2 2 0 0 0 2 2h15a1 1 0 0 0 1-1v-4" />
  </Icon>
)

export const LogOutIcon = () => (
  <Icon strokeWidth={2}>
    <path d="m16 17 5-5-5-5" /><path d="M21 12H9" /><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
  </Icon>
)

export const CloseIcon = () => (
  <Icon strokeWidth={2}>
    <path d="M18 6 6 18" /><path d="m6 6 12 12" />
  </Icon>
)
