import { useNavigate } from 'react-router'

/** Opens Add. Until the side panel exists it is the full-screen composer, as on the phone. */
export function useOpenAdd(): () => void {
  const navigate = useNavigate()
  return () => void navigate('/new')
}
