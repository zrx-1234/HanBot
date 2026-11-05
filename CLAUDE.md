# HanBot

单用户自托管 Personal Agent。文档链：docs/requirement.md（做什么）→ docs/design.md（怎么做）→ docs/plan.md（按什么顺序）。动手前先读本文件和 DEVLOG.md。

## 开发环境（Windows + Docker，严禁裸机装 Python 依赖、严禁裸机跑后端）

```bash
# 起全部服务（本地开发，http://localhost）
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml up -d --build

# 跑测试（容器内）
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml run --rm backend pytest -q tests

# lint + 类型检查
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml run --rm backend sh -c "ruff check . && mypy app"

# 日志 / 停止
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml logs -f backend
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml down
```

依赖变更后需重新 build。deploy/.env 不入库（从 deploy/.env.example 复制）。

## 纪律

1. 测试不绿不提交：pytest + ruff + mypy 全过才算完成。TDD：先写测试、亲眼看它红。
2. 一次开发会话只做当前里程碑内的事。Phase 2/3 的念头记进 DEVLOG.md 的"以后"栏，不写进代码。
3. 新依赖必须 == 锁版本，且先核实版本真实存在再用。
4. docs/orig_requirement.md 是原始需求备份，不许改。
5. 对 design.md 的任何偏离都是裁定，必须记 DEVLOG.md。
6. 会话结束前追加 DEVLOG.md：做了什么 / 裁定 / 遗留。
7. 完成声明前先实际验证（跑命令、看输出），没有证据不说话。
