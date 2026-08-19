// 日期选择器 — @mantine/dates DatePickerInput 的薄封装
//
// 设计:
//   - 对外保持原有 props 契约不变: 字符串日期 'YYYY-MM-DD' 进、字符串出,
//     调用方无需感知 Mantine 的值类型
//   - 弹层定位/翻转/边界裁剪全部交给 Mantine Popover 处理 (Floating UI),
//     不再手写 portal 与坐标计算
//   - 颜色直接引用 index.css 的设计 token (--elevated/--border/--fg-*),
//     随 MantineBridge 的暗/亮切换自动适配
import 'dayjs/locale/zh-cn'
import { DatePickerInput } from '@mantine/dates'
import { Calendar } from 'lucide-react'

interface DatePickerProps {
  value: string          // YYYY-MM-DD,空字符串表示未选
  onChange: (v: string) => void
  min?: string
  max?: string
  placeholder?: string
  className?: string
  buttonClassName?: string
  align?: 'left' | 'right'
}

export function DatePicker({
  value,
  onChange,
  min,
  max,
  placeholder = '选择日期',
  className = '',
  buttonClassName = '',
  align = 'right',
}: DatePickerProps) {
  return (
    <DatePickerInput
      value={value || null}
      onChange={(v) => onChange(v ?? '')}
      minDate={min}
      maxDate={max}
      placeholder={placeholder}
      valueFormat="YYYY-MM-DD"
      locale="zh-cn"
      firstDayOfWeek={1}
      leftSection={<Calendar className="h-3.5 w-3.5 text-accent" />}
      leftSectionPointerEvents="none"
      className={`inline-flex ${className}`}
      classNames={{ input: buttonClassName }}
      popoverProps={{
        position: align === 'left' ? 'bottom-start' : 'bottom-end',
        shadow: 'lg',
        radius: 8,
      }}
      styles={{
        input: {
          height: 28,
          minHeight: 28,
          paddingInline: 10,
          paddingLeft: 30,
          fontSize: 12,
          borderRadius: 4, // rounded-input
          backgroundColor: 'hsl(var(--elevated))',
          borderColor: 'hsl(var(--border))',
          color: 'hsl(var(--fg-primary))',
        },
        placeholder: { color: 'hsl(var(--fg-muted))' },
        section: { color: 'hsl(var(--accent))' },
      }}
    />
  )
}
