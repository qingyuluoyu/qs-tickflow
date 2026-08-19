// 页面容器 — 统一页面级边距 / 居中宽度 / 响应式
//
// 收编历史上 7 种页边距 (p-1.5 / p-4 / px-3 lg:px-4 / px-5 py-4 /
// px-6 py-5 / px-8 py-6) 与 4 种居中宽度 (max-w-6xl/7xl/[1280px]/[1440px])。
// 用法: <PageContainer>...</PageContainer>
//   wide   — 表格/看板类宽页 (默认, 不限宽, 跟随主区)
//   narrow — 表单/报告类窄页 (max-w-7xl 居中)
import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

export function PageContainer({
  children,
  narrow = false,
  className,
}: {
  children: ReactNode
  /** true = 内容居中限宽 (表单/报告类页面) */
  narrow?: boolean
  className?: string
}) {
  return (
    <div
      className={cn(
        'px-4 py-4 lg:px-6 lg:py-5',
        narrow && 'mx-auto w-full max-w-7xl',
        className,
      )}
    >
      {children}
    </div>
  )
}
