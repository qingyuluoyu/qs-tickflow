import { useState, useEffect } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Badge, Button, PasswordInput, Select, Switch, TextInput } from '@mantine/core'
import {
  Save, Loader2, Check, Wifi, WifiOff, Shield,
  Shuffle, Plug, Zap, Settings2, ExternalLink, Trash2,
  Terminal,
} from 'lucide-react'
import { useSettings } from '@/lib/useSharedQueries'
import { api, type SettingsState } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { Modal } from '@/components/Modal'

const CODEX_PROVIDER = 'codex_cli'
const OPENAI_PROVIDER = 'openai_compat'
const CODEX_COMMAND = 'codex'
const DEFAULT_CODEX_MODEL = 'gpt-5.6-sol'
const DEFAULT_CODEX_REASONING_EFFORT = 'xhigh'
const SAVED_CODEX_OPTION_VALUE = '__saved_codex_config__'
// Mantine Select 不接受空字符串 value, 用哨兵值代表"跟随本机 Codex 默认"
const CODEX_DEFAULT_OPTION_VALUE = '__codex_local_default__'
const CODEX_REASONING_LABELS: Record<string, string> = {
  high: '高',
  xhigh: '极高',
}

type CodexModelOption = { label: string; value: string; model: string; effort: string; hint: string }

const CODEX_MODEL_OPTIONS: CodexModelOption[] = [
  { label: 'GPT-5.6 Sol · 极高（推荐）', value: 'gpt-5.6-sol:xhigh', model: 'gpt-5.6-sol', effort: 'xhigh', hint: '旗舰档，适合复杂金融分析与专业任务' },
  { label: 'GPT-5.6 Terra · 极高', value: 'gpt-5.6-terra:xhigh', model: 'gpt-5.6-terra', effort: 'xhigh', hint: '平衡智能、速度与使用成本' },
  { label: 'GPT-5.6 Luna · 极高', value: 'gpt-5.6-luna:xhigh', model: 'gpt-5.6-luna', effort: 'xhigh', hint: '适合成本敏感与高频分析任务' },
  { label: 'gpt-5.5 · 高', value: 'gpt-5.5:high', model: 'gpt-5.5', effort: 'high', hint: '使用 gpt-5.5 + high 推理档' },
  { label: 'gpt-5.5 · 极高', value: 'gpt-5.5:xhigh', model: 'gpt-5.5', effort: 'xhigh', hint: '使用 gpt-5.5 + xhigh 推理档' },
  { label: '跟随本机 Codex 默认', value: '', model: '', effort: '', hint: '使用本机 Codex CLI 配置的默认模型与推理强度' },
]

const codexModelLabel = (model?: string, effort?: string) => {
  if (!model && !effort) return '默认模型'
  const modelLabel = model || '默认模型'
  const effortLabel = effort ? CODEX_REASONING_LABELS[effort] ?? effort : ''
  return effortLabel ? `${modelLabel} · ${effortLabel}` : modelLabel
}

const PRESETS: { label: string; provider?: string; url: string; model: string; codexCommand?: string; website: string; websiteLabel: string; description: string; custom?: boolean }[] = [
  { label: '自定义', url: '', model: '', website: '', websiteLabel: '', description: '不自动填充任何配置，完全手动填写 API 地址、模型和密钥。', custom: true },
  { label: 'DeepSeek', url: 'https://api.deepseek.com', model: 'deepseek-v4-flash', website: 'https://www.deepseek.com/', websiteLabel: 'deepseek.com', description: 'DeepSeek 官方 OpenAI 兼容接口。' },
  { label: '通义千问', url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen-3.6plus', website: 'https://tongyi.aliyun.com/', websiteLabel: 'tongyi.aliyun.com', description: '阿里云 DashScope 兼容模式接口。' },
  { label: '智谱 GLM', url: 'https://open.bigmodel.cn/api/paas/v4', model: 'glm-5.2', website: 'https://open.bigmodel.cn/', websiteLabel: 'open.bigmodel.cn', description: '智谱 AI 官方 OpenAI 兼容接口。' },
  { label: 'Kimi', url: 'https://api.moonshot.cn/v1', model: 'kimi-k2.7-code', website: 'https://platform.moonshot.cn/', websiteLabel: 'platform.moonshot.cn', description: '月之暗面 Moonshot 官方 OpenAI 兼容接口，支持超长上下文。' },
  { label: 'Codex CLI', provider: CODEX_PROVIDER, url: '', model: DEFAULT_CODEX_MODEL, codexCommand: CODEX_COMMAND, website: 'https://developers.openai.com/codex/noninteractive', websiteLabel: 'codex exec', description: '调用本机 Codex CLI 的 codex exec, 适合已登录 ChatGPT/Codex 的本地环境。' },
  { label: '炸鸡中转站', url: 'https://api.zhaji.dev/v1', model: 'gpt-5.5', website: 'https://api.zhaji.dev', websiteLabel: 'api.zhaji.dev', description: 'OpenAI 兼容中转服务，适合直接使用国际模型。' },
]

export function SettingsAIPanel() {
  const qc = useQueryClient()
  const settings = useSettings()
  const s = settings.data

  const [provider, setProvider] = useState(OPENAI_PROVIDER)
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState('')
  const [codexReasoningEffort, setCodexReasoningEffort] = useState('')
  const [codexCommand, setCodexCommand] = useState(CODEX_COMMAND)
  const [customUa, setCustomUa] = useState(false)
  const [userAgent, setUserAgent] = useState('')
  const [saved, setSaved] = useState(false)
  const [confirmClear, setConfirmClear] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; msg: string } | null>(null)

  const isCodexProvider = provider === CODEX_PROVIDER
  const savedCodexProvider = s?.ai_provider === CODEX_PROVIDER
  const usingServerDefault = s?.ai_source === 'server_default'
  const usingOwnOverride = s?.ai_source === 'user_override'
  const configured = s?.ai_configured ?? (savedCodexProvider ? !!(s?.ai_codex_command ?? CODEX_COMMAND) : s?.has_ai_key)
  // 选中的预设: 精确匹配 provider+url/codexCommand; 匹配不上时默认"自定义"
  const matchedPreset = PRESETS.find(p => (p.provider ?? OPENAI_PROVIDER) === provider && (isCodexProvider ? p.codexCommand === codexCommand : p.url === baseUrl))
  const selectedPreset = matchedPreset ?? PRESETS.find(p => p.custom)
  const savedCodexModel = savedCodexProvider ? (s?.ai_model ?? '') : ''
  const savedCodexEffort = savedCodexProvider ? (s?.ai_codex_reasoning_effort ?? '') : ''
  const savedCodexOptionKnown = CODEX_MODEL_OPTIONS.some(option =>
    option.model === savedCodexModel && option.effort === savedCodexEffort,
  )
  const savedCodexOption: CodexModelOption | null =
    (savedCodexModel || savedCodexEffort) && !savedCodexOptionKnown
      ? {
          label: `${codexModelLabel(savedCodexModel, savedCodexEffort)}（当前配置）`,
          value: SAVED_CODEX_OPTION_VALUE,
          model: savedCodexModel,
          effort: savedCodexEffort,
          hint: '保留项目中已保存的模型与推理档；此兼容项不可编辑',
        }
      : null
  const codexModelOptions = savedCodexOption
    ? [savedCodexOption, ...CODEX_MODEL_OPTIONS]
    : CODEX_MODEL_OPTIONS
  const selectedCodexModelOption = codexModelOptions.find(option =>
    option.model === model && option.effort === codexReasoningEffort,
  ) ?? CODEX_MODEL_OPTIONS[0]
  const codexModelSelectValue = selectedCodexModelOption.value
  const canSave = !isCodexProvider && !!baseUrl.trim() && !!model.trim() && (usingOwnOverride || !!apiKey.trim())

  useEffect(() => {
    if (!s) return
    // 平台默认模型不能被复写到个人表单；只有已保存的个人覆盖才回填。
    const ownOverride = s.ai_source === 'user_override'
    setProvider(ownOverride ? (s.ai_provider ?? OPENAI_PROVIDER) : OPENAI_PROVIDER)
    setBaseUrl(ownOverride ? (s.ai_base_url ?? '') : '')
    setModel(ownOverride ? (s.ai_model ?? '') : '')
    setCodexReasoningEffort(ownOverride ? (s.ai_codex_reasoning_effort ?? '') : '')
    setCodexCommand(ownOverride ? (s.ai_codex_command ?? CODEX_COMMAND) : CODEX_COMMAND)
    const ua = ownOverride ? (s.ai_user_agent ?? '') : ''
    setCustomUa(!!ua)
    setUserAgent(ua)
  }, [s])

  const startPersonalOverride = () => {
    setProvider(OPENAI_PROVIDER)
    setBaseUrl('')
    setApiKey('')
    setModel('')
    setCodexReasoningEffort('')
    setCodexCommand(CODEX_COMMAND)
    setCustomUa(false)
    setUserAgent('')
    setTestResult(null)
  }

  const payload = () => ({
    provider,
    base_url: baseUrl,
    api_key: apiKey || undefined,
    model,
    codex_command: isCodexProvider ? CODEX_COMMAND : codexCommand,
    codex_reasoning_effort: isCodexProvider ? codexReasoningEffort : '',
    user_agent: customUa ? userAgent : '',
  })

  const save = useMutation({
    mutationFn: () => api.saveAiSettings(payload()),
    onSuccess: (result) => {
      setSaved(true)
      setApiKey('')
      qc.setQueryData<SettingsState>(QK.settings, prev => prev ? {
        ...prev,
        ai_provider: result.ai_provider ?? provider,
        ai_base_url: baseUrl,
        ai_model: result.ai_model ?? model,
        ai_codex_command: result.ai_codex_command ?? (isCodexProvider ? CODEX_COMMAND : codexCommand),
        ai_codex_reasoning_effort: result.ai_codex_reasoning_effort ?? (isCodexProvider ? codexReasoningEffort : ''),
        ai_configured: result.ai_configured ?? (isCodexProvider ? true : (apiKey ? true : prev.ai_configured)),
        ai_source: result.ai_source ?? 'user_override',
        has_ai_override: result.has_ai_override ?? true,
        ...(apiKey ? {
          has_ai_key: true,
          ai_api_key_masked: `${apiKey.slice(0, 4)}......${apiKey.slice(-4)}`,
        } : {}),
      } : prev)
      qc.invalidateQueries({ queryKey: QK.settings })
      setTimeout(() => setSaved(false), 2000)
    },
  })

  const clear = useMutation({
    mutationFn: () => api.clearAiSettings(),
    onSuccess: (result) => {
      setConfirmClear(false)
      setProvider(OPENAI_PROVIDER)
      setBaseUrl('')
      setApiKey('')
      setModel('')
      setCodexReasoningEffort('')
      setCodexCommand(CODEX_COMMAND)
      setTestResult(null)
      qc.setQueryData<SettingsState>(QK.settings, prev => prev ? {
        ...prev,
        ai_provider: result.ai_provider ?? prev.ai_provider,
        ai_base_url: '',
        ai_model: result.ai_model ?? prev.ai_model,
        ai_codex_command: CODEX_COMMAND,
        ai_codex_reasoning_effort: '',
        has_ai_key: false,
        ai_configured: result.ai_configured ?? prev.ai_configured,
        ai_api_key_masked: '',
        ai_source: result.ai_source ?? 'server_default',
        has_ai_override: result.has_ai_override ?? false,
      } : prev)
      qc.invalidateQueries({ queryKey: QK.settings })
    },
  })

  const genRandomUa = () => {
    const major = 128 + Math.floor(Math.random() * 8)
    const platforms = [
      'Windows NT 10.0; Win64; x64',
      'Macintosh; Intel Mac OS X 10_15_7',
      'X11; Linux x86_64',
    ]
    const pf = platforms[Math.floor(Math.random() * platforms.length)]
    setUserAgent(`Mozilla/5.0 (${pf}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${major}.0.0.0 Safari/537.36`)
  }

  const handlePreset = (p: typeof PRESETS[number]) => {
    if (p.custom) {
      // 自定义: 清空所有自动填充字段, 由用户完全手动填写
      setProvider(OPENAI_PROVIDER)
      setBaseUrl('')
      setModel('')
      setCodexReasoningEffort('')
      return
    }
    setProvider(p.provider ?? OPENAI_PROVIDER)
    setBaseUrl(p.url)
    setModel(p.model)
    setCodexReasoningEffort(p.provider === CODEX_PROVIDER ? DEFAULT_CODEX_REASONING_EFFORT : '')
    if (p.codexCommand) setCodexCommand(CODEX_COMMAND)
  }

  const handleTest = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      if (canSave) await api.saveAiSettings(payload())
      const r = await api.strategyAiTest()
      setTestResult({ ok: r.ok, msg: r.ok ? `连通成功 · ${r.model ?? provider}` : (r.error ?? '未知错误') })
    } catch (e: any) {
      setTestResult({ ok: false, msg: String(e?.message ?? '测试失败') })
    } finally {
      setTesting(false)
    }
  }

  return (
    <div className="space-y-5 max-w-2xl">
      <Card icon={Plug} title="连接状态" right={
        configured && (
          <Button
            size="xs" variant="subtle" color="gray"
            onClick={handleTest} disabled={testing}
            leftSection={testing ? <Loader2 className="h-3 w-3 animate-spin" /> : <Wifi className="h-3 w-3" />}
          >
            {testing ? '测试中' : '测试'}
          </Button>
        )
      }>
        <div className="flex items-center gap-3">
          <div className={`w-9 h-9 rounded-lg flex items-center justify-center shrink-0 ${configured ? 'bg-bear/10 text-bear' : 'bg-warning/10 text-warning'}`}>
            {configured ? <Wifi className="h-4.5 w-4.5" /> : <WifiOff className="h-4.5 w-4.5" />}
          </div>
          <div className="min-w-0">
            <div className="text-sm font-medium text-foreground">{configured ? 'AI 已连接' : 'AI 未配置'}</div>
            <div className="text-xs text-muted mt-0.5 truncate">
              {configured
                ? (usingServerDefault
                  ? `正在使用平台默认模型 · ${s?.ai_model ?? '默认模型'}`
                  : savedCodexProvider
                  ? `${s?.ai_codex_command ?? CODEX_COMMAND} · ${codexModelLabel(s?.ai_model, s?.ai_codex_reasoning_effort)}`
                  : `${s?.ai_model} · ${s?.ai_api_key_masked}`)
                : (isCodexProvider ? '使用本机 codex exec, 此处无需填写 API Key。' : '配置 API Key 后即可使用 AI 功能。')}
            </div>
          </div>
        </div>
        {testResult && (
          <div className={`mt-3 rounded-btn border px-3 py-2 text-xs flex items-center gap-2 ${testResult.ok ? 'border-bear/20 bg-bear/[0.04] text-bear' : 'border-danger/20 bg-danger/[0.04] text-danger'}`}>
            <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${testResult.ok ? 'bg-bear' : 'bg-danger'}`} />
            {testResult.msg}
          </div>
        )}
      </Card>

      {usingServerDefault && (
        <div className="rounded-card border border-accent/20 bg-accent/[0.04] px-4 py-3 flex items-center justify-between gap-3">
          <div className="text-xs text-secondary leading-relaxed">
            当前账户使用平台提供的默认模型。配置个人 API 后，仅你的分析请求会使用该配置。
          </div>
          <Button size="xs" variant="light" onClick={startPersonalOverride} className="shrink-0">
            配置个人 API
          </Button>
        </div>
      )}

      <Card icon={Zap} title="快速预设">
        <div className="flex flex-wrap items-start gap-2">
          {PRESETS.filter(p => p.provider !== CODEX_PROVIDER).map(p => (
            <button key={p.label} onClick={() => handlePreset(p)}
              className={`rounded-lg border px-3 py-2 text-left transition-all ${selectedPreset?.label === p.label ? 'border-accent/40 bg-accent/10 text-accent' : 'border-border bg-base text-secondary hover:border-accent/30'}`}>
              <div className="flex items-center gap-1.5 text-xs font-medium">
                <span>{p.label}</span>
                {p.provider === CODEX_PROVIDER && <Terminal className="h-3 w-3" />}
              </div>
            </button>
          ))}
        </div>
        {selectedPreset && (
          <div className="mt-3 rounded-btn border border-border/30 bg-base/30 px-3 py-2 text-[11px] leading-relaxed">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <span className="text-secondary">{selectedPreset.description}</span>
            </div>
            {selectedPreset.website && (
              <a href={selectedPreset.website} target="_blank" rel="noreferrer"
                className="mt-1 inline-flex items-center gap-1 text-muted hover:text-accent transition-colors">
                {selectedPreset.websiteLabel}
                <ExternalLink className="h-3 w-3" />
              </a>
            )}
          </div>
        )}
      </Card>

      <Card
        icon={Settings2}
        title="自定义配置"
        right={
          <span className="inline-flex items-center gap-1.5 text-[10px] text-muted/60" title={isCodexProvider ? 'Use local Codex CLI via codex exec' : 'Use OpenAI-compatible Chat Completions API'}>
            <Badge size="sm" variant="light" color="gray" className="font-mono normal-case">{isCodexProvider ? 'codex exec' : 'Chat Completions'}</Badge>
            {isCodexProvider ? 'CLI' : '接口'}
          </span>
        }
      >
        <div className="space-y-4">
          {isCodexProvider ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <Field label="CLI 命令" hint="固定使用默认 codex 命令, 由后端自动解析本机 Codex Desktop/CLI, 不支持自定义可执行路径。">
                <TextInput size="sm" value={CODEX_COMMAND} readOnly aria-label="Codex CLI command" classNames={{ input: 'font-mono text-muted/80 select-none' }} />
              </Field>
              <Field
                label="模型 / 推理档"
                hint={selectedCodexModelOption.hint}
              >
                <Select
                  size="sm"
                  value={codexModelSelectValue || CODEX_DEFAULT_OPTION_VALUE}
                  onChange={value => {
                    const option = codexModelOptions.find(item => (item.value || CODEX_DEFAULT_OPTION_VALUE) === value) ?? CODEX_MODEL_OPTIONS[0]
                    setModel(option.model)
                    setCodexReasoningEffort(option.effort)
                  }}
                  data={codexModelOptions.map(option => ({
                    label: option.label,
                    value: option.value || CODEX_DEFAULT_OPTION_VALUE,
                  }))}
                  allowDeselect={false}
                />
              </Field>
            </div>
          ) : (
            <>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <Field label="API 地址">
                  <TextInput size="sm" value={baseUrl} onChange={e => setBaseUrl(e.target.value)} placeholder="https://api.zhaji.dev/v1" classNames={{ input: 'font-mono' }} />
                </Field>
                <Field label="模型">
                  <TextInput size="sm" value={model} onChange={e => setModel(e.target.value)} placeholder="gpt-5.6-sol" classNames={{ input: 'font-mono' }} />
                </Field>
              </div>

              <Field label="API Key">
                <div className="flex gap-2">
                  <PasswordInput
                    className="flex-1" size="sm"
                    value={apiKey} onChange={e => setApiKey(e.target.value)}
                    placeholder={usingOwnOverride ? `${s?.ai_api_key_masked} · 留空不修改` : 'sk-...'}
                    classNames={{ input: 'font-mono' }}
                  />
                  <Button
                    size="sm" variant="default"
                    onClick={handleTest} disabled={testing || !apiKey}
                    leftSection={testing ? <Loader2 className="h-3 w-3 animate-spin" /> : <Wifi className="h-3 w-3" />}
                  >
                    测试
                  </Button>
                </div>
              </Field>

              <div className="border-t border-border/20" />

              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Field label="自定义 User-Agent" inline>
                    <Switch size="sm" checked={customUa} onChange={() => setCustomUa(v => !v)} />
                  </Field>
                </div>
                {customUa && (
                  <div className="flex gap-2">
                    <TextInput className="flex-1" size="sm" value={userAgent} onChange={e => setUserAgent(e.target.value)} placeholder="粘贴浏览器 User-Agent" classNames={{ input: 'font-mono' }} />
                    <Button size="sm" variant="default" onClick={genRandomUa} title="随机生成浏览器 User-Agent" leftSection={<Shuffle className="h-3 w-3" />}>
                      随机
                    </Button>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </Card>

      <div className="rounded-card border border-warning/20 bg-warning/[0.04] px-4 py-3 flex items-start gap-3">
        <Shield className="h-4 w-4 text-warning/70 mt-0.5 shrink-0" />
        <div className="text-[11px] text-warning/70 leading-relaxed">
          {isCodexProvider
            ? 'Codex CLI 模式会复用本机已登录的 Codex 账户, 个股、财务、复盘等分析上下文会发送给 OpenAI/Codex。保存即表示确认仅在本机或可信内网使用。'
            : '个人 API Key 会加密保存在你的独立账户数据中，仅用于你的分析请求；未配置时继续使用平台默认模型。'}
        </div>
      </div>

      <div className="flex gap-2">
        <Button
          size="md" className="flex-1"
          onClick={() => save.mutate()} disabled={save.isPending || !canSave}
          leftSection={save.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : saved ? <Check className="h-4 w-4" /> : <Save className="h-4 w-4" />}
        >
          {save.isPending ? '保存中...' : saved ? '已保存' : '保存配置'}
        </Button>
        {usingOwnOverride && (
          <Button
            size="md" variant="subtle" color="red"
            onClick={() => setConfirmClear(true)} disabled={clear.isPending}
            leftSection={<Trash2 className="h-4 w-4" />}
            title="Clear AI provider configuration"
          >
            恢复平台默认
          </Button>
        )}
      </div>

      {confirmClear && (
        <Modal
          onClose={() => setConfirmClear(false)}
          ariaLabel="恢复平台默认模型"
          panelClassName="w-[90vw] max-w-[380px] rounded-card border border-border bg-base shadow-2xl p-6"
          overlayClassName="bg-black/60 backdrop-blur-sm"
        >
          <h3 className="text-sm font-medium text-foreground mb-2">恢复平台默认模型</h3>
          <p className="text-xs text-secondary mb-5 leading-relaxed">
            仅删除当前账户保存的个人 API 配置，之后将使用平台默认模型；不会影响其他用户。
          </p>
          <div className="flex items-center justify-end gap-2">
            <Button size="sm" variant="default" onClick={() => setConfirmClear(false)}>
              取消
            </Button>
            <Button size="sm" color="red" variant="light" onClick={() => clear.mutate()} disabled={clear.isPending}>
              {clear.isPending ? '恢复中...' : '确认恢复'}
            </Button>
          </div>
        </Modal>
      )}
    </div>
  )
}

// ===== 通用卡片(与 Keys 页风格统一) =====

interface CardProps {
  icon: React.ComponentType<{ className?: string }>
  title: string
  right?: React.ReactNode
  children: React.ReactNode
}

function Card({ icon: Icon, title, right, children }: CardProps) {
  return (
    <section className="rounded-card border border-border bg-surface p-5">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2.5">
          <Icon className="h-4 w-4 text-secondary" />
          <h2 className="text-sm font-medium text-foreground">{title}</h2>
        </div>
        {right}
      </div>
      {children}
    </section>
  )
}

// ===== 表单字段(统一 label + 输入框样式) =====

function Field({ label, hint, inline, children }: {
  label: string
  hint?: string
  inline?: boolean
  children: React.ReactNode
}) {
  if (inline) {
    return (
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-[10px] text-muted/50 uppercase tracking-wider">{label}</div>
          {hint && <div className="text-[10px] text-muted mt-0.5">{hint}</div>}
        </div>
        {children}
      </div>
    )
  }
  return (
    <div className="space-y-1.5">
      <div className="text-[10px] text-muted/50 uppercase tracking-wider">{label}</div>
      {children}
      {hint && <div className="text-[10px] text-muted">{hint}</div>}
    </div>
  )
}
