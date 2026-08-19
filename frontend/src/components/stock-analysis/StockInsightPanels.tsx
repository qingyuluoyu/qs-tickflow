import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'framer-motion'
import {
  ChevronDown, Loader2, Gauge, BarChart3, FileText, Megaphone, Newspaper, Wallet, Trophy,
  type LucideIcon,
} from 'lucide-react'
import { Badge, Button } from '@mantine/core'
import {
  api,
  type ValPercentileMetric,
} from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { cn } from '@/lib/cn'

/**
 * 个股洞察数据子板块 —— 估值分位 / 财务指标 / 研报 / 公告 / 新闻 / 资金面 / 龙虎榜。
 *
 * - 每个子板块默认收起, 展开时才发起请求 (useQuery enabled: open), 互不影响
 * - 数据接口: /api/stock-insight/*, symbol 形如 000001.SZ
 */
export function StockInsightPanels({ symbol }: { symbol: string }) {
  const [active, setActive] = useState<InsightPanelKey>('valuation')
  const tabs: Array<{ key: InsightPanelKey; label: string; icon: LucideIcon }> = [
    { key: 'valuation', label: '估值分位', icon: Gauge },
    { key: 'financials', label: '财务指标', icon: BarChart3 },
    { key: 'reports', label: '近期研报', icon: FileText },
    { key: 'announcements', label: '近期公告', icon: Megaphone },
    { key: 'news', label: '个股新闻', icon: Newspaper },
    { key: 'fund-flow', label: '资金面', icon: Wallet },
    { key: 'dragon-tiger', label: '龙虎榜', icon: Trophy },
  ]
  return (
    <div className="space-y-3">
      <div role="tablist" aria-label="个股分析模块" className="flex min-w-0 gap-1 overflow-x-auto rounded-card border border-border/60 bg-surface/40 p-1">
        {tabs.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={active === key}
            onClick={() => setActive(key)}
            className={cn(
              'flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-2 text-xs transition-colors',
              active === key
                ? 'bg-accent/15 font-medium text-accent shadow-sm'
                : 'text-muted hover:bg-elevated/30 hover:text-foreground',
            )}
          >
            <Icon className="h-3.5 w-3.5" />
            {label}
          </button>
        ))}
      </div>
      {active === 'valuation' && <ValuationPanel symbol={symbol} />}
      {active === 'financials' && <FinancialsPanel symbol={symbol} />}
      {active === 'reports' && <ReportsPanel symbol={symbol} />}
      {active === 'announcements' && <AnnouncementsPanel symbol={symbol} />}
      {active === 'news' && <NewsPanel symbol={symbol} />}
      {active === 'fund-flow' && <FundFlowPanel symbol={symbol} />}
      {active === 'dragon-tiger' && <DragonTigerPanel symbol={symbol} />}
    </div>
  )
}

type InsightPanelKey = 'valuation' | 'financials' | 'reports' | 'announcements' | 'news' | 'fund-flow' | 'dragon-tiger'

// ===== 通用:折叠卡片外壳 =====
function PanelShell({ icon: Icon, title, open, onToggle, children }: {
  icon: LucideIcon
  title: string
  open: boolean
  onToggle: () => void
  children: React.ReactNode
}) {
  return (
    <div className="rounded-card border border-border/60 bg-surface/40 overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-2 px-4 py-3 hover:bg-elevated/20 transition-colors"
      >
        <Icon className="h-4 w-4 text-sky-400 shrink-0" />
        <span className="text-sm font-medium text-foreground">{title}</span>
        <ChevronDown className={cn('h-4 w-4 ml-auto text-muted transition-transform', open && 'rotate-180')} />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="overflow-hidden"
          >
            <div className="p-3 border-t border-border/40">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

// ===== 通用:加载 / 错误 / 空态 =====
function PanelLoading() {
  return (
    <div className="flex items-center justify-center py-8">
      <Loader2 className="h-4 w-4 animate-spin text-muted" />
    </div>
  )
}

function PanelError({ message, onRetry }: { message?: string; onRetry: () => void }) {
  return (
    <div className="flex items-center justify-center gap-3 py-8">
      <span className="text-[11px] text-muted truncate max-w-[60%]" title={message}>
        加载失败{message ? `: ${message}` : ''}
      </span>
      <Button size="compact-xs" variant="light" color="accent" onClick={onRetry} className="shrink-0">
        重试
      </Button>
    </div>
  )
}

function PanelEmpty() {
  return <p className="py-8 text-center text-[11px] text-muted">暂无数据</p>
}

// ===== 通用格式化 =====
/** 红涨绿跌 */
const signedCls = (v: number) => (v > 0 ? 'text-bull' : v < 0 ? 'text-bear' : 'text-muted')

const numOrDash = (v: number | null | undefined, digits = 2) =>
  v == null || !Number.isFinite(v) ? '—' : v.toFixed(digits)

/** 金额(元) → 亿/万 自适应 */
function fmtYuan(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  const a = Math.abs(v)
  if (a >= 1e8) return `${(v / 1e8).toFixed(2)} 亿`
  if (a >= 1e4) return `${(v / 1e4).toFixed(2)} 万`
  return v.toFixed(2)
}

/** 万元金额 → 亿/万 自适应 */
function fmtWan(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  const a = Math.abs(v)
  if (a >= 1e4) return `${(v / 1e4).toFixed(2)} 亿`
  return `${v.toFixed(2)} 万`
}

// ===== 估值分位 =====
function ValuationPanel({ symbol }: { symbol: string }) {
  const [open, setOpen] = useState(true)
  const q = useQuery({
    queryKey: QK.stockInsightValuation(symbol),
    queryFn: () => api.stockInsightValuation(symbol),
    enabled: open,
    staleTime: 10 * 60_000,
  })
  const pe = q.data?.metrics.pe_ttm
  const pb = q.data?.metrics.pb
  return (
    <PanelShell icon={Gauge} title="估值分位" open={open} onToggle={() => setOpen(v => !v)}>
      {q.isLoading ? <PanelLoading />
        : q.isError ? <PanelError message={q.error?.message} onRetry={() => q.refetch()} />
        : !pe && !pb ? <PanelEmpty />
        : (
          <div className="space-y-4">
            <p className="text-[11px] text-muted">
              {q.data?.period} · 绿=低估区 / 灰=合理区 / 红=高估区,只显示当前处于历史什么位置,不构成买卖建议。
            </p>
            {pe && <ValBand label="PE-TTM" m={pe} />}
            {pb && <ValBand label="市净率 PB" m={pb} />}
          </div>
        )}
    </PanelShell>
  )
}

/** 估值历史分位带(理杏仁式三段色带 + 当前位置竖线) */
function ValBand({ label, m }: { label: string; m: ValPercentileMetric }) {
  const span = Math.max(m.max - m.min, 1e-6)
  const pos = (v: number) => Math.min(100, Math.max(0, ((v - m.min) / span) * 100))
  const p20 = pos(m.p20)
  const p80 = pos(m.p80)
  const cur = pos(m.current)
  const zoneColor = m.percentile < 20 ? 'text-bear' : m.percentile > 80 ? 'text-bull' : 'text-muted'
  const zoneLabel = m.percentile < 20 ? '低估区' : m.percentile > 80 ? '高估区' : '合理区'
  return (
    <div>
      <div className="mb-1.5 flex flex-wrap items-baseline justify-between gap-1 text-xs">
        <span className="font-medium text-foreground">
          {label} <span className="text-[10px] text-muted/60">{m.n} 点</span>
        </span>
        <span className="text-muted">
          当前 <b className="font-mono tabular-nums text-foreground">{m.current}</b>
          {' · '}分位 <b className={cn('font-mono tabular-nums', zoneColor)}>{m.percentile}%</b>
          （<span className={zoneColor}>{zoneLabel}</span>）
        </span>
      </div>
      <div className="relative h-2.5 w-full overflow-hidden rounded-full">
        <div className="absolute inset-0 flex">
          <div className="bg-bear/35" style={{ width: `${p20}%` }} />
          <div className="bg-elevated" style={{ width: `${Math.max(p80 - p20, 0)}%` }} />
          <div className="flex-1 bg-bull/35" />
        </div>
        <div
          className="absolute top-1/2 h-4 w-[3px] -translate-x-1/2 -translate-y-1/2 rounded bg-foreground shadow"
          style={{ left: `${cur}%` }}
        />
      </div>
      <div className="mt-1 flex justify-between font-mono tabular-nums text-[10px] text-muted/60">
        <span>低 {m.min}</span><span>20% {m.p20}</span><span>中 {m.p50}</span><span>80% {m.p80}</span><span>高 {m.max}</span>
      </div>
    </div>
  )
}

// ===== 财务指标 =====
function FinancialsPanel({ symbol }: { symbol: string }) {
  const [open, setOpen] = useState(true)
  const q = useQuery({
    queryKey: QK.stockInsightFinancials(symbol),
    queryFn: () => api.stockInsightFinancials(symbol),
    enabled: open,
    staleTime: 10 * 60_000,
  })
  const f = q.data
  const hasData = f && [f.revenue, f.net_profit, f.eps, f.roe].some(v => v != null)
  const metrics = f ? [
    { k: '营业总收入', v: fmtYuan(f.revenue), yoy: f.revenue_yoy },
    { k: '归母净利润', v: fmtYuan(f.net_profit), yoy: f.net_profit_yoy },
    { k: '每股收益 EPS', v: numOrDash(f.eps) },
    { k: '每股净资产 BVPS', v: numOrDash(f.bvps) },
    { k: 'ROE', v: f.roe == null ? '—' : `${numOrDash(f.roe)}%` },
    { k: '销售毛利率', v: f.gross_margin == null ? '—' : `${numOrDash(f.gross_margin)}%` },
    { k: '销售净利率', v: f.net_margin == null ? '—' : `${numOrDash(f.net_margin)}%` },
    { k: '每股经营现金流', v: numOrDash(f.op_cf_ps) },
  ] : []
  return (
    <PanelShell icon={BarChart3} title="财务指标" open={open} onToggle={() => setOpen(v => !v)}>
      {q.isLoading ? <PanelLoading />
        : q.isError ? <PanelError message={q.error?.message} onRetry={() => q.refetch()} />
        : !hasData ? <PanelEmpty />
        : (
          <div>
            <p className="mb-3 text-[11px] text-muted">
              报告期 {f.period || '—'} · 金额已由元换算为亿/万,比率为百分数。
            </p>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {metrics.map(m => (
                <div key={m.k} className="rounded-lg border border-border/40 bg-elevated/20 p-2.5">
                  <p className="text-[11px] text-muted">{m.k}</p>
                  <p className="mt-0.5 font-mono tabular-nums text-sm font-bold text-foreground">{m.v}</p>
                  {'yoy' in m && m.yoy != null && (
                    <p className={cn('text-[11px] font-mono tabular-nums', signedCls(m.yoy))}>
                      同比 {m.yoy > 0 ? '+' : ''}{numOrDash(m.yoy)}%
                    </p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
    </PanelShell>
  )
}

// ===== 近期研报 =====
function ReportsPanel({ symbol }: { symbol: string }) {
  const [open, setOpen] = useState(true)
  const q = useQuery({
    queryKey: QK.stockInsightReports(symbol),
    queryFn: () => api.stockInsightReports(symbol, 2),
    enabled: open,
    staleTime: 10 * 60_000,
  })
  const reports = q.data?.reports ?? []
  return (
    <PanelShell icon={FileText} title="近期研报" open={open} onToggle={() => setOpen(v => !v)}>
      {q.isLoading ? <PanelLoading />
        : q.isError ? <PanelError message={q.error?.message} onRetry={() => q.refetch()} />
        : reports.length === 0 ? <PanelEmpty />
        : (
          <div className="space-y-2">
            {reports.slice(0, 12).map((r, i) => (
              <div key={r.infoCode || i} className="flex items-center gap-3 border-b border-border/40 pb-2 text-xs last:border-0">
                <span className="w-20 shrink-0 font-mono tabular-nums text-[11px] text-muted">{(r.publishDate || '').slice(0, 10)}</span>
                <span className="w-24 shrink-0 truncate text-[11px] text-muted">{r.orgSName}</span>
                {r.pdfUrl ? (
                  <a href={r.pdfUrl} target="_blank" rel="noreferrer" className="flex-1 truncate text-foreground hover:text-sky-300 transition-colors">{r.title}</a>
                ) : (
                  <span className="flex-1 truncate text-foreground">{r.title}</span>
                )}
                {r.emRatingName && (
                  <Badge size="xs" variant="light" color="accent" radius="sm" className="shrink-0 normal-case">{r.emRatingName}</Badge>
                )}
              </div>
            ))}
          </div>
        )}
    </PanelShell>
  )
}

// ===== 近期公告 =====
function AnnouncementsPanel({ symbol }: { symbol: string }) {
  const [open, setOpen] = useState(true)
  const q = useQuery({
    queryKey: QK.stockInsightAnnouncements(symbol),
    queryFn: () => api.stockInsightAnnouncements(symbol),
    enabled: open,
    staleTime: 10 * 60_000,
  })
  const anns = q.data?.announcements ?? []
  return (
    <PanelShell icon={Megaphone} title="近期公告" open={open} onToggle={() => setOpen(v => !v)}>
      {q.isLoading ? <PanelLoading />
        : q.isError ? <PanelError message={q.error?.message} onRetry={() => q.refetch()} />
        : anns.length === 0 ? <PanelEmpty />
        : (
          <div className="space-y-2">
            {anns.slice(0, 12).map((a, i) => (
              <div key={i} className="flex items-center gap-3 border-b border-border/40 pb-2 text-xs last:border-0">
                <span className="w-20 shrink-0 font-mono tabular-nums text-[11px] text-muted">{a.date}</span>
                {a.type && <span className="w-24 shrink-0 truncate text-[11px] text-muted">{a.type}</span>}
                {a.url ? (
                  <a href={a.url} target="_blank" rel="noreferrer" className="flex-1 truncate text-foreground hover:text-sky-300 transition-colors">{a.title}</a>
                ) : (
                  <span className="flex-1 truncate text-foreground">{a.title}</span>
                )}
              </div>
            ))}
          </div>
        )}
    </PanelShell>
  )
}

// ===== 个股新闻 =====
function NewsPanel({ symbol }: { symbol: string }) {
  const [open, setOpen] = useState(true)
  const q = useQuery({
    queryKey: QK.stockInsightNews(symbol),
    queryFn: () => api.stockInsightNews(symbol, 20),
    enabled: open,
    staleTime: 10 * 60_000,
  })
  const news = q.data?.news ?? []
  return (
    <PanelShell icon={Newspaper} title="个股新闻" open={open} onToggle={() => setOpen(v => !v)}>
      {q.isLoading ? <PanelLoading />
        : q.isError ? <PanelError message={q.error?.message} onRetry={() => q.refetch()} />
        : news.length === 0 ? <PanelEmpty />
        : (
          <div className="space-y-2">
            {news.slice(0, 10).map((n, i) => (
              <div key={i} className="flex items-center gap-3 border-b border-border/40 pb-2 text-xs last:border-0">
                <span className="w-28 shrink-0 font-mono tabular-nums text-[11px] text-muted">{(n.发布时间 || '').slice(0, 16)}</span>
                {n.文章来源 && <span className="w-20 shrink-0 truncate text-[11px] text-muted">{n.文章来源}</span>}
                {n.新闻链接 ? (
                  <a href={n.新闻链接} target="_blank" rel="noreferrer" className="flex-1 truncate text-foreground hover:text-sky-300 transition-colors">{n.新闻标题}</a>
                ) : (
                  <span className="flex-1 truncate text-foreground">{n.新闻标题}</span>
                )}
              </div>
            ))}
          </div>
        )}
    </PanelShell>
  )
}

// ===== 资金面 =====
function FundFlowPanel({ symbol }: { symbol: string }) {
  const [open, setOpen] = useState(true)
  const q = useQuery({
    queryKey: QK.stockInsightFundFlow(symbol),
    queryFn: () => api.stockInsightFundFlow(symbol),
    enabled: open,
    staleTime: 10 * 60_000,
  })
  const rows = q.data?.rows ?? []
  // rows 按日期升序, 取末尾 N 日求和
  const sumMain = (n: number) => rows.slice(-n).reduce((s, r) => s + (r.main_net ?? 0), 0)
  const last = rows[rows.length - 1]
  return (
    <PanelShell icon={Wallet} title="资金面" open={open} onToggle={() => setOpen(v => !v)}>
      {q.isLoading ? <PanelLoading />
        : q.isError ? <PanelError message={q.error?.message} onRetry={() => q.refetch()} />
        : rows.length === 0 ? <PanelEmpty />
        : (
          <div>
            <div className="grid grid-cols-3 gap-2">
              {([5, 10, 20] as const).map(n => (
                <div key={n} className="rounded-lg border border-border/40 bg-elevated/20 p-2.5">
                  <p className="text-[11px] text-muted">近{n}日主力净流入</p>
                  <p className={cn('mt-0.5 font-mono tabular-nums text-sm font-bold', signedCls(sumMain(n)))}>
                    {fmtYuan(sumMain(n))}
                  </p>
                </div>
              ))}
            </div>
            {last && (
              <div className="mt-3 border-t border-border/40 pt-3">
                <p className="mb-2 text-[11px] text-muted">最新一日（{last.date}）明细</p>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
                  {([
                    ['主力', last.main_net],
                    ['超大单', last.super_net],
                    ['大单', last.large_net],
                    ['中单', last.mid_net],
                    ['小单', last.small_net],
                  ] as const).map(([k, v]) => (
                    <div key={k} className="rounded-lg border border-border/40 bg-elevated/20 p-2.5">
                      <p className="text-[11px] text-muted">{k}净流入</p>
                      <p className={cn('mt-0.5 font-mono tabular-nums text-xs font-bold', signedCls(v))}>{fmtYuan(v)}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
            <p className="mt-3 text-[11px] text-muted/60">原始单位为元,已换算为亿/万;近 {rows.length} 个交易日。</p>
          </div>
        )}
    </PanelShell>
  )
}

// ===== 龙虎榜 =====
function DragonTigerPanel({ symbol }: { symbol: string }) {
  const [open, setOpen] = useState(true)
  const q = useQuery({
    queryKey: QK.stockInsightDragonTiger(symbol),
    queryFn: () => api.stockInsightDragonTiger(symbol),
    enabled: open,
    staleTime: 10 * 60_000,
  })
  const dt = q.data
  const records = dt?.records ?? []
  const buySeats = dt?.seats.buy ?? []
  const sellSeats = dt?.seats.sell ?? []
  const inst = dt?.institution
  const empty = records.length === 0 && buySeats.length === 0 && sellSeats.length === 0
  return (
    <PanelShell icon={Trophy} title="龙虎榜" open={open} onToggle={() => setOpen(v => !v)}>
      {q.isLoading ? <PanelLoading />
        : q.isError ? <PanelError message={q.error?.message} onRetry={() => q.refetch()} />
        : !dt || empty ? <PanelEmpty />
        : (
          <div>
            {records.length > 0 && (
              <div className="space-y-2">
                <p className="text-[11px] text-muted">上榜记录（{records.length} 次）· 金额单位万元</p>
                {records.slice(0, 8).map((r, i) => (
                  <div key={i} className="flex items-center gap-3 border-b border-border/40 pb-2 text-xs last:border-0">
                    <span className="w-20 shrink-0 font-mono tabular-nums text-[11px] text-muted">{r.date}</span>
                    <span className="flex-1 truncate text-foreground" title={r.reason}>{r.reason}</span>
                    <span className="shrink-0 font-mono tabular-nums text-[11px] text-muted">成交 {fmtWan(r.turnover)}</span>
                    <span className={cn('shrink-0 font-mono tabular-nums text-[11px]', signedCls(r.net_buy))}>
                      净买 {fmtWan(r.net_buy)}
                    </span>
                  </div>
                ))}
              </div>
            )}
            {inst && (inst.buy_amt !== 0 || inst.sell_amt !== 0) && (
              <div className="mt-3 rounded-lg border border-border/40 bg-elevated/20 p-2.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px]">
                <span className="text-muted">机构专用席位</span>
                <span className="font-mono tabular-nums text-bull">买 {fmtWan(inst.buy_amt)}</span>
                <span className="font-mono tabular-nums text-bear">卖 {fmtWan(inst.sell_amt)}</span>
                <span className={cn('font-mono tabular-nums', signedCls(inst.net_amt))}>净 {fmtWan(inst.net_amt)}</span>
              </div>
            )}
            {(buySeats.length > 0 || sellSeats.length > 0) && (
              <div className="mt-3 grid gap-4 border-t border-border/40 pt-3 sm:grid-cols-2">
                <div>
                  <p className="mb-1.5 text-[11px] font-medium text-bull">买入席位 TOP5</p>
                  {buySeats.slice(0, 5).map((s, i) => (
                    <div key={i} className="flex justify-between gap-2 py-0.5 text-[11px] text-muted">
                      <span className="truncate" title={s.name}>{s.name}</span>
                      <span className={cn('shrink-0 font-mono tabular-nums', signedCls(s.net))}>净 {fmtWan(s.net)}</span>
                    </div>
                  ))}
                </div>
                <div>
                  <p className="mb-1.5 text-[11px] font-medium text-bear">卖出席位 TOP5</p>
                  {sellSeats.slice(0, 5).map((s, i) => (
                    <div key={i} className="flex justify-between gap-2 py-0.5 text-[11px] text-muted">
                      <span className="truncate" title={s.name}>{s.name}</span>
                      <span className={cn('shrink-0 font-mono tabular-nums', signedCls(s.net))}>净 {fmtWan(s.net)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
    </PanelShell>
  )
}
