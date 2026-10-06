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
      this.fuelCategoryId = cfg.fuelCategoryId || '';
      this.currentUserId = cfg.currentUserId || '';
      this.form.paid_by = this.currentUserId;
      // Paid the way this user paid last time (the server looks it up).
      this.form.payment_method = cfg.paymentMethod || 'card';
      // Optional prefill from a link (e.g. stock "Mark bought"); the server
      // already validated amount and category.
      const pre = cfg.prefill || {};
      for (const key of ['amount', 'category_id', 'notes', 'merchant']) {
        if (pre[key]) this.form[key] = String(pre[key]);
      }
      // Another category clears the fuel price, so going back to Fuel starts
      // empty instead of resubmitting a stale price.
      this.$watch('form.category_id', () => {
        if (!this.isFuel()) this.form.fuel_price_per_litre = '';
      });
      this._wireOfflineSubmit();
    },

    /* Offline: queue the expense in IndexedDB and register Background Sync
       instead of letting the browser submit a request that cannot succeed.
       Wired here (not in a page <script>) because a swapped-in body's scripts
       run after Alpine, and the form is a fresh node on every navigation, so
       the listener never accumulates. */
    _wireOfflineSubmit() {
      const form = this.$el.querySelector('#expense-form');
      if (!form) return;
      form.addEventListener('submit', async (e) => {
        if (navigator.onLine) return; // normal submission proceeds
        e.preventDefault();
        e.stopImmediatePropagation();
        if (!window.offlineExpenses) {
          alert('Offline support is loading. Please try again in a moment.');
          return;
        }
        try {
          await window.offlineExpenses.saveOfflineTransaction(new FormData(form));
        } catch (err) {
          // IndexedDB unavailable / quota / private mode: the submit was already
          // cancelled, so say plainly that nothing was saved and keep the form
          // (and the user's input) exactly as it is.
          console.error('offline save failed', err);
          alert("Couldn't save offline \u2014 your expense was NOT saved. " +
                'Please keep this page open and retry when online.');
          return;
        }
        if ('serviceWorker' in navigator && 'SyncManager' in window) {
          const reg = await navigator.serviceWorker.ready;
          await reg.sync.register('submit-expense').catch(() => {});
        }
        const result = document.getElementById('wizard-result');
        if (result) {
          result.innerHTML = '<div class="mt-6 p-4 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-xl text-center"><p class="text-sm font-medium text-amber-700 dark:text-amber-400">\u{1F4F6} You\'re offline. Your expense has been saved and will sync automatically when you reconnect.</p></div>';
        }
        this.step = 5; // hide the wizard steps
      });
    },

    buckets: {},
    fuelCategoryId: '',  // the built-in Fuel category: unlocks the price per litre
    currentUserId: '',
    ownShareChoice: '',
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
      payment_method: 'card',
      took_cash: false,        // "I took this from my stash": logs the take too (cash only)
      take_from: 'stash',      // where that cash came from: 'stash' or 'bank'
      merchant: '',
      is_shared: false,
      fuel_price_per_litre: '',  // only sent while the Fuel category is picked
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

    isFuel() {
      return !!this.fuelCategoryId && this.form.category_id === this.fuelCategoryId;
    },

    /* Mirrors the server rule: a price, when given, is above zero. */
    fuelPriceInvalid() {
      if (!this.isFuel() || String(this.form.fuel_price_per_litre).trim() === '') return false;
      const price = parseFloat(String(this.form.fuel_price_per_litre).replace(',', '.'));
      return !(price > 0);
    },

    /* A preview only: the server works the litres out again (amount / price,
       both in the expense currency) and never trusts a client value. */
    fuelLitres() {
      if (!this.isFuel() || this.fuelPriceInvalid()) return '';
      const price = parseFloat(String(this.form.fuel_price_per_litre).replace(',', '.'));
      const amount = parseFloat(this.form.amount);
      if (!(price > 0) || !(amount > 0)) return '';
      return (amount / price).toFixed(2);
    },

    bucketName(id) {
      return this.buckets[id] || '—';
    },

    /* "Each paid their own share": the payer value is a sentinel the server
       maps to payer_mode=own_share. The splits are what each person paid, so
       the split section has to be open. */
    chooseOwnShare(value) {
      this.ownShareChoice = value;
      this.form.paid_by = value;
      this.form.is_shared = true;
    },

    isOwnShare() {
      return !!this.ownShareChoice && this.form.paid_by === this.ownShareChoice;
    },

    toggleShared() {
      this.form.is_shared = !this.form.is_shared;
      // Own share without the split makes no sense: fall back to "I paid".
      if (!this.form.is_shared && this.isOwnShare()) this.form.paid_by = this.currentUserId;
    },

    /* Mirrors the server rule: own-share shares must add up to the total. */
    ownShareInvalid() {
      if (!this.isOwnShare()) return false;
      return Math.abs(this.splitTotal - parseFloat(this.form.amount || 0)) > 0.01;
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
