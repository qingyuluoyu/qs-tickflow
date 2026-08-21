import { useEffect, useRef, useState, Suspense } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { AppShell, Box, Burger, Group } from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import { useQuoteStream, useQuoteStreamStatus } from '@/lib/useQuoteStream'
import { registerAlertNavigator } from '@/lib/alertNotify'
import { AiAnalysisHost } from '@/components/financials/AiAnalysisHost'
import { AiReportBubble } from '@/components/financials/AiReportBubble'
import { StockAnalysisHost } from '@/components/stock-analysis/StockAnalysisHost'
import { StockAnalysisBubble } from '@/components/stock-analysis/StockAnalysisBubble'
import {
  useCapabilities,
  usePreferences,
  useQuoteStatus,
  useVersion,
} from '@/lib/useSharedQueries'
import {
  useToggleRealtimeQuotes,
} from '@/lib/useSharedMutations'
import { QK } from '@/lib/queryKeys'
import { tierRank } from '@/lib/capability-labels'
import { accountStorage } from '@/lib/storage'
import {
  Star,
  History,
  FileText,
  Settings,
  Database,
  Loader2,
  Tags,
  TrendingUp,
  BarChart3,
  Gauge,
  Layers3,
  Landmark,
  RadioTower,
  CheckCircle2,
  BookOpenCheck,
  Sun,
  Moon,
  X,
  WifiOff,
  LogOut,
  UserRound,
  Grid2X2,
  Crosshair,
  ChartNoAxesColumnIncreasing,
  PieChart,
  ChevronLeft,
  ChevronRight,
  Sparkles,
} from 'lucide-react'
import { AskAiHost } from '@/components/ask-ai/AskAiHost'
import { AskAiBubble } from '@/components/ask-ai/AskAiBubble'
import { openAskAi } from '@/lib/askAiStore'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { toggleTheme, useTheme } from '@/lib/theme'
import { setCurrentTotal as setAlertTotal, useUnreadAlerts } from '@/lib/monitorBadge'
import { useAuth, useIsAdmin } from '@/lib/auth'
import { canonicalNavRoute } from '@/lib/navRoutes'

// 品牌色 — 只用于 logo / brand 区域,不影响功能语义色
const BRAND = '#8B5CF6'

const nav = [
  { to: '/',                label: '看板',     icon: Grid2X2, tone: 'blue' },
  { to: '/watchlist',  label: '自选',   icon: Star, tone: 'orange' },
  { to: '/screener',   label: '策略',   icon: Crosshair, tone: 'blue' },
  { to: '/backtest',   label: '回测',   icon: History, tone: 'purple' },
  { to: '/stock-analysis',    label: '个股分析', icon: TrendingUp, tone: 'green' },
  { to: '/limit-ladder', label: '连板梯队', icon: ChartNoAxesColumnIncreasing, tone: 'blue' },
  { to: '/concept-analysis', label: '概念分析', icon: Layers3, tone: 'purple' },
  { to: '/industry-analysis', label: '行业分析', icon: Landmark, tone: 'cyan' },
  { to: '/financials', label: '财务分析', icon: FileText, tone: 'orange' },
  { to: '/monitor', label: '监控中心', icon: RadioTower, tone: 'red' },
  { to: '/regime', label: '市场环境', icon: Gauge, tone: 'blue' },
  { to: '/review',      label: '复盘',   icon: BookOpenCheck, tone: 'purple' },
  { to: '/indices', label: '指数', icon: BarChart3, tone: 'orange' },
  { to: '/asset-allocation', label: '资产配置', icon: PieChart, tone: 'purple' },
  { to: '/data',       label: '数据',   icon: Database, tone: 'blue' },
] as const

const NAV_TONES = {
  blue: { icon: 'text-blue-600 dark:text-blue-400', bg: 'bg-blue-500/10 ring-blue-500/20', active: 'bg-blue-500/15' },
  orange: { icon: 'text-orange-600 dark:text-orange-400', bg: 'bg-orange-500/10 ring-orange-500/20', active: 'bg-orange-500/15' },
  purple: { icon: 'text-violet-600 dark:text-violet-400', bg: 'bg-violet-500/10 ring-violet-500/20', active: 'bg-violet-500/15' },
  green: { icon: 'text-emerald-600 dark:text-emerald-400', bg: 'bg-emerald-500/10 ring-emerald-500/20', active: 'bg-emerald-500/15' },
  cyan: { icon: 'text-cyan-600 dark:text-cyan-400', bg: 'bg-cyan-500/10 ring-cyan-500/20', active: 'bg-cyan-500/15' },
  red: { icon: 'text-red-600 dark:text-red-400', bg: 'bg-red-500/10 ring-red-500/20', active: 'bg-red-500/15' },
} as const
type NavTone = keyof typeof NAV_TONES

/** 亮/暗主题切换 — 状态存 localStorage, 生效见 lib/theme.ts */
function ThemeToggle() {
  const theme = useTheme()
  const dark = theme === 'dark'
  return (
    <button
      onClick={() => toggleTheme()}
      className="flex items-center justify-center rounded-btn p-2 text-foreground/80 transition-colors duration-150 ease-smooth hover:bg-elevated hover:text-foreground cursor-pointer"
      title={dark ? '切换到亮色模式' : '切换到暗色模式'}
    >
      {dark ? <Sun className="h-4 w-4 shrink-0" /> : <Moon className="h-4 w-4 shrink-0" />}
    </button>
  )
}

/** 监控中心未读徽标 — 仅在非监控页且有未读时显示。 */
function MonitorBadge({ active }: { active: boolean }) {
  const unread = useUnreadAlerts()
  // 尊重用户设置: 可在菜单设置里关闭数字提示
  const badgeEnabled = (() => {
    return accountStorage.getItem('monitor_badge_enabled') !== '0'
  })()
  if (active || unread <= 0 || !badgeEnabled) return null
  return (
    <span className="inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-danger px-1 text-[9px] font-bold text-white animate-pulse">
      {unread > 99 ? '99+' : unread}
    </span>
  )
}

/** 常驻问 AI 入口：右下角悬浮按钮，每个页面一个持久会话。 */
function AskAiEntry() {
  const { pathname } = useLocation()
  const open = () => {
    // 抓取当前页面可见文本作为上下文,让 AI 直接"阅读"本页内容
    const pageText = (document.querySelector('main')?.innerText ?? '')
      .replace(/\n{2,}/g, '\n')
      .trim()
      .slice(0, 1500)
    openAskAi(
      `${pathname}#general`,
      '',
      '',
      `用户正在浏览页面「${pathname}」。以下是该页面当前展示的内容快照：\n${pageText || '（页面内容为空）'}`,
      ['这页数据说明了什么？', '有哪些值得关注的变化？'],
    )
  }
  return (
    <button
      type="button"
      onClick={open}
      className="fixed bottom-4 right-4 z-[65] flex h-11 items-center gap-1.5 rounded-full border border-accent/40 bg-accent px-4 text-xs font-medium text-white shadow-xl transition hover:scale-105"
      title="问 AI"
    >
      <Sparkles className="h-4 w-4" />
      问 AI
    </button>
  )
}

export function Layout() {
  const { user, logout } = useAuth()
  const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(() => {
    try {
      return accountStorage.getItem('sidebar-collapsed') === '1'
    } catch {
      return false
    }
  })
  // 移动端抽屉式导航 (AppShell.Navbar collapsed.mobile)
  const [mobileOpened, { toggle: toggleMobile, close: closeMobile }] = useDisclosure(false)
  // 移动端抽屉展开时始终渲染完整侧栏内容; 收起态只对桌面端生效
  const navCollapsed = sidebarCollapsed && !mobileOpened

  useEffect(() => {
    try {
      accountStorage.setItem('sidebar-collapsed', sidebarCollapsed ? '1' : '0')
    } catch {
      // 无法使用本地存储时仍允许当前会话切换侧栏
    }
  }, [sidebarCollapsed])

  // ===== 共享 hooks (替代内联 useQuery) =====
  const { data: caps } = useCapabilities()
  const { data: versionData } = useVersion()
  const { data: prefs } = usePreferences()
  // 数据源列表 (用于实时行情状态显示当前数据源名称)
  const { data: dataSources } = useQuery({
    queryKey: QK.dataSources,
    queryFn: api.dataSources,
    staleTime: 60_000,
  })
  // poll=true: 全局唯一开启条件轮询 (非交易时段 60s 兜底, 交易时段靠 SSE)
  const { data: quoteStatus } = useQuoteStatus({ poll: true })
  const { data: analysisMenus } = useQuery({
    queryKey: QK.analysisMenus,
    queryFn: api.analysisMenus,
  })

  // 数据同步状态轮询: 有活跃 job 时「数据」菜单项显示转圈
  const { data: pipelineJobs } = useQuery({
    queryKey: QK.pipelineJobs,
    queryFn: () => api.pipelineJobs(1),
    refetchInterval: (query) => (query.state.data?.active_id ? 2000 : 15000),
    refetchIntervalInBackground: true,
  })
  const isDataSyncing = !!pipelineJobs?.active_id

  // 数据同步完成的"瞬时反馈": isDataSyncing 从 true→false 时显示绿色对勾,
  // 闪烁约 3 秒后自动消失。
  const [dataSyncJustDone, setDataSyncJustDone] = useState(false)
  const prevSyncingRef = useRef(false)
  useEffect(() => {
    // 仅在"刚结束"(true→false)且非首次挂载时触发
    if (prevSyncingRef.current && !isDataSyncing) {
      setDataSyncJustDone(true)
      const t = setTimeout(() => setDataSyncJustDone(false), 3000)
      prevSyncingRef.current = isDataSyncing
      return () => clearTimeout(t)
    }
    prevSyncingRef.current = isDataSyncing
  }, [isDataSyncing])

  const qc = useQueryClient()
  const navigate = useNavigate()
  // 告警通知点击跳转监控中心 — 通知挂在 Router 之外, 在此注册 navigate
  useEffect(() => { registerAlertNavigator(navigate) }, [navigate])
  const version = versionData?.version
  const realtimeEnabled = prefs?.realtime_quotes_enabled ?? false
  // Free 档监控限制提示: 可手动关闭, 不持久化 (刷新后恢复显示)
  const [dismissFreeHint, setDismissFreeHint] = useState(false)
  // SSE: 行情更新时自动刷新相关 queries + 告警通知
  useQuoteStream(realtimeEnabled, prefs?.sse_refresh_pages)
  // 实时 SSE 连接状态 — 断开时底部显示提示, 提示可能漏策略告警
  const streamStatus = useQuoteStreamStatus()

  const toggleQuote = useToggleRealtimeQuotes()
  // 实时行情开关(PUT realtime-quotes)为管理员操作,普通用户只看状态点
  const isAdmin = useIsAdmin()
  const isRunning = quoteStatus?.running ?? false
  const isTrading = quoteStatus?.is_trading_hours ?? false
  // 管道/数据修正运行期间实时行情被临时暂停 — 此时禁止开启
  const isPaused = quoteStatus?.paused ?? false
  const tier = tierRank(caps?.label ?? '')
  const isNoneTier = tier < 0
  const isWatchlistMode = tier === 0
  const realtimeModeLabel = isWatchlistMode ? '自选股' : '全市场'
  // 当前实时行情数据源名称 (custom 时显示源名, tickflow 时不显示)
  const realtimeProvider = prefs?.realtime_data_provider
  const realtimeProviderName = realtimeProvider && realtimeProvider !== 'tickflow'
    ? (dataSources?.custom?.find(s => s.name === realtimeProvider)?.display_name || realtimeProvider)
    : null

  // 轮询触发记录总数 → 更新监控中心徽标 (每 15 秒)
  const alertsTotalQuery = useQuery({
    queryKey: ['alerts-total'],
    queryFn: () => api.alertsList({ days: 7, limit: 1 }),
    refetchInterval: 15000,
    refetchIntervalInBackground: true,
    select: (data) => data.total,
  })
  // 只在拿到真实总数时同步徽标 (避免 data=undefined 时传 0 重置 lastSeen)
  const alertsTotal = alertsTotalQuery.data
  useEffect(() => {
    if (alertsTotal != null) setAlertTotal(alertsTotal)
  }, [alertsTotal])

  // 合并内置页面 + 可见的扩展分析菜单
  type NavItem = { to: string; label: string; icon: typeof Gauge; badge?: string; tone?: NavTone; external?: boolean }
  const analysisNav: NavItem[] = (analysisMenus?.items ?? [])
    .filter(m => m.visible)
    .map(m => ({ to: `/analysis/${m.id}`, label: m.label, icon: m.icon === 'tags' ? Tags : BarChart3, tone: 'blue' as const }))

  const allNav: NavItem[] = [...nav, ...analysisNav]
  const savedOrder = (prefs?.nav_order ?? []).map(canonicalNavRoute)

  const navItems = savedOrder.length > 0
    ? (() => {
        const byTo = new Map(allNav.map(n => [n.to, n]))
        const ordered = savedOrder
          .map(id => byTo.get(id) ?? byTo.get(`/analysis/${id}`))
          .filter(Boolean)
        const seen = new Set(ordered.map(n => n!.to))
        return [...ordered as typeof allNav, ...allNav.filter(n => !seen.has(n.to))]
      })()
    : allNav

  const hiddenIds = new Set((prefs?.nav_hidden ?? []).map(canonicalNavRoute))
  const visibleNavItems = navItems.filter(n => !hiddenIds.has(n.to) && !hiddenIds.has(n.to.replace(/^\/analysis\//, '')))

  const handleToggle = async (enabled: boolean) => {
    // 开启时重新校验档位
    if (enabled) {
      const fresh = await qc.fetchQuery({
        queryKey: QK.capabilities,
        queryFn: api.capabilities,
      })
      const freshTier = tierRank(fresh.label ?? '')
      if (freshTier < 0) return
      if (freshTier === 0 && (prefs?.realtime_watchlist_symbols?.length ?? 0) === 0) {
        navigate('/watchlist')
        return
      }
    }
    await toggleQuote.mutateAsync(enabled)
    // 仅在交易时段立即获取一次行情
    if (enabled && isTrading) {
      api.intradayRefresh().catch(() => {})
    }
  }

  return (
    <AppShell
      header={{ height: 52 }}
      navbar={{
        width: { base: 280, lg: sidebarCollapsed ? 72 : 224 },
        breakpoint: 'lg',
        collapsed: { mobile: !mobileOpened, desktop: false },
      }}
      className="h-screen overflow-hidden bg-base text-foreground"
    >
      <AppShell.Header withBorder={false} className="border-b border-border bg-surface">
        <div className="flex h-full items-center px-3">
          {/* 移动端: Burger 打开抽屉式导航 (Mantine 断点 lg 以下) */}
          <Group gap="sm" wrap="nowrap" hiddenFrom="lg">
            <Burger
              opened={mobileOpened}
              onClick={toggleMobile}
              size="sm"
              aria-label={mobileOpened ? '关闭导航菜单' : '打开导航菜单'}
            />
            <img src="/brand-icon.png" alt="清数智算" className="h-7 w-7 object-contain" />
          </Group>
          {/* 用户胶囊 — 固定在 Header 右侧, 不再悬浮遮挡页面内容 */}
          <div className="ml-auto flex items-center gap-2 rounded-full border border-border bg-elevated px-2.5 py-1.5 text-xs">
            <UserRound className="h-3.5 w-3.5 text-accent" />
            <span className="max-w-32 truncate text-foreground" title={user.name}>{user.name}</span>
            <button
              onClick={() => { void logout() }}
              className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-muted transition-colors hover:bg-surface hover:text-foreground"
              title="切换账户"
            >
              <LogOut className="h-3.5 w-3.5" />
              <span>切换账户</span>
            </button>
          </div>
        </div>
      </AppShell.Header>

      <AppShell.Navbar withBorder={false} className="border-r border-border bg-surface">
        <div className="relative flex h-full min-h-0 flex-col overflow-hidden">
          {/* 收起/展开按钮 — 仅桌面端 (移动端由 Burger 控制抽屉) */}
          <Box visibleFrom="lg" pos="absolute" top={16} right={8} className="z-20">
            <button
              type="button"
              onClick={() => setSidebarCollapsed(value => !value)}
              aria-label={sidebarCollapsed ? '展开侧栏' : '收起侧栏'}
              aria-pressed={sidebarCollapsed}
              title={sidebarCollapsed ? '展开侧栏' : '收起侧栏'}
              className="flex h-6 w-6 items-center justify-center rounded-full border border-border bg-surface text-muted shadow-sm transition-colors hover:bg-elevated hover:text-foreground cursor-pointer"
            >
              {sidebarCollapsed ? <ChevronRight className="h-3.5 w-3.5" /> : <ChevronLeft className="h-3.5 w-3.5" />}
            </button>
          </Box>

          <div className={cn('border-b border-border shrink-0', navCollapsed ? 'px-2 py-3' : 'px-5 py-5')}>
            {/* Brand block: supplied 清数智算 horizontal wordmark */}
            {navCollapsed ? (
              <div className="flex h-[38px] items-center justify-center">
                <img src="/brand-icon.png" alt="清数智算" className="h-9 w-9 object-contain" />
              </div>
            ) : (
              <div className="flex h-[58px] items-center">
                <img
                  src="/brand-wordmark.png"
                  alt="清数智算 · 智能投研工作台"
                  className="h-full w-full object-contain object-left"
                />
              </div>
            )}

            {!navCollapsed && (
              <div
                className="mt-3 h-px"
                style={{ background: `linear-gradient(90deg, ${BRAND}88, transparent 80%)` }}
              />
            )}
          </div>

          <nav className={cn('flex-1 min-h-0 overflow-y-auto py-3 space-y-0.5', navCollapsed ? 'w-full px-1' : 'w-full px-2')}>
            {visibleNavItems.map(({ to, label, icon: Icon, badge, tone = 'blue', external }) => (
              <NavLink
                key={to}
                to={to}
                reloadDocument={external}
                onClick={closeMobile}
                title={navCollapsed ? label : undefined}
                className={({ isActive }) =>
                  cn(
                    'flex items-center rounded-btn text-sm transition-colors duration-150 ease-smooth',
                    navCollapsed ? 'justify-center px-1.5 py-2' : 'gap-3 px-3 py-2',
                    isActive
                      ? 'bg-elevated text-foreground font-medium'
                      : 'text-foreground/80 hover:bg-elevated hover:text-foreground',
                  )
                }
              >
                {({ isActive }) => {
                  const iconTone = NAV_TONES[tone]
                  return (
                  <>
                    <span
                      className={cn(
                        'flex h-8 w-8 shrink-0 items-center justify-center rounded-xl ring-1 transition-colors',
                        iconTone.bg,
                        isActive && iconTone.active,
                      )}
                    >
                      <Icon className={cn('h-[18px] w-[18px]', iconTone.icon)} strokeWidth={1.9} />
                    </span>
                    {!navCollapsed && <span className="flex-1">{label}</span>}
                    {!navCollapsed && badge && (
                      <span className="ml-auto inline-flex items-center rounded-full border border-amber-400/30 bg-amber-400/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-amber-400 shrink-0">
                        {badge}
                      </span>
                    )}
                    {/* 数据同步状态: 同步中转圈, 刚完成显示绿色对勾闪烁 3 秒 */}
                    {!navCollapsed && to === '/data' && isDataSyncing && (
                      <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-accent" />
                    )}
                    {!navCollapsed && to === '/data' && !isDataSyncing && dataSyncJustDone && (
                      <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-bull animate-pulse" />
                    )}
                    {/* 监控中心徽标: 仅非监控页且有未读时显示 */}
                    {!navCollapsed && to === '/monitor' && <MonitorBadge active={isActive} />}
                  </>
                  )
                }}
              </NavLink>
            ))}
          </nav>

          {/* 全局行情开关 */}
          <div className={cn('border-t border-border shrink-0', navCollapsed ? 'px-1 py-2.5' : 'px-3 py-2.5')}>
            {/* 行情开关 + 设置入口 */}
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 min-w-0">
                  <span className={`inline-block h-1.5 w-1.5 rounded-full shrink-0 ${
                    realtimeEnabled && isRunning && isTrading
                      ? 'bg-accent animate-pulse'
                      : realtimeEnabled
                        ? 'bg-warning/60'
                        : 'bg-muted'
                  }`} />
                  <span className="hidden">
                    实时行情 · {realtimeProviderName || realtimeModeLabel}
                  </span>
                  <button
                    onClick={() => navigate('/settings?tab=monitoring')}
                    className="text-secondary hover:text-foreground transition-colors shrink-0"
                    title="实时监控设置"
                  >
                    <Settings className="h-3 w-3" />
                  </button>
                </div>
                {isAdmin && (
                <button
                  onClick={() => handleToggle(!realtimeEnabled)}
                  disabled={toggleQuote.isPending || isPaused}
                  title={isPaused ? '数据同步运行中，实时行情已临时暂停' : undefined}
                  className={`relative inline-flex h-4 w-7 items-center rounded-full shrink-0 transition-colors duration-200 ${
                    realtimeEnabled
                      ? 'bg-accent shadow-[0_0_6px_rgba(59,130,246,0.3)]'
                      : 'bg-elevated'
                  } ${toggleQuote.isPending || isPaused ? 'opacity-50' : 'cursor-pointer'}`}
                >
                  <span className={`inline-block h-3 w-3 rounded-full bg-white shadow-sm transition-transform duration-200 ${
                    realtimeEnabled ? 'translate-x-[14px]' : 'translate-x-0.5'
                  }`} />
                </button>
                )}
            </div>

            {/* 状态提示 */}
            {realtimeEnabled && (!isNoneTier || realtimeProviderName) && (
              <div className="mt-1.5 text-[10px] leading-snug space-y-0.5">
                {isWatchlistMode && !dismissFreeHint && !realtimeProviderName && (
                  <div className="flex items-start gap-1 text-amber-400/80">
                    <span className="flex-1">监控自选股前 5 只，全市场监控需 Starter+</span>
                    <button
                      onClick={() => setDismissFreeHint(true)}
                      className="text-amber-400/50 hover:text-amber-400 shrink-0 transition-colors"
                      title="关闭提示"
                    >
                      <X className="h-2.5 w-2.5" />
                    </button>
                  </div>
                )}
                {isPaused ? (
                  <div className="text-warning/80">数据同步运行中，实时行情已临时暂停</div>
                ) : isRunning && isTrading ? (
                  <div className="text-accent">行情运行中</div>
                ) : realtimeEnabled && !isTrading ? (
                  <div className="text-warning/70">非交易时段，将在交易时间自动开启</div>
                ) : null}
              </div>
            )}
          </div>

          <div className="border-t border-border px-2 py-3 shrink-0">
            <div className="flex items-center gap-1">
              <ThemeToggle />
              <NavLink
                to="/settings"
                onClick={closeMobile}
                title={navCollapsed ? '设置' : undefined}
                className={({ isActive }) =>
                  cn(
                    'flex items-center rounded-btn text-sm transition-colors duration-150 ease-smooth',
                    navCollapsed ? 'justify-center px-2 py-2' : 'flex-1 justify-between gap-3 px-3 py-2',
                    isActive
                      ? 'bg-elevated text-foreground font-medium'
                      : 'text-foreground/80 hover:bg-elevated hover:text-foreground',
                  )
                }
              >
                <span className={cn('flex items-center', navCollapsed ? 'gap-0' : 'gap-3')}>
                  <Settings className="h-4 w-4 shrink-0" />
                  {!navCollapsed && <span>设置</span>}
                </span>
                {!navCollapsed && (
                  <span className="font-mono text-[10px] text-muted/50 select-none">
                    {version ?? ''}
                  </span>
                )}
              </NavLink>
            </div>
          </div>
        </div>
      </AppShell.Navbar>

      <AppShell.Main className="relative overflow-auto scrollbar-gutter-stable bg-base" h="100dvh">
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
        >
          <Suspense
            fallback={
              <div className="flex items-center justify-center py-24">
                <Loader2 className="h-5 w-5 animate-spin text-muted" />
              </div>
            }
          >
            <Outlet />
          </Suspense>
        </motion.div>
        {streamStatus === 'reconnecting' && (
          <div
            role="status"
            aria-live="polite"
            className="fixed bottom-4 left-1/2 z-[9998] flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-warning/30 bg-warning/10 px-2.5 py-1 text-[11px] font-medium text-warning shadow-lg backdrop-blur-md"
          >
            <WifiOff className="h-3 w-3 shrink-0 animate-pulse" />
            与服务连接已断开 · 正在重连
          </div>
        )}
      </AppShell.Main>

      <AiAnalysisHost />
      <AiReportBubble />
      <StockAnalysisHost />
      <StockAnalysisBubble />
      <AskAiHost />
      <AskAiBubble />
      <AskAiEntry />
    </AppShell>
  )
}
