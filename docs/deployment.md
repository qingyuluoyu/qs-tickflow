# 部署指南

本项目的几种运行方式，按推荐程度排序。配置项详解见 [configuration.md](./configuration.md)。

> 📌 前置依赖:Python ≥ 3.11 · Node ≥ 20 · [`uv`](https://docs.astral.sh/uv/) · `pnpm`（`npm i -g pnpm`）

---

## 方式 A:Dev 模式(二次开发推荐)

由于刚开源近期更新频繁,推荐开发模式运行,可随时 `git pull` 同步最新代码。

```bash
git clone https://github.com/shy3130/tickflow-stock-panel.git
cd tickflow-stock-panel
cp .env.example .env       # 按需填 TICKFLOW_API_KEY(留空 = None 模式)
./dev.sh                   # Windows: .\dev.ps1
```

`dev.sh` 自动检查 / 下载依赖、释放端口、同时起前后端,Ctrl-C 一并关闭。默认:

- 后端 → <http://localhost:3018> · 前端 → <http://localhost:3011>
- 自定义端口:`BACKEND_PORT=8000 FRONTEND_PORT=5173 ./dev.sh`

### 手动分别启动(不想用 dev.sh)

```bash
# 后端
cd backend && uv sync --extra backtest   # 含回测依赖
# 老 CPU: uv sync --extra legacy-cpu
# 老 CPU + 回测: uv sync --extra legacy-cpu --extra backtest
uv run uvicorn app.main:app --reload --port 3018

# 前端
cd frontend && pnpm install && pnpm dev   # http://localhost:3011
```

---

## 方式 B:Docker(部署最省心)

```bash
cp .env.example .env
docker compose up --build
# 打开 http://localhost:3018
```

Docker 采用两阶段构建,前端 dist 拷进后端镜像,**单容器**运行,数据完全在自己手里。

容器存活探针为 `/health`,就绪探针为 `/api/health`。只有账户库、数据仓库和行情服务都初始化后,
`/api/health` 才返回 HTTP 200。反向代理或负载均衡必须使用就绪探针接流量,不能只判断端口已打开。

依赖安装严格使用 `pnpm-lock.yaml` 和 `uv.lock`;锁文件不一致时镜像构建会直接失败,不会回退到浮动版本。
Windows Docker Desktop 若提示 `HOME` 未设置,请在 `.env` 中把 `CODEX_HOME_HOST` 设置为主机
`.codex` 目录的绝对路径。未使用 Codex CLI 时也可以在部署版 Compose 中移除该只读挂载。

> ⚠️ **stock-sdk 插件默认不打包(合规考虑)**
>
> stock-sdk 数据源本质是抓取第三方财经网站(如东方财富)的行情接口,未经对方授权,可能违反其服务条款并涉及交易所行情版权问题。**出于合规考虑,Docker 默认构建不再内置 stock-sdk 插件依赖**。
>
> - **默认行为**:`docker compose up --build` 构建出的镜像**不含** stock-sdk,插件不可用。
> - **如确需启用**(自行承担合规责任):
>   ```bash
>   docker compose build --build-arg INCLUDE_STOCKSDK=1
>   docker compose up -d
>   ```
> - 启用后镜像会额外内置 Node.js 运行时并预装 stock-sdk 依赖,插件开箱即用。
> - **建议优先使用 TickFlow 等正规授权数据源。**

更新到新版本:

```bash
git pull
docker compose up --build -d
```

---

## 老 CPU 兼容(avx2/fma 缺失)

如果运行时报 `avx2`/`fma` 缺失,或进程 `exit 132`,说明 CPU 不支持 AVX2 指令集(常见于老 VPS)。解决:

- **Dev 源码启动**:在根目录 `.env` 设置后运行 `./dev.sh` 或 Windows 的 `.\dev.ps1`;即使已有 `.venv`,启动器也会同步兼容内核
- **Docker**:在根目录 `.env` 设置后执行 `docker compose up --build`

```ini
BACKEND_EXTRAS=legacy-cpu          # 兼容老 CPU
BACKEND_EXTRAS=legacy-cpu backtest # 兼容老 CPU + 回测依赖
```

手动启动源码时，也可以在 `backend/` 目录直接执行 `uv sync --extra legacy-cpu`。不要设置 `POLARS_SKIP_CPU_CHECK`，它只会隐藏警告，实际执行不支持的指令时仍可能崩溃。

### 回测依赖说明

vectorbt → numba 体积较大,作为可选 extras(`uv sync --extra backtest`)。macOS / Intel 无预构建 wheel 时需 `brew install cmake` 现场编译。

---

## 更新代码(已部署用户必读)

拉取新版本只需一条命令:

```bash
git pull
```

**整个 `data/` 目录都不纳入 git** —— 行情 K线、财务、自选、回测、监控记录,乃至概念/行业扩展数据,全部是程序运行时生成/拉取的用户数据,`git pull` 物理上无法影响它们。新用户首次启动时,概念/行业两份扩展数据会自动从远程接口拉取,无需任何手动操作。

> ⚠️ **切勿使用以下命令"解决冲突"或"清理",它们会一次性删光 `data/` 下所有未被 git 跟踪的数据:**
> - `git clean -fdx`(最危险,会删掉所有 `.gitignore` 忽略的文件)
> - `git reset --hard`
> - 直接删除整个项目文件夹重新 `git clone`
>
> 若 `git pull` 报冲突,通常是本地误改了被跟踪的文件,请先 `git stash` 暂存再 pull,或单独联系作者,不要直接执行上面的命令。

---

## 访问密码设置(公网部署必读)

面板部署在公网服务器时,首次设置访问密码有限制 —— **必须从本机或内网访问**,以防公网上陌生人抢先设置密码锁死你的面板。

如果你在公网浏览器直接打开页面,会看到提示:

> 首次设置密码仅允许本机或内网访问,请通过 SSH/本地浏览器操作

有两种方式解决,任选其一。

### 方式一:环境变量预置密码(最简单,推荐)

在 `.env` 文件(或 Docker / 系统环境变量)里设置 `AUTH_PASSWORD`:

```bash
AUTH_PASSWORD=你的密码
```

然后重启服务。启动时会自动:

1. 读取 `AUTH_PASSWORD`
2. 用 PBKDF2 哈希后写入 `auth.json`(`chmod 600`,只存哈希不存明文)
3. **之后这个环境变量就不再被读取** —— 是一次性的初始化

设完后即可用公网地址 + 这个密码正常登录。后续改密码请用页面 UI(`设置 → 修改密码`),不受环境变量影响。

**注意事项:**

- **密码至少 6 位**,否则会被跳过并记一条 warning 日志
- **仅在未设过密码时生效**。已设过密码后,改这里不会覆盖(避免重启时重置你在 UI 改的密码)
- `.env` 文件权限保持 `600`,**不要提交到 Git**
- 明文密码只存在于 `.env` / 环境变量中,落盘的是哈希,安全性等同 `auth.json`

**重置密码(忘密码时):** 删除或清空 `data/user_data/auth.json`,重启服务,会回到"未设密码"状态,此时 `AUTH_PASSWORD` 会重新生效。

```bash
rm data/user_data/auth.json   # 停服后执行,清空后重启
```

### 方式二:SSH 端口转发

不用改配置,在你**自己电脑**的终端执行(不是服务器上):

```bash
ssh -L 3018:127.0.0.1:3018 用户名@服务器IP
```

例如服务器是 `123.45.67.89`、用户名 `root`、面板端口 `3018`:

```bash
ssh -L 3018:127.0.0.1:3018 root@123.45.67.89
```

保持这个 SSH 连接**不要关**,然后在**自己电脑的浏览器**打开 `http://127.0.0.1:3018`。此时后端看到的客户端 IP 是 `127.0.0.1`(本机),能通过校验,正常显示设置密码界面。

**设完密码后**,SSH 连接可以断开 —— 密码已存进服务器,之后直接用公网地址 + 刚设的密码访问即可。

> 如果用 `PORT` 改过端口(比如 `PORT=8080`),两处都要替换:`ssh -L 8080:127.0.0.1:8080 root@IP`。

### 两种方式怎么选

| | 环境变量 | SSH 转发 |
|---|---|---|
| 操作 | 改一行配置 + 重启 | 一条 ssh 命令 |
| 需要改配置 | 是 | 否 |
| 适合 | Docker / 自动化部署 / 不熟 SSH | 临时设密码 / 能 SSH 到服务器 |
| 后续改密码 | UI(`设置 → 修改密码`) | 同左 |

推荐**方式一(环境变量)**,一次配置即可,Docker 部署尤其方便。

> 当前 C 端账户入口使用“姓名 + 电话 + 密码”和 HttpOnly 会话 Cookie。上面的 `AUTH_PASSWORD`
> 是旧版单用户部署兼容项,不会代替每个 C 端用户的独立账户。新部署不要把它当作用户注册密码。

### 原理说明

- **为什么限制本机/内网?** 面板部署到公网后,任何人都能访问 URL。如果不限制,攻击者可以在你之前打开页面、设置一个密码,把你的面板锁死。
- **本机/内网如何判断?** 后端检查客户端 IP 是否属于 `127.0.0.1 / ::1 / 10.x / 192.168.x / 172.16-31.x`。
- **SSH 转发为什么有效?** `-L` 把本机端口通过 SSH 隧道转发到服务器的 `127.0.0.1`,等同于在服务器本地访问,客户端 IP 变成 `127.0.0.1`,通过校验。
- **反向代理注意:** 若面板在 Nginx 等反代之后,需正确配置 `X-Forwarded-For` 头,后端据此取真实客户端 IP。

---

## C 端生产上线检查单

上线前必须逐项完成,未完成的项目不能用本地测试结果替代:

1. **HTTPS 与代理边界**:只对外开放 443;由可信反向代理终止 TLS;准确传递 `Host`、
   `X-Forwarded-For` 和 `X-Forwarded-Proto`;不得让公网客户端绕过代理直连 3018。
2. **跨域**:前后端同源时保持 `CORS_ORIGINS` 为空。确需分域时只填写明确的 HTTPS Origin,
   多个值用逗号分隔,不要填写 `*`。
3. **TeaJoin**:在服务器密钥管理或权限为 600 的 `.env` 中提供 `TEAJOIN_API_KEY`,并在
   `data/server_config.json` 选择 TeaJoin。上线前用业务健康接口确认标的、日线、实时、分钟、
   财务数据的权限和最新交易日,不能以空数组或默认零值作为成功。
4. **管理员隐藏页**:设置至少 16 字符的随机 `QINGSHU101_ADMIN_KEY`,并将
   `QINGSHU101_HOST` 精确设为管理子域名。代理层还应限制该子域名的访问来源。
5. **账户入口口径**:产品明确采用“姓名 + 电话 + 密码”直接创建或进入账户,不接短信验证码、
   邀请码或人工审批。电话只作为唯一账户标识,不代表系统已验证号码归属。运营和客服处理账户争议时,
   不能把该字段当作实名或号码持有证明。
6. **数据授权**:确认 TeaJoin 以及概念/行业成分数据允许在面向 C 端用户的产品中展示和再分发。
   未获书面授权的数据源不得通过启用抓取插件替代。
7. **备份与恢复**:定时备份整个 `data/` 到异机或对象存储,备份应加密并设置保留期。至少做一次
   隔离环境恢复演练,验证 `accounts.sqlite3`、会话、用户工作区和共享行情数据均能恢复。
8. **发布验证**:执行后端全量测试、前端生产构建、`docker compose config --quiet`,镜像构建和
   容器启动;确认 `/health` 与 `/api/health` 均为 200 后再接入流量。

建议的上线后检查:

```bash
curl -fsS https://你的域名/health
curl -fsS https://你的域名/api/health
docker compose ps
docker compose logs --since=10m app
```

注册接口已按客户端来源做持久化小时窗口限流,该限制在进程重启后仍保留。它只用于控制匿名创建账户的
资源消耗；生产环境仍应配置边缘层速率限制和异常注册监控,但不会增加短信或邀请码流程。
