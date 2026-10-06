/*
 * Receipt scanner Alpine component (scan page).
 *
 * Loaded from <head>, before alpine.min.js, like the other factories: hx-boost
 * swaps the <body> and HTMX inserts it before evaluating inline scripts, so a
 * factory defined in the page does not exist when Alpine initialises it.
 *
 * Third-party code is vendored under /static/vendor (npm run vendor:copy):
 *   qr-scanner/  tesseract/ (worker, core, ell + eng language data)  pdfjs/
 * qr-scanner and tesseract.min.js are loaded by <script> tags on the scan page;
 * pdf.js is imported on first use. Per-page defaults come from data-init.
 */
function receiptScanner() {
  const TESS_BASE = location.origin + '/static/vendor/tesseract';
  const PDFJS_BASE = '/static/vendor/pdfjs';
  return {
    // --- state ---
    file: null,
    fileName: '',
    dragging: false,
    scanning: false,
    progress: 0,
    progressLabel: 'Initialising…',
    errorMsg: '',
    previewUrl: '',
    receiptFilename: '',
    resultReady: false,
    _qrScanner: null,
    _pdfjs: null,

    result: {
      amount: '',
      currency: 'EUR',
      date: '',
      merchant: '',
      category_id: '',
      bucket_id: '',
      paid_by: '',
      payment_method: 'card',
    },

    /* Per-page defaults arrive through the root element's data-init attribute
       (JSON from `| tojson`), because this factory is a static file. */
    init() {
      let cfg = {};
      try { cfg = JSON.parse(this.$el.dataset.init || '{}'); } catch (_) {}
      this.result.currency = cfg.currency || 'EUR';
      this.result.date = cfg.today || '';
      this.result.bucket_id = cfg.bucketId || '';
    },

    /* PDF.js 4.x is an ES module; import it once, on first use, from the
       vendored copy (npm run vendor:copy). */
    async loadPdfjs() {
      if (!this._pdfjs) {
        const lib = await import(PDFJS_BASE + '/pdf.min.mjs');
        lib.GlobalWorkerOptions.workerSrc = PDFJS_BASE + '/pdf.worker.min.mjs';
        this._pdfjs = lib;
      }
      return this._pdfjs;
    },

    // --- file handling ---
    handleFile(event) {
      const f = event.target.files[0];
      if (f) this.setFile(f);
    },

    handleDrop(event) {
      this.dragging = false;
      const f = event.dataTransfer.files[0];
      if (f) this.setFile(f);
    },

    setFile(f) {
      this.file = f;
      this.fileName = f.name;
      this.errorMsg = '';
      // Show image preview immediately (not for PDFs)
      if (f.type.startsWith('image/')) {
        this.previewUrl = URL.createObjectURL(f);
      } else {
        this.previewUrl = '';
      }
      // Auto-start scan so mobile users don't need a second tap
      this.$nextTick(() => this.startScan());
    },

    // --- scan pipeline ---
    async startScan() {
      if (!this.file) return;
      this.scanning = true;
      this.errorMsg = '';
      this.progress = 0;
      this.progressLabel = 'Preparing…';

      try {
        const isPdf = this.file.type === 'application/pdf' || this.file.name.toLowerCase().endsWith('.pdf');

        // ── Step 1: For digital PDFs try text layer directly ───────────────
        if (isPdf) {
          const extracted = await this.extractPdfTextLayer(this.file);
          if (extracted && extracted.trim().length > 40) {
            this.progressLabel = 'Parsing fields…';
            this.progress = 90;
            await this.parseOnServer(extracted);
            this.progress = 100;
            return;
          }
          // Sparse text layer → scanned PDF, fall through to OCR
        }

        const canvas = await this.fileToCanvas(this.file);
        this.progressLabel = 'Running OCR…';

        // Fix 3: PSM 4 = single column (receipts are always narrow single column).
        // OEM 1 = LSTM only (more accurate than legacy+LSTM combo for Greek).
        const worker = await Tesseract.createWorker(['ell', 'eng'], 1, {
          // Everything is served from /static/vendor/tesseract (no CDN). Absolute
          // URLs and no blob wrapper: the default blob worker resolves relative
          // paths against blob:, which fails.
          workerPath: TESS_BASE + '/worker.min.js',
          corePath: TESS_BASE + '/core',
          langPath: TESS_BASE + '/lang',
          workerBlobURL: false,
          logger: (m) => {
            if (m.status === 'recognizing text') {
              this.progress = Math.round(m.progress * 100);
              this.progressLabel = 'Recognising text…';
            } else if (m.status.includes('load')) {
              this.progressLabel = 'Loading language pack…';
              this.progress = Math.min(this.progress + 5, 30);
            }
          },
        });
        await worker.setParameters({
          // PSM 6 = SINGLE_BLOCK: treats receipt as one uniform text block.
          // Better than PSM 4 (single column) for two-column receipt layouts
          // where item names are left-aligned and prices are right-aligned.
          tessedit_pageseg_mode: Tesseract.PSM.SINGLE_BLOCK,
          tessedit_ocr_engine_mode: Tesseract.OEM.LSTM_ONLY,
        });

        const { data: { text } } = await worker.recognize(canvas);
        await worker.terminate();

        this.progressLabel = 'Parsing fields…';
        this.progress = 95;

        await this.parseOnServer(text);
        this.progress = 100;

      } catch (err) {
        console.error(err);
        this.errorMsg = 'Could not read the receipt. Please fill in the details manually.';
        this.resultReady = true;
      } finally {
        this.scanning = false;
      }
    },

    // ─── Live QR camera ──────────────────────────────────────────────

    async startQrCamera() {
      if (typeof QrScanner === 'undefined') {
        this.errorMsg = 'QR scanner failed to load. Please refresh the page.';
        return;
      }
      const overlay  = document.getElementById('qr-overlay');
      const video    = document.getElementById('qr-video');
      const cancelBtn = document.getElementById('qr-cancel');
      const status   = document.getElementById('qr-status');

      overlay.style.display = 'flex';
      status.textContent = '';

      const stop = () => {
        if (this._qrScanner) {
          this._qrScanner.stop();
          this._qrScanner.destroy();
          this._qrScanner = null;
        }
        overlay.style.display = 'none';
      };

      cancelBtn.onclick = stop;

      try {
        this._qrScanner = new QrScanner(
          video,
          async (result) => {
            const url = result && (result.data || result);
            if (!url || typeof url !== 'string') return;
            // Any https link goes to the server, which reads AADE pages and
            // follows a provider's receipt page to its AADE link.
            if (!/^https:\/\//i.test(url.trim())) {
              status.textContent = 'This QR code is not a receipt link.';
              return;
            }
            stop();
            this.scanning = true;
            this.progressLabel = 'Reading the receipt from AADE…';
            this.progress = 50;
            const err = await this.fetchFromAade(url.trim());
            this.scanning = false;
            if (err) this.errorMsg = err;
          },
          {
            preferredCamera: 'environment',
            highlightScanRegion: true,
            highlightCodeOutline: true,
            onDecodeError: () => {},   // silence per-frame misses
          }
        );
        await this._qrScanner.start();
      } catch (e) {
        stop();
        this.errorMsg = 'Camera access denied. Please allow camera access or upload a photo instead.';
        console.warn('QrScanner error:', e);
      }
    },

    // ─── AADE portal fetch ───────────────────────────────────────────

    // Fetch receipt data from the QR link via our backend proxy.
    // Returns null on success, else the message to show.
    async fetchFromAade(url) {
      try {
        const data = await app.fetchJSON('/transactions/scan/qr', {
          method: 'POST',
          body: { url },
        });
        if (data.amount)       this.result.amount      = data.amount;
        if (data.currency)     this.result.currency    = data.currency;
        if (data.date)         this.result.date        = data.date;
        if (data.merchant)     this.result.merchant    = data.merchant;
        if (data.category_id)  this.result.category_id = data.category_id;
        this.resultReady = true;
        return null;
      } catch (e) {
        console.warn('Receipt QR fetch failed:', e);
        return (e && e.status === 400 && e.message)
          ? e.message
          : 'Could not load the receipt from AADE. Try uploading a photo instead.';
      }
    },

    // Fix 1: Extract text layer from a digital PDF (skips OCR entirely).
    async extractPdfTextLayer(file) {
      try {
        const pdfjsLib = await this.loadPdfjs();
        const arrayBuffer = await file.arrayBuffer();
        const pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;
        let allText = '';
        // Extract up to first 3 pages (multi-page invoices)
        const pageCount = Math.min(pdf.numPages, 3);
        for (let i = 1; i <= pageCount; i++) {
          const page = await pdf.getPage(i);
          const content = await page.getTextContent();
          const pageText = content.items.map(item => item.str).join(' ');
          allText += pageText + '\n';
        }
        return allText;
      } catch (e) {
        console.warn('PDF text layer extraction failed:', e);
        return null;
      }
    },

    async fileToCanvas(file) {
      const isPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');
      const raw = isPdf ? await this.pdfToCanvas(file) : await this.imageToCanvas(file);
      // Fix 2: Preprocess for better OCR on thermal/printed receipts
      return this.preprocessCanvas(raw);
    },

    // Fix 2: Grayscale + Otsu threshold + upscale.
    // Converts a noisy photo of a thermal receipt to clean black-on-white.
    preprocessCanvas(src) {
      const MIN_WIDTH = 1800;
      let w = src.width, h = src.height;
      // Upscale small images — Tesseract struggles below ~150 DPI effective
      if (w < MIN_WIDTH) {
        const scale = MIN_WIDTH / w;
        w = Math.round(w * scale);
        h = Math.round(h * scale);
      }
      const dst = document.createElement('canvas');
      dst.width = w;
      dst.height = h;
      const ctx = dst.getContext('2d');
      ctx.drawImage(src, 0, 0, w, h);

      const imageData = ctx.getImageData(0, 0, w, h);
      const data = imageData.data;
      const len = w * h;

      // Step 1: convert to grayscale in-place
      const gray = new Uint8Array(len);
      for (let i = 0; i < len; i++) {
        const r = data[i * 4], g = data[i * 4 + 1], b = data[i * 4 + 2];
        gray[i] = Math.round(0.299 * r + 0.587 * g + 0.114 * b);
      }

      // Step 2: Otsu's threshold — find optimal split from histogram
      const hist = new Int32Array(256);
      for (let i = 0; i < len; i++) hist[gray[i]]++;
      let sum = 0;
      for (let t = 0; t < 256; t++) sum += t * hist[t];
      let sumB = 0, wB = 0, max = 0, threshold = 128;
      for (let t = 0; t < 256; t++) {
        wB += hist[t];
        if (wB === 0) continue;
        const wF = len - wB;
        if (wF === 0) break;
        sumB += t * hist[t];
        const mB = sumB / wB;
        const mF = (sum - sumB) / wF;
        const between = wB * wF * (mB - mF) ** 2;
        if (between > max) { max = between; threshold = t; }
      }

      // Step 3: binarize — white background, black text
      for (let i = 0; i < len; i++) {
        const v = gray[i] > threshold ? 255 : 0;
        data[i * 4] = data[i * 4 + 1] = data[i * 4 + 2] = v;
        data[i * 4 + 3] = 255;
      }

      // Step 4: sharpening (unsharp mask on the binary image).
      // Thermal print can be slightly blurry when photographed — sharpening
      // reinforces thin strokes (Greek accents, small digits, decimal dots).
      // Kernel: identity * 2 - 3x3 box blur * 1 (lightweight, no extra libs)
      const sharpened = new Uint8ClampedArray(data.length);
      for (let y = 0; y < h; y++) {
        for (let x = 0; x < w; x++) {
          const idx = (y * w + x) * 4;
          // 3×3 neighbour average
          let sum3 = 0, count3 = 0;
          for (let dy = -1; dy <= 1; dy++) {
            for (let dx = -1; dx <= 1; dx++) {
              const nx = x + dx, ny = y + dy;
              if (nx >= 0 && nx < w && ny >= 0 && ny < h) {
                sum3 += data[(ny * w + nx) * 4];
                count3++;
              }
            }
          }
          const blurred = sum3 / count3;
          // sharpened = 2*original - blurred, clamped
          const sharp = Math.max(0, Math.min(255, 2 * data[idx] - blurred));
          // Re-binarize after sharpening to keep clean B&W
          const out = sharp < 128 ? 0 : 255;
          sharpened[idx] = sharpened[idx + 1] = sharpened[idx + 2] = out;
          sharpened[idx + 3] = 255;
        }
      }
      const sharpData = new ImageData(sharpened, w, h);
      ctx.putImageData(sharpData, 0, 0);
      return dst;
    },

    imageToCanvas(file) {
      return new Promise((resolve, reject) => {
        const img = new Image();
        const url = URL.createObjectURL(file);
        img.onload = () => {
          const canvas = document.createElement('canvas');
          // Cap at 3000px — above this Tesseract slows dramatically with no gain
          const MAX = 3000;
          let w = img.naturalWidth, h = img.naturalHeight;
          if (w > MAX || h > MAX) {
            const ratio = Math.min(MAX / w, MAX / h);
            w = Math.round(w * ratio);
            h = Math.round(h * ratio);
          }
          canvas.width = w;
          canvas.height = h;
          canvas.getContext('2d').drawImage(img, 0, 0, w, h);
          URL.revokeObjectURL(url);
          resolve(canvas);
        };
        img.onerror = reject;
        img.src = url;
      });
    },

    async pdfToCanvas(file) {
      const pdfjsLib = await this.loadPdfjs();
      const arrayBuffer = await file.arrayBuffer();
      const pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;
      const page = await pdf.getPage(1);
      const scale = 2.0; // render at 2× for better OCR accuracy
      const viewport = page.getViewport({ scale });
      const canvas = document.createElement('canvas');
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      const ctx = canvas.getContext('2d');
      await page.render({ canvasContext: ctx, viewport }).promise;
      return canvas;
    },

    async parseOnServer(text) {
      // Rejects on a non-2xx response, which startScan() reports to the user.
      const data = await app.fetchJSON('/transactions/scan/parse', {
        method: 'POST',
        body: { text },
      });

      if (data.amount)       this.result.amount      = data.amount;
      if (data.currency)     this.result.currency    = data.currency;
      if (data.date)         this.result.date        = data.date;
      if (data.merchant)     this.result.merchant    = data.merchant;
      if (data.category_id)  this.result.category_id = data.category_id;

      this.resultReady = true;
    },

    // --- form submission ---
    // We POST to the standard /transactions endpoint as a normal form.
    // Because we use enctype=multipart/form-data and the receipt is already
    // on the server (receipt_path hidden field), we just submit normally.
    submitForm(event) {
      event.target.submit();
    },

    // --- reset ---
    reset() {
      this.file = null;
      this.fileName = '';
      this.previewUrl = '';
      this.scanning = false;
      this.progress = 0;
      this.resultReady = false;
      this.errorMsg = '';
    },
  };
}
