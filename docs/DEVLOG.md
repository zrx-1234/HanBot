# HanBot 开发日志

按时间倒序或正序追加，每会话一条。字段：日期、做了什么、裁定（对 design.md 的偏离）、遗留、"以后"栏（想去但本里程碑不做的事）。

---

## 2026-11-07 会话3：M2 配置底座（代码完成，验收差最后一步）

做了什么：M2 基本完成。全部 13 张表建模（users/login_log/settings/llm_sources/sessions/messages/tasks/task_steps/abilities/memories/usage_log/notifications/credentials）；alembic 收编（0001 基线= M1 两表，0002 = 新 11 表，init_db 改为迁移驱动：新库直跑、M1 遗留库 stamp 0001 后升级，幂等）；DB 层切 async（asession_scope，同步 session_scope 仅供迁移与测试断言）；AES-256-GCM 密钥加密（crypto.py，scrypt 派生 + 随机 nonce + GCM 完整性校验）；GET/PUT /api/settings（默认值合并、类型/范围/HH:MM 校验）；/api/sources 全套 CRUD + POST /{id}/test 连通性测试（openai → {base}/models，anthropic → {base}/v1/models，httpx.MockTransport 注入不打真网）；HANBOT_DATA_KEY 启动强校验（secure 模式拒弱值）；极简 settings.html 配置页 + 登录页入口。测试 61 项全绿（pytest + ruff + mypy），活栈 API 验收全过（匿名 401、登录、settings 合并持久、密钥全程不泄漏只回显尾4位、不可达源测试按钮返回原因、PATCH 换密钥、删除）。

裁定（对 design.md / plan.md 的偏离）：
- 本会话在 ECS 生产机上直接开发（此前计划是 Windows 开发机；现实是代码就在这台机器上）。期间处理了环境问题：磁盘扩容 30G→50G（growpart+resize2fs）、docker-compose v2.23→2.40（旧版 API 1.43 被新 daemon 拒）、装 buildx 缺失用 legacy builder 手动 build、镜像经 DaoCloud 拉（Docker Hub 直连慢/被墙，M1 已有先例）。
- lessons 缺口#1/#2 已补进 design.md §4.11（usage_log 加 cached_tokens/cache_creation_tokens）与 §4.7（tasks.origin）；§4.4 补 models JSON 结构与 priority 语义（数字越小越优先）。
- llm_sources 连通性测试语义：成功清 last_error/cooldown，失败只记 last_error，不动 status（degraded 语义留给 M3 网关运行时管理）。
- DATA_KEY 加密格式：base64(nonce(12B)+ct+tag)，scrypt(n=2^14) 派生，固定盐 + AAD。解密失败（换 key/损坏）在列表接口降级为 hint="…????" 不 500，测试接口返回 500 明确报错。
- settings 存储：未知键 422 拒绝（白名单校验），DEFAULTS 在代码里（design §4.3 的全部默认值）。
- 仓库文件属主 chown 1000:1000（容器 appuser 需写 pytest/ruff 缓存）。

遗留：
- 【明天第一件事】`docker compose ... build backend` 被 buildx 缺失挡住（legacy builder 可用手动 build，compose build 走不了）——要么装 buildx 插件，要么 CLAUDE.md 记录用手动 build。compose build 验证被用户打断未完成。
- caddy:2.8.4-alpine 镜像经 DaoCloud 拉取未完成（慢），完整栈（含 80 端口页面）未起。栈已 down，backend 单独验收过。
- 用户浏览器验收 M2 界面（http://localhost/settings）：未做（等栈起来 + 用户）。
- M2 验收标准"界面配好一个真实 API 源，测试按钮返回成功"需要用户提供真实 API Key。
- 会话结束未 git 提交（M1 在 m1-bootstrap 分支；本会话改动未提交）——纪律要求测试全绿才提交，测试已全绿，明天提交并补全分支策略。

以后：
- DATA_KEY 轮换流程文档化（设计上不可轮换，需要明确告知用户）。
- settings.html 的系统提示词/风格编辑区（当前页面只做了 sources 管理，general 设置走 API）。

---

## 2026-11-05 会话1：仓库初始化 + M1 部署底座（已完成）

做了什么：M1 全部完成并通过验收。骨架（FastAPI+Dockerfile+compose）、caddy 双配置（prod 域名 / dev :80）、SQLite WAL + users/login_log、登录/登出/会话（argon2id + itsdangerous 签名 cookie + 空库引导）、同 IP 失败限次锁定、CSRF 中间件（变更类请求必须带 X-Requested-With）、极简静态登录页。测试 29 项全绿（pytest + ruff + mypy），活栈 curl 验收全过，用户浏览器验收通过。全分支评审（新鲜视角子代理）发现 1 Critical + 6 Important + 11 Minor，Critical/Important 已全部修复（含一个活栈验收时新发现的同秒连续失败漏计 bug），Minor 记档延后。

裁定（对 design.md / plan.md 的偏离）：
- main 只放既有 docs，代码在 m1-bootstrap 分支开发；不建 linked worktree。
- M1 含极简静态登录页（M3 React 上线后保留为兜底）。
- M1 用 metadata.create_all 建基线表，alembic 在 M2 收编。
- DB 层暂用同步 SQLAlchemy，M2 切 async。
- pip 默认阿里云镜像源；caddy 镜像经 DaoCloud 镜像源拉取（Docker Hub 直连被墙）。
- 锁定语义：锁定期内尝试不计不续（固定 15 分钟窗，贴合 design §15.1）；连续失败以最近一次成功为界（按 id 判序，同秒不漏计），成功不删除失败记录（保审计）。
- backend 容器不固定 IP，只有 caddy 固定（uvicorn 信任边界用）。
- 生产模式（secure_cookies=true）启动校验：弱/默认密钥与默认初始密码直接拒启；dev 模式不校验。
- deploy/.env 成为必填（compose `:?` 语法），缺失拒启。
- plan.md M1 的"空ntfy位"未落地：P2-2 直接上真 ntfy，不放假占位。

遗留：
- M1.5 上生产（域名、ECS、HTTPS、ufw/SSH 加固）——等用户资源。
- 11 项 Minor 延后（完整清单见当时会话的 ledger 与评审报告；关键项：/docs 公开暴露、dev 依赖进生产镜像、logout 仅客户端撤销、429 无 Retry-After）。

以后：
- Phase 2 拆分生产镜像（不含 pytest/ruff/mypy）。
- logout 服务端撤销（或文档化 secret 轮换流程）。
- 登录页首屏 /session 失败时的兜底提示。

---

## 2026-11-06 会话2：Claude Code 源码研究 → docs/claude-code-lessons.md

做了什么：读 E:\ZZZProjects\ClaudeCodeStudy（Claude Code 34 章源码分析），三路并行精读（05-09 章主循环/系统提示词/压缩/缓存/thinking；10-17 章工具协议/bash/文件族/问询/Agent/任务模型/Coordinator/cron；18-21、23、24、31、34 章 MCP/权限/hooks/skills/传输/bridge/memory/架构模式），合并提炼写成 docs/claude-code-lessons.md：方法论 15 条 + 按 HanBot 子系统的技术方案（参数照抄、design.md 节号映射、里程碑标注）+ 不抄清单（13 项）+ 反面教训速查（24 条）。未精读章节 00-04、22、25-30、32-33（CLI/终端产品形态为主，与 HanBot 相关度低；25 章上游代理在 P2 多源容灾时可回看）。

裁定：无对 design.md 的偏离——本文档是研究笔记，不改动设计。文档第十二节列出 11 条 design.md 待补缺口，动工对应里程碑时逐条裁定并入（其中 usage_log 缓存列、tasks.origin 列两条建议 M2 建表时就加，省迁移）。

遗留：
- docs/claude-code-lessons.md 第十二节 11 条缺口，按各自补进时机处理（最早的两条在 M2）。
- 研究未覆盖章节中，25 章（DirectConnect 与上游代理）P2 做 LLM 多源时值得回读一次。
