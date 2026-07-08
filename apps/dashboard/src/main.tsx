import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router'
import './index.css'
import { AppLayout } from './components/layout/AppLayout'
import { DataProviderProvider } from './data/DataProviderContext'
import { HttpDataProvider } from './data/http/HttpDataProvider'
import { MockDataProvider } from './data/mock/MockDataProvider'
import { I18nProvider } from './i18n/I18nContext'
import { CustomerPage } from './pages/CustomerPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { OverviewPage } from './pages/OverviewPage'
import { VillagePage } from './pages/VillagePage'

const router = createBrowserRouter([
  {
    path: '/',
    element: <AppLayout />,
    children: [
      { index: true, element: <OverviewPage /> },
      { path: 'villages/:villageId', element: <VillagePage /> },
      { path: 'customers/:customerId', element: <CustomerPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
])

// point VITE_API_BASE_URL at a GridCook API (see apps/api, or `npm run dev:api` /
// `npm run dev:live`) for live data; without it the app runs on the seeded mock.
// VITE_SURVEY_API_BASE_URL additionally pulls SMS survey history from apps/survey.
const apiBaseUrl: string | undefined = import.meta.env.VITE_API_BASE_URL
const surveyBaseUrl: string | undefined = import.meta.env.VITE_SURVEY_API_BASE_URL
const provider = apiBaseUrl
  ? new HttpDataProvider(apiBaseUrl, { surveyBaseUrl })
  : new MockDataProvider(42)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <I18nProvider>
      <DataProviderProvider provider={provider}>
        <RouterProvider router={router} />
      </DataProviderProvider>
    </I18nProvider>
  </StrictMode>,
)
