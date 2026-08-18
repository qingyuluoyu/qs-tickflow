import { Group, Text, Title } from '@mantine/core'
import { cn } from '@/lib/cn'

interface Props {
  title: string
  subtitle?: string
  /** 标题右侧、subtitle 之前的额外节点(如状态徽标) */
  titleExtra?: React.ReactNode
  right?: React.ReactNode
  className?: string
}

// Mantine 组件承载结构, 视觉沿用既有设计 token (px-5 pt-3 pb-2 border-b / text-lg font-semibold)。
// gap 用数字(px) 以精确对应原 Tailwind gap-4 / gap-2, 避免 Mantine 间距档位 (xs=10px) 造成偏移。
export function PageHeader({ title, subtitle, titleExtra, right, className }: Props) {
  return (
    <Group
      component="header"
      justify="space-between"
      gap={16}
      wrap="nowrap"
      className={cn('px-5 pt-3 pb-2 border-b border-border', className)}
    >
      <Group gap={8} wrap="nowrap">
        <Title order={1} className="text-lg font-semibold tracking-tight">
          {title}
        </Title>
        {titleExtra}
        {subtitle && (
          <Text component="span" className="text-xs text-muted">
            {subtitle}
          </Text>
        )}
      </Group>
      {right}
    </Group>
  )
}
