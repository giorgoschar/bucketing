import { useNavigate } from 'react-router'
import { usePanel } from './panel'

/** ✕ and Back: the previous route, or Home when the composer was opened directly. In the side panel: close the panel. */
export function useClose(): () => void {
  const navigate = useNavigate()
  const panel = usePanel()
  return () => {
    if (panel) return panel.close()
    if ((window.history.state?.idx ?? 0) > 0) void navigate(-1)
    else void navigate('/', { replace: true })
  }
}
