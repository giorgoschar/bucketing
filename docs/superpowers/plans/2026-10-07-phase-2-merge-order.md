# Phase 2 merge order and shared files

This document is binding for every Phase 2 plan (2a, 2b, 2c, 2d). Where a plan disagrees with it, this document wins.

## Streams, worktrees and integration

- **Separate worktrees.** Every stream runs in its own git worktree and branch, cut from the integration branch `feat/phase2` at the point given below. Two implementers never share a worktree.
- **Merging.** A stream merges back into `feat/phase2` once its task reviews are clean. Merges follow the order in the table below.
- **Pushes.** The user pushes `feat/phase2` to `main` at the three marked points, P1 to P3. Each push deploys.

| # | Stream(s) | Cut from | Can run alongside | Merge after |
|---|---|---|---|---|
| 1 | **2d-M** (payment_method migration `b8c9d0e1f2a3`, services, API) | `feat/phase2` @ start | 2a-A, 2a-B, 2c-B2, 2b-C3 | — |
| 2 | **2a-A** (kit, data layer, test kit) and **2a-B** (rule preview) | start | 2d-M, 2c-B2, 2b-C3 | 2d-M |
| 3 | **2a-C** (C1 first, tagged `2a-c1`), then **2a-D** and **2a-E** from `2a-c1` | after 2a-A | each other | 2a-A, 2a-B |
| **P1** | push: 2d-M + all of 2a | | | |
| 4 | **2c-B1** (bulk, migration `c9d0e1f2a3b4`) | after 2d-M merged | 2c-B2, 2d-B, 2b-C3 | 2d-M |
| 5 | **2c-B2** (filter, feed, counts, duplicates, receipt, history) | start | everything backend | after 2c-B1 (join task T10) |
| 6 | **2d-B** (rules CRUD first, then person, monthly_in_out, category detail, security, passkey return_to) | after 2d-M merged | 2c-B1/B2, 2b-C3 | 2d-M |
| 7 | **2b-C3** (scan/qr, check-duplicate) | start | all backend | **after 2c-B2** (both edit `app/api/transactions.py`) |
| 8 | **2d-N** (mutes migration `d0e1f2a3b4c5`) | after 2c-B1 merged | frontend streams | 2c-B1 |
| 9 | **2b-C1/C2/C4/C5/C6** (composer UI) | after P1 | 2c-F, 2d-F | 2a, 2b-C3, 2d-B rules |
| **P2** | push: backends (2c-B, 2d-B, 2d-N, 2b-C3) + 2b composer | | | |
| 10 | **2c-F1/F2** (Activity, bulk UI) | after 2b-C2 merged (needs `/new`, `/edit/:id`) | 2d-F | 2b |
| 11 | **2d-F1…F5** (Insights, Settings, push sw) | after P1 | 2c-F | 2c-F (router.tsx order) |
| **P3** | push: 2c and 2d frontends | | | |

**Migration chain:** `a7b8c9d0e1f2` → `b8c9d0e1f2a3` (2d-M) → `c9d0e1f2a3b4` (2c-B1) → `d0e1f2a3b4c5` (2d-N). 2a and 2b add no migrations.

## Shared files: one owner each, later plans edit on top

| File | Edited by (in merge order) | Rule |
|---|---|---|
| `web/src/router.tsx` | 2a-D5 → 2b-C2-10 → 2c → 2d-F1.7 | Each adds its routes without removing earlier ones. 2b's `/new` and `/edit/:id` sit outside `AppShell` under `FullScreenShell`. |
| `web/src/data/keys.ts` | 2a-A → 2c → 2d | Additive only. Never rename a 2a key. |
| `web/src/data/reads.ts`, `data/types.ts`, `test/fakeApi.ts`, `test/fixtures.ts` | 2a-A → 2b-C1-1 | 2b widens types and fixtures additively. 2d-F1.6 widens `Category` additively, on top of 2b. |
| `web/src/shell/AppShell.tsx`, `offline/queue.ts`, `offline/db.ts` | 2a-A → 2b | 2b adds `FullScreenShell` and `offline/queuedBodies.ts` next to them. It does not restructure them. |
| `web/src/features/home/RecentActivity.tsx` | 2a-E → 2b-C5 | 2b adds pending rows. |
| `web/src/features/plan/Budgets.tsx`, `features/plan/items/ItemSheet.tsx` | 2a → 2d-F5 | 2d adds Archive and the payment method field. |
| `web/src/shell/TopBar.tsx` | 2a → 2d | Additive. |
| `app/api/transactions.py` | 2c-B2 → 2b-C3 | 2b's `scan/qr` and `check-duplicate` routes go **above** `/{txn_id}`, next to 2c's `/counts`, `/duplicates` and `/bulk`. |
| `app/api/__init__.py`, `app/models.py` | 2d-M → 2c-B1 → 2d-N | Additive. |
| `app/api/recurring.py` | 2a-B (preview) → 2d-M (payment_method) | Both are additive. Merging 2d-M first makes 2a-B rebase trivially. |
| `app/web_app.py` | 2b-C6-1 (`APP_CSP` worker-src, only if needed) → 2d-B6 (passkey `return_to`) | Separate functions. |
| `tests/test_planning_upgrade.py` | 2d-M → 2c-B1 | Additive cases. |
| `web/src/api/openapi.json`, `schema.d.ts` | many | On any conflict, take either side, then re-run `npm run gen:api` and commit. |

## One owner for overlapping features

- **Receipt view:** 2c-B2 owns `GET /api/v1/transactions/{id}/receipt`. 2b's "View" uses the old cookie route until 2c-B2 merges, then switches. The switch happens in 2b-C2 if 2c-B2 has already merged, otherwise in 2c-F1.
- **Duplicates:**
  - 2b-C3 owns the single-entry `GET /transactions/check-duplicate`, a pre-save check for one amount, date and merchant.
  - 2c-B2 owns the listing `GET /transactions/duplicates` and the dismissals.
  - Both call the same service function in `app/services/`. Whichever lands second reuses it instead of copying it.
- **Category rules:** 2d-B1 owns them. 2b reads `RULES_API_READY`, which is flipped at P2.
- **Online state:** 2a's export, if it has one, is used everywhere. Otherwise 2c's `useOnline` in `features/activity/hooks.ts` is the only one.
- **update_transaction:** it stays strict (production fix, `fixed_cost = recurring_bill_id and bucket_id is None and type == expense`). No plan relaxes it.

## Verification per push

- **P1, P2, P3:**
  - the full pytest suite (`-n 8`);
  - the Postgres run of the upgrade, migration and bulk tests;
  - `npm test`, `typecheck`, `lint` and `build`;
  - `docker build`;
  - a check that the branch fast-forwards from `origin/main`.
- **Final review:** one per push, on the most capable model, scoped to that push's diff.
