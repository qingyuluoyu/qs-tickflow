// 全局轻提示 — 统一走 @mantine/notifications (替代原 components/Toast.tsx)
// 签名与原 toast() 完全一致, 调用方只需改 import。
// 颜色用 Mantine 语义色, 随 MantineBridge 的 forceColorScheme 自动适配双主题。
import { notifications } from '@mantine/notifications'

export function toast(msg: string, kind: 'error' | 'success' = 'error') {
  notifications.show({
    message: msg,
    color: kind === 'error' ? 'red' : 'green',
    autoClose: 4000,
  })
}
