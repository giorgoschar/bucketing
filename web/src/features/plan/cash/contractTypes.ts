import type { MovementBody } from './types'

/** POST /cash/movements with the sheet's `client_id` (a uuid4): a retry of the same write applies once (C5). */
export type MovementWrite = MovementBody
