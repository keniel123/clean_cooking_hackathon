import { Outlet } from 'react-router'
import { Header } from './Header'

export function AppLayout() {
  return (
    <div className="min-h-screen bg-page">
      <Header />
      <main className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6">
        <Outlet />
      </main>
    </div>
  )
}
