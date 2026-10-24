import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { lazy, Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { Toaster } from 'sonner'

import { AppShell } from '@/components/AppShell'
import { RequireAuth } from '@/components/RequireAuth'
import { AuthProvider } from '@/lib/auth'
import Dashboard from '@/pages/Dashboard'
import Login from '@/pages/Login'

// Less-visited pages load on demand to keep the first load small.
const Activate = lazy(() => import('@/pages/Activate'))
const Register = lazy(() => import('@/pages/Register'))
const Admin = lazy(() => import('@/pages/Admin'))
const Audit = lazy(() => import('@/pages/Audit'))
const DesignSystem = lazy(() => import('@/pages/DesignSystem'))
const NewPrescription = lazy(() => import('@/pages/NewPrescription'))
const MyPrescriptions = lazy(() => import('@/pages/MyPrescriptions'))
const Verify = lazy(() => import('@/pages/Verify'))

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 10_000, refetchOnWindowFocus: false } },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <Suspense fallback={<div role="status" aria-label="Loading" className="p-10" />}>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/register" element={<Register />} />
            <Route path="/activate" element={<Activate />} />
            <Route
              element={
                <RequireAuth>
                  <AppShell />
                </RequireAuth>
              }
            >
              <Route index element={<Dashboard />} />
              <Route
                path="prescriptions/new"
                element={
                  <RequireAuth roles={['doctor']}>
                    <NewPrescription />
                  </RequireAuth>
                }
              />
              <Route
                path="prescriptions"
                element={
                  <RequireAuth roles={['doctor', 'patient']}>
                    <MyPrescriptions />
                  </RequireAuth>
                }
              />
              <Route
                path="verify"
                element={
                  <RequireAuth roles={['pharmacist']}>
                    <Verify />
                  </RequireAuth>
                }
              />
              <Route
                path="admin"
                element={
                  <RequireAuth roles={['admin']}>
                    <Admin />
                  </RequireAuth>
                }
              />
              <Route
                path="audit"
                element={
                  <RequireAuth roles={['auditor']}>
                    <Audit />
                  </RequireAuth>
                }
              />
              {import.meta.env.DEV && <Route path="design" element={<DesignSystem />} />}
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
          </Suspense>
        </BrowserRouter>
        <Toaster position="bottom-right" />
      </AuthProvider>
    </QueryClientProvider>
  )
}
