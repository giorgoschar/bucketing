import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useParams } from 'react-router'
import { api } from '../../api/client'
import { ApiError, unwrap } from '../../data/http'
import { runOnline } from '../../data/onlineAction'
import type { RawResult } from '../../data/rawJson'
import { queuedBlock } from '../../offline/queuedChanges'
import { afterHouseholdChange } from '../../session/householdChange'
import { BackHeader } from '../../ui/BackHeader'
import { EmptyState } from '../../ui/EmptyState'
import { useToast } from '../../ui/Toast'
import '../settings/settings.css'

interface Preview { household_name: string; inviter: string | null }

/** An invite link (/app/join/<token>): who invited you to which household, and one button to join.
 *  The token is a credential: it stays in the URL and in memory, never in a cache key or a log. */
export function Join() {
  const { token = '' } = useParams()
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const preview = useQuery({
    queryKey: ['invite-preview', token],
    queryFn: async ({ signal }) =>
      (await unwrap(api.GET('/api/v1/invites/{token}', { params: { path: { token } }, signal }))) as unknown as Preview,
    retry: false,
    gcTime: 0,
  })

  const join = async () => {
    const blocked = await queuedBlock()
    if (blocked) { toast.show(blocked, { tone: 'error' }); return }
    setBusy(true)
    const out = await runOnline(
      () => api.POST('/api/v1/invites/{token}/accept', { params: { path: { token } } }) as Promise<RawResult<{ household_id: string }>>,
    )
    setBusy(false)
    if (out.ok) afterHouseholdChange()
    else if (out.kind !== 'auth') toast.show(out.message, { tone: 'error' })
  }

  const h = preview.data
  return (
    <>
      <BackHeader title="Join household" back="/" />
      <section className="screen settings">
        {h ? (
          <section className="ui-card settings__card" aria-label="Invitation">
            <p className="settings__help">{h.inviter ? `${h.inviter} invited you to join` : 'You are invited to join'}</p>
            <p className="settings__name">{h.household_name}</p>
            <p className="settings__help">You will see its shared budget and spending. You can leave later in Settings.</p>
            <button type="button" className="btn btn--primary btn--block" disabled={busy} onClick={() => void join()}>
              Join {h.household_name}
            </button>
          </section>
        ) : preview.isError ? (
          <EmptyState
            title={preview.error instanceof ApiError && preview.error.status < 500 ? preview.error.detail : 'Could not load this invite. Check your connection and try again.'}
          />
        ) : (
          <div className="ui-skeleton" role="status" aria-busy="true" aria-label="Loading" />
        )}
      </section>
    </>
  )
}
