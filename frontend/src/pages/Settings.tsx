/**
 * 统一设置页面 — Tab 切换外壳。
 *
 * 通过 URL query param ?tab=xxx 同步 Tab 状态。
 */
import { useSearchParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Badge } from '@mantine/core'
import { BarChart3, Database, Key, Radio, SlidersHorizontal, Sparkles, Settings2, Zap } from 'lucide-react'
import { SettingsKeysPanel } from './settings/Keys'
import { SettingsAIPanel } from './settings/AI'
import { SettingsMonitoringPanel } from './settings/Monitoring'
import { SettingsExtPagesPanel } from './settings/ExtPages'
import { SettingsMenuSettingsPanel } from './settings/MenuSettings'
import { SettingsSystemPanel } from './settings/System'
import { SettingsCustomSignalsPanel } from './settings/CustomSignals'
import { SettingsDataSourcesPanel } from './settings/DataSources'
import { PageHeader } from '@/components/PageHeader'
import { PageContainer } from '@/components/PageContainer'
import { useIsAdmin } from '@/lib/auth'
import { cn } from '@/lib/cn'

import type { ComponentType } from 'react'

// ===== Tab 定义 =====

type TabDef = {
  key: string
  label: string
  icon: ComponentType<{ className?: string }>
  panel: ComponentType<{ highlight?: string }>
  badge?: string
}

const TABS: readonly TabDef[] = [
  { key: 'account',    label: '账户与接口', icon: Key,       panel: SettingsKeysPanel },
  { key: 'ai',         label: 'AI 设置',    icon: Sparkles,  panel: SettingsAIPanel },
  { key: 'monitoring', label: '实时监控',   icon: Radio,     panel: SettingsMonitoringPanel },
  { key: 'data-sources', label: '数据源',     icon: Database,  panel: SettingsDataSourcesPanel },
  { key: 'ext-pages',  label: '扩展页面',   icon: BarChart3, panel: SettingsExtPagesPanel },
  { key: 'signals',    label: '信号库',     icon: Zap,       panel: SettingsCustomSignalsPanel },
  { key: 'menus',      label: '菜单设置',   icon: SlidersHorizontal, panel: SettingsMenuSettingsPanel },
  { key: 'system',     label: '系统设置',   icon: Settings2, panel: SettingsSystemPanel },
]

type TabKey = (typeof TABS)[number]['key']

export function Settings() {
  const [searchParams, setSearchParams] = useSearchParams()
  // 数据源面板为纯服务器级管理功能(增删/重载/插件/切换 provider 均要求管理员),
  // 普通用户隐藏整个入口,避免看到必然 403 的操作
  const isAdmin = useIsAdmin()
  const tabs = isAdmin ? TABS : TABS.filter((t) => t.key !== 'data-sources')
  const tabParam = searchParams.get('tab') as TabKey | null
  const activeTab = tabs.find((t) => t.key === tabParam) ?? tabs[0]
  const highlight = searchParams.get('highlight') ?? ''

  return (
    <>
      <PageHeader
        title="设置"
        subtitle="管理账户、数据刷新策略和高级功能配置。"
      />

      <PageContainer>
        <div className="flex flex-col gap-4 lg:flex-row lg:gap-6 lg:items-stretch">
          {/* ===== 竖向 Tab 侧栏（内容垂直居中; 窄屏横排堆叠到顶部） ===== */}
          <nav className="shrink-0 lg:w-36">
            <div className="flex flex-row flex-wrap gap-0.5 lg:min-h-[60vh] lg:flex-col lg:flex-nowrap lg:justify-center lg:sticky lg:top-6">
              {tabs.map(({ key, label, icon: Icon, badge }) => (
                <button
                  key={key}
                  onClick={() => setSearchParams({ tab: key }, { replace: true })}
                  className={cn(
                    'relative flex items-center gap-2 px-3 py-2 rounded-btn text-sm transition-colors duration-150 ease-smooth text-left',
                    activeTab.key === key
                      ? 'bg-accent/10 text-accent font-medium'
                      : 'text-secondary hover:text-foreground hover:bg-elevated/60',
                  )}
                >
                  <Icon className="h-3.5 w-3.5 shrink-0" />
                  <span>{label}</span>
                  {badge && (
                    <Badge size="xs" variant="light" color="blue" className="ml-auto shrink-0 normal-case">
                      {badge}
                    </Badge>
                  )}
                </button>
              ))}
            </div>
          </nav>

          {/* ===== Tab 内容 ===== */}
          <motion.div
            key={activeTab.key}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.15 }}
            className="min-w-0 flex-1"
          >
            {activeTab.key === 'monitoring'
            ? <SettingsMonitoringPanel highlight={highlight} />
            : <activeTab.panel />}
          </motion.div>
        </div>
      </PageContainer>
    </>
  )
}
