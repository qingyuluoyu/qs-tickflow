import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Play, Square, Trophy } from 'lucide-react'
import { Badge, Button, Progress, Select, Table } from '@mantine/core'
import { api, type StrategyDetail } from '@/lib/api'
import { fmtPct } from '@/lib/format'
import { EmptyState } from '@/components/EmptyState'
import { DatePicker } from '@/components/DatePicker'
import {
  startOptimize,
  stopOptimize,
  clearOptimize,
  tryReconnectOptimize,
  useOptimizerTask,
} from '@/lib/optimizerTask'
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
const ONE_YEAR_AGO = new Date(Date.now() - 365 * 864e5).toISOString().slice(0, 10)

export function StrategyOptimizer() {
  const task = useOptimizerTask()
  const { data: stratData } = useQuery({ queryKey: ['strategies'], queryFn: () => api.strategyList() })
  const strategies: StrategyDetail[] = stratData?.strategies ?? []

  // 切策略: 有任务在跑时先真正取消 (关 SSE + 后端 cancel + 清 localStorage), 不能静默丢
  const sweep = useParamSweep(strategies, () => {
    if (task?.isPending) stopOptimize()
    else clearOptimize()
  })
  const [objective, setObjective] = useState('sortino')
  const [start, setStart] = useState(ONE_YEAR_AGO)
  const [end, setEnd] = useState(TODAY)
  const [mode, setMode] = useState<'position' | 'full'>('position')

  // 刷新/切页后: 恢复未完成的优化任务
  useEffect(() => {
    tryReconnectOptimize()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const canRun = sweep.strategyId && sweep.combos > 0 && sweep.combos <= GRID_MAX_COMBINATIONS
    && !sweep.gridError && !task?.isPending

  const onRun = () => {
    if (!canRun) return
    clearOptimize()
    startOptimize({
      strategy_id: sweep.strategyId,
      param_grid: sweep.buildGrid(),
      objective,
      // 未扫描参数固定为策略当前默认值; overrides 让 basic_filter/信号/风控按当前策略参与,
      // 保证优化的就是用户实际回测的策略 (而非被剥离配置的裸策略)。
      params: sweep.selected?.params_defaults,
      overrides: sweep.selected ? buildDefaultOverrides(sweep.selected) : undefined,
      start,
      end,
      mode,
    })
  }

  const result = task?.result
  const progress = task?.progress

  return (
    <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(15rem,2fr)_minmax(0,5fr)] h-full min-h-0 overflow-hidden">
      {/* ── 配置面板 ── */}
      <div className="space-y-3 rounded-card border border-border bg-surface p-4 overflow-y-auto min-h-0">
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

        {task?.isPending ? (
          <Button fullWidth size="xs" color="red" leftSection={<Square className="h-3.5 w-3.5" />} onClick={stopOptimize}>
            停止
          </Button>
        ) : (
          <Button fullWidth size="xs" leftSection={<Play className="h-3.5 w-3.5" />} disabled={!canRun} onClick={onRun}>
            开始优化
          </Button>
        )}
      </div>

      {/* ── 结果面板 ── */}
      <div className="min-h-0 rounded-card border border-border bg-surface p-4 overflow-y-auto">
        {task?.error && (
          <div className="mb-3 rounded-input border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger">{task.error}</div>
        )}

        {task?.isPending && progress && (
          <div className="mb-4">
            <div className="mb-1 flex justify-between text-xs text-secondary">
              <span>进度 {progress.done}/{progress.total}</span>
              <span>当前最优: {progress.best_score != null ? progress.best_score.toFixed(3) : '—'}</span>
            </div>
            <Progress
              size="sm"
              radius="xl"
              value={progress.total ? (progress.done / progress.total) * 100 : 0}
            />
          </div>
        )}

        {!result && !task?.isPending && (
          <EmptyState title="参数优化" hint="选择策略、勾选要扫描的参数与优化目标；任务会在独立 worker 中复用基础数据并串行执行组合。" />
        )}

        {result && (
          <div className="space-y-4">
            {result.best_params && (
              <div className="rounded-card border border-accent/30 bg-accent/5 p-3">
                <div className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold text-accent">
                  <Trophy className="h-3.5 w-3.5" /> 最优参数 · {result.objective} = {result.best_score}
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(result.best_params).map(([k, v]) => (
                    <Badge key={k} variant="outline" color="gray" size="sm" className="normal-case font-normal">
                      {k}: {String(v)}
                    </Badge>
                  ))}
                </div>
              </div>
            )}

            <div className="text-xs text-secondary">
              {result.n_completed}/{result.n_combinations} 组完成 · 耗时 {(result.elapsed_ms / 1000).toFixed(1)}s
            </div>

            <div className="overflow-x-auto">
              <Table verticalSpacing={4} horizontalSpacing="xs" highlightOnHover className="text-xs">
                <Table.Thead>
                  <Table.Tr className="text-secondary">
                    <Table.Th className="text-left font-normal">#</Table.Th>
                    <Table.Th className="text-left font-normal">参数</Table.Th>
                    <Table.Th className="text-right font-normal">{result.objective}</Table.Th>
                    <Table.Th className="text-right font-normal">夏普</Table.Th>
                    <Table.Th className="text-right font-normal">索提诺</Table.Th>
                    <Table.Th className="text-right font-normal">总收益</Table.Th>
                    <Table.Th className="text-right font-normal">最大回撤</Table.Th>
                    <Table.Th className="text-right font-normal">胜率</Table.Th>
                    <Table.Th className="text-right font-normal">交易数</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {result.results.slice(0, 50).map(r => (
                    <Table.Tr key={r.rank}>
                      <Table.Td className="text-secondary">{r.rank}</Table.Td>
                      <Table.Td>
                        {r.error
                          ? <span className="text-danger">失败: {r.error.slice(0, 40)}</span>
                          : <span className="text-foreground">{Object.entries(r.params).map(([k, v]) => `${k}=${v}`).join(', ')}</span>}
                      </Table.Td>
                      <Table.Td className="text-right font-medium">{r.objective_raw != null ? r.objective_raw.toFixed(3) : '—'}</Table.Td>
                      <Table.Td className="text-right">{r.stats?.sharpe ?? '—'}</Table.Td>
                      <Table.Td className="text-right">{r.stats?.sortino ?? '—'}</Table.Td>
                      <Table.Td className="text-right">{r.stats?.total_return != null ? fmtPct(r.stats.total_return) : '—'}</Table.Td>
                      <Table.Td className="text-right">{r.stats?.max_drawdown != null ? fmtPct(r.stats.max_drawdown) : '—'}</Table.Td>
                      <Table.Td className="text-right">{r.stats?.win_rate != null ? fmtPct(r.stats.win_rate) : '—'}</Table.Td>
                      <Table.Td className="text-right">{r.stats?.n_trades ?? '—'}</Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
              {result.results.length > 50 && (
                <div className="mt-2 text-center text-[11px] text-secondary">
                  仅显示前 50 组 · 共 {result.results.length} 组
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
