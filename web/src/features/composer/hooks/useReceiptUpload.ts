import { useQueryClient } from '@tanstack/react-query'
import { useCallback } from 'react'
import { readCsrf } from '../../../api/client'
import { editKey } from '../bridge'

/**
 * POST /transactions/{id}/receipt (multipart). Raw fetch because the queue holds JSON only and the
 * typed client would JSON-encode the body; receipts therefore need a connection (spec §5.4).
 */
export function useReceiptUpload() {
  const qc = useQueryClient()
  return useCallback(
    async (id: string, file: File): Promise<'ok' | 'failed'> => {
      const form = new FormData()
      form.append('file', file, file.name)
      try {
        const res = await fetch(`/api/v1/transactions/${encodeURIComponent(id)}/receipt`, {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'X-CSRF-Token': readCsrf() },
          body: form,
        })
        if (!res.ok) return 'failed'
        await qc.invalidateQueries({ queryKey: editKey(id) })
        return 'ok'
      } catch {
        return 'failed'
      }
    },
    [qc],
  )
}
