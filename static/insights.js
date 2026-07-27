/*
 * Insights page Alpine components.
 *
 * Loaded from <head> deliberately. hx-boost swaps the <body>, and HTMX inserts
 * the whole fragment before it evaluates any <script> inside it — so a factory
 * defined in the swapped markup does not exist yet when Alpine's
 * MutationObserver initialises x-data on the nodes being inserted. That threw
 * "insightsFilters is not defined" and left the filter bar inert until a hard
 * refresh. Defining these in <head> means they are always present, on first
 * load and on every subsequent boosted navigation.
 *
 * Initial state is read from the root element's data-init attribute rather
 * than a global, so there is no second ordering dependency.
 */
/* -----------------------------------------------------------------------
 * insightsFilters — filter bar state; triggers the HTMX swap.
 *
 * These components MUST be defined here, above the markup that uses them,
 * rather than in the template's trailing scripts block.
 *
 * base.html renders the content block (~line 378) before the scripts block
 * (~line 412), so a definition placed in the scripts block lands *after* the
 * x-data element that references it. Alpine's MutationObserver initialises
 * nodes as they are inserted, so on an hx-boost navigation it reached
 * x-data="insightsFilters(...)" before this function existed and threw
 * "insightsFilters is not defined" — leaving the whole filter bar inert until
 * a hard refresh. base.html hoists pushSettings() for the same reason.
 * ----------------------------------------------------------------------- */
function insightsFilters() {
  return {
    /* Alpine calls init() once the element exists, so the config can be read
       from the DOM instead of relying on a global defined by a sibling script. */
    init() {
      let cfg = {};
      try { cfg = JSON.parse(this.$el.dataset.init || '{}'); } catch (_) {}
      this.preset      = cfg.preset      || 'this_month';
      this.startDate   = cfg.startDate   || '';
      this.endDate     = cfg.endDate     || '';
      this.bucketType  = cfg.bucketType  || '';
      this.bucketIds   = (cfg.bucketIds   || []).slice();
      this.categoryIds = (cfg.categoryIds || []).slice();
      this.paidBy      = cfg.paidBy      || '';
      this.membersMap  = cfg.membersMap  || {};
      this.bucketsMap  = cfg.bucketsMap  || {};
      this.catsMap     = cfg.catsMap     || {};
    },

    preset: 'this_month', startDate: '', endDate: '', bucketType: '',
    bucketIds: [], categoryIds: [], paidBy: '',
    membersMap: {}, bucketsMap: {}, catsMap: {},

    // Dropdown open states
    openPreset:    false,
    openBuckets:   false,
    openCats:      false,
    openPaidBy:    false,

    // Request state — `loading` dims the widgets so a filter click gives
    // instant feedback instead of appearing to do nothing for ~half a second.
    loading:       false,
    failed:        false,

    _timer:    null,
    _inflight: false,
    _pending:  false,

    paidByLabel() {
      return (this.paidBy && this.membersMap[this.paidBy]) ? this.membersMap[this.paidBy] : 'Paid by';
    },

    presetLabel() {
      const map = {
        'this_month': 'This month', 'last_month': 'Last month',
        'last_3m': 'Last 3 months', 'last_6m': 'Last 6 months',
        'this_year': 'This year',   'all_time': 'All time',
        'custom': 'Custom range',
      };
      return map[this.preset] || this.preset;
    },

    setPreset(p) {
      this.preset = p;
      this.openPreset = false;
      if (p !== 'custom') {
        this.startDate = '';
        this.endDate   = '';
        this._debounce(0);
      }
    },

    applyCustom() {
      if (this.startDate && this.endDate) {
        this.preset = 'custom';
        this.openPreset = false;
        this._debounce(0);
      }
    },

    toggleBucket(id) {
      this.bucketIds = this.bucketIds.includes(id)
        ? this.bucketIds.filter(b => b !== id)
        : [...this.bucketIds, id];
      this._debounce();
    },

    toggleCategory(id) {
      this.categoryIds = this.categoryIds.includes(id)
        ? this.categoryIds.filter(c => c !== id)
        : [...this.categoryIds, id];
      this._debounce();
    },

    setBucketType(t) {
      this.bucketType = (this.bucketType === t) ? '' : t;
      this.bucketIds  = [];
      this._debounce(0);
    },

    clearAll() {
      this.preset      = 'this_month';
      this.startDate   = '';
      this.endDate     = '';
      this.bucketType  = '';
      this.bucketIds   = [];
      this.categoryIds = [];
      this.paidBy      = '';
      this.openPreset  = false;
      this.openBuckets = false;
      this.openCats    = false;
      this.openPaidBy  = false;
      this._debounce(0);
    },

    hasFilters() {
      return this.preset !== 'this_month' || this.bucketType || this.bucketIds.length ||
             this.categoryIds.length || this.paidBy;
    },

    /* Every filter mutation funnels through here.
     *
     * Previously some actions (preset, bucket type, clear) called _go()
     * immediately while others went through a 400ms debounce. Two requests
     * could then be in flight at once and whichever *responded* last won —
     * so a filter could visibly "not apply" because a slower earlier request
     * overwrote it. Now there is a single path, and _go() serialises. */
    _debounce(delay = 180) {
      clearTimeout(this._timer);
      this.loading = true;            // immediate feedback, before the request
      this.failed  = false;
      this._timer = setTimeout(() => this._go(), delay);
    },

    _url() {
      let p = '?preset=' + encodeURIComponent(this.preset);
      if (this.startDate)            p += '&start_date=' + this.startDate;
      if (this.endDate)              p += '&end_date='   + this.endDate;
      if (this.bucketType)           p += '&bucket_type='  + encodeURIComponent(this.bucketType);
      if (this.bucketIds.length)     p += '&bucket_ids='   + this.bucketIds.join(',');
      if (this.categoryIds.length)   p += '&category_ids=' + this.categoryIds.join(',');
      if (this.paidBy)               p += '&paid_by='      + encodeURIComponent(this.paidBy);
      return '/insights' + p;
    },

    /* Only ever one request in flight. If the user keeps clicking while one is
     * running we just flag _pending and re-fire once it lands, so the final
     * render always reflects the final filter state — no out-of-order swaps. */
    _go() {
      if (this._inflight) { this._pending = true; return; }

      const url = this._url();
      history.replaceState({}, '', url);

      this._inflight = true;
      this.loading   = true;

      htmx.ajax('GET', url, { target: '#insights-swap', swap: 'innerHTML' })
        .then(() => { this.failed = false; })
        .catch(() => { this.failed = true; })
        .finally(() => {
          this._inflight = false;
          if (this._pending) {
            this._pending = false;
            this._go();               // coalesce into one trailing request
          } else {
            this.loading = false;
          }
        });
    },
  };
}

/* -----------------------------------------------------------------------
 * widgetToggle — persists widget visibility to localStorage
 * ----------------------------------------------------------------------- */
function widgetToggle() {
  const DEFAULTS = {
    kpi: true, forecast: true, trend: true, categories: true,
    budget: true, who_paid: true, bucket_breakdown: true, cat_trend: true,
  };
  const stored = (() => {
    try { return JSON.parse(localStorage.getItem('insights_widgets') || '{}'); }
    catch (_) { return {}; }
  })();
  const state = Object.assign({}, DEFAULTS, stored);

  return {
    open: false,
    ...state,

    toggle(key) {
      this[key] = !this[key];
      this._save();
    },

    show(key) { return !!this[key]; },

    _save() {
      const out = {};
      Object.keys(DEFAULTS).forEach(k => { out[k] = !!this[k]; });
      try { localStorage.setItem('insights_widgets', JSON.stringify(out)); } catch (_) {}
    },
  };
}
