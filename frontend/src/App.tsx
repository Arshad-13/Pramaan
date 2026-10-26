import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { lazy, Suspense } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { Toaster } from 'sonner'

import { AppShell } from '@/components/AppShell'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { RequireAuth } from '@/components/RequireAuth'
import { RouteEffects } from '@/components/RouteEffects'
import { AuthProvider } from '@/lib/auth'
import Dashboard from '@/pages/Dashboard'
import Login from '@/pages/Login'
import NotFound from '@/pages/NotFound'

// Less-visited pages load on demand to keep the first load small.
const Account = lazy(() => import('@/pages/Account'))
const Activate = lazy(() => import('@/pages/Activate'))
const Register = lazy(() => import('@/pages/Register'))
const Admin = lazy(() => import('@/pages/Admin'))
const Audit = lazy(() => import('@/pages/Audit'))
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
          <RouteEffects />
          <ErrorBoundary>
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
              <Route path="account" element={<Account />} />
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
              <Route path="*" element={<NotFound />} />
            </Route>
          </Routes>
          </Suspense>
          </ErrorBoundary>
        </BrowserRouter>
        <Toaster position="bottom-right" />
      </AuthProvider>
    </QueryClientProvider>
  )
}
