// The decoder's wasm is emitted by our build and served from /app/assets (CSP: 'self' + 'wasm-unsafe-eval');
// the package's default would fetch it from a CDN, which the CSP forbids. zxing-wasm is pinned in package.json at
// the exact version barcode-detector pins, so this wasm always matches the ponyfill's glue: bump them together.
import zxingWasmUrl from 'zxing-wasm/reader/zxing_reader.wasm?url'

export interface Detector { detect(source: HTMLVideoElement): Promise<{ rawValue: string }[]> }
type DetectorClass = {
  new (o: { formats: string[] }): Detector
  getSupportedFormats?: () => Promise<readonly string[]>
}

/** Module-level, so it is `===` across calls (zxing compares overrides by identity before reusing its module). */
const OVERRIDES = {
  locateFile: (path: string, prefix: string) => (path.endsWith('.wasm') ? zxingWasmUrl : prefix + path),
}

const FORMATS = ['ean_13', 'ean_8', 'upc_a', 'upc_e']
const NEEDED = ['ean_13', 'ean_8', 'upc_a']

/** The browser's own BarcodeDetector when it reads EAN/UPC (Android Chrome); else ZXing in wasm (iOS Safari). */
export async function makeDetector(): Promise<Detector> {
  const Native = (globalThis as { BarcodeDetector?: DetectorClass }).BarcodeDetector
  if (Native?.getSupportedFormats) {
    try {
      const supported = await Native.getSupportedFormats()
      if (NEEDED.every((f) => supported.includes(f))) return new Native({ formats: FORMATS.filter((f) => supported.includes(f)) })
    } catch {
      // fall through to the wasm reader
    }
  }
  const { BarcodeDetector, prepareZXingModule } = await import('barcode-detector/ponyfill')
  // Load and compile the wasm now, not on the first detect(): a failed load rejects here, so the camera stops
  // and the typed barcode takes over (instead of a live camera that never reads). The same overrides object
  // every time, so zxing keeps its compiled module across Scan taps.
  await prepareZXingModule({ overrides: OVERRIDES, fireImmediately: true })
  return new BarcodeDetector({ formats: FORMATS as never })
}
