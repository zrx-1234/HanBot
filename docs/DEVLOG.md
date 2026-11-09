# HanBot 开发日志

按时间倒序或正序追加，每会话一条。字段：日期、做了什么、裁定（对 design.md 的偏离）、遗留、"以后"栏（想去但本里程碑不做的事）。

---

## 2026-11-09 会话6：M1.5 生产就绪（AI 侧完成，等域名 DNS + 备案）

做了什么：M1.5 的机器侧全部完成。① caddy 生产配置改 443-only（本机 80 被同机 family-server-nginx 占用，证书签发走 TLS-ALPN-01 只需 443；代价 http 不重定向 https，单用户直接用 https 链接）+ HTTP/3（443/udp）；② 登录密码改 16 位强随机（argon2 改库；root-only 文件保存，用户上机自取）；③ HANBOT_SECRET 轮换为真随机 43 位；④ ufw 启用（放行 22/80/443/8080/5984，拒 8081）；⑤ deploy/README.md 部署文档（密钥说明、端口布局、dev→prod 切换、备份最小集、新机初始化）；⑥ **发现并修复 M2 遗留 bug：base compose 从未把 HANBOT_DATA_KEY 注入容器**——容器实际用 config.py 的 dev 兜底值加密 API Key，.env 真 key 从未生效，生产切换会导致全部已存密钥解不开。修复：compose 补必填注入 + .env INITIAL_PASSWORD 轮换（原值 dev-password 在 secure 黑名单）+ 存量密文一次性迁移（2 个源全部回验通过）+ dev 栈重建实测登录与方舟连通均过；⑦ 域名 hanbot.cc 已定并写入 .env，prod secure 校验 + caddy validate（hanbot.cc, 443-only）均通过。提交 180e0c7 + 3999551，push。

裁定（对 design.md / plan.md 的偏离）：
- 生产 caddy 只发布 443（design 默认 80+443）：80 被同机服务占用不可动，TLS-ALPN-01 方案成立但放弃 http→https 自动重定向。
- DATA_KEY 漏传属于 M2 建栈时的实现 bug 而非设计偏离（design §15.4 本意就是 .env 真 key 加密），修复时存量密文从 dev 兜底 key 迁到真 key——与"DATA_KEY 一旦使用不可更换"的语义自洽：真正生效的 key 从今天起是真 key。
- HANBOT_INITIAL_PASSWORD 在 .env 中的值从 dev-password 轮换为随机值：该值仅空库引导用，现库已有用户，无行为影响（登录密码走库）。
- ufw 启用但明确认知：docker 发布端口走 iptables NAT 不经 ufw INPUT 链，公网闸门实际是阿里云安全组；ufw 保护宿主服务（SSH 等）。README 已写明。

遗留：
- 【用户侧】域名 hanbot.cc：DNS A 记录 → 106.14.247.165；阿里云 ICP 备案（大陆 ECS 上域名 web 服务必需，未备案 80/443 域名流量会被拦）；安全组放行 443/tcp+udp。
- 【用户侧】SSH 加固待用户公钥（PasswordAuthentication no / PermitRootLogin no 尚未执行——公网 22 密码可 root，当前机器最大风险项）。
- 切生产操作：dev 栈 down → prod compose up -d --build → 验收（手机 https 登录）。DNS 生效后随时可做。
- M2 验收时的 bce-v3 第二源（用户新增）已随迁移覆盖。

以后：
- 登录密码 root-only 文件仅单份（/root/hanbot-login-password.txt），用户应转移至自己的密码管理。
- caddy 证书签发失败告警（DNS 未生效就起 prod 栈会反复重试）——起栈前先 dig 确认。

---

## 2026-11-09 会话5：M3 Agent 循环 v1（完成 + 活栈验收通过）

做了什么：M3 全部完成并活栈验收通过。四块实现（全部 TDD）：① llm/types.py 内部统一消息格式（UMessage + Text/ToolUse/ToolResult 块，thinking 块不入格式——lessons 2.4，为 M4 换模型消毒预留）；② anthropic_adapter（消息/工具 schema 互转、流式事件归一，InputJSONDelta partial_json 拼装，恒以 MessageDoneEvent 收尾）；③ gateway（选源 priority 最小且 enabled、lessons 2.3 重试参数：500ms 基础/指数退避 32s 上限/25% 抖动/10 次预算/连续 3 次失败熔断 degraded、401 等不重试、usage_log 记账含 cached 双列）；④ tools（registry + http_request：URL≤2000、拒内嵌凭据、域名含点、60s 超时、10MB 截断、重定向链写进结果——lessons 3.7 校验链）+ agent/runner（while 状态机 CALL_LLM→EXEC_TOOLS，先落库再广播，用户消息 API 层先落库——lessons 2.1）+ ws.py（按 session 广播流式 delta）+ chat_routes（会话 CRUD + chat 后台 task 执行）+ chat.html 极简聊天页（原生 JS，含 WS 流式打字光标、tool_use/tool_result 渲染）。测试 102 项全绿（pytest + ruff + mypy）。

活栈验收（真实方舟源，glm-latest）：① 纯文本问答——"7*6"答 42，消息按 user→assistant 序落库；② 工具闭环——"用 http_request 访问 httpbin.org/get 然后告诉我 origin IP"，四条消息按序落库（user→assistant(tool_use)→user(tool_result)→assistant 总结），origin IP 正确识别为本机公网 IP；③ usage_log 记账。验收中发现一个真 bug：方舟 Coding 端点在 message_start 事件的 usage.input_tokens 恒为 0，真实值随 message_delta.usage 送达（官方 anthropic 端点则相反），导致 tokens_in 全部记 0——修复为 delta.usage 取到非零 input_tokens 才覆盖（两边兼容），活栈复测 tokens_in=598 正确落库。提交 def0888（M3 主体）+ 5263075（usage 修复），push origin main。

裁定（对 design.md / plan.md 的偏离）：
- 聊天前端用极简静态页 chat.html（原生 JS 单文件，复用 M1 登录页模式）而非提前动 React——完整 React UI 是 M6 范围，M3 验收只需"能流式问答"。页面挂在 /chat，登录页入口加了"进入聊天"。
- anthropic SDK 2.6.0 的流事件实际类名是 Raw*（RawMessageStartEvent 等），at.MessageStartEvent 是其别名，isinstance 判断两边等效——探测脚本用类名字符串匹配曾误导排查方向。
- message_delta.usage 的 input_tokens 语义：方舟把它当权威值（start 恒 0），官方端点不含该字段；适配器取"非零才覆盖"策略兼容两者。

遗留：
- 浏览器端到端验收（用户在 http://106.14.247.165:8081/chat 看流式打字）——API/WS 层验收已过（curl + 测试套件），页面操作待安全组放行后用户自测。
- 阿里云安全组放行 8081/tcp 仍未确认（M2 遗留，用户侧操作）。
- 登录弱口令未换（M2 遗留，公网放行前应处理）。
- M1.5 上生产（域名/HTTPS/安全组收敛）——等用户资源。

以后：
- chat.html 的 WS 断线重连已有雏形（1.5s 重试），多标签页/离线消息缓冲留给 M6。
- 会话列表只有 title 没有 updated_at 排序外的管理（重命名/删除），M6。
- 上下文窗口是简单最近 50 条（design P2 压缩摘要）。

---

## 2026-11-08 会话4：M2 验收完成（真实源连通 + 探测适配修复）

做了什么：M2 正式验收通过。用户配置真实源（火山方舟 anthropic 格式，/api/coding 端点，glm-latest），测试按钮返回成功。过程发现并修复三类问题：① 方舟 Coding 端点无 /v1/models 列表接口（返回 401 误导），anthropic 探测改用 max_tokens=1 的轻量 /v1/messages 请求；② 方舟版本段不在 base 结尾（/api/coding），探测加双候选路径回退（{base}/v1/messages 404/405 再试 {base}/messages，401 等其余状态码直接定论不重试）；③ 方舟对不存在的模型名回 404 UnsupportedModel（与路径 404 无法区分），探测模型名改用该源配置的真实模型。修复 test_auth 锁定窗口竞态（argon2 5 次校验纯 CPU 约 2.3s > 2s 窗口，首次失败滑出窗口漏锁——窗口改 30s + 改库时间戳模拟过期，不真等）。装 docker-buildx 0.30.1，compose build 恢复可用；完整栈起在宿主 8081（80 被同机 family-server-nginx 占用）。测试 63 项全绿（pytest + ruff + mypy），活栈验收 {"ok":true,"detail":"连通正常"}。

裁定（对 design.md / plan.md 的偏离）：
- M2 验收在 dev 栈（http://IP:8081）完成而非"ECS 生产形态"（M1.5 未做，域名未到位；plan.md 说"从 M2 起所有里程碑的验收都在 ECS 上做"——本机就是那台 ECS，但走的是 dev compose + 8081 端口，非 443 域名形态）。
- anthropic 连通性探测语义变化：成功消息不再报"模型数"（messages 探测拿不到列表），只报"连通正常"。
- 阿里云安全组需放行 8081/tcp（用户侧操作，已告知；M1.5 上线后应关闭）。

遗留：
- 浏览器端到端验收（用户在 http://106.14.247.165:8081/settings 点测试按钮）——API 层验收已过，页面操作待用户确认安全组放行后自测。
- M1.5 上生产（域名、DNS、HTTPS、ufw/SSH 加固、安全组收敛）——等用户资源。
- 登录密码仍是 dev 弱口令（dev-password），公网放行 8081 前应换强密码（改密界面是 M6 范围，现阶段改 .env 无效——密码只在空库引导时生效，需直接改库）。
- 下一步：M3 Agent 循环 v1（LLM 网关 + anthropic 适配器优先——用户 Key 是方舟 anthropic 格式，即 plan.md 决策点 1 已定）。

以后：
- settings 页面的"编辑源"入口（现在只能删除重建）。
- 通用改密流程/界面（M6 或提前）。

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
