// The decoder's wasm is emitted by our build and served from /app/assets (CSP: 'self' + 'wasm-unsafe-eval');
// the package's default would fetch it from a CDN, which the CSP forbids.
import zxingWasmUrl from 'zxing-wasm/reader/zxing_reader.wasm?url'

export interface Detector { detect(source: HTMLVideoElement): Promise<{ rawValue: string }[]> }
type DetectorClass = {
  new (o: { formats: string[] }): Detector
  getSupportedFormats?: () => Promise<readonly string[]>
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
  prepareZXingModule({
    overrides: { locateFile: (path: string, prefix: string) => (path.endsWith('.wasm') ? zxingWasmUrl : prefix + path) },
  })
  return new BarcodeDetector({ formats: FORMATS as never })
}
