import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ActionIcon, Badge, Button, TextInput, Tooltip } from '@mantine/core'
import { AlertCircle, ArrowLeft, ExternalLink, RefreshCw, Search, X } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { Modal } from '@/components/Modal'
import { api, type WatchlistEntry, type WatchlistNewsCategory, type WatchlistNewsItem } from '@/lib/api'
import { QK } from '@/lib/queryKeys'

type Props = {
  opened: boolean
  onClose: () => void
  userId: string
  symbols: WatchlistEntry[]
  initialCategory?: WatchlistNewsCategory
}

const CATEGORIES: Array<{ value: WatchlistNewsCategory; label: string }> = [
  { value: 'announcement', label: 'A股公告' },
  { value: 'public_news', label: '公开新闻' },
  { value: 'today_highlight', label: '今日要点' },
]

function formatTime(value?: string | null): string {
  if (!value) return '时间未知'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

function statusLabel(status: string): string {
  return {
    unavailable: '资讯数据源暂不可用',
    stale: '接口暂时失败，以下为最近一次已缓存资讯',
    invalid: '接口返回字段无法校验',
    empty: '当前自选范围暂无资讯',
  }[status] ?? ''
}

function NewsCard({ item, onSelect }: { item: WatchlistNewsItem; onSelect: () => void }) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className="w-full text-left rounded-lg border border-border/70 bg-elevated/40 px-3 py-2.5 hover:border-accent/50 hover:bg-accent/5 transition-colors"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm font-medium text-foreground leading-5">{item.title}</div>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted">
            {item.symbol && <span className="font-mono text-secondary">{item.name || item.symbol}</span>}
            {item.symbol && <span className="font-mono">{item.symbol}</span>}
            <span>{item.source}</span>
            <span>{formatTime(item.published_at || item.fetched_at)}</span>
          </div>
        </div>
        <ExternalLink className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted" />
      </div>
      {item.summary && <div className="mt-1.5 line-clamp-2 text-xs leading-5 text-secondary">{item.summary}</div>}
    </button>
  )
}

export function WatchlistNewsModal({ opened, onClose, userId, symbols, initialCategory = 'announcement' }: Props) {
  const navigate = useNavigate()
  const [category, setCategory] = useState<WatchlistNewsCategory>(initialCategory)
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)

  useEffect(() => {
    if (!opened) return
    setCategory(initialCategory)
    setSelectedSymbol(null)
    setQuery('')
    setDebouncedQuery('')
    setSelectedId(null)
  }, [opened, initialCategory])

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query.trim()), 250)
    return () => window.clearTimeout(timer)
  }, [query])

  useEffect(() => {
    setSelectedId(null)
  }, [category, selectedSymbol, debouncedQuery])

  const listQuery = useQuery({
    queryKey: QK.watchlistNewsFor(userId, category, selectedSymbol, debouncedQuery),
    queryFn: ({ signal }) => api.watchlistNews(category, {
      symbol: selectedSymbol,
      query: debouncedQuery,
      limit: 50,
      signal,
    }),
    enabled: opened && Boolean(userId),
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  })

  const detailQuery = useQuery({
    queryKey: QK.watchlistNewsDetailFor(userId, category, selectedId ?? ''),
    queryFn: ({ signal }) => api.watchlistNewsDetail(selectedId!, category, signal),
    enabled: opened && Boolean(selectedId),
    staleTime: 60_000,
  })

  const selectedName = useMemo(
    () => symbols.find(item => item.symbol === selectedSymbol)?.name || selectedSymbol,
    [selectedSymbol, symbols],
  )
  const activeItem = detailQuery.data || listQuery.data?.items.find(item => item.id === selectedId)
  const sourceStatus = listQuery.data?.source_status

  const openStock = (item: WatchlistNewsItem) => {
    if (!item.symbol) return
    onClose()
    navigate(`/stock-analysis?symbol=${encodeURIComponent(item.symbol)}&name=${encodeURIComponent(item.name || item.symbol)}`)
  }

  if (!opened) return null

  return (
    <Modal
      onClose={onClose}
      labelledBy="watchlist-news-title"
      panelClassName="w-[94vw] max-w-4xl max-h-[86vh] bg-surface border border-border rounded-card shadow-xl"
    >
      <div className="flex min-h-0 flex-col">
        <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
          <div className="min-w-0">
            <div id="watchlist-news-title" className="text-base font-semibold text-foreground">自选资讯雷达</div>
            <div className="mt-0.5 text-[11px] text-muted">只显示当前账户自选股关联内容</div>
          </div>
          <ActionIcon variant="subtle" size="lg" aria-label="关闭" onClick={onClose}>
            <X className="h-4 w-4" />
          </ActionIcon>
        </div>

        <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-2.5">
          {CATEGORIES.map(item => (
            <Button
              key={item.value}
              variant={category === item.value ? 'filled' : 'subtle'}
              size="compact-sm"
              onClick={() => setCategory(item.value)}
              className={category === item.value ? 'bg-accent text-white' : 'text-secondary'}
            >
              {item.label}
            </Button>
          ))}
          <div className="ml-auto flex min-w-[220px] max-w-full flex-1 items-center gap-2 sm:max-w-xs">
            <TextInput
              value={query}
              onChange={event => setQuery(event.currentTarget.value)}
              placeholder="搜索标题、摘要或来源"
              leftSection={<Search className="h-3.5 w-3.5" />}
              rightSection={query ? <ActionIcon size="sm" variant="subtle" aria-label="清除搜索" onClick={() => setQuery('')}><X className="h-3 w-3" /></ActionIcon> : null}
              classNames={{ input: 'h-8 min-h-0 bg-elevated border-border text-xs' }}
              className="flex-1"
            />
            <Tooltip label="刷新">
              <ActionIcon variant="subtle" size="lg" aria-label="刷新资讯" onClick={() => listQuery.refetch()} disabled={listQuery.isFetching}>
                <RefreshCw className={`h-3.5 w-3.5 ${listQuery.isFetching ? 'animate-spin' : ''}`} />
              </ActionIcon>
            </Tooltip>
          </div>
        </div>

        <div className="flex flex-wrap gap-1.5 border-b border-border px-4 py-2">
          <Button size="compact-xs" variant={selectedSymbol == null ? 'filled' : 'subtle'} onClick={() => setSelectedSymbol(null)} className="text-[11px]">全部自选</Button>
          {symbols.map(item => (
            <Button key={item.symbol} size="compact-xs" variant={selectedSymbol === item.symbol ? 'filled' : 'subtle'} onClick={() => setSelectedSymbol(item.symbol)} className="text-[11px]">
              {item.name || item.symbol}
            </Button>
          ))}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
          {selectedId && (
            <div className="mb-3 flex items-center justify-between gap-2">
              <Button variant="subtle" size="compact-sm" leftSection={<ArrowLeft className="h-3.5 w-3.5" />} onClick={() => setSelectedId(null)}>返回列表</Button>
              {activeItem?.symbol && <Button variant="light" size="compact-sm" rightSection={<ExternalLink className="h-3.5 w-3.5" />} onClick={() => openStock(activeItem)}>打开个股分析</Button>}
            </div>
          )}

          {selectedId ? (
            detailQuery.isLoading ? <div className="py-12 text-center text-sm text-muted">加载资讯详情…</div>
              : detailQuery.isError || !activeItem ? <div className="py-12 text-center text-sm text-danger">资讯详情读取失败</div>
                : (
                  <article className="rounded-lg border border-border bg-elevated/30 p-4">
                    <div className="text-lg font-semibold leading-7 text-foreground">{activeItem.title}</div>
                    <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted">
                      {activeItem.symbol && <Badge variant="light" size="sm">{activeItem.name || activeItem.symbol}</Badge>}
                      <span>{activeItem.source}</span>
                      <span>{formatTime(activeItem.published_at || activeItem.fetched_at)}</span>
                    </div>
                    {activeItem.summary && <p className="mt-4 whitespace-pre-wrap text-sm leading-7 text-secondary">{activeItem.summary}</p>}
                    {activeItem.content && <p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-foreground">{activeItem.content}</p>}
                    {activeItem.url && <a className="mt-4 inline-flex items-center gap-1 text-xs text-accent hover:underline" href={activeItem.url} target="_blank" rel="noreferrer">查看原文 <ExternalLink className="h-3 w-3" /></a>}
                  </article>
                )
          ) : (
            <>
              {listQuery.isLoading && <div className="py-12 text-center text-sm text-muted">正在读取资讯…</div>}
              {listQuery.isError && <div className="flex items-center justify-center gap-2 py-12 text-sm text-danger"><AlertCircle className="h-4 w-4" />资讯请求失败，请稍后重试</div>}
              {!listQuery.isLoading && !listQuery.isError && sourceStatus && sourceStatus !== 'ok' && (
                <div className={`mb-3 flex items-start gap-2 rounded-md border px-3 py-2 text-xs ${sourceStatus === 'stale' ? 'border-warning/30 bg-warning/5 text-warning' : 'border-border bg-elevated/30 text-muted'}`}>
                  <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  <span>{statusLabel(sourceStatus)}{listQuery.data?.source_message ? `：${listQuery.data.source_message}` : ''}</span>
                </div>
              )}
              {!listQuery.isLoading && !listQuery.isError && listQuery.data?.items.length === 0 && (
                <div className="py-12 text-center text-sm text-muted">{statusLabel(sourceStatus || 'empty') || '暂无资讯'}</div>
              )}
              <div className="space-y-2">
                {listQuery.data?.items.map(item => <NewsCard key={item.id} item={item} onSelect={() => setSelectedId(item.id)} />)}
              </div>
            </>
          )}
        </div>
        <div className="border-t border-border px-4 py-2 text-[11px] text-muted">
          {selectedSymbol ? `当前筛选：${selectedName || selectedSymbol}` : `当前账户共 ${listQuery.data?.watchlist_count ?? symbols.length} 只自选股`}
          {listQuery.data?.as_of && ` · 数据截至 ${formatTime(listQuery.data.as_of)}`}
        </div>
      </div>
    </Modal>
  )
}
