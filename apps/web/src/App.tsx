import { Route, Routes } from 'react-router'
import RowPage from './pages/RowPage'
import ProfilesPage from './pages/ProfilesPage'
import CabinetProfilePage from './pages/CabinetProfilePage'
import RequireAuth from './auth/RequireAuth'
import Layout from './components/Layout'
import ChangePasswordPage from './pages/ChangePasswordPage'
import LoginPage from './pages/LoginPage'
import CabinetPage from './pages/CabinetPage'
import DevicesPage from './pages/DevicesPage'
import SearchPage from './pages/SearchPage'
import HallPage from './pages/HallPage'
import HomePage from './pages/HomePage'
import ImportPage from './pages/ImportPage'
import JobIntakePage from './pages/JobIntakePage'
import JobPage from './pages/JobPage'
import ReportsPage from './pages/ReportsPage'
import NotFoundPage from './pages/NotFoundPage'

export default function App() {
  return (
    <Routes>
      <Route path="login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route path="account/password" element={<ChangePasswordPage />} />
        <Route index element={<HomePage />} />
        <Route path="halls/:hallId" element={<HallPage />} />
        <Route path="halls/:hallId/rows/:rowId" element={<RowPage />} />
        <Route path="halls/:hallId/cabinets/:rackId" element={<CabinetPage />} />
        <Route path="cabinets/:rackId" element={<CabinetPage />} />
        <Route path="search" element={<SearchPage />} />
        <Route path="devices" element={<DevicesPage />} />
        <Route path="profiles" element={<ProfilesPage />} />
        <Route path="profiles/cabinet/:id" element={<CabinetProfilePage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="import" element={<ImportPage />} />
        <Route path="jobs/new" element={<JobIntakePage />} />
        <Route path="jobs/:idOrDcreq" element={<JobPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}
