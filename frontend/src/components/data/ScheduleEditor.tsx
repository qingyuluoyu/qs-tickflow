import { useState, useEffect } from 'react'
import { Button, NumberInput } from '@mantine/core'

export function ScheduleEditor({ value, onSave, loading, hint }: {
  value: { hour: number; minute: number }
  onSave: (hour: number, minute: number) => void
  loading: boolean
  hint?: string
}) {
  const [h, setH] = useState(value.hour)
  const [m, setM] = useState(value.minute)

  useEffect(() => { setH(value.hour); setM(value.minute) }, [value.hour, value.minute])

  const handleSave = () => {
    if (h === value.hour && m === value.minute) return
    onSave(h, m)
  }

  const inputCls = 'rounded-btn bg-base border-border font-mono text-center'

  return (
    <div className="flex items-center gap-2 pt-1.5">
      <span className="text-[10px] text-muted">每日</span>
      <NumberInput
        size="xs"
        w={48}
        hideControls
        min={0} max={23}
        value={h}
        onChange={v => setH(Math.max(0, Math.min(23, Number(v) || 0)))}
        classNames={{ input: inputCls }}
      />
      <span className="text-xs text-muted">:</span>
      <NumberInput
        size="xs"
        w={48}
        hideControls
        min={0} max={59}
        value={m}
        onChange={v => setM(Math.max(0, Math.min(59, Number(v) || 0)))}
        classNames={{ input: inputCls }}
      />
      <Button
        size="compact-xs"
        variant="light"
        onClick={handleSave}
        loading={loading}
        disabled={h === value.hour && m === value.minute}
      >
        保存
      </Button>
      <span className="text-[10px] text-muted">工作日自动执行{hint ? ` · ${hint}` : ''}</span>
    </div>
  )
}
