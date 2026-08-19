import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Popover } from '@mantine/core'
import { HelpCircle } from 'lucide-react'
import { api } from '@/lib/api'
import { toast } from '@/lib/notify'

/** 单方向(涨停/跌停)的修正明细块 */
function SealedDirBlock({ title, color, counts, rawTotal }: {
  title: string
  color: 'bull' | 'bear'
  counts?: { real: number; fake: number; pending: number }
  rawTotal?: number
}) {
  const real = counts?.real ?? 0
  const fake = counts?.fake ?? 0
  // pending 从原始总数推算(后端 pending 含另一方向票, 不可用)
  const pending = Math.max(0, (rawTotal ?? 0) - real - fake)
  const original = rawTotal ?? (real + fake + pending)
  const fixed = real + pending
  return (
    <div className="mb-2 last:mb-0">
      <div className={`flex items-center justify-between px-1 py-0.5 rounded bg-${color}/5 mb-1`}>
        <span className={`text-[10px] font-medium text-${color}`}>{title}</span>
        <span className="tabular-nums text-[10px]">
          <span className="text-muted line-through">{original}</span>
          <span className="text-muted/50 mx-1">→</span>
          <span className={`font-bold text-${color}`}>{fixed}</span>
        </span>
      </div>
      <div className="flex gap-3 px-1 text-[10px]">
        <span className={`flex items-center gap-0.5 text-${color}`}><span className={`h-1 w-1 rounded-full bg-${color}`} />真封 {real}</span>
        <span className="flex items-center gap-0.5 text-yellow-500"><span className="h-1 w-1 rounded-full bg-yellow-500" />假 {fake}</span>
        {pending > 0 && (
          <span className="flex items-center gap-0.5 text-muted"><span className="h-1 w-1 rounded-full bg-muted" />待 {pending}</span>
        )}
      </div>
    </div>
  )
}

/** 修正/降级 标识 + 问号弹窗(连板梯队/看板共用)
 *  Mantine Popover: 自动定位(flip/shift 防溢出)、点击外部/ESC 关闭、portal 渲染 */
export function SealedBadge({ degraded, hasDepth, isHistorical, sealedReady, sealedCountsUp, sealedCountsDown, rawUp, rawDown, invalidateKeys = ['limit-ladder'] }: {
  degraded: boolean
  hasDepth: boolean
  isHistorical: boolean
  sealedReady: boolean | undefined
  sealedCountsUp?: { real: number; fake: number; pending: number }
  sealedCountsDown?: { real: number; fake: number; pending: number }
  rawUp?: number
  rawDown?: number
  /** 修正后要刷新的 queryKey 前缀(默认连板梯队) */
  invalidateKeys?: string[]
}) {
  const [showHint, setShowHint] = useState(false)
  const navigate = useNavigate()
  const qc = useQueryClient()
  const runFix = useMutation({
    mutationFn: () => api.runLimitLadderFix(),
    onSuccess: (data) => {
      toast(data.msg, data.ok ? 'success' : 'error')
      if (data.ok) invalidateKeys.forEach(k => qc.invalidateQueries({ queryKey: [k] }))
    },
    onError: () => toast('修正请求失败', 'error'),
  })

  // 组装原因文案(仅降级时用)
  const reasons: string[] = []
  if (!hasDepth) reasons.push('当前套餐无五档盘口能力(需 Pro+),涨停判定基于收盘价,可能含假涨停')
  if (isHistorical) reasons.push('历史日期的盘口快照不可获取,无法判定真假板')
  if (hasDepth && !isHistorical && !sealedReady) reasons.push('盘中 sealed 数据尚未就绪,收盘后自动恢复')

  const label = degraded ? '降级' : '修正'

  return (
    <Popover
      opened={showHint}
      onChange={setShowHint}
      position="bottom-start"
      width={256}
      withinPortal
      shadow="xl"
      transitionProps={{ duration: 150 }}
      classNames={{ dropdown: 'bg-surface border border-border rounded-md p-3 text-[11px] text-secondary leading-relaxed' }}
    >
      <Popover.Target>
        <button
          onClick={() => setShowHint(v => !v)}
          className="group inline-flex items-center gap-1 h-5 px-2 rounded-full bg-yellow-500/10 border border-yellow-500/30 cursor-help transition-all hover:bg-yellow-500/20 hover:border-yellow-500/50"
        >
          <span className="h-1.5 w-1.5 rounded-full bg-yellow-500" />
          <span className="text-[10px] font-medium text-yellow-600 dark:text-yellow-500 leading-none">{label}</span>
          <HelpCircle className="h-3 w-3 text-yellow-500/70 group-hover:text-yellow-500 transition-colors" />
        </button>
      </Popover.Target>
      <Popover.Dropdown>
        {degraded ? (
          <>
            <div className="font-medium text-foreground mb-1.5">真假涨停判定降级</div>
            {reasons.map((r, i) => (
              <div key={i} className="flex gap-1 mb-1">
                <span className="text-yellow-500 shrink-0">·</span>
                <span>{r}</span>
              </div>
            ))}
            <div className="mt-1.5 pt-1.5 border-t border-border text-muted">
              真假板判定依赖五档盘口实时快照(卖一/买一量)。Pro+ 套餐的当天数据在收盘后自动恢复。
            </div>
          </>
        ) : (
          <>
            <div className="font-medium text-foreground mb-1.5">五档盘口修正结果</div>
            <SealedDirBlock title="涨停" color="bull" counts={sealedCountsUp} rawTotal={rawUp} />
            <SealedDirBlock title="跌停" color="bear" counts={sealedCountsDown} rawTotal={rawDown} />
            <div className="mt-1.5 pt-1.5 border-t border-border text-muted">
              真封板显示封单量,假涨停/假跌停已归入炸板/翘板视图。{sealedReady && '数据为盘中快照,收盘后自动定版。'}
            </div>
          </>
        )}
        <div className="mt-2 flex gap-1.5">
          {hasDepth && !isHistorical && (
            <button
              onClick={() => { runFix.mutate(); setShowHint(false) }}
              disabled={runFix.isPending}
              className="flex-1 px-2 py-1.5 rounded text-[11px] bg-accent/15 text-accent hover:bg-accent/25 transition-colors text-center disabled:opacity-50"
            >
              {runFix.isPending ? '修正中…' : '立即修正'}
            </button>
          )}
          <button
            onClick={() => { setShowHint(false); navigate('/settings?tab=monitoring&highlight=depth-fix') }}
            className={`${hasDepth && !isHistorical ? '' : 'w-full'} px-2 py-1.5 rounded text-[11px] bg-elevated text-secondary hover:text-foreground transition-colors text-center`}
          >
            去设置 →
          </button>
        </div>
      </Popover.Dropdown>
    </Popover>
  )
}
