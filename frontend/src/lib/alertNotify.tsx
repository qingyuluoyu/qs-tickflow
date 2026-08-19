// 监控告警通知 — 统一走 @mantine/notifications (替代原 components/AlertToast.tsx)
// 业务逻辑保持不变: 开关/maxVisible 上限(超出丢最旧)/整批一次提示音+语音播报。
// 渲染层换成 notifications.show() 自定义内容; 进出动画由 Mantine Notifications 接管。
import { notifications } from '@mantine/notifications'
import { Bell, TrendingUp, TrendingDown, X } from 'lucide-react'
import type { AlertEvent } from '@/lib/api'
import { fmtPct, fmtPrice } from '@/lib/format'
import { cnSignal } from '@/lib/signals'
import { cn } from '@/lib/cn'
import { playNotificationSound } from '@/lib/notificationSound'
import { speakAlerts } from '@/lib/voiceBroadcast'
import { usePreferences } from '@/lib/useSharedQueries'
import { strategyEventMeta, strategyName } from '@/lib/strategyMonitorEvents'
import { accountStorage } from '@/lib/storage'

/** 通知渠道分发 — 所有副作用渠道在此汇合, 新增渠道只改这里 */
function dispatchSideEffects(alerts: AlertEvent[]) {
  playNotificationSound()        // 提示音 (Web Audio 合成)
  speakAlerts(alerts)            // 语音播报 (speechSynthesis, 各自独立开关)
}

// ===== 全局状态 (模块级, 沿用原 AlertToast.tsx 模式) =====
type Item = { id: string; alert: AlertEvent }
let _id = 0
let _queue: Item[] = []
const AUTO_DISMISS = 5000      // 5 秒自动消失

/** 从 localStorage 读取配置 */
function getEnabled(): boolean {
  try {
    const v = accountStorage.getItem('alert_toast_enabled')
    return v === null ? true : v === '1'   // 默认开启
  } catch { return true }
}

function getMaxVisible(): number {
  try {
    const v = parseInt(accountStorage.getItem('alert_toast_max') || '', 10)
    return v >= 1 && v <= 10 ? v : 3       // 默认 3, 范围 1-10
  } catch { return 3 }
}

/** 通知外部配置变更后刷新 (设置页改了配置后调用): 按新上限裁剪当前弹窗 */
export function refreshAlertToastConfig() {
  _trim()
}

/** 超出 maxVisible 时丢弃最旧的 */
function _trim() {
  const maxVisible = getMaxVisible()
  if (_queue.length > maxVisible) {
    const dropped = _queue.slice(0, _queue.length - maxVisible)
    _queue = _queue.slice(-maxVisible)
    for (const item of dropped) notifications.hide(item.id)
  }
}

/** 推入单条监控告警通知 (兼容入口, 不发声 — 发声由批量入口统一处理) */
export function pushAlertToast(alert: AlertEvent) {
  pushAlertToasts([alert])
}

/**
 * 批量推入监控告警通知 (一轮 SSE 多只新命中时调用)。
 * - 每条都弹通知 (受 maxVisible 上限, 超出丢最旧)
 * - 整批只播放一声通知音, 避免短时连续响多声刷屏
 */
export function pushAlertToasts(alerts: AlertEvent[]) {
  if (alerts.length === 0) return
  if (!getEnabled()) return                  // 开关关闭: 不弹
  const newItems = alerts.map(alert => ({ id: `alert-${++_id}`, alert }))
  _queue = [..._queue, ...newItems]
  for (const item of newItems) {
    notifications.show({
      id: item.id,
      autoClose: AUTO_DISMISS,
      withCloseButton: false,
      className: 'cursor-pointer',
      style: { width: 320, padding: 0, overflow: 'hidden' },
      styles: { body: { width: '100%' }, description: { width: '100%' } },
      message: <AlertToastContent alert={item.alert} onClose={() => dismiss(item.id)} />,
      onClose: () => { _queue = _queue.filter(t => t.id !== item.id) },
    })
  }
  _trim()
  dispatchSideEffects(alerts)                  // 副作用分发: 提示音 + 语音 (整批各一次)
}

/** 手动关闭 */
export function dismiss(id: string) {
  _queue = _queue.filter(t => t.id !== id)
  notifications.hide(id)
}

// ===== 点击跳转 (通知挂在 Router 之外, 由 Layout 注册 navigate) =====
type NavigateFn = (path: string) => void
let _navigate: NavigateFn | null = null

/** 由 Layout (Router 内) 注册 react-router 的 navigate, 点击通知跳转监控中心用 */
export function registerAlertNavigator(navigate: NavigateFn) {
  _navigate = navigate
}

// ===== 配色 =====
const SEVERITY_BAR: Record<string, string> = {
  info: 'bg-accent', warn: 'bg-warning', critical: 'bg-danger',
}
const SOURCE_BADGE: Record<string, { label: string; cls: string }> = {
  strategy:  { label: '策略',   cls: 'bg-amber-400/15 text-amber-400' },
  signal:    { label: '信号',   cls: 'bg-accent/15 text-accent' },
  price:     { label: '价格',   cls: 'bg-emerald-400/15 text-emerald-400' },
  market:    { label: '异动',   cls: 'bg-purple-500/15 text-purple-400' },
  sector:    { label: '板块',   cls: 'bg-cyan-500/15 text-cyan-700 dark:text-cyan-300' },
  pool_entry: { label: '进入', cls: 'bg-emerald-400/15 text-emerald-400' },
  pool_exit:   { label: '移出', cls: 'bg-warning/15 text-warning' },
  buy_signal: { label: '买入', cls: 'bg-danger/15 text-danger' },
  sell_signal: { label: '卖出', cls: 'bg-bear/15 text-bear' },
  new_entry: { label: '进入', cls: 'bg-emerald-400/15 text-emerald-400' },
  dropped:   { label: '移出', cls: 'bg-warning/15 text-warning' },
}

// ===== 通知内容 (原 AlertToast 卡片, 去掉 framer-motion 包装) =====
function AlertToastContent({ alert: ev, onClose }: { alert: AlertEvent; onClose: () => void }) {
  const { data: prefs } = usePreferences()
  const extFields = prefs?.monitor_ext_fields ?? {
    concept: { field: 'ext_gn_ths.所属概念' },
    industry: { field: 'ext_hy_ths.所属同花顺行业' },
  }

  // 点击通知 → 跳转监控中心 + 关闭当前通知
  const handleClick = () => {
    onClose()
    _navigate?.('/monitor')
  }

  const sev = SEVERITY_BAR[ev.severity ?? 'info'] ?? SEVERITY_BAR.info
  const badgeKey = (ev.source === 'strategy' && ev.type) ? ev.type : ev.source
  const badge = SOURCE_BADGE[badgeKey] ?? { label: badgeKey, cls: 'bg-elevated text-muted' }
  const pct = ev.change_pct ?? 0
  const isStrategy = ev.source === 'strategy'
  const sname = isStrategy ? strategyName(ev.message ?? '') : ''
  const eventMeta = strategyEventMeta(ev.type)

  return (
    <div
      onClick={handleClick}
      role="button"
      tabIndex={0}
      aria-label={`查看监控通知${ev.name ? ` ${ev.name}` : ''}${ev.symbol ? ` ${ev.symbol}` : ''}`}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          handleClick()
        }
      }}
      className="relative overflow-hidden pl-3 pr-2 py-2.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/60"
    >
      {/* 左侧色条 */}
      <div className={cn('absolute left-0 top-0 h-full w-0.5', sev)} />

      {/* 顶行: 分类标签 + 代码/名称 + 涨跌幅 + 关闭 */}
      <div className="flex items-center gap-2">
        <span className={cn('shrink-0 rounded px-1 py-px text-[9px] font-medium', badge.cls)}>
          {badge.label}
        </span>
        {ev.symbol && <span className="font-mono text-xs font-medium text-foreground shrink-0">{ev.symbol}</span>}
        {ev.name && <span className="text-xs text-secondary truncate flex-1">{ev.name}</span>}
        {ev.change_pct != null && (
          <span className={cn('inline-flex items-center gap-0.5 text-[10px] font-mono font-medium shrink-0', pct >= 0 ? 'text-danger' : 'text-bear')}>
            {pct >= 0 ? <TrendingUp className="h-2.5 w-2.5" /> : <TrendingDown className="h-2.5 w-2.5" />}
            {fmtPct(pct)}
          </span>
        )}
        <button aria-label="关闭通知" onClick={(e) => { e.stopPropagation(); onClose() }} className="shrink-0 p-0.5 rounded text-muted/50 hover:text-foreground hover:bg-elevated transition-colors cursor-pointer">
          <X className="h-3 w-3" />
        </button>
      </div>

      {/* 底行: 策略类型走新格式, 其他走旧格式 */}
      {isStrategy ? (
        <>
          {ev.symbol ? (
            <div className="mt-1 flex min-w-0 items-center gap-1.5 pl-0.5">
              <Bell className={cn('h-3 w-3 shrink-0', sev.replace('bg-', 'text-'))} />
              <span className={cn('shrink-0 text-[11px] font-medium', eventMeta.className)}>
                {eventMeta.action}
              </span>
              {sname
                ? <span className="truncate text-[11px] font-medium text-amber-400">「{sname}」</span>
                : ev.message && <span className="truncate text-[10px] text-muted">{ev.message}</span>}
              <span className="flex-1" />
              {ev.price != null && <span className="text-[10px] font-mono text-muted shrink-0">{fmtPrice(ev.price)}</span>}
            </div>
          ) : (
            <div className="mt-1 flex min-w-0 items-center gap-1.5 pl-0.5">
              <Bell className={cn('h-3 w-3 shrink-0', sev.replace('bg-', 'text-'))} />
              <span className="truncate text-[11px] text-foreground/70">{ev.message}</span>
            </div>
          )}
          {ev.signals && ev.signals.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-1 pl-0.5">
              {ev.signals.map(signal => (
                <span key={signal} className="rounded bg-accent/8 px-1 py-px text-[9px] text-accent/80">{cnSignal(signal)}</span>
              ))}
            </div>
          )}
        </>
      ) : (
        <div className="mt-1 flex items-center gap-1.5 pl-0.5">
          <Bell className={cn('h-3 w-3 shrink-0', sev.replace('bg-', 'text-'))} />
          {/* message 已含「条件摘要 · 现价 · 涨跌幅」(后端生成), 直接展示避免重复 */}
          {ev.message && <span className="text-[11px] text-foreground/70 truncate flex-1">{ev.message}</span>}
        </div>
      )}

      {/* 行业/概念标签 (后端 SSE 推送时已富化, 字段配置来自监控中心全局设置) */}
      {(() => {
        const tags: { text: string; cls: string }[] = []
        for (const [isIndustry, item] of [[true, extFields.industry], [false, extFields.concept]] as const) {
          if (!item?.field) continue
          const key = item.field.replace('.', '__')
          const v = (ev as Record<string, unknown>)[key]
          if (v == null) continue
          let parts = String(v).split(/[、,，;；-]/).map(s => s.trim()).filter(Boolean)
          const mt = item.maxTags ?? 0
          if (mt > 0) parts = parts.slice(0, mt)
          const hi = item.hiddenIndices
          if (hi?.length) parts = parts.filter((_, i) => !hi.includes(i))
          for (const t of parts) {
            tags.push({ text: t, cls: isIndustry ? 'bg-sky-500/10 text-sky-400' : 'bg-orange-500/10 text-orange-400' })
          }
        }
        if (!tags.length) return null
        return (
          <div className="mt-1 flex flex-wrap items-center gap-1 pl-0.5">
            {tags.map((t, i) => (
              <span key={i} className={cn('rounded px-1 py-px text-[9px] leading-tight', t.cls)}>{t.text}</span>
            ))}
          </div>
        )
      })()}
    </div>
  )
}
