import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { expect, it } from 'vitest'
import { BackHeader } from './BackHeader'

const href = (ui: React.ReactElement, url = '/x?p=last_month&lens=m') => {
  render(<MemoryRouter initialEntries={[url]}>{ui}</MemoryRouter>)
  return screen.getByRole('link', { name: 'Back' }).getAttribute('href')
}

it('goes to the plain parent, or keeps the current query when asked', () => {
  expect(href(<BackHeader title="T" back="/insights" />)).toBe('/insights')
  expect(href(<BackHeader title="T" back="/insights" keepSearch />)).toBe('/insights?p=last_month&lens=m')
})

it('a parent that carries its own query keeps it, and writes it over a kept query', () => {
  expect(href(<BackHeader title="T" back="/insights?tab=bills" />)).toBe('/insights?tab=bills')
  expect(href(<BackHeader title="T" back="/insights?tab=trends" keepSearch />)).toBe('/insights?p=last_month&lens=m&tab=trends')
})
