import { useEffect, useMemo, useState } from 'react'
import { Clock, X } from 'lucide-react'
import { ActionIcon, Badge, Button } from '@mantine/core'
import { StockPanel } from '@/components/StockPanel'
import { Modal } from '@/components/Modal'
import type { ChartPriceLine, ChartRange } from '@/components/EChartsCandlestick'
import type { StrategyBacktestTrade } from '@/lib/api'
import { fmtPct, fmtPrice, priceColorClass } from '@/lib/format'

interface Props {
  trade: StrategyBacktestTrade | null
  onClose: () => void
}

function addDays(date: string, days: number): string {
  const d = new Date(date)
  d.setDate(d.getDate() + days)
  return d.toISOString().slice(0, 10)
}

function fmtMoney(v: number | null | undefined): string {
  if (v == null || Number.isNaN(Number(v))) return '—'
  const n = Number(v)
  const abs = Math.abs(n)
  if (abs >= 100_000_000) return `${(n / 100_000_000).toFixed(2)}亿`
  if (abs >= 10_000) return `${(n / 10_000).toFixed(2)}万`
  return n.toFixed(0)
}

function fmtSignedMoney(v: number | null | undefined): string {
  if (v == null || Number.isNaN(Number(v))) return '—'
  const prefix = Number(v) > 0 ? '+' : ''
  return `${prefix}${fmtMoney(v)}`
}

export function TradeKlineModal({ trade, onClose }: Props) {
  const [showIntraday, setShowIntraday] = useState(false)

  useEffect(() => {
    if (trade) setShowIntraday(false)
  }, [trade])

  const dateRange = useMemo(() => {
    if (!trade) return null
    return {
      start: addDays(String(trade.entry_date).slice(0, 10), -45),
      end: addDays(String(trade.exit_date).slice(0, 10), 20),
    }
  }, [trade])

  const ranges = useMemo<ChartRange[]>(() => {
    if (!trade) return []
    return [{
      start: String(trade.entry_date).slice(0, 10),
      end: String(trade.exit_date).slice(0, 10),
      label: '持仓区间',
      color: 'rgba(59,130,246,0.07)',
    }]
  }, [trade])

  const priceLines = useMemo<ChartPriceLine[]>(() => {
    if (!trade) return []
    const start = String(trade.entry_date).slice(0, 10)
    const end = String(trade.exit_date).slice(0, 10)
    return [
      {
        value: Number(trade.entry_price),
        label: `买入价 ${fmtPrice(trade.entry_price)}`,
        color: '#C74040',
        start,
        end,
      },
      {
        value: Number(trade.exit_price),
        label: `卖出价 ${fmtPrice(trade.exit_price)}`,
        color: '#2D9B65',
        start,
        end,
      },
    ]
  }, [trade])

  if (!trade || !dateRange) return null
  return (
    <Modal
      onClose={onClose}
      ariaLabel={`交易回放 ${trade.symbol}`}
      panelClassName="flex max-h-[94vh] w-[92vw] max-w-[1120px] flex-col overflow-hidden rounded-card border border-border bg-base shadow-2xl"
      overlayClassName="bg-black/60 backdrop-blur-sm"
    >
      <div className="flex items-center justify-between gap-4 border-b border-border px-5 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm font-semibold text-foreground">{trade.symbol}</span>
            <span className="truncate text-sm text-foreground">{trade.name || '交易回放'}</span>
            <Badge size="sm" variant="light" color="accent">交易回放</Badge>
          </div>
          <div className="mt-1 text-[11px] text-muted">
            {String(trade.entry_date).slice(0, 10)} 买入 → {String(trade.exit_date).slice(0, 10)} 卖出 · 持仓 {trade.duration ?? '—'} 天
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-3 text-xs">
          <div className="text-right">
            <div className="text-muted">买 / 卖</div>
            <div className="num text-foreground">{fmtPrice(trade.entry_price)} / {fmtPrice(trade.exit_price)}</div>
          </div>
          <div className="text-right">
            <div className="text-muted">盈亏</div>
            <div className={`num font-semibold ${priceColorClass(trade.pnl_amount ?? trade.pnl_pct)}`}>
              {fmtSignedMoney(trade.pnl_amount)} / {fmtPct(trade.pnl_pct)}
            </div>
          </div>
          <Button
            size="xs"
            variant={showIntraday ? 'light' : 'default'}
            leftSection={<Clock className="h-3 w-3" />}
            onClick={() => setShowIntraday((v) => !v)}
          >
            分时
          </Button>
          <ActionIcon variant="subtle" color="gray" size="md" onClick={onClose} aria-label="关闭">
            <X className="h-4 w-4" />
          </ActionIcon>
        </div>
      </div>

      <div className="flex-1 overflow-auto p-4">
        <StockPanel
          symbol={trade.symbol}
          height={520}
          dateRange={dateRange}
          ranges={ranges}
          priceLines={priceLines}
          showLimitMarkers={false}
          showMarkerToggle={false}
          showIntraday={showIntraday}
          onSelectDate={() => { if (!showIntraday) setShowIntraday(true) }}
        />
      </div>
    </Modal>
  )
}
