/* Stock page: add-product panel with product barcode (EAN-13/EAN-8/UPC) scanning.
 *
 * The vendored qr-scanner only decodes QR codes, so product barcodes use the
 * browser's built-in BarcodeDetector where it exists (Chrome/Edge on Android,
 * ChromeOS, macOS). Elsewhere (notably iOS Safari) the scan button is hidden
 * and the barcode is typed into the manual field instead. No CDN, no library.
 *
 * Loaded from <head> (see base.html) so the factory exists before Alpine
 * initialises an hx-boost-swapped body.
 */
function stockAdd() {
  return {
    open: false,
    scanning: false,
    scanError: '',
    scanSupported: typeof window !== 'undefined' && 'BarcodeDetector' in window,
    _stream: null,
    _timer: null,

    lookup(code) {
      code = String(code || '').replace(/\D/g, '');
      if (!code) return;
      const input = document.getElementById('stock-barcode-input');
      if (input) input.value = code;
      htmx.ajax('GET', '/stock/barcode?code=' + encodeURIComponent(code), {
        target: '#stock-lookup-results', swap: 'innerHTML',
      });
    },

    async startScan() {
      this.scanError = '';
      if (!this.scanSupported) {
        this.scanError = 'Barcode scanning is not supported in this browser — type the number instead.';
        return;
      }
      let detector;
      try {
        const wanted = ['ean_13', 'ean_8', 'upc_a', 'upc_e'];
        const supported = await window.BarcodeDetector.getSupportedFormats();
        const formats = wanted.filter((f) => supported.includes(f));
        if (!formats.length) throw new Error('no EAN support');
        detector = new window.BarcodeDetector({ formats });
      } catch (e) {
        this.scanSupported = false;
        this.scanError = 'Barcode scanning is not supported on this device — type the number instead.';
        return;
      }
      try {
        this._stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: 'environment' }, audio: false,
        });
      } catch (e) {
        this.scanError = 'Camera access denied — type the barcode instead.';
        return;
      }
      this.scanning = true;
      await this.$nextTick();
      const video = this.$refs.video;
      video.srcObject = this._stream;
      try { await video.play(); } catch (e) { /* autoplay quirks: detection still runs */ }
      this._timer = setInterval(async () => {
        if (!this.scanning || video.readyState < 2) return;
        try {
          const codes = await detector.detect(video);
          if (codes && codes.length) {
            const value = codes[0].rawValue;
            this.stopScan();
            this.lookup(value);
          }
        } catch (e) { /* per-frame miss */ }
      }, 300);
    },

    stopScan() {
      this.scanning = false;
      if (this._timer) { clearInterval(this._timer); this._timer = null; }
      if (this._stream) {
        this._stream.getTracks().forEach((t) => t.stop());
        this._stream = null;
      }
    },

    destroy() { this.stopScan(); },
  };
}
