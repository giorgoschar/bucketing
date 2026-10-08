/** Mirrors app/api/transactions.py: MAX_RECEIPT_SIZE and ALLOWED_RECEIPT_EXTENSIONS. */
export const RECEIPT_MAX_BYTES = 10 * 1024 * 1024
export const RECEIPT_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.pdf', '.heic', '.heif']
export const RECEIPT_ACCEPT = 'image/*,application/pdf'

export function receiptProblem(file: File): 'Max 10 MB' | 'Unsupported file type' | null {
  const ext = /\.[^.]+$/.exec(file.name.toLowerCase())?.[0] ?? ''
  if (!RECEIPT_EXTENSIONS.includes(ext)) return 'Unsupported file type'
  if (file.size > RECEIPT_MAX_BYTES) return 'Max 10 MB'
  return null
}
