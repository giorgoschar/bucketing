import { useCallback } from 'react'
import { api } from '../../../api/client'
import type { QrReceipt } from '../types'

export type QrLookup = { status: 'ok'; data: QrReceipt } | { status: 'error'; message: string }

/** POST /api/v1/transactions/scan/qr (B1): AADE lookup by the URL in the receipt's QR. */
export function useQrLookup() {
  return useCallback(async (url: string): Promise<QrLookup> => {
    try {
      const { data, error, response } = await api.POST('/api/v1/transactions/scan/qr', { body: { url } })
      if (response.ok && data) return { status: 'ok', data }
      const detail = (error as { detail?: unknown } | undefined)?.detail
      return { status: 'error', message: typeof detail === 'string' ? detail : 'Could not read the receipt' }
    } catch {
      return { status: 'error', message: 'Scanning needs a connection. Type it instead' }
    }
  }, [])
}
