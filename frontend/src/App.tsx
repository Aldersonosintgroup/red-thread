import { Navigate, Route, Routes } from 'react-router-dom'
import { Sidebar } from './components/Sidebar'
import { TitleBar } from './components/TitleBar'
import { CaseProvider, useCases } from './context/CaseContext'
import { VaultGate } from './context/VaultContext'
import { CaseIntake } from './pages/CaseIntake'
import { CaseWorkspace } from './pages/CaseWorkspace'
import { HelpPage } from './pages/HelpPage'
import { SettingsPage } from './pages/SettingsPage'
import { WatchlistPage } from './pages/WatchlistPage'

function HomeRedirect() {
  const { selectedCaseId, cases, loading } = useCases()
  if (loading) return <div className="p-6 text-neutral-500 text-sm">Loading…</div>
  if (selectedCaseId && cases.some((c) => c.id === selectedCaseId)) {
    return <Navigate to={`/cases/${selectedCaseId}`} replace />
  }
  if (cases.length > 0) return <Navigate to={`/cases/${cases[0].id}`} replace />
  // First launch (no cases yet): start on the guide.
  return <Navigate to="/help" replace />
}

function AppShell() {
  return (
    <div className="flex flex-col h-screen bg-neutral-950">
      <TitleBar />
      <div className="flex flex-1 min-h-0">
        <Sidebar />
        <main className="flex-1 min-w-0 overflow-y-auto">
          <Routes>
            <Route path="/" element={<HomeRedirect />} />
            <Route path="/intake" element={<CaseIntake />} />
            <Route path="/cases/:caseId" element={<CaseWorkspace />} />
            <Route path="/watchlist" element={<WatchlistPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/help" element={<HelpPage />} />
          </Routes>
        </main>
      </div>
    </div>
  )
}

export default function App() {
  return (
    <VaultGate>
      <CaseProvider>
        <AppShell />
      </CaseProvider>
    </VaultGate>
  )
}
