import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Play, Square, TrendingDown } from 'lucide-react'
import { Button, NumberInput, Progress, Select, Table } from '@mantine/core'
import { api, type StrategyDetail } from '@/lib/api'
import { fmtPct } from '@/lib/format'
import { EmptyState } from '@/components/EmptyState'
import { DatePicker } from '@/components/DatePicker'
import {
  startWalkForward,
  stopWalkForward,
  clearWalkForward,
  tryReconnectWalkForward,
  useWalkForwardTask,
} from '@/lib/walkforwardTask'
import { buildDefaultOverrides } from '@/lib/strategyOverrides'
import {
  OBJECTIVES,
  GRID_MAX_COMBINATIONS,
  useParamSweep,
  StrategySelect,
  SweepParamList,
  CombosHint,
} from './components/paramSweep'

const TODAY = new Date().toISOString().slice(0, 10)
const THREE_YEARS_AGO = new Date(Date.now() - 3 * 365 * 864e5).toISOString().slice(0, 10)

// 涨跌语义色 (A股: 红涨 bull / 绿跌 bear); 负面结论用 danger
const BULL = 'hsl(var(--bull))'
const BEAR = 'hsl(var(--bear))'
const DANGER = 'hsl(var(--danger))'

function Stat({ label, value, hint, color }: { label: string; value: string; hint?: string; color?: string }) {
  return (
    <div className="rounded-input border border-border bg-elevated/40 p-2.5">
      <div className="text-[11px] text-secondary">{label}</div>
      <div className="mt-0.5 text-sm font-semibold" style={color ? { color } : undefined}>{value}</div>
      {hint && <div className="mt-0.5 text-[10px] text-secondary">{hint}</div>}
    </div>
  )
}

/** 把 NaN/Infinity 归一为 null (走 ?! '—' 的既有降级路径), 防止 toFixed 渲染出 "NaN"。 */
function fin(v: number | null | undefined): number | null {
  return v != null && Number.isFinite(v) ? v : null
}

/** OOS 拼接净值曲线 (逐折复利) — walk-forward 核心产出的极简 SVG 折线。 */
function OosEquityChart({ curve }: { curve: { fold: number; date: string; value: number }[] }) {
  // 过滤非有限值: 零成交折等边界可能产出 NaN/Infinity, 混入会让坐标全 NaN → SVG 空白。
  const vals = curve.map(p => p.value).filter(v => Number.isFinite(v))
  if (!vals.length) return null
  const W = 600, H = 120, pad = 8
  const lo = Math.min(1, ...vals), hi = Math.max(1, ...vals)
  const span = hi - lo || 1
  // 起点补一个 value=1 基准, 让曲线从 1.0 起步
  const pts = [1, ...vals]
  const x = (i: number) => pad + (i / (pts.length - 1 || 1)) * (W - 2 * pad)
  const y = (v: number) => pad + (1 - (v - lo) / span) * (H - 2 * pad)
  const d = pts.map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
  const last = vals[vals.length - 1]
  const up = last >= 1
  return (
    <div>
      <div className="mb-1 text-xs font-medium text-secondary">OOS 拼接净值 (逐折复利)</div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" preserveAspectRatio="none" style={{ height: 120 }}>
        <line x1={pad} y1={y(1)} x2={W - pad} y2={y(1)} stroke="currentColor" strokeWidth="0.5" className="text-border" strokeDasharray="3 3" />
        <path d={d} fill="none" stroke={up ? BULL : BEAR} strokeWidth="1.5" />
      </svg>
      <div className="mt-0.5 text-[10px] text-secondary">终值 {last.toFixed(4)} · {curve.length} 折</div>
    </div>
  )
}

export function StrategyWalkForward() {
  const task = useWalkForwardTask()
  const { data: stratData } = useQuery({ queryKey: ['strategies'], queryFn: () => api.strategyList() })
  const strategies: StrategyDetail[] = stratData?.strategies ?? []

  // 切策略: 有任务在跑时先真正取消 (关 SSE + 后端 cancel + 清 localStorage), 不能静默丢
  const sweep = useParamSweep(strategies, () => {
    if (task?.isPending) stopWalkForward()
    else clearWalkForward()
  })
  const [objective, setObjective] = useState('sortino')
  const [start, setStart] = useState(THREE_YEARS_AGO)
  const [end, setEnd] = useState(TODAY)
  const [mode, setMode] = useState<'position' | 'full'>('position')
  const [trainDays, setTrainDays] = useState('252')
  const [testDays, setTestDays] = useState('63')
  const [stepDays, setStepDays] = useState('63')

  useEffect(() => {
    tryReconnectWalkForward()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const canRun = sweep.strategyId && sweep.combos > 0 && sweep.combos <= GRID_MAX_COMBINATIONS
    && !sweep.gridError
    && Number(trainDays) > 0 && Number(testDays) > 0 && Number(stepDays) > 0 && !task?.isPending

  const onRun = () => {
    if (!canRun) return
    clearWalkForward()
    startWalkForward({
      strategy_id: sweep.strategyId,
      param_grid: sweep.buildGrid(),
      objective,
      train_days: Number(trainDays),
      test_days: Number(testDays),
      step_days: Number(stepDays),
      // 未扫描参数固定为策略当前默认值; overrides 让 basic_filter/信号/风控按当前策略参与,
      // 否则 walk-forward 优化的策略与用户实际回测的不一致 (同 PR #82 优化器修复)。
      params: sweep.selected?.params_defaults,
      overrides: sweep.selected ? buildDefaultOverrides(sweep.selected) : undefined,
      start,
      end,
      mode,
    })
  }

  const result = task?.result
  const progress = task?.progress
  const summary = result?.summary
  // 汇总里的可空数值先归一: 零成交折等边界可能产出 NaN/Infinity,
  // 直接 toFixed 会渲染出 "NaN"; 这里把非有限值转 null, 下游统一走 '—' 降级。
  const compounded = fin(summary?.compounded_oos_return)
  const degradation = fin(summary?.degradation)
  const avgIs = fin(summary?.avg_is_objective)
  const avgOos = fin(summary?.avg_oos_objective)

  return (
    <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(15rem,2fr)_minmax(0,5fr)]">
      {/* ── 配置面板 ── */}
      <div className="space-y-3 rounded-card border border-border bg-surface p-4">
        <div>
          <label className="mb-1.5 block text-xs font-medium text-secondary">策略</label>
          <StrategySelect strategies={strategies} value={sweep.strategyId} onChange={sweep.selectStrategy} />
        </div>

        <div>
          <label className="mb-1.5 block text-xs font-medium text-secondary">优化目标</label>
          <Select
            size="xs"
            value={objective}
            onChange={v => v && setObjective(v)}
            allowDeselect={false}
            data={OBJECTIVES.map(o => ({ value: o.id, label: o.label }))}
          />
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="mb-1.5 block text-xs font-medium text-secondary">起始</label>
            <DatePicker value={start} onChange={setStart} />
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-medium text-secondary">结束</label>
            <DatePicker value={end} onChange={setEnd} />
          </div>
        </div>

        {/* 滚动窗口 */}
        <div className="grid grid-cols-3 gap-1.5">
          <div>
            <label className="mb-1 block text-[11px] text-secondary">训练(天)</label>
            <NumberInput size="xs" min={1} value={trainDays} onChange={v => setTrainDays(String(v))} />
          </div>
          <div>
            <label className="mb-1 block text-[11px] text-secondary">测试(天)</label>
            <NumberInput size="xs" min={1} value={testDays} onChange={v => setTestDays(String(v))} />
          </div>
          <div>
            <label className="mb-1 block text-[11px] text-secondary">步进(天)</label>
            <NumberInput size="xs" min={1} value={stepDays} onChange={v => setStepDays(String(v))} />
          </div>
        </div>

        <div>
          <label className="mb-1.5 block text-xs font-medium text-secondary">模式</label>
          <Select
            size="xs"
            value={mode}
            onChange={v => v && setMode(v as 'position' | 'full')}
            allowDeselect={false}
            data={[
              { value: 'position', label: '组合仓位' },
              { value: 'full', label: '全量独立' },
            ]}
          />
        </div>

        <SweepParamList params={sweep.params} sweeps={sweep.sweeps} updateSweep={sweep.updateSweep} />
        <CombosHint show={!!sweep.strategyId} combos={sweep.combos} gridError={sweep.gridError} />
        <div className="text-[11px] text-secondary">每折跑 {sweep.combos || 0} 组优化 × N 折，耗时较长</div>

        {task?.isPending ? (
          <Button fullWidth size="xs" color="red" leftSection={<Square className="h-3.5 w-3.5" />} onClick={stopWalkForward}>
            停止
          </Button>
        ) : (
          <Button fullWidth size="xs" leftSection={<Play className="h-3.5 w-3.5" />} disabled={!canRun} onClick={onRun}>
            开始步进优化
          </Button>
        )}
      </div>

      {/* ── 结果面板 ── */}
      <div className="min-h-[300px] rounded-card border border-border bg-surface p-4">
        {task?.error && (
          <div className="mb-3 rounded-input border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger">{task.error}</div>
        )}

        {task?.isPending && progress && (
          <div className="mb-4">
            <div className="mb-1 flex justify-between text-xs text-secondary">
              <span>第 {progress.done}/{progress.total} 折</span>
            </div>
            <Progress
              size="sm"
              radius="xl"
              value={progress.total ? (progress.done / progress.total) * 100 : 0}
            />
          </div>
        )}

        {!result && !task?.isPending && (
          <EmptyState
            title="步进优化"
            hint="每折在训练区间网格优化选最优参数，再在紧邻的测试区间做样本外(OOS)验证。样本内漂亮、样本外崩溃即过拟合。"
          />
        )}

        {result && result.n_folds === 0 && (
          <EmptyState title="未产生有效折"
            hint={`计划 ${result.n_planned_folds} 折, 但 ${result.n_skipped} 折因训练区间未优化出参数或 OOS 回测失败被跳过。请检查数据范围或放宽参数网格。`} />
        )}

        {result && summary && result.n_folds > 0 && (
          <div className="space-y-4">
            {/* 汇总卡 — 可空数值已在上游用 fin() 归一, NaN/Infinity 走 '—' 而非渲染 "NaN" */}
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Stat label="OOS 复利收益" value={fmtPct(compounded)}
                color={compounded != null ? (compounded >= 0 ? BULL : BEAR) : undefined} />
              <Stat label="IS→OOS 退化"
                value={degradation != null ? degradation.toFixed(3) : '—'}
                hint={degradation != null && degradation > 0 ? '样本外退化=过拟合' : '样本外未退化'}
                color={degradation != null ? (degradation > 0 ? DANGER : BEAR) : undefined} />
              <Stat label="一致性" value={fmtPct(summary.consistency)} hint="OOS 盈利折占比" />
              <Stat label="有效折" value={result.n_skipped > 0 ? `${result.n_folds} (跳过${result.n_skipped})` : String(result.n_folds)} />
            </div>

            <div className="text-xs text-secondary">
              IS 目标均值 {avgIs != null ? avgIs.toFixed(3) : '—'} · OOS 目标均值 {avgOos != null ? avgOos.toFixed(3) : '—'} · 耗时 {(result.elapsed_ms / 1000).toFixed(1)}s
            </div>

            {/* OOS 拼接净值曲线 (walk-forward 核心产出) */}
            <OosEquityChart curve={summary.oos_equity_curve} />

            {/* 每折表 */}
            <div className="overflow-x-auto">
              <Table verticalSpacing={4} horizontalSpacing="xs" highlightOnHover className="text-xs">
                <Table.Thead>
                  <Table.Tr className="text-secondary">
                    <Table.Th className="text-left font-normal">折</Table.Th>
                    <Table.Th className="text-left font-normal">测试区间</Table.Th>
                    <Table.Th className="text-left font-normal">最优参数</Table.Th>
                    <Table.Th className="text-right font-normal">IS 目标</Table.Th>
                    <Table.Th className="text-right font-normal">OOS 目标</Table.Th>
                    <Table.Th className="text-right font-normal">OOS 收益</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {result.folds.map(f => {
                    const is = f.is_score
                    const oos = f.oos_objective
                    // 用后端方向感知的退化标志 (min 类目标 oos<is 未必是退化)
                    const degraded = f.oos_degraded === true
                    return (
                      <Table.Tr key={f.index}>
                        <Table.Td className="text-secondary">{f.index + 1}</Table.Td>
                        <Table.Td className="text-secondary">{f.test_start} ~ {f.test_end}</Table.Td>
                        <Table.Td className="text-foreground">
                          {f.best_params ? Object.entries(f.best_params).map(([k, v]) => `${k}=${v}`).join(', ') : '—'}
                        </Table.Td>
                        <Table.Td className="text-right">{is != null ? is.toFixed(3) : '—'}</Table.Td>
                        <Table.Td className="text-right" style={degraded ? { color: DANGER } : undefined}>
                          {oos != null ? oos.toFixed(3) : '—'}
                        </Table.Td>
                        <Table.Td className="text-right">
                          {f.oos_stats?.total_return != null ? fmtPct(f.oos_stats.total_return) : '—'}
                        </Table.Td>
                      </Table.Tr>
                    )
                  })}
                </Table.Tbody>
              </Table>
            </div>

            {degradation != null && degradation > 0 && (
              <div className="flex items-center gap-1.5 rounded-input border border-danger/30 bg-danger/5 px-3 py-2 text-[11px] text-danger">
                <TrendingDown className="h-3.5 w-3.5" />
                样本外目标较样本内退化 {degradation.toFixed(3)}，提示参数可能过拟合训练区间。
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
