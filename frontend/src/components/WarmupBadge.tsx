/**
 * 回测预热期徽标 — 点击弹出说明气泡。
 *
 * 解释「回测开头几个月没有交易」这一高频疑问: 技术指标需要历史数据预热,
 * 系统会自动在回测起点之前多取约 120 天 (≈4 个月) 数据; 若本地数据恰好从
 * 起点才开始, 开头几个月指标算不出、信号不触发, 属正常现象。
 *
 * 实现要点:
 *   - 点击触发 (非 hover), 移动端友好
 *   - Mantine Popover: portal 渲染绕开父容器 overflow 裁剪, 自动定位防溢出,
 *     点击外部 / ESC 关闭均为内置行为
 */
import { useState } from 'react'
import { Popover } from '@mantine/core'
import { Info } from 'lucide-react'

export function WarmupBadge() {
  const [open, setOpen] = useState(false)

  return (
    <Popover
      opened={open}
      onChange={setOpen}
      position="bottom-start"
      width={272}
      offset={8}
      withinPortal
      withArrow
      shadow="xl"
      transitionProps={{ duration: 150 }}
      classNames={{
        dropdown: 'rounded-btn border border-border bg-surface p-3 text-[11px] leading-relaxed text-secondary shadow-2xl',
        arrow: 'border-l border-t border-border bg-surface',
      }}
    >
      <Popover.Target>
        <button
          type="button"
          onClick={() => setOpen(o => !o)}
          className="inline-flex items-center gap-0.5 rounded-full px-1.5 text-[10px] text-amber-500/70 transition-colors hover:bg-amber-400/10 hover:text-amber-500"
          title="为什么开头可能没交易?"
        >
          <Info className="h-3 w-3" strokeWidth={1.5} />
          预热 ≥120 天
        </button>
      </Popover.Target>
      <Popover.Dropdown>
        <div className="mb-1.5 font-medium text-foreground">为什么开头几个月可能没有交易?</div>
        <p className="text-muted">
          技术指标 (MA / MACD / RSI 等) 需要历史数据才能算出。系统会自动在回测起点之前多取约
          <span className="font-medium text-amber-300"> 120 天 (≈4 个月)</span> 数据做预热。
        </p>
        <p className="mt-1.5 text-muted">
          若本地数据恰好从回测起点才开始, 开头几个月指标算不出、信号不触发,
          <span className="text-secondary"> 属正常现象, 不是 bug</span>。等数据攒够后自然开始产生交易。
        </p>
        <div className="mt-2 border-t border-border/60 pt-2 text-muted">
          <span className="text-secondary">解决:</span> 把历史数据补到回测起点之前至少半年, 或把起点往后挪。
        </div>
      </Popover.Dropdown>
    </Popover>
  )
}
