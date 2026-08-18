/**
 * 系统设置面板 — 全局行为开关。
 *
 * 独立于实时监控, 放置影响整体应用行为的开关项。
 */
import { useState, useCallback, useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Button, Select, Slider, Switch } from '@mantine/core'
import { Settings2, Trash2, RefreshCw, Bell, Volume2, Info } from 'lucide-react'
import { usePreferences, useVersion } from '@/lib/useSharedQueries'
import { api } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { PageHeader } from '@/components/PageHeader'
import { refreshAlertToastConfig } from '@/lib/alertNotify'
import { SOUND_OPTIONS, previewSound } from '@/lib/notificationSound'
import {
  listZhVoices, previewVoice, activateVoice, getCurrentVoiceURI,
} from '@/lib/voiceBroadcast'

export function SettingsSystemPanel() {
  const qc = useQueryClient()
  const { data: prefs } = usePreferences()
  const { data: versionData } = useVersion()
  const [saving, setSaving] = useState(false)

  const screenerAutoRun = prefs?.screener_auto_run ?? true
  const [clearing, setClearing] = useState(false)
  const [toastEnabled, setToastEnabled] = useState(() => {
    try { return localStorage.getItem('alert_toast_enabled') !== '0' } catch { return true }
  })
  const [toastMax, setToastMax] = useState(() => {
    try {
      const v = parseInt(localStorage.getItem('alert_toast_max') || '', 10)
      return v >= 1 && v <= 5 ? v : 3
    } catch { return 3 }
  })
  const [soundEnabled, setSoundEnabled] = useState(() => {
    try { return localStorage.getItem('alert_sound_enabled') !== '0' } catch { return true }
  })
  const [soundType, setSoundType] = useState(() => {
    try { return localStorage.getItem('alert_sound') || 'ding' } catch { return 'ding' }
  })
  const [voiceEnabled, setVoiceEnabled] = useState(() => {
    try { return localStorage.getItem('voice_broadcast_enabled') === '1' } catch { return false }
  })
  const [voices, setVoices] = useState(listZhVoices())
  // 用户手选值 (空=走默认偏好 Google 中国大陆)
  const [voiceConfigured, setVoiceConfigured] = useState(() => {
    try { return localStorage.getItem('voice_broadcast_voice') || '' } catch { return '' }
  })
  // 下拉回显值: 用户手选优先, 否则显示当前解析到的语音
  const [voiceURI, setVoiceURI] = useState(() => {
    try { return localStorage.getItem('voice_broadcast_voice') || getCurrentVoiceURI() } catch { return getCurrentVoiceURI() }
  })
  const [voiceRate, setVoiceRate] = useState(() => {
    try {
      const v = parseFloat(localStorage.getItem('voice_broadcast_rate') || '')
      return v >= 0.5 && v <= 2 ? v : 1
    } catch { return 1 }
  })

  // 语音包异步加载 (Google 云语音为 Chrome 联网注入, 比本地晚到), 监听刷新
  useEffect(() => {
    const h = () => {
      setVoices(listZhVoices())
      // 用户未手选时, 跟随默认偏好 (Google CN 到货后自动同步回显)
      if (!voiceConfigured) setVoiceURI(getCurrentVoiceURI())
    }
    if ('speechSynthesis' in window) {
      window.speechSynthesis.addEventListener('voiceschanged', h)
      // 部分浏览器首次需主动触发一次
      h()
    }
    return () => {
      if ('speechSynthesis' in window) window.speechSynthesis.removeEventListener('voiceschanged', h)
    }
  }, [voiceConfigured])

  const save = useCallback(async (cfg: Record<string, unknown>) => {
    setSaving(true)
    try {
      await api.updateRealtimeMonitorConfig(cfg)
      qc.invalidateQueries({ queryKey: QK.preferences })
    } finally {
      setSaving(false)
    }
  }, [qc])

  // 刷新前端缓存: 清除 react-query 缓存 + 强制重载 (绕过浏览器缓存)
  // 不动 localStorage (用户列配置/策略池等偏好保留), 也不影响后端的本地股票数据
  const handleClearCache = useCallback(() => {
    setClearing(true)
    qc.clear()
    // 加时间戳参数强制浏览器重新下载所有静态资源
    setTimeout(() => {
      window.location.href = window.location.pathname + '?_t=' + Date.now()
    }, 300)
  }, [qc])

  // Mantine Select 不接受空字符串 value; 未解析到语音时用哨兵值代表"默认偏好"
  const defaultVoiceValue = getCurrentVoiceURI() || '__voice_default__'

  return (
    <>
      <PageHeader
        title="系统设置"
        subtitle="全局行为开关"
      />

      <section className="rounded-card border border-border bg-surface p-5">
        <div className="flex items-center gap-2 mb-4">
          <Settings2 className="h-4 w-4 text-accent" />
          <h3 className="text-sm font-medium text-foreground">策略页</h3>
        </div>

        <ToggleRow
          label="进入策略页自动运行策略"
          desc="开启后进入策略页自动跑所有策略获取命中数; 关闭则需手动点击"
          checked={screenerAutoRun}
          disabled={saving}
          onChange={(v) => save({ screener_auto_run: v })}
        />
      </section>

      <section className="rounded-card border border-border bg-surface p-5 mt-6">
        <div className="flex items-center gap-2 mb-4">
          <Bell className="h-4 w-4 text-accent" />
          <h3 className="text-sm font-medium text-foreground">通知弹窗</h3>
        </div>

        <ToggleRow
          label="开启监控通知弹窗"
          desc="收到监控告警时在右下角弹出通知卡片"
          checked={toastEnabled}
          disabled={saving}
          onChange={(v) => {
            localStorage.setItem('alert_toast_enabled', v ? '1' : '0')
            setToastEnabled(v)
            refreshAlertToastConfig()
          }}
        />

        <div className="flex items-center justify-between gap-4 py-2">
          <div className="min-w-0">
            <div className="text-sm text-foreground">最大弹窗个数</div>
            <div className="text-[11px] text-muted truncate">同时显示的通知数量 (1-5), 超出丢弃最旧的</div>
          </div>
          <Select
            size="xs"
            w={64}
            value={String(toastMax)}
            disabled={!toastEnabled}
            onChange={(v) => {
              if (!v) return
              const n = Number(v)
              localStorage.setItem('alert_toast_max', String(n))
              setToastMax(n)
              refreshAlertToastConfig()
            }}
            data={['1', '2', '3', '4', '5']}
            allowDeselect={false}
          />
        </div>

        <ToggleRow
          label="通知声效"
          desc="收到监控告警时播放提示音"
          checked={soundEnabled}
          disabled={!toastEnabled}
          onChange={(v) => {
            localStorage.setItem('alert_sound_enabled', v ? '1' : '0')
            setSoundEnabled(v)
            if (v) previewSound(soundType)
          }}
        />

        <div className="flex items-center justify-between gap-4 py-2">
          <div className="min-w-0 flex items-center gap-1.5">
            <Volume2 className="h-3.5 w-3.5 text-muted" />
            <div>
              <div className="text-sm text-foreground">声效选择</div>
              <div className="text-[11px] text-muted truncate">选择提示音风格</div>
            </div>
          </div>
          <div className="flex items-center gap-1.5">
            <Select
              size="xs"
              w={96}
              value={soundType}
              disabled={!toastEnabled || !soundEnabled}
              onChange={(v) => {
                if (!v) return
                localStorage.setItem('alert_sound', v)
                setSoundType(v)
                if (v !== 'none') previewSound(v)
              }}
              data={SOUND_OPTIONS.map(s => ({ value: s.key, label: s.label }))}
              allowDeselect={false}
            />
            <Button
              size="xs" variant="default"
              onClick={() => previewSound(soundType)}
              disabled={!toastEnabled || !soundEnabled || soundType === 'none'}
            >
              试听
            </Button>
          </div>
        </div>
      </section>

      <section className="rounded-card border border-border bg-surface p-5 mt-6">
        <div className="flex items-center gap-2 mb-4">
          <Volume2 className="h-4 w-4 text-accent" />
          <h3 className="text-sm font-medium text-foreground">语音播报</h3>
        </div>

        <ToggleRow
          label="监控告警语音播报"
          desc="收到告警时用中文语音播报内容 (需浏览器支持, 默认关闭)"
          checked={voiceEnabled}
          disabled={!toastEnabled}
          onChange={(v) => {
            localStorage.setItem('voice_broadcast_enabled', v ? '1' : '0')
            setVoiceEnabled(v)
            if (v) { activateVoice(); previewVoice() }   // 开启即激活 + 试听一句
          }}
        />

        <div className="flex items-center justify-between gap-4 py-2">
          <div className="min-w-0 flex items-center gap-1.5">
            <Volume2 className="h-3.5 w-3.5 text-muted" />
            <div>
              <div className="text-sm text-foreground">语音音色</div>
              <div className="text-[11px] text-muted truncate">
                {voices.length === 0
                  ? '未检测到中文语音, 将用系统默认'
                  : '默认优先 Google 中国大陆 (音质最佳)'}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-1.5">
            <Select
              size="xs"
              w={144}
              value={voiceURI || defaultVoiceValue}
              disabled={!toastEnabled || !voiceEnabled}
              onChange={(v) => {
                if (v && v !== defaultVoiceValue) {
                  // 手选某一语音包
                  localStorage.setItem('voice_broadcast_voice', v)
                  setVoiceConfigured(v)
                  setVoiceURI(v)
                } else {
                  // 选"默认偏好": 清空手选, 走 Google 中国大陆偏好
                  localStorage.removeItem('voice_broadcast_voice')
                  setVoiceConfigured('')
                  setVoiceURI(getCurrentVoiceURI())
                }
              }}
              data={[
                { value: defaultVoiceValue, label: '默认偏好' },
                ...voices
                  .filter(v => v.voiceURI !== getCurrentVoiceURI())
                  .map(v => ({ value: v.voiceURI, label: v.name })),
              ]}
              allowDeselect={false}
            />
            <Button
              size="xs" variant="default"
              onClick={() => previewVoice()}
              disabled={!toastEnabled || !voiceEnabled}
            >
              试听
            </Button>
          </div>
        </div>

        <div className="flex items-center justify-between gap-4 py-2">
          <div className="min-w-0">
            <div className="text-sm text-foreground">语速</div>
            <div className="text-[11px] text-muted truncate">0.5 慢 — 2.0 快</div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <Slider
              w={128}
              min={0.5} max={2} step={0.1} value={voiceRate}
              disabled={!toastEnabled || !voiceEnabled}
              onChange={(v) => {
                localStorage.setItem('voice_broadcast_rate', String(v))
                setVoiceRate(v)
              }}
              label={null}
            />
            <span className="text-xs text-muted w-8 text-right">{voiceRate.toFixed(1)}</span>
          </div>
        </div>
      </section>

      <section className="rounded-card border border-border bg-surface p-5 mt-6">
        <div className="flex items-center gap-2 mb-4">
          <Trash2 className="h-4 w-4 text-accent" />
          <h3 className="text-sm font-medium text-foreground">缓存</h3>
        </div>

        <div className="flex items-center justify-between gap-4 py-2">
          <div className="min-w-0">
            <div className="text-sm text-foreground">刷新前端缓存</div>
            <div className="text-[11px] text-muted truncate">
              清除页面缓存并强制重新加载 (不影响个人配置和本地股票数据)
            </div>
          </div>
          <Button
            size="xs" variant="default"
            onClick={handleClearCache}
            disabled={clearing}
            leftSection={<RefreshCw className={`h-3.5 w-3.5 ${clearing ? 'animate-spin' : ''}`} />}
          >
            {clearing ? '清理中…' : '清理并刷新'}
          </Button>
        </div>
      </section>

      <section className="rounded-card border border-border bg-surface p-5 mt-6">
        <div className="flex items-center gap-2 mb-4">
          <Info className="h-4 w-4 text-accent" />
          <h3 className="text-sm font-medium text-foreground">关于</h3>
        </div>

        <div className="flex items-center justify-between gap-4 py-2">
          <div className="min-w-0">
            <div className="text-sm text-foreground">版本</div>
            <div className="text-[11px] text-muted truncate">当前安装的应用版本</div>
          </div>
          <span className="font-mono text-xs text-secondary shrink-0">
            {versionData?.version ?? '—'}
          </span>
        </div>

        <div className="flex items-center justify-between gap-4 py-2">
          <div className="min-w-0">
            <div className="text-sm text-foreground">检查更新</div>
            <div className="text-[11px] text-muted truncate">前往 GitHub Releases 下载最新版本</div>
          </div>
          <Button
            component="a"
            href="https://github.com/shy3130/tickflow-stock-panel/releases/latest"
            target="_blank"
            rel="noreferrer"
            size="xs" variant="default"
            leftSection={<RefreshCw className="h-3.5 w-3.5" />}
          >
            检查更新
          </Button>
        </div>
      </section>
    </>
  )
}


// ===== ToggleRow =====

function ToggleRow({
  label,
  desc,
  checked,
  disabled,
  onChange,
}: {
  label: string
  desc: string
  checked: boolean
  disabled?: boolean
  onChange: (v: boolean) => void
}) {
  return (
    <div className="flex items-center justify-between gap-4 py-2">
      <div className="min-w-0">
        <div className="text-sm text-foreground">{label}</div>
        <div className="text-[11px] text-muted truncate">{desc}</div>
      </div>
      <Switch
        size="sm"
        className="shrink-0"
        checked={checked}
        onChange={() => onChange(!checked)}
        disabled={disabled}
      />
    </div>
  )
}
