import { NavLink } from 'react-router'
import { CalendarRangeIcon, ChartPieIcon, HouseIcon, ListIcon, PlusIcon } from './icons'

const tab = ({ isActive }: { isActive: boolean }) => (isActive ? 'tabbar__tab is-active' : 'tabbar__tab')

export function TabBar() {
  return (
    <nav className="tabbar" aria-label="Main">
      <NavLink to="/" end className={tab}><HouseIcon />Home</NavLink>
      <NavLink to="/activity" className={tab}><ListIcon />Activity</NavLink>
      <NavLink to="/new" className="tabbar__add" aria-label="Add"><PlusIcon /></NavLink>
      <NavLink to="/plan" className={tab}><CalendarRangeIcon />Plan</NavLink>
      <NavLink to="/insights" className={tab}><ChartPieIcon />Insights</NavLink>
    </nav>
  )
}
