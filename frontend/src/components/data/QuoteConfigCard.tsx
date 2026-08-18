import { useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { ActionIcon, Button, Card, Slider, Switch, Tooltip } from '@mantine/core'
import { Activity, Settings } from 'lucide-react'
import { Skeleton } from './Skeleton'

export function QuoteConfigCard({ enabled, running, isTrading, lastFetchMs, intervalS, intervalMin, intervalMax, loading, onToggle, toggling, showIntervalEdit, onShowIntervalEdit, onIntervalChange, isAdmin = true }: {
  enabled: boolean
  running: boolean
  isTrading: boolean
  lastFetchMs: number | null
  intervalS: number
  intervalMin: number
  intervalMax: number
  loading: boolean
  onToggle: (enabled: boolean) => void
  toggling: boolean
  showIntervalEdit: boolean
  onShowIntervalEdit: () => void
  onIntervalChange: (v: number) => void
  /** 开关与轮询间隔为服务器级写操作(管理员闸门),普通用户隐藏控件只保留状态展示 */
  isAdmin?: boolean
}) {
  const statusColor = running && isTrading
    ? 'bg-accent shadow-[0_0_6px_rgba(61,214,140,0.5)]'
    : enabled && running
      ? 'bg-warning/60'
      : 'bg-muted'

  const statusText = !enabled
    ? '已关闭'
    : !isTrading
      ? '非交易时段'
      : running
        ? '行情运行中'
        : '已停止'

  const lastFetchTime = lastFetchMs
    ? new Date(lastFetchMs).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' })
    : null

  return (
    <Card padding="md" className="border border-border bg-surface relative">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-secondary" />
          <h3 className="text-sm font-medium text-foreground">实时行情</h3>
        </div>
        {isAdmin && (
        <Switch
          size="sm"
          checked={enabled}
          onChange={(e) => onToggle(e.currentTarget.checked)}
          disabled={toggling}
          aria-label="实时行情开关"
        />
        )}
      </div>

      {loading ? (
        <div className="space-y-2">
          <div className="flex items-center justify-between"><Skeleton w="w-8" /><Skeleton w="w-16" /></div>
          <div className="flex items-center justify-between"><Skeleton w="w-12" /><Skeleton w="w-20" /></div>
          <div className="flex items-center justify-between"><Skeleton w="w-10" /><Skeleton w="w-14" /></div>
          <div className="flex items-center justify-between"><Skeleton w="w-12" /><Skeleton w="w-12" /></div>
        </div>
      ) : (
        <div className="space-y-2">
          <div className="flex items-center justify-between text-[11px]">
            <span className="text-muted">状态</span>
            <div className="flex items-center gap-1.5">
              <span className={`inline-block h-1.5 w-1.5 rounded-full ${statusColor} ${running && isTrading ? 'animate-pulse' : ''}`} />
              <span className="font-mono text-secondary">{statusText}</span>
            </div>
          </div>
          <div className="flex items-center justify-between text-[11px]">
            <span className="text-muted">交易时段</span>
            <span className={`font-mono ${isTrading ? 'text-accent' : 'text-muted'}`}>{isTrading ? '交易中' : '休市'}</span>
          </div>
          <div className="flex items-center justify-between text-[11px]">
            <div className="flex items-center gap-1">
              <span className="text-muted">轮询间隔</span>
              {isAdmin && (
              <Tooltip label="设置轮询间隔" position="top">
                <ActionIcon
                  variant="subtle"
                  color="gray"
                  size="xs"
                  aria-label="设置轮询间隔"
                  onClick={() => onShowIntervalEdit()}
                  className={showIntervalEdit ? 'text-accent' : 'text-secondary'}
                >
                  <Settings className="h-3 w-3" />
                </ActionIcon>
              </Tooltip>
              )}
            </div>
            <span className="font-mono text-secondary">{intervalS}s</span>
          </div>
          <div className="flex items-center justify-between text-[11px]">
            <span className="text-muted">最后获取</span>
            <span className="font-mono text-secondary">{lastFetchTime ?? '—'}</span>
          </div>
        </div>
      )}

      <AnimatePresence>
        {showIntervalEdit && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
            className="overflow-hidden"
          >
            <IntervalEditor
              min={intervalMin}
              max={intervalMax}
              value={intervalS}
              onChange={onIntervalChange}
            />
          </motion.div>
        )}
      </AnimatePresence>
    </Card>
  )
}

function IntervalEditor({ min, max, value, onChange }: {
  min: number; max: number; value: number; onChange: (v: number) => void
}) {
  const [draft, setDraft] = useState(value)
  const clamped = Math.max(min, Math.min(max, draft))
  const step = min < 1 ? 0.1 : min < 3 ? 0.5 : 1
  const presets = min <= 3 ? [3, 5, 10, 30, 60] : [5, 10, 15, 30, 60]

  return (
    <div className="mt-2 pt-2 border-t border-border/50">
      <div className="text-[10px] text-muted mb-1.5">
        轮询间隔 <span className="text-muted/60">({min}s ~ {max}s)</span>
      </div>
      <div className="flex flex-wrap gap-1 mb-2">
        {presets.map(p => (
          <Button
            key={p}
            size="compact-xs"
            variant={Math.abs(clamped - p) < 0.01 ? 'light' : 'default'}
            onClick={() => { setDraft(p); onChange(p) }}
            className="font-mono"
          >
            {p}s
          </Button>
        ))}
      </div>
      <div className="flex items-center gap-2">
        <Slider
          size="xs"
          min={min} max={max} step={step}
          value={clamped}
          onChange={v => { setDraft(v); onChange(v) }}
          label={null}
          className="flex-1"
        />
        <span className="text-[10px] font-mono text-foreground w-8 text-right">
          {clamped < 1 ? clamped.toFixed(1) : clamped.toFixed(0)}s
        </span>
      </div>
    </div>
  )
}
