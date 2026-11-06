# HanBot 开发日志

按时间倒序或正序追加，每会话一条。字段：日期、做了什么、裁定（对 design.md 的偏离）、遗留、"以后"栏（想去但本里程碑不做的事）。

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
