import { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Sparkles, LineChart, History as HistoryIcon, Loader2, ExternalLink, Bell, AlertTriangle, Star, Swords } from 'lucide-react'
import { Badge, Button, Tooltip } from '@mantine/core'
import { PageHeader } from '@/components/PageHeader'
import { PageContainer } from '@/components/PageContainer'
import { EmptyState } from '@/components/EmptyState'
import { StockFinancialSearch } from '@/components/financials/StockFinancialSearch'
import { StockPreviewDialog } from '@/components/StockPreviewDialog'
import { LastStockChip } from '@/components/LastStockChip'
import { AnalysisKChart, type PriceLevel, type LevelType } from '@/components/stock-analysis/AnalysisKChart'
import { PriceAlertDialog } from '@/components/stock-analysis/PriceAlertDialog'
import { DebateDialog } from '@/components/stock-analysis/DebateDialog'
import { StockInsightPanels } from '@/components/stock-analysis/StockInsightPanels'
import { Modal } from '@/components/Modal'
import { api } from '@/lib/api'
import { useLastStock } from '@/lib/useLastStock'
import { QK } from '@/lib/queryKeys'
import { toast } from '@/lib/notify'
import { useAuth } from '@/lib/auth'
import {
  startAnalysis, findTodayReport, useHistoryReports,
  deleteReport, openHistoryReport, loadHistory,
} from '@/lib/stockAnalysisStore'

/**
 * 个股分析页 —— 日 K + 关键价位(压力/支撑/密集区/枢轴/前高前低)+ AI 四维分析。
 *
 * 与财务分析页的区别:
 *  - 以【行情 + 关键价位】为视觉主体(专用日 K 图表,不复用个股对话框图表)
 *  - AI 分析输出客观技术状态与风险提示(非买卖建议、非财务质量评级)
 *  - 报告胶囊用蓝色系,与财务分析(紫色)并存
 */
export function StockAnalysis() {
  const [symbol, setSymbol] = useState<string>('')
  const [name, setName] = useState<string>('')
  const [checking, setChecking] = useState(false)
  const [confirmReport, setConfirmReport] = useState<{ id: string; created_at: string; focus: string } | null>(null)
  const [previewSymbol, setPreviewSymbol] = useState<string | null>(null)
  const [showPriceAlerts, setShowPriceAlerts] = useState(false)
  const [showDebate, setShowDebate] = useState(false)
  const qc = useQueryClient()
  const { user } = useAuth()
  const { last: lastStock, remember: rememberStock } = useLastStock('stock-analysis')
  const [searchParams] = useSearchParams()
  const querySymbol = searchParams.get('symbol')?.trim() ?? ''
  const queryName = searchParams.get('name')?.trim() ?? ''

  // 自选状态使用用户隔离的 query key；切换账户后不会复用上一账户的列表。
  const watchlist = useQuery({
    queryKey: QK.watchlistFor(user.id),
    queryFn: api.watchlistList,
    enabled: !!symbol,
  })
  const inWatchlist = (watchlist.data?.symbols ?? []).some((entry) => entry.symbol === symbol)
  const toggleWatchlist = useMutation({
    mutationFn: () => inWatchlist ? api.watchlistRemove(symbol) : api.watchlistAdd(symbol),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: QK.watchlistFor(user.id) })
      qc.invalidateQueries({ queryKey: ['watchlist-enriched', user.id] })
      qc.invalidateQueries({ queryKey: ['watchlist-news', user.id] })
    },
    onError: (error) => toast(error instanceof Error ? error.message : '自选操作失败', 'error'),
  })

  // 进入页面立即加载历史报告(供右侧常驻列表)。store 内部有 historyLoaded 去重, 重复调用安全。
  useEffect(() => { loadHistory() }, [])

  // 优先使用 URL 中的股票代码/名称(看板榜单跳转会带入), 无 URL 时才恢复上次选中的股票。
  useEffect(() => {
    if (!querySymbol) return
    setSymbol(current => current === querySymbol ? current : querySymbol)
    setName(current => current === queryName ? current : queryName)
    rememberStock(querySymbol, queryName)
  }, [queryName, querySymbol, rememberStock])

  useEffect(() => {
    if (querySymbol || symbol || !lastStock) return
    setSymbol(lastStock.symbol)
    setName(lastStock.name)
  }, [lastStock, querySymbol, symbol])

  const onSelect = (sym: string, nm: string) => {
    setSymbol(sym)
    setName(nm)
    setConfirmReport(null)
    setShowPriceAlerts(false)
    setShowDebate(false)
    rememberStock(sym, nm)
  }

  const handleAnalyze = async () => {
    if (!symbol || checking) return
    setChecking(true)
    try {
      // 当日已分析过 → 二次确认(查看今日报告 / 重新分析)
      const today = await findTodayReport(symbol)
      if (today) {
        setConfirmReport({ id: today.id, created_at: today.created_at, focus: today.focus })
      } else {
        await doAnalysis()
      }
    } catch {
      await doAnalysis()
    } finally {
      setChecking(false)
    }
  }

  const doAnalysis = async () => {
    const r = await startAnalysis(symbol, name)
    if (r.error) toast(r.error, 'error')
  }

  return (
    <>
      <PageHeader
        title="个股分析"
        subtitle="日 K · 关键价位 · AI 四维分析(技术 / 基本面 / 财务 / 消息面)"
        right={
          <div className="flex items-center gap-2">
            <LastStockChip stock={lastStock} onSelect={onSelect} />
          </div>
        }
      />

      <PageContainer className="space-y-6">
        {/* 搜索栏 */}
        <div className="flex items-center gap-3 flex-wrap">
          <div className="w-72 max-w-full">
            <StockFinancialSearch onSelect={onSelect} assetTypes="stock,index" />
          </div>
          {symbol && (
            <>
              <button
                onClick={() => setPreviewSymbol(symbol)}
                title="查看个股日 K 详情"
                className="group flex items-center gap-2 text-sm rounded-md px-1.5 py-0.5 -mx-1.5 hover:bg-elevated transition-colors"
              >
                <span className="text-foreground font-medium group-hover:text-sky-300 transition-colors">{name || symbol}</span>
                <span className="text-[10px] font-mono text-muted">{symbol}</span>
                <ExternalLink className="h-3 w-3 text-muted opacity-0 group-hover:opacity-100 transition-opacity" />
              </button>
              <Button
                size="xs"
                variant={inWatchlist ? 'light' : 'default'}
                color={inWatchlist ? 'yellow' : undefined}
                onClick={() => toggleWatchlist.mutate()}
                loading={watchlist.isLoading || toggleWatchlist.isPending}
                disabled={watchlist.isLoading}
                leftSection={!watchlist.isLoading && !toggleWatchlist.isPending && <Star className="h-3.5 w-3.5" fill={inWatchlist ? 'currentColor' : 'none'} />}
                aria-pressed={inWatchlist}
                title={inWatchlist ? '移出自选' : '加入自选'}
              >
                {inWatchlist ? '已加自选' : '加入自选'}
              </Button>
              <Button
                size="xs"
                variant="light"
                color="accent"
                onClick={handleAnalyze}
                loading={checking}
                leftSection={!checking && <Sparkles className="h-3.5 w-3.5" />}
              >
                AI 个股分析
              </Button>
              <Tooltip label="设置价格点位提醒" position="bottom">
                <Button
                  size="xs"
                  variant="default"
                  onClick={() => setShowPriceAlerts(true)}
                  leftSection={<Bell className="h-3.5 w-3.5" />}
                >
                  点位提醒
                </Button>
              </Tooltip>
              <Button
                size="xs"
                variant="light"
                color="blue"
                onClick={() => setShowDebate(true)}
                leftSection={<Swords className="h-3.5 w-3.5" />}
              >
                多空辩论
              </Button>
            </>
          )}
        </div>

        {/* 主体:左侧当前个股看板 + 右侧常驻历史报告(窄屏堆叠为单列) */}
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_288px] gap-6 items-start">
          <div className="min-w-0">
            {!symbol ? (
              <EmptyState
                icon={LineChart}
                title="选择一只股票开始分析"
                hint="搜索代码或名称,查看日 K 与关键价位,并可让 AI 进行技术面 / 基本面 / 财务面 / 消息面四维综合分析。"
              />
            ) : (
              <StockAnalysisBoard symbol={symbol} />
            )}
          </div>
          <HistorySidebar />
        </div>

        {/* 数据子板块:横向 tab 切换,只请求当前选中的估值/财务/研报/公告/新闻/资金面/龙虎榜 */}
        {symbol && <StockInsightPanels key={symbol} symbol={symbol} />}
      </PageContainer>

      {/* 二次确认:已有历史报告 */}
      {confirmReport && (
        <ConfirmModal
          report={confirmReport}
          onView={() => { openHistoryReport(confirmReport.id); setConfirmReport(null) }}
          onRedo={async () => { setConfirmReport(null); await doAnalysis() }}
          onClose={() => setConfirmReport(null)}
        />
      )}

      {/* 个股日 K 详情对话框(点击名称/代码打开) */}
      <StockPreviewDialog
        symbol={previewSymbol}
        name={previewSymbol === symbol ? name : undefined}
        triggerInfo={null}
        onClose={() => setPreviewSymbol(null)}
      />

      {showPriceAlerts && symbol && (
        <PriceAlertDialog
          key={symbol}
          symbol={symbol}
          name={name}
          onClose={() => setShowPriceAlerts(false)}
        />
      )}

      {showDebate && symbol && (
        <DebateDialog
          key={symbol}
          symbol={symbol}
          name={name}
          onClose={() => setShowDebate(false)}
        />
      )}
    </>
  )
}

// ===== 分析看板:日 K + 关键价位 =====
function StockAnalysisBoard({ symbol }: { symbol: string }) {
  const kline = useQuery({
    queryKey: ['kline', symbol, ''],
    queryFn: () => api.klineDaily(symbol, 250),
    enabled: !!symbol,
    staleTime: 60_000,
  })

  const levelsQ = useQuery({
    queryKey: QK.stockLevels(symbol),
    queryFn: () => api.stockAnalysisLevels(symbol, 250),
    enabled: !!symbol,
    staleTime: 60_000,
  })

  if (kline.isLoading) {
    return <div className="flex items-center justify-center py-20"><Loader2 className="h-5 w-5 animate-spin text-muted" /></div>
  }

  if (kline.isError) {
    return (
      <EmptyState
        icon={AlertTriangle}
        title="日 K 数据加载失败"
        hint="请检查网络或数据源配置后重试。"
      />
    )
  }

  const rows = kline.data?.rows ?? []
  if (rows.length === 0) {
    return <EmptyState icon={LineChart} title="暂无日 K 数据" hint="该标的尚未同步日 K,请先在数据页或自选页同步。" />
  }

  const levels = (levelsQ.data?.levels ?? {}) as Record<LevelType, PriceLevel[]>

  // 涨跌色:最后一根 K 线收 vs 前一根收(无前日则按开收判断)
  const last = rows[rows.length - 1]
  const prev = rows[rows.length - 2]
  const curClose = levelsQ.data?.close
  const isUp = prev ? (last.close >= prev.close) : (last.close >= last.open)

  return (
    <div className="rounded-card border border-border/60 bg-surface/40 overflow-hidden">
      <div className="px-4 py-3 border-b border-border/40">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <LineChart className="h-4 w-4 text-sky-400 shrink-0" />
            <span className="text-sm font-medium text-foreground">关键价位分析</span>
          </div>
          <div className="flex items-baseline gap-2 shrink-0">
            <span className="text-[10px] text-muted">{rows.length} 个交易日</span>
            <span className="text-[10px] text-muted/60">·</span>
            <span className="text-[10px] text-muted">当前价</span>
            <span className={`text-base font-mono font-bold ${isUp ? 'text-bull' : 'text-bear'}`}>
              {curClose?.toFixed(2) ?? '—'}
            </span>
          </div>
        </div>
      </div>
      <div className="p-3">
        <AnalysisKChart
          rows={rows}
          levels={levels}
          series={levelsQ.data?.series}
          seriesDates={levelsQ.data?.dates}
          defaultLevelTypes={['sr', 'pivot', 'keltner_s']}
          height={480}
        />
      </div>
    </div>
  )
}

// ===== 左侧常驻:历史报告侧栏(所有股票,按时间倒序平铺) =====
function HistorySidebar() {
  const { reports, loaded } = useHistoryReports()

  return (
    <aside className="self-start lg:sticky lg:top-0">
      <div className="rounded-card border border-border/60 bg-surface/40 overflow-hidden">
        <div className="px-3 py-2.5 border-b border-border/40 flex items-center gap-2">
          <HistoryIcon className="h-3.5 w-3.5 text-sky-400 shrink-0" />
          <span className="text-xs font-medium text-foreground">历史报告</span>
          {loaded && reports.length > 0 && (
            <Badge size="xs" variant="light" color="gray" className="ml-auto">{reports.length}</Badge>
          )}
        </div>

        {!loaded ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="h-4 w-4 animate-spin text-muted" />
          </div>
        ) : reports.length === 0 ? (
          <div className="px-3 py-10 text-center">
            <p className="text-xs text-muted">还没有任何个股分析报告</p>
            <p className="text-[10px] text-muted/60 mt-1">选一只股票,点「AI 个股分析」生成</p>
          </div>
        ) : (
          <div className="max-h-[calc(100vh-220px)] overflow-y-auto p-2 space-y-1.5">
            {reports.map(r => (
              <div
                key={r.id}
                className="group rounded-lg border border-border/40 bg-elevated/20 p-2.5 hover:border-border hover:bg-elevated/40 transition-colors"
              >
                <div className="flex items-center justify-between gap-2">
                  <button
                    onClick={() => openHistoryReport(r.id)}
                    className="flex-1 text-left min-w-0"
                  >
                    <div className="flex items-center gap-1.5 min-w-0">
                      <span className="text-xs font-medium text-foreground truncate">{r.name || r.symbol}</span>
                      <span className="text-[10px] font-mono text-muted shrink-0">{r.symbol}</span>
                    </div>
                    <div className="mt-0.5 flex items-center gap-2 text-[10px] text-muted">
                      <span>{fmtRelative(r.created_at)}</span>
                      {r.close != null && <span className="font-mono">价 {r.close.toFixed(2)}</span>}
                      {r.focus && <span className="text-sky-300/70 truncate">关注: {r.focus}</span>}
                    </div>
                    {r.summary && (
                      <div className="mt-1 text-[11px] text-muted truncate">{r.summary}</div>
                    )}
                  </button>
                  <Tooltip label="删除" position="left">
                    <Button
                      size="compact-xs"
                      variant="subtle"
                      color="red"
                      onClick={() => { deleteReport(r.id); toast('已删除', 'success') }}
                      className="shrink-0 opacity-0 group-hover:opacity-100"
                    >
                      删除
                    </Button>
                  </Tooltip>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </aside>
  )
}

// ===== 二次确认弹窗 =====
function ConfirmModal({ report, onView, onRedo, onClose }: {
  report: { id: string; created_at: string; focus: string }
  onView: () => void
  onRedo: () => void
  onClose: () => void
}) {
  return (
    <Modal
      onClose={onClose}
      ariaLabel="该个股已有分析报告"
      panelClassName="w-full max-w-sm bg-surface border border-border rounded-dialog p-5 shadow-2xl"
      overlayClassName="bg-black/50 backdrop-blur-sm"
    >
      <div className="flex items-center gap-2 mb-2">
        <HistoryIcon className="h-4 w-4 text-sky-400" />
        <span className="text-sm font-medium text-foreground">该个股已有分析报告</span>
      </div>
      <p className="text-xs text-secondary leading-relaxed mb-1">
        最近一次报告生成于 <span className="text-foreground">{fmtRelative(report.created_at)}</span>。
      </p>
      {report.focus && <p className="text-xs text-muted mb-1">关注点: {report.focus}</p>}
      <p className="text-xs text-muted mb-4">可直接查看历史,或重新生成一份新报告。</p>
      <div className="flex gap-2">
        <Button size="xs" variant="default" className="flex-1" onClick={onView}>
          查看历史
        </Button>
        <Button size="xs" variant="light" color="accent" className="flex-1" onClick={onRedo}>
          重新分析
        </Button>
      </div>
    </Modal>
  )
}

function fmtRelative(iso: string): string {
  try {
    const t = new Date(iso).getTime()
    const diff = Date.now() - t
    if (diff < 60_000) return '刚刚'
    if (diff < 3600_000) return `${Math.floor(diff / 60_000)} 分钟前`
    if (diff < 86400_000) return `${Math.floor(diff / 3600_000)} 小时前`
    if (diff < 7 * 86400_000) return `${Math.floor(diff / 86400_000)} 天前`
    return new Date(iso).toLocaleDateString('zh-CN')
  } catch { return iso }
}
