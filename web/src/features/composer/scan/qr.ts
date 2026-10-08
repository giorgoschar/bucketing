export interface QrSession { stop(): void }

/** Lazy-loads qr-scanner (its own chunk) and decodes continuously from the back camera; no shutter. */
export async function startQr(video: HTMLVideoElement, onDecode: (text: string) => void): Promise<QrSession> {
  const { default: QrScanner } = await import('qr-scanner')
  const scanner = new QrScanner(video, (r) => onDecode(r.data), {
    preferredCamera: 'environment',
    maxScansPerSecond: 5,
    returnDetailedScanResult: true,
  })
  try {
    await scanner.start()
  } catch (e) {
    scanner.destroy()
    throw e
  }
  return {
    stop: () => {
      scanner.stop()
      scanner.destroy()
    },
  }
}

export function isReceiptUrl(text: string): boolean {
  try {
    return new URL(text.trim()).protocol === 'https:'
  } catch {
    return false
  }
}
