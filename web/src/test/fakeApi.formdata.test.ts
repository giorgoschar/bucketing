import { afterEach, expect, it } from 'vitest'
import { fakeApi } from './fakeApi'
import { resetTestEnv } from './render'

afterEach(resetTestEnv)

it('keeps a multipart body as the FormData itself', async () => {
  const api = fakeApi({ 'POST /api/v1/transactions/{txn_id}/receipt': () => ({ receipt_path: 'x.jpg' }) })
  const form = new FormData()
  form.append('file', new File(['img'], 'r.jpg', { type: 'image/jpeg' }))
  const res = await fetch('/api/v1/transactions/t1/receipt', { method: 'POST', body: form })
  expect(res.ok).toBe(true)
  expect((api.calls[0].body as FormData).get('file')).toBeInstanceOf(File)
})
