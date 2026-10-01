/**
 * offline.js — IndexedDB helpers for offline expense queuing.
 *
 * Offline transactions are stored in IndexedDB and flushed via
 * Background Sync (tag: "submit-expense") once connectivity returns.
 */

var DB_NAME = 'expenses-offline';
var DB_VERSION = 1;
var STORE = 'pending_transactions';

function _openDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = (e) => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE, { keyPath: 'id', autoIncrement: true });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror   = () => reject(req.error);
  });
}

/** Persist a FormData payload (as plain object) into IndexedDB. */
async function saveOfflineTransaction(formData) {
  const db = await _openDB();
  const record = { saved_at: new Date().toISOString() };
  for (const [k, v] of formData.entries()) {
    // Skip file inputs — we can't queue receipts offline
    if (v instanceof File) continue;
    record[k] = v;
  }
  // Stable id so a retry after a lost response is recognised by the server as
  // the same expense rather than creating a duplicate.
  if (!record.client_id) {
    record.client_id = (crypto.randomUUID && crypto.randomUUID()) ||
      ('off-' + Date.now() + '-' + Math.random().toString(36).slice(2));
  }
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite');
    const req = tx.objectStore(STORE).add(record);
    req.onsuccess = () => resolve(req.result);
    req.onerror   = () => reject(req.error);
  });
}

/** Returns the count of pending offline transactions. */
async function getPendingCount() {
  try {
    const db = await _openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, 'readonly');
      const req = tx.objectStore(STORE).count();
      req.onsuccess = () => resolve(req.result);
      req.onerror   = () => reject(req.error);
    });
  } catch {
    return 0;
  }
}

/** Returns all pending records. */
async function _getAllPending() {
  const db = await _openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, 'readonly');
    const req = tx.objectStore(STORE).getAll();
    req.onsuccess = () => resolve(req.result);
    req.onerror   = () => reject(req.error);
  });
}

/** Delete a record by id. */
async function _deletePending(id) {
  const db = await _openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite');
    const req = tx.objectStore(STORE).delete(id);
    req.onsuccess = () => resolve();
    req.onerror   = () => reject(req.error);
  });
}

/**
 * Did the replayed POST /transactions really store the expense?
 * fetch follows redirects, so a stale session lands on /login (or the 2FA
 * pages) with a 200 — that is NOT success, and deleting the record would lose
 * the expense. Success is a 2xx that either was not redirected or ended on the
 * create's own destination (the bucket page / transactions). Replays are
 * idempotent via client_id, so keeping a record queued is always safe.
 */
function _replaySucceeded(resp) {
  if (!resp.ok) return false;
  if (!resp.redirected) return true;
  let path = '';
  try { path = new URL(resp.url, location.origin).pathname; } catch { return false; }
  return path.startsWith('/buckets/') || path === '/transactions' || path.startsWith('/transactions/');
}

/**
 * Called by the service worker's sync event (or as a fallback on page load).
 * Submits each queued record to POST /transactions, then removes it.
 */
async function flushPendingTransactions() {
  let records;
  try {
    records = await _getAllPending();
  } catch {
    return { sent: 0, failed: 0, rejected: 0 };
  }

  let sent = 0, failed = 0, rejected = 0;
  for (const record of records) {
    const { id, saved_at, ...fields } = record;
    const body = new FormData();
    for (const [k, v] of Object.entries(fields)) body.append(k, v);

    // app.csrfToken() reads the cookie, which the server refreshes mid-session; a
    // queued expense flushed after a refresh used to be rejected with 403.
    const csrf = app.csrfToken();
    if (csrf) body.append('_csrf_token', csrf);

    try {
      const resp = await fetch('/transactions', {
        method: 'POST',
        headers: csrf ? { 'X-CSRF-Token': csrf } : {},
        body,
        credentials: 'same-origin',
      });
      if (_replaySucceeded(resp)) {
        await _deletePending(id);
        sent++;
      } else if (resp.status >= 400 && resp.status < 500 && resp.status !== 403) {
        // The server rejected the content itself (bad bucket, bad amount).
        // Retrying will never succeed, so drop it rather than retry forever;
        // 403 is excluded because that is usually a recoverable CSRF issue.
        await _deletePending(id);
        rejected++;
      } else {
        failed++;
      }
    } catch {
      failed++;
    }
  }
  return { sent, failed, rejected };
}

// Export for use in pages and the SW
if (typeof window !== 'undefined') {
  window.offlineExpenses = {
    saveOfflineTransaction,
    getPendingCount,
    flushPendingTransactions,
  };
}
