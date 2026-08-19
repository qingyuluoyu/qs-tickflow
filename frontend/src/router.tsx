import { lazy, type ComponentType } from 'react'
import { createBrowserRouter, Navigate } from 'react-router-dom'
import { Layout } from './components/Layout'
import { AuthGate } from './components/AuthGate'
import { RouteErrorFallback } from './components/RouteErrorFallback'
import { Qingshu101Admin } from './pages/Qingshu101Admin'

type RouteModule = { default: ComponentType<Record<string, never>> }

/**
 * Vite dev/HMR and deployed hashed chunks can briefly return a stale or
 * incomplete module. Retry once before showing React Router's fatal boundary,
 * then allow one guarded reload to recover a stale module graph. The short
 * sessionStorage window prevents an actual syntax/import error from causing an
 * infinite reload loop.
 */
function lazyRoute(load: () => Promise<RouteModule>) {
  return lazy(async () => {
    let lastError: unknown
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        return await load()
      } catch (error) {
        lastError = error
        if (attempt === 0) {
          await new Promise(resolve => setTimeout(resolve, 150))
        }
      }
    }

    if (typeof window !== 'undefined') {
      const key = `tickflow:lazy-reload:${window.location.pathname}`
      try {
        const previous = Number(window.sessionStorage.getItem(key) ?? 0)
        if (!Number.isFinite(previous) || Date.now() - previous > 10_000) {
          window.sessionStorage.setItem(key, String(Date.now()))
          window.location.reload()
          await new Promise(() => undefined)
        }
      } catch {
        // Private browsing may disable sessionStorage; surface the original
        // import error instead of risking an unbounded reload loop.
      }
    }

    throw lastError
  })
}

// 代码分割: 页面全部 lazy 加载, 避免首屏打包所有页面 (ECharts / lightweight-charts /
// framer-motion 等重库) → 大幅减小首屏 bundle。命名导出用 .then 映射为 default。
// Layout / Onboarding / Auth 为应用外壳与入口, 保持同步加载。
const Watchlist = lazyRoute(() => import('./pages/Watchlist').then(m => ({ default: m.Watchlist })))
const Screener = lazyRoute(() => import('./pages/Screener').then(m => ({ default: m.Screener })))
const Backtest = lazyRoute(() => import('./pages/Backtest').then(m => ({ default: m.Backtest })))
const Financials = lazyRoute(() => import('./pages/Financials').then(m => ({ default: m.Financials })))
const Data = lazyRoute(() => import('./pages/Data').then(m => ({ default: m.Data })))
const Monitor = lazyRoute(() => import('./pages/Monitor').then(m => ({ default: m.Monitor })))
const Dashboard = lazyRoute(() => import('./pages/Dashboard').then(m => ({ default: m.Dashboard })))
const AnalysisDetail = lazyRoute(() => import('./pages/AnalysisDetail').then(m => ({ default: m.AnalysisDetail })))
const ConceptAnalysis = lazyRoute(() => import('./pages/ConceptAnalysis').then(m => ({ default: m.ConceptAnalysis })))
const IndustryAnalysis = lazyRoute(() => import('./pages/IndustryAnalysis').then(m => ({ default: m.IndustryAnalysis })))
const StockAnalysis = lazyRoute(() => import('./pages/StockAnalysis').then(m => ({ default: m.StockAnalysis })))
const Review = lazyRoute(() => import('./pages/Review').then(m => ({ default: m.Review })))
const LimitUpLadder = lazyRoute(() => import('./pages/LimitUpLadder').then(m => ({ default: m.LimitUpLadder })))
const Branding = lazyRoute(() => import('./pages/Branding').then(m => ({ default: m.Branding })))
const Settings = lazyRoute(() => import('./pages/Settings').then(m => ({ default: m.Settings })))
const Indices = lazyRoute(() => import('./pages/Indices').then(m => ({ default: m.Indices })))
const Regime = lazyRoute(() => import('./pages/Regime').then(m => ({ default: m.Regime })))
const Dev = lazyRoute(() => import('./pages/Dev').then(m => ({ default: m.Dev })))
const AssetAllocation = lazyRoute(() => import('./pages/AssetAllocation').then(m => ({ default: m.AssetAllocation })))

const isQingshu101Host = typeof window !== 'undefined'
  && /^qingshu101(?:\.|$)/i.test(window.location.hostname)
const siteRoot = isQingshu101Host ? <Qingshu101Admin /> : <AuthGate />

// 账户入口是应用外壳的一部分，不新增独立登录页面。
export const router = createBrowserRouter([
  { path: '/onboarding', element: <Navigate to="/" replace /> },
  { path: '/login', element: <Navigate to="/" replace /> },
  // Hidden operator route; production use is the qingshu101 subdomain.
  { path: '/qingshu101', element: <Qingshu101Admin /> },
  {
    path: '/',
    element: siteRoot,
    errorElement: <RouteErrorFallback />,
    children: [
      {
        element: <Layout />,
        children: [
          { index: true, element: <Dashboard /> },
          { path: 'overview', element: <Navigate to="/" replace /> },
          { path: 'analysis', element: <Navigate to="/settings?tab=ext-pages" replace /> },
          { path: 'analysis/:menuId', element: <AnalysisDetail /> },
          { path: 'concept-analysis', element: <ConceptAnalysis /> },
          { path: 'industry-analysis', element: <IndustryAnalysis /> },
          { path: 'stock-analysis', element: <StockAnalysis /> },
          { path: 'review', element: <Review /> },
          { path: 'watchlist', element: <Watchlist /> },
          { path: 'screener', element: <Screener /> },
          { path: 'backtest', element: <Backtest /> },
          { path: 'financials', element: <Financials /> },
          { path: 'data', element: <Data /> },
          { path: 'monitor', element: <Monitor /> },
          { path: 'limit-ladder', element: <LimitUpLadder /> },
          { path: 'indices', element: <Indices /> },
          { path: 'asset-allocation', element: <AssetAllocation /> },
          { path: 'regime', element: <Regime /> },
          { path: 'branding', element: <Branding /> },
          { path: 'settings', element: <Settings /> },
          // 隐藏路由：开发者工具（不暴露在菜单，仅供调试）
          { path: 'dev', element: <Dev /> },
          // 旧路由兼容重定向
          { path: 'settings/keys', element: <Navigate to="/settings?tab=account" replace /> },
          { path: 'settings/ai', element: <Navigate to="/settings?tab=ai" replace /> },
          { path: 'settings/queries', element: <Navigate to="/settings?tab=queries" replace /> },
        ],
      },
    ],
  },
])
