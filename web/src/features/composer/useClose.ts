import { useNavigate } from 'react-router'

/** ✕ and Back: the previous route, or Home when the composer was opened directly. */
export function useClose(): () => void {
  const navigate = useNavigate()
  return () => {
    if ((window.history.state?.idx ?? 0) > 0) void navigate(-1)
    else void navigate('/', { replace: true })
  }
}
