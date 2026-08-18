/**
 * 集中管理所有 localStorage 持久化。
 *
 * - key 在此注册，各页面只通过 storage.xxx.get/set 调用。
 * - 类型安全，不再散落 try/catch。
 */

// All values managed by this module are user-facing workspace state. Keep a
// process-local account scope so a browser account switch cannot fall back to
// another account's localStorage values while the backend is being refreshed.
// The scope is deliberately not persisted separately: AuthGate is the source
// of truth and clears it before mounting a different account.
let activeUserScope = 'anonymous'

export function setStorageUser(userId: string | null): void {
  activeUserScope = userId ? encodeURIComponent(userId) : 'anonymous'
}

function scopedKey(key: string): string {
  return `tf-user:${activeUserScope}:${key}`
}

/**
 * Namespaced browser storage for small per-account preferences that predate
 * the typed `storage` registry.  Keeping the namespace in one place prevents
 * a direct localStorage call from leaking a previous account's UI state when
 * the user switches accounts in the same tab.
 */
function scopedBrowserStorage(target: Storage | null) {
  return {
    getItem(key: string): string | null {
      try { return target?.getItem(scopedKey(key)) ?? null } catch { return null }
    },
    setItem(key: string, value: string): void {
      try { target?.setItem(scopedKey(key), value) } catch { /* ignore */ }
    },
    removeItem(key: string): void {
      try { target?.removeItem(scopedKey(key)) } catch { /* ignore */ }
    },
  } as const
}

function browserStorage(name: 'localStorage' | 'sessionStorage'): Storage | null {
  try {
    if (typeof globalThis === 'undefined') return null
    return (globalThis as typeof globalThis & Record<string, unknown>)[name] as Storage | undefined ?? null
  } catch {
    return null
  }
}

const browserLocalStorage = browserStorage('localStorage')
export const accountStorage = scopedBrowserStorage(browserLocalStorage)
export const accountSessionStorage = scopedBrowserStorage(browserStorage('sessionStorage'))

function kv<T>(key: string, options?: { explicitScope?: string }) {
  const resolveKey = () => options?.explicitScope
    ? `tf-user:${options.explicitScope}:${key}`
    : scopedKey(key)
  return {
    get(fallback: T): T {
      try {
        const raw = browserLocalStorage?.getItem(resolveKey()) ?? null
        if (raw !== null) return JSON.parse(raw) as T
      } catch { /* ignore */ }
      return fallback
    },
    set(val: T) {
      try {
        browserLocalStorage?.setItem(resolveKey(), JSON.stringify(val))
      } catch { /* ignore */ }
    },
  }
}

/** User-interface preferences that must not bleed between local accounts. */
export function storageForUser(userId: string) {
  const userKey = <T,>(key: string) => kv<T>(key, { explicitScope: encodeURIComponent(userId) })
  return {
    // Keep these names stable for existing account-scoped callers.
    watchlistColumns:     userKey<unknown[]>('watchlist_columns'),
    watchlistView:        userKey<string>('watchlist_view'),
    watchlistCandle:      userKey<boolean>('watchlist_showCandle'),
    watchlistIntraday:    userKey<boolean>('watchlist_showIntraday'),
    watchlistBoardFilter: userKey<string[]>('watchlist_boardFilter'),
    strategyPool:         userKey<string[]>('strategy_pool'),
  } as const
}

export const storage = {
  /** 查询轮询 / SSE 配置 */
  queryConfig:          kv<unknown>('tf-stocks-query-config'),

  /** 策略池 (screener) */
  strategyPool:         kv<string[]>('strategy-pool'),

  /** 自选列表列配置 */
  watchlistColumns:     kv<unknown[]>('watchlist_columns'),

  /** 个股日K信息条指标配置 */
  stockInfoBarFields:   kv<unknown[]>('stock_info_bar_fields'),

  /** 个股日K成交量对比设置 */
  stockVolumeCompare:   kv<{ enabled: boolean; days: number }>('stock_volume_compare'),

  /** 策略结果列表列配置 */
  screenerResultColumns: kv<unknown[]>('screener_result_columns'),

  /** 自选列表视图模式 table | card */
  watchlistView:        kv<string>('watchlist_view'),

  /** 自选列表日K蜡烛图显示状态 */
  watchlistCandle:      kv<boolean>('watchlist_showCandle'),

  /** 自选列表分时图显示状态 */
  watchlistIntraday:    kv<boolean>('watchlist_showIntraday'),

  /** 策略结果列表日K蜡烛图显示状态 */
  screenerCandle:       kv<boolean>('screener_showCandle'),

  /** 策略结果列表分时图显示状态 */
  screenerIntraday:     kv<boolean>('screener_showIntraday'),

  /** 自选列表板块筛选 */
  watchlistBoardFilter: kv<string[]>('watchlist_boardFilter'),

  /** Screener 卡片尺寸 */
  screenerCardSize:     kv<string>('screener-card-size'),

  /** 连板梯队板块筛选 */
  limitLadderBoard:     kv<string[]>('limit-ladder-board-filter'),

  /** 连板梯队 ext 字段配置 */
  limitLadderExtFields: kv<Record<string, any>>('limit-ladder-ext-fields'),

  /** 连板梯队 概念/行业 显示开关 */
  limitLadderShowExt:   kv<{ concept: boolean; industry: boolean }>('limit-ladder-show-ext'),

  /** 连板梯队 涨停/跌停 切换方向 */
  limitLadderDirection: kv<'up' | 'down'>('limit-ladder-direction'),

  /** 连板梯队 封单显示模式: vol=按成交量(手), amount=按金额(元) */
  limitLadderSealMode:  kv<'vol' | 'amount'>('limit-ladder-seal-mode'),

  /** 策略创建草稿（新建专用） */
  strategyDraft: kv<{ name: string; description: string; direction: string; style?: string; rules: string; code: string; step: number; strategyId: string; source?: 'ai' | 'custom' } | null>('strategy-draft'),

  /** 策略修改草稿（AI修改专用，不影响创建按钮） */
  strategyModify: kv<{ name: string; description: string; direction: string; style?: string; rules: string; code: string; step: number; strategyId: string; source?: 'ai' | 'custom' } | null>('strategy-modify'),

  /** 策略构建器草稿（旧版兼容，逐渐废弃） */
  strategyBuilderDraft: kv<{ name: string; description: string; direction: string; style?: string; rules: string; code: string; step: number; strategyId: string; source?: 'ai' | 'custom' } | null>('strategy-builder-draft'),

  /** 已保存策略的原始规则（策略ID → 规则文本） */
  strategyRules: kv<Record<string, string>>('strategy-rules'),

  /** 策略回测快捷区间按钮配置 */
  strategyBacktestQuickRanges: kv<unknown>('strategy-backtest-quick-ranges'),

  /** 策略回测最后一次成功结果和参数 */
  strategyBacktestLast: kv<{
    selectedStrategy: string | null
    symbols: string
    assetType?: 'stock' | 'etf'
    start: string
    end: string
    matching: 'close_t' | 'open_t+1'
    entryFill: 'close_t' | 'open_t+1'
    exitFill: 'close_t' | 'open_t+1' | 'signal_next_minute'
    fees: string
    stampTax?: string
    slippage: string
    maxPositions: string
    maxExposure: string
    initialCapital: string
    positionSizing: 'equal' | 'score_weight'
    mode: 'position' | 'full'
    holdingDays: string
    minuteFill?: boolean
    params?: Record<string, any>
    overrides?: Record<string, any>
    strategyConfigSignature?: string
    result: any
  } | null>('strategy-backtest-last'),

  /** 概念分析页面字段配置 */
  conceptAnalysisConfig: kv<Record<string, any>>('concept-analysis-config'),

  /** 行业分析页面字段配置 */
  industryAnalysisConfig: kv<Record<string, any>>('industry-analysis-config'),

  /** 数据页画像卡片显隐 (卡片key → 是否显示) */
  dataCardVisible: kv<Record<string, boolean>>('data-card-visible'),
  /** 数据页画像卡片顺序 (卡片key 数组, 长度=卡片总数) */
  dataCardOrder: kv<string[]>('data-card-order'),
} as const
