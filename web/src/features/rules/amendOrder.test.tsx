import { act, cleanup, render, screen } from '@testing-library/react'
import { QueryClient } from '@tanstack/react-query'
import { afterEach, expect, it } from 'vitest'
import { dismissToast, toast, Toaster } from '../../ui/Toast'
import { amendSavedToast } from './RulePrompt'

afterEach(() => { act(() => dismissToast()); cleanup() })

it('amending the Saved toast keeps Undo last, so it stays in the bottom-right corner', () => {
  render(<Toaster />)
  let id = 0
  act(() => { id = toast('Saved', { action: { label: 'Undo', onClick: () => {} } }) })
  act(() => {
    amendSavedToast(new QueryClient(), id, { text: 'Saved', action: { label: 'Undo', onPress: () => {} } },
      { pattern: 'lidl', label: 'Lidl', category_id: 'c', category_name: 'Groceries' })
  })
  const names = screen.getAllByRole('button').map((b) => b.textContent)
  expect(names[names.length - 1]).toBe('Undo')
})
