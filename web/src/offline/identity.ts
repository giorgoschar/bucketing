/** Who is signed in on this tab. SessionProvider sets it; enqueue stamps it onto each queued write. */
export interface Identity { user_id: string; household_id: string }

let current: Identity | null = null

export const setIdentity = (id: Identity | null): void => { current = id }
export const getIdentity = (): Identity | null => current
