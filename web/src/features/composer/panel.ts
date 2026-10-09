import { createContext, useContext } from 'react'

/** What the Add side panel (shell/AddPanel.tsx) tells the composer it is mounted in. Absent on the phone, where
 *  the composer is a full screen. The composer is the same component either way (Phase A spec §4.5). */
export interface PanelHost {
  /** Close the panel: the screen behind stays. Replaces "go back" for ✕, Esc and after an edit saves. */
  close: () => void
  /** The entry being edited (`?edit=<id>`). In the panel the router's :id is the screen behind's, not this. */
  editId?: string
  /** Swap to editing another entry ("Open that one"). */
  openEdit: (id: string) => void
}

const Ctx = createContext<PanelHost | null>(null)
export const PanelProvider = Ctx.Provider
export const usePanel = (): PanelHost | null => useContext(Ctx)
