/*
 * Add-expense wizard Alpine component.
 *
 * Loaded from <head> deliberately. hx-boost swaps the <body>, and HTMX inserts
 * the whole fragment before evaluating any <script> inside it — so a factory
 * defined in the page's trailing scripts block does not exist yet when Alpine
 * initialises x-data on the nodes being inserted. That threw "expenseWizard is
 * not defined", cascading into "step is not defined" for every x-show on the
 * page, and left the wizard dead until a hard refresh.
 *
 * Per-page config (buckets, preselected bucket, today, currency) arrives via
 * the root element's data-init attribute, so nothing here depends on Jinja.
 */
function expenseWizard() {
  return {
    /* Config arrives from the element's data-init attribute rather than Jinja
       baked into this file, because this factory is loaded from <head>. */
    init() {
      let cfg = {};
      try { cfg = JSON.parse(this.$el.dataset.init || '{}'); } catch (_) {}
      this.buckets = cfg.buckets || {};
      this.form.bucket_id = cfg.selectedBucketId || '';
      this.form.transaction_date = cfg.today || '';
      this.form.currency = cfg.currency || 'EUR';
      // Default the payer to whoever is logged in. Leaving it blank saved the
      // expense with no payer at all, which settle-up cannot use: the shares
      // were charged to members but the money was credited to nobody, so both
      // members appeared to owe a third party who does not exist.
      this.form.paid_by = cfg.currentUserId || '';
    },

    buckets: {},
    step: 1,
    receiptName: '',
    duplicates: [],      // advisory only — never blocks submission
    dupLoading: false,
    catSearch: '',
    splits: {},
    splitTotal: 0,
    form: {
      bucket_id: '',
      transaction_date: '',
      amount: '',
      currency: 'EUR',
      category_id: '',
      paid_by: '',
      notes: '',
      is_shared: false,
    },

    stepLabel() {
      const labels = { 1: 'Bucket & Date', 2: 'Amount', 3: 'Category', 4: 'Details' };
      return labels[this.step] || '';
    },

    nextStep() {
      if (this.step < 4) this.step++;
      // Reaching the review step is the natural moment to warn about a
      // possible repeat: the amount and date are known, and the user has not
      // committed yet.
      if (this.step === 4) this.checkDuplicates();
    },

    async checkDuplicates() {
      this.duplicates = [];
      if (!this.form.amount || !this.form.transaction_date) return;
      this.dupLoading = true;
      try {
        const params = new URLSearchParams({
          amount: this.form.amount,
          transaction_date: this.form.transaction_date,
          bucket_id: this.form.bucket_id || '',
        });
        const resp = await fetch('/transactions/check-duplicate?' + params, {
          headers: { 'Accept': 'application/json' },
          credentials: 'same-origin',
        });
        if (resp.ok) this.duplicates = (await resp.json()).duplicates || [];
      } catch (_) {
        // A failed check must never get in the way of logging an expense.
      } finally {
        this.dupLoading = false;
      }
    },

    prevStep() {
      if (this.step > 1) this.step--;
    },

    bucketName(id) {
      return this.buckets[id] || '—';
    },

    updateSplitTotal() {
      let total = 0;
      for (const v of Object.values(this.splits)) {
        const n = parseFloat(v);
        if (!isNaN(n)) total += n;
      }
      this.splitTotal = total;
    },

    handleResult(evt) {
      if (evt.detail.successful) {
        this.step = 5; // hides all steps, result shown in #wizard-result
      }
    }
  };
}
