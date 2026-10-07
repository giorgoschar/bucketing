import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { query } from '../insights/fixtures'

const toast = vi.hoisted(() => vi.fn())
vi.mock('../../ui/Toast', () => ({ useToast: () => ({ show: toast }) }))
vi.mock('../../session/SessionProvider', () => ({ useSession: () => ({ status: 'signedIn', me: { id: 'me', household_id: 'hh1' } }) }))
vi.mock('./hooks', () => ({
  useCategories: () => query([
    { id: 'g', name: 'Groceries', color: '#10b981', icon: '🛒', is_default: false, system_key: null, locked: false, expense_count: 31, rule_count: 2 },
    { id: 'f', name: 'Fuel', color: '#f97316', icon: '⛽', is_default: true, system_key: 'fuel', locked: true, expense_count: 9, rule_count: 0 },
  ]),
  useRules: () => query([
    { id: 'r1', pattern: 'sklaven', category_id: 'g', match_count: 48, created_at: null },
    { id: 'r2', pattern: 'lidl', category_id: 'g', match_count: 3, created_at: null },
  ]),
}))

import { Categories } from './Categories'
import { deleteMessage, ruleChip } from './categoryHooks'

const renderIt = () => render(<QueryClientProvider client={new QueryClient()}><MemoryRouter><Categories /></MemoryRouter></QueryClientProvider>)
afterEach(() => { vi.restoreAllMocks(); toast.mockClear() })

describe('Categories & rules', () => {
  it('lists categories with System badges and rule chips beside them', () => {
    renderIt()
    expect(screen.getByRole('button', { name: 'sklaven 48' })).toBeInTheDocument()
    expect(within(screen.getByTestId('cat-f')).getByText('System')).toBeInTheDocument()
  })

  it('a locked category explains itself and has no editor', () => {
    renderIt()
    fireEvent.click(screen.getByRole('button', { name: /Fuel/ }))
    expect(screen.getByText('The composer needs this one to ask for litres.')).toBeInTheDocument()
    expect(screen.queryByLabelText('Category name')).toBeNull()
  })

  it('delete confirms with both counts', () => {
    expect(deleteMessage({ expense_count: 31, rule_count: 2 } as never)).toBe('31 expenses will become uncategorised and its 2 rules will be deleted.')
    renderIt()
    fireEvent.click(screen.getByRole('button', { name: /Groceries/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    expect(screen.getByText('31 expenses will become uncategorised and its 2 rules will be deleted.')).toBeInTheDocument()
  })

  it('edits a category with PUT', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 200 }))
    renderIt()
    fireEvent.click(screen.getByRole('button', { name: /Groceries/ }))
    fireEvent.change(screen.getByLabelText('Category name'), { target: { value: 'Food ' } })
    fireEvent.click(screen.getByRole('radio', { name: 'Cyan' }))
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    const req = fetch.mock.calls[0][0] as Request
    expect([req.method, new URL(req.url).pathname]).toEqual(['PUT', '/api/v1/settings/categories/g'])
    expect(await req.json()).toEqual({ name: 'Food', color: '#06b6d4', icon: '🛒' })
  })

  it('a rule collision is shown on the field', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ detail: 'Another rule already uses this pattern.' }), { status: 409, headers: { 'Content-Type': 'application/json' } }))
    renderIt()
    fireEvent.click(screen.getByRole('button', { name: 'lidl 3' }))
    const sheet = screen.getByRole('dialog', { name: 'Edit rule', hidden: true })
    fireEvent.change(within(sheet).getByLabelText('Merchant contains'), { target: { value: 'Sklaven' } })
    fireEvent.click(within(sheet).getByRole('button', { name: 'Save rule', hidden: true }))
    expect(await within(sheet).findByText('Another rule already uses this pattern.')).toBeInTheDocument()
    expect(toast).not.toHaveBeenCalled()
  })

  it('adds a rule with POST and the expanded category', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ id: 'r3', pattern: 'ab', category_id: 'g', match_count: 0, created_at: null }), { status: 201, headers: { 'Content-Type': 'application/json' } }))
    renderIt()
    fireEvent.click(screen.getByRole('button', { name: /Groceries/ }))
    fireEvent.click(screen.getByRole('button', { name: '＋ Rule' }))
    const sheet = screen.getByRole('dialog', { name: 'New rule', hidden: true })
    expect(within(sheet).getByText('Matches any merchant containing this text, ignoring case and accents. Minimum 2 characters.')).toBeInTheDocument()
    fireEvent.change(within(sheet).getByLabelText('Merchant contains'), { target: { value: 'AB' } })
    fireEvent.click(within(sheet).getByRole('button', { name: 'Save rule', hidden: true }))
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    const req = fetch.mock.calls[0][0] as Request
    expect([req.method, new URL(req.url).pathname]).toEqual(['POST', '/api/v1/settings/category-rules'])
    expect(await req.json()).toEqual({ pattern: 'AB', category_id: 'g' })
  })

  it('a one-character pattern is refused before sending', () => {
    const fetch = vi.spyOn(globalThis, 'fetch')
    renderIt()
    fireEvent.click(screen.getByRole('button', { name: 'lidl 3' }))
    const sheet = screen.getByRole('dialog', { name: 'Edit rule', hidden: true })
    fireEvent.change(within(sheet).getByLabelText('Merchant contains'), { target: { value: 'x' } })
    fireEvent.click(within(sheet).getByRole('button', { name: 'Save rule', hidden: true }))
    expect(within(sheet).getByText('Enter at least 2 characters.')).toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('writes are blocked offline', async () => {
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false)
    const fetch = vi.spyOn(globalThis, 'fetch')
    renderIt()
    fireEvent.click(screen.getByRole('button', { name: /Groceries/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(toast).toHaveBeenCalledWith("You're offline. This change needs a connection.", { tone: 'error' }))
    expect(fetch).not.toHaveBeenCalled()
  })

  it('chip text', () => {
    expect(ruleChip({ pattern: 'sklaven', match_count: 48 })).toBe('sklaven 48')
  })
})
