import { expect, it } from 'vitest'
import { receiptProblem } from './receipt'

const file = (name: string, size = 10) => {
  const f = new File(['x'], name)
  Object.defineProperty(f, 'size', { value: size })
  return f
}

it('accepts the server extensions up to 10 MB', () => {
  for (const n of ['a.jpg', 'a.JPEG', 'a.png', 'a.gif', 'a.webp', 'a.pdf', 'a.heic', 'a.HEIF']) expect(receiptProblem(file(n))).toBeNull()
  expect(receiptProblem(file('a.jpg', 10 * 1024 * 1024))).toBeNull()
})
it('refuses other types and anything over 10 MB', () => {
  expect(receiptProblem(file('a.txt'))).toBe('Unsupported file type')
  expect(receiptProblem(file('noext'))).toBe('Unsupported file type')
  expect(receiptProblem(file('a.jpg', 10 * 1024 * 1024 + 1))).toBe('Max 10 MB')
})
