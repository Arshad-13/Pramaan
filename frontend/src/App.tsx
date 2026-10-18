import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { FilePlus2, Files, ScanLine, ScrollText, UsersRound } from 'lucide-react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { Toaster } from 'sonner'

import { AppShell } from '@/components/AppShell'
import Dashboard from '@/pages/Dashboard'
import DesignSystem from '@/pages/DesignSystem'
import Login from '@/pages/Login'
import Placeholder from '@/pages/Placeholder'

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 10_000, refetchOnWindowFocus: false } },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route element={<AppShell />}>
            <Route index element={<Dashboard />} />
            <Route
              path="prescriptions/new"
              element={
                <Placeholder
                  title="New prescription"
                  icon={FilePlus2}
                  phase="Phase 4"
                  description="Choose a patient, add medicines, review the risk check, and sign with your signing password. A live preview shows exactly what will be printed and signed."
                />
              }
            />
            <Route
              path="prescriptions"
              element={
                <Placeholder
                  title="My prescriptions"
                  icon={Files}
                  phase="Phase 4"
                  description="Your issued prescriptions with their status. Doctors can revoke; patients see their dispense PIN here."
                />
              }
            />
            <Route
              path="verify"
              element={
                <Placeholder
                  title="Verify"
                  icon={ScanLine}
                  phase="Phase 5"
                  description="Scan a prescription's QR code, upload a photo or PDF, or paste the code. You get a verdict and the evidence behind it."
                />
              }
            />
            <Route
              path="admin"
              element={
                <Placeholder
                  title="Administration"
                  icon={UsersRound}
                  phase="Phase 3"
                  description="Create doctor accounts, approve pharmacists, and review security events."
                />
              }
            />
            <Route
              path="audit"
              element={
                <Placeholder
                  title="Audit log"
                  icon={ScrollText}
                  phase="Phase 2"
                  description="Every security-relevant action, chained so that any edit or deletion is detected."
                />
              }
            />
            {import.meta.env.DEV && <Route path="design" element={<DesignSystem />} />}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
      <Toaster position="bottom-right" />
    </QueryClientProvider>
  )
}
