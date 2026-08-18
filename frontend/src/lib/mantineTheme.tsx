// Mantine 主题桥接 — 与既有 theme.ts 双主题体系严格同步
//
// 设计:
//   - 现有 theme.ts (localStorage 'qs-theme' + html.dark class) 仍是唯一事实源
//   - MantineBridge 用 useTheme() 读取当前主题, forceColorScheme 强制 Mantine 跟随,
//     保证 Tailwind token、图表调色板、Mantine 组件三者永远一致
//   - 色板对齐 index.css 的设计 token: accent = 电光蓝 #3B82F6,
//     dark 灰阶映射 --base/--surface/--elevated/--border/--fg-*
import { MantineProvider, createTheme, type MantineColorsTuple } from '@mantine/core'
import { ModalsProvider } from '@mantine/modals'
import { Notifications } from '@mantine/notifications'
import type { ReactNode } from 'react'
import { useTheme } from './theme'

// 电光蓝色阶 (accent #3B82F6 为 index 5)
const accent: MantineColorsTuple = [
  '#eff6ff', '#dbeafe', '#bfdbfe', '#93c5fd', '#60a5fa',
  '#3b82f6', '#2563eb', '#1d4ed8', '#1e40af', '#1e3a8a',
]

// 暗色灰阶, 对齐 index.css 的 html.dark token
// Mantine 约定: 0=主文字 1=次要文字 4=边框 5=hover 底 6=卡片/面板底 7=页面底
const dark: MantineColorsTuple = [
  '#C4C4CB', '#8E8E96', '#6b6b72', '#3a3a3f', '#353539',
  '#212126', '#18181B', '#101012', '#0A0A0B', '#050506',
]

export const mantineTheme = createTheme({
  primaryColor: 'accent',
  primaryShade: { light: 6, dark: 5 },
  colors: { accent, dark },
  fontFamily: 'Inter, "HarmonyOS Sans SC", "PingFang SC", system-ui, sans-serif',
  fontFamilyMonospace: '"JetBrains Mono", "IBM Plex Mono", ui-monospace, monospace',
  defaultRadius: 'md',
  respectReducedMotion: true,
})

/** 把现有主题系统 (theme.ts) 桥接进 MantineProvider。 */
export function MantineBridge({ children }: { children: ReactNode }) {
  const theme = useTheme()
  return (
    <MantineProvider theme={mantineTheme} forceColorScheme={theme}>
      <Notifications position="top-right" zIndex={10000} limit={10} />
      <ModalsProvider>{children}</ModalsProvider>
    </MantineProvider>
  )
}
