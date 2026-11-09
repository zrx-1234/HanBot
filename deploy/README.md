# HanBot 部署指南

单用户自托管 Personal Agent。生产形态：caddy（443 HTTPS，自动签证书）+ backend（FastAPI + SQLite）。

## 前置条件（用户侧）

1. **域名 + DNS**：一条 A 记录指向 ECS 公网 IP（当前机器：106.14.247.165）。
2. **阿里云安全组**：放行 22/tcp（SSH）、443/tcp+udp（HanBot）。
   同机还有其他服务，保持放行：80（family-server）、8080（chileme）、5984（couchdb）。
   **不要放行 8081**（dev 端口，仅本机调试用）。
3. `deploy/.env` 从 `.env.example` 复制并填好密钥（见下）。

## deploy/.env 密钥说明

| 变量 | 说明 |
|---|---|
| `HANBOT_DOMAIN` | 你的域名，如 `han.example.com` |
| `HANBOT_SECRET` | 会话签名密钥，32+ 随机字符。可随时换（换后所有人需重新登录） |
| `HANBOT_DATA_KEY` | **库内密钥的 AES 主密钥，32+ 随机字符。一旦使用不可更换**——丢失/更换 = 库里存的 API Key 全部解不开。务必备份 |
| `HANBOT_USERNAME` / `HANBOT_INITIAL_PASSWORD` | 仅空库首次启动时创建用户用；之后改密直接改库或走设置页 |

生产模式（`HANBOT_SECURE_COOKIES=true`，默认）启动时强校验：弱/默认/过短密钥直接拒启。

## 本机端口布局（ECS：106.14.247.165）

| 端口 | 用途 |
|---|---|
| 22 | SSH（宿主服务） |
| 80 | 同机 family-server-nginx（**不属于 HanBot**） |
| 443 | **HanBot 生产入口（caddy，TLS-ALPN-01 自动签证书）** |
| 8080 | 同机 chileme（不属于 HanBot） |
| 5984 | 同机 couchdb（不属于 HanBot） |
| 8081 | HanBot **dev 栈**（caddy HTTP，仅调试，勿对公网放行） |

因为 80 被同机服务占用，生产 caddy 只发布 443：证书走 TLS-ALPN-01 验证（只需 443），
代价是 `http://` 明文访问不会被重定向到 `https://`——直接用 https:// 链接即可。

## 从 dev 栈切换到生产栈

dev 栈和 prod 栈共用 project name `deploy`，切换 = 重建容器：

```bash
# 1. 填好 HANBOT_DOMAIN（.env 里其他密钥已就绪）
# 2. 停 dev 栈
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml down

# 3. 起生产栈（不带 dev overlay；caddy 监听 443，自动签证书需要 DNS 已生效）
docker compose -f deploy/docker-compose.yml up -d --build
```

验证：`curl -I https://你的域名/api/health` 应返回 200，证书为 Let's Encrypt。

数据（SQLite 库、会话目录）在 `../data/`，dev 与 prod 共用，切换不丢数据。
backend 以 uid 1000 跑，改过代码后记得 `chown -R 1000:1000 data/`（root 编辑过的文件会破坏属主）。

## ufw 说明

本机 ufw 已启用（default deny incoming，放行 22/80/443/8080/5984）。
**注意 Docker 的已知行为：docker 发布的端口走 iptables NAT，不经过 ufw 的 INPUT 链**，
所以对容器端口而言，真正有效的公网闸门是**阿里云安全组**，ufw 保护的是宿主服务（SSH 等）。
收敛暴露面时以安全组为准。

## 新 ECS 初始化（若换机器重装）

1. `apt update && apt install -y docker.io docker-compose-v2 docker-buildx`（或官方源）
2. SSH 加固：`/etc/ssh/sshd_config` 设 `PasswordAuthentication no`、`PermitRootLogin no`（先确保普通用户 + 密钥登录已配好再改，否则锁死）
3. ufw：见上文
4. clone 仓库、配 `.env`、`docker compose -f deploy/docker-compose.yml up -d --build`
5. 数据迁移：打包 `data/`（含 SQLite）+ `.env`（含 DATA_KEY，二者必须成对备份）

## 备份（重要）

最小备份集 = `data/` 目录 + `deploy/.env`。丢失 `.env` 里的 `HANBOT_DATA_KEY`
等于丢失库里所有加密的 API Key——它们互为钥匙，成对备份、成对恢复。
