import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router'
import { Badge } from './Badge'
import { EmptyState } from './EmptyState'
import { List, ListRow } from './ListRow'
import { OfflineBanner } from './OfflineBanner'
import { ProgressBar, progressTone } from './ProgressBar'
import { Segmented } from './Segmented'

afterEach(cleanup)

it('ListRow is a button only when it has onClick', () => {
  const onClick = vi.fn()
  render(
    <List label="Bills">
      <ListRow title="Cosmote" subtitle="Out" trailing="€38.90" onClick={onClick} />
      <ListRow title="Salary" />
    </List>,
  )
  fireEvent.click(screen.getByRole('button', { name: /Cosmote/ }))
  expect(onClick).toHaveBeenCalledOnce()
  expect(screen.queryByRole('button', { name: /Salary/ })).toBeNull()
  expect(screen.getByRole('group', { name: 'Bills' })).toBeInTheDocument()
})

it('Segmented marks the current option and reports changes', () => {
  const onChange = vi.fn()
  const opts = [{ value: 'a', label: 'Upcoming' }, { value: 'b', label: 'Month' }] as const
  render(<Segmented label="View" options={opts} value="a" onChange={onChange} />)
  expect(screen.getByRole('button', { name: 'Upcoming' })).toHaveAttribute('aria-pressed', 'true')
  expect(screen.getByRole('button', { name: 'Month' })).toHaveAttribute('aria-pressed', 'false')
  fireEvent.click(screen.getByRole('button', { name: 'Month' }))
  expect(onChange).toHaveBeenCalledWith('b')
})

it('ProgressBar tone changes at 80% and 100%, and is safe with a zero max', () => {
  expect([0, 79.9, 80, 99.9, 100, 140].map(progressTone)).toEqual(['ok', 'ok', 'warn', 'warn', 'over', 'over'])
  render(<><ProgressBar value={1050} max={1200} label="Day to day" /><ProgressBar value={50} max={0} label="Empty" /></>)
  const bar = screen.getByRole('progressbar', { name: 'Day to day' })
  expect(bar).toHaveAttribute('data-tone', 'warn')
  expect(bar).toHaveAttribute('aria-valuenow', '88')
  const empty = screen.getByRole('progressbar', { name: 'Empty' })
  expect(empty).toHaveAttribute('aria-valuenow', '0')
  expect((empty.firstChild as HTMLElement).style.width).toBe('0%')
})

it('Badge renders its tone class', () => {
  render(<Badge tone="warn">over pace</Badge>)
  expect(screen.getByText('over pace')).toHaveClass('ui-badge', 'ui-badge--warn')
})

it('OfflineBanner shows the time today and the date otherwise', () => {
  const now = new Date(2026, 9, 7, 18, 0).getTime()
  const { rerender } = render(<OfflineBanner updatedAt={new Date(2026, 9, 7, 14, 2).getTime()} now={now} />)
  expect(screen.getByRole('status')).toHaveTextContent('Offline · updated 14:02')
  rerender(<OfflineBanner updatedAt={new Date(2026, 9, 5, 9, 30).getTime()} now={now} />)
  expect(screen.getByRole('status')).toHaveTextContent('Offline · updated 5 Oct 09:30')
})

it('EmptyState renders a link action or a button action', () => {
  const onClick = vi.fn()
  render(
    <MemoryRouter>
      <EmptyState title="Nothing due in the next 30 days" action={{ label: 'Add a recurring item', to: '/plan/items?new=1' }} />
      <EmptyState title="Couldn’t load this." action={{ label: 'Try again', onClick }} />
    </MemoryRouter>,
  )
  expect(screen.getByRole('link', { name: 'Add a recurring item' })).toHaveAttribute('href', '/plan/items?new=1')
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
  expect(onClick).toHaveBeenCalledOnce()
})
