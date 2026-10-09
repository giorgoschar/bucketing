// One module for the three desktop-only panels, so the phone's main chunk does not carry them
// (Insights lazy-loads this file, and only on a viewport of 1024 px or more).
export { BillsPanel } from './BillsPanel'
export { CategoriesTable } from './CategoriesTable'
export { MonthsTable } from './MonthsTable'
