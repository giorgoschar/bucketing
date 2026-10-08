import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { Sheet } from './Sheet'

afterEach(cleanup)

function Harness({ closeOnBackdrop, onClose = () => {} }: { closeOnBackdrop?: boolean; onClose?: () => void }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>Open</button>
      <Sheet open={open} title="Cosmote" closeOnBackdrop={closeOnBackdrop}
        onClose={() => { onClose(); setOpen(false) }}>
        <button type="button">First</button>
        <button type="button">Last</button>
      </Sheet>
    </>
  )
}

it('opens as a named modal dialog and moves focus inside', () => {
  render(<Harness />)
  fireEvent.click(screen.getByRole('button', { name: 'Open' }))
  const dialog = screen.getByRole('dialog', { name: 'Cosmote' })
  expect(dialog).toHaveAttribute('aria-modal', 'true')
  expect(dialog.contains(document.activeElement)).toBe(true)
})

it('Esc closes and focus returns to the opener', () => {
  render(<Harness />)
  const opener = screen.getByRole('button', { name: 'Open' })
  opener.focus()
  fireEvent.click(opener)
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(document.activeElement).toBe(opener)
})

it('a backdrop tap closes unless closeOnBackdrop is false', () => {
  const onClose = vi.fn()
  const { unmount } = render(<Harness onClose={onClose} />)
  fireEvent.click(screen.getByRole('button', { name: 'Open' }))
  fireEvent.click(screen.getByTestId('sheet-backdrop'))
  expect(onClose).toHaveBeenCalledOnce()
  unmount()
  render(<Harness closeOnBackdrop={false} onClose={onClose} />)
  fireEvent.click(screen.getByRole('button', { name: 'Open' }))
  fireEvent.click(screen.getByTestId('sheet-backdrop'))
  expect(onClose).toHaveBeenCalledOnce()
  expect(screen.getByRole('dialog')).toBeInTheDocument()
})

it('traps Tab inside the sheet', () => {
  render(<Harness />)
  fireEvent.click(screen.getByRole('button', { name: 'Open' }))
  const last = screen.getByRole('button', { name: 'Last' })
  last.focus()
  fireEvent.keyDown(document, { key: 'Tab' })
  expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Close' }))
  fireEvent.keyDown(document, { key: 'Tab', shiftKey: true })
  expect(document.activeElement).toBe(last)
})

it('a sheet that ignores the backdrop ignores Esc too (2d backup codes)', () => {
  const onClose = vi.fn()
  render(<Harness closeOnBackdrop={false} onClose={onClose} />)
  fireEvent.click(screen.getByRole('button', { name: 'Open' }))
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(onClose).not.toHaveBeenCalled()
  expect(screen.getByRole('dialog', { name: 'Cosmote' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Close' })) // the explicit Close still works
  expect(onClose).toHaveBeenCalledOnce()
})
