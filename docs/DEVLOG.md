# HanBot 开发日志

按时间倒序或正序追加，每会话一条。字段：日期、做了什么、裁定（对 design.md 的偏离）、遗留、"以后"栏（想去但本里程碑不做的事）。

---

## 2026-11-05 会话1：仓库初始化 + M1 部署底座（进行中）

做了什么：进行中。

裁定：
- main 只放既有 docs，代码在 m1-bootstrap 分支开发。
- M1 含极简静态登录页（M3 React 上线后保留为兜底）。
- M1 用 metadata.create_all 建基线表，alembic 在 M2 收编。
- DB 层暂用同步 SQLAlchemy，M2 切 async。
- pip 默认阿里云镜像源。

遗留：无。

以后：无。
