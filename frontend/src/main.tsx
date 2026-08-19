import React from 'react'
import ReactDOM from 'react-dom/client'
import { RouterProvider } from 'react-router-dom'
import { QueryClient, QueryClientProvider, QueryCache } from '@tanstack/react-query'
import { router } from './router'
import { MantineBridge } from './lib/mantineTheme'
import '@mantine/core/styles.css'
import '@mantine/notifications/styles.css'
import '@mantine/dates/styles.css'
import './index.css'

const queryClient = new QueryClient({
  queryCache: new QueryCache(),
  defaultOptions: {
    queries: {
      staleTime: 5_000,           // 5s 内复用,与 §4.2 Repository 不变量一致
      refetchOnWindowFocus: false,
    },
    mutations: {},
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <MantineBridge>
        <RouterProvider router={router} />
      </MantineBridge>
    </QueryClientProvider>
  </React.StrictMode>
)
