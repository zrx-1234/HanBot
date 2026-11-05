HanBot详细设计文档

    本文档对应requirement.md，是其实现层面的设计。文中所有"默认值"均指设置项里有默认配置、用户可改。

一、总体架构

    单机部署，全部组件跑在同一台ECS上，docker compose管理。整体结构：

                        用户浏览器 / Flutter APP
                                 │ HTTPS
                            Caddy（443）
                                 │
        ┌────────────────────────┼─────────────────────────┐
        │                     后端服务                        │
        │  ┌──────────┐  ┌──────────────┐  ┌────────────┐  │
        │  │ API层     │  │ WS推送       │  │ 定时调度     │  │
        │  │ (FastAPI) │  │              │  │ (记忆复盘等) │  │
        │  └────┬─────┘  └──────┬───────┘  └─────┬──────┘  │
        │       │   ┌───────────┴──────────┐      │         │
        │       │   │ 任务调度器（队列/并发上限）│      │         │
        │       │   └───────────┬──────────┘      │         │
        │       │      ┌────────┴─────────┐       │         │
        │       │      │ Agent执行引擎      │       │         │
        │       │      └──┬─────────┬─────┘       │         │
        │  ┌────┴────┐ ┌─┴──────┐ ┌┴─────────┐ ┌┴────────┐  │
        │  │ LLM网关  │ │ 工具系统 │ │ 记忆系统   │ │ 通知分发 │  │
        │  └────┬────┘ │(双面)   │ └──────────┘ └────┬────┘  │
        │       │      └────┬────┘                   │        │
        │  ┌────┴────┐ ┌────┴──────────────┐   ┌────┴─────┐  │
        │  │ 密钥管理 │ │ 沙箱管理器          │   │ ntfy服务 │  │
        │  └─────────┘ │ (调用宿主机Docker)  │   └──────────┘  │
        │             └────┬──────────────┘                  │
        └──────────────────┼─────────────────────────────────┘
                     ┌──────┴───────┐
                     │ Docker容器     │  每个任务一个，随任务生灭
                     │ (沙箱，见第七节) │
                     └──────────────┘
        持久化数据（宿主机目录，挂载进后端）：
        data/db/hanbot.db        SQLite数据库
        data/sessions/           各会话目录
        data/abilities/          已安装能力
        data/memory/             记忆文档导出快照
        data/backups/            备份包

    组件职责的一句话说明：
    Caddy只做TLS终止和反向代理。后端是一个进程内的单体（FastAPI + asyncio），内部分模块，不搞微服务，单人项目拆服务只会增加运维负担。沙箱容器是唯一在任务执行期间存在的额外进程。

二、技术选型

    后端：Python 3.12 + FastAPI + asyncio。理由：Agent生态（MCP客户端、社区SKILL示例、各类工具库）Python最厚；单人开发，框架越主流越好找人找资料。
    LLM调用：直接使用官方openai和anthropic两个SDK，各自指向用户配置的base_url。不引入litellm这类中间层，原因：容灾逻辑我们自己写在网关里（第八节），中间层反而黑盒；两个SDK已覆盖OpenAI和Anthropic两种格式，这就是需求的全部。
    数据库：SQLite（WAL模式）。单人使用，写入量极小，备份就是复制文件，省掉一个常驻服务。ORM用SQLAlchemy 2.0 async，建表语句保持标准SQL，将来要换Postgres成本很低。
    沙箱：宿主机Docker，python官方docker SDK（docker-py）管理容器生命周期。
    定时任务：APScheduler（进程内），用于记忆复盘、备份、配额扫描。
    网页端：React 18 + TypeScript + Vite。状态管理：zustand（WS推送的会话/任务状态）+ TanStack Query（REST请求）。样式用Tailwind。Markdown渲染用react-markdown，聊天流式按字增量追加。
    Android端（Phase 3）：Flutter，状态管理Riverpod，网络dio，WS用web_socket_channel，路由go_router。
    通知：ntfy自托管（docker镜像binwiederhier/ntfy），浏览器端用Notification API。
    代理与证书：Caddy（自动ACME续期）。

三、代码仓库结构

    HanBot/
    ├─ docs/                  需求与设计文档
    ├─ backend/
    │  ├─ app/
    │  │  ├─ main.py          FastAPI入口，启动时初始化调度器
    │  │  ├─ config.py        环境变量与路径
    │  │  ├─ db.py            引擎与建表
    │  │  ├─ auth/            登录、会话cookie、失败锁定
    │  │  ├─ api/             REST路由（sessions/tasks/chat/sources/settings/abilities/memories/usage/storage/backup）
    │  │  ├─ ws.py            WebSocket连接管理与事件广播
    │  │  ├─ orchestrator/    任务队列、调度器、TaskRunner（状态机）
    │  │  ├─ llm/             gateway.py + openai_adapter.py + anthropic_adapter.py + pricing.py
    │  │  ├─ tools/           工具注册表、内置工具、ask_user、凭据代理
    │  │  ├─ sandbox/         镜像构建、容器创建/执行/回收
    │  │  ├─ memory/          记忆存取、检索注入、记忆Agent
    │  │  ├─ abilities/       SKILL.md加载、（Phase 3）MCP客户端
    │  │  ├─ notify/          分发器 + ws/browser/ntfy三个通道实现
    │  │  └─ scheduler.py      APScheduler注册（复盘、备份、配额扫描）
    │  ├─ Dockerfile.sandbox  沙箱镜像定义
    │  └─ tests/
    ├─ web/                   React工程（src/api、src/store、src/pages、src/ws）
    ├─ app/                   Flutter工程（Phase 3才动工）
    └─ deploy/
       ├─ docker-compose.yml
       ├─ Caddyfile
       ├─ .env.example        APP_SECRET、初始密码、域名等
       └─ backup.sh

四、数据模型

    所有表主键均为INTEGER自增，另有各自的业务ID（uuid字符串）对外暴露。列名用英文，说明如下。时间统一存UTC时间戳。

    1. users：单用户。username，password_hash（argon2id），created_at。
    2. login_log：ip，ok，created_at。锁定判断用最近记录计算。
    3. settings：key/value（value为JSON）。存：系统提示词、回答风格、任务并发上限（默认2）、单任务最大步数（默认50）、单任务超时（默认30分钟）、单次bash超时（默认120秒）、沙箱内存上限（默认512M）、存储总配额、备份保留份数（默认14）、记忆注入预算（默认1500 token）、复盘时段（默认每日3:00）等。
    4. llm_sources：name，format（openai/anthropic），base_url，api_key_encrypted，models（JSON数组：模型名+单价），priority，enabled，status（ok/degraded），cooldown_until，last_error。
    5. sessions：uuid，title，created_at，updated_at，dir_path，archived。
    6. messages：session_uuid，role（user/assistant），content，meta（JSON，如附带的任务uuid），created_at。
    7. tasks：uuid，session_uuid，status（queued/running/awaiting/done/stopped/failed），title（从首条指令截取），created_at，started_at，ended_at，error，tokens_in，tokens_out，cost_estimate。
    8. task_steps：task_uuid，seq，type（llm_call/tool_call/tool_result/confirm_request/user_reply/model_switch/error/note），content（JSON，按type存不同结构），created_at。时间线即本表按序展示。
    9. abilities：uuid，kind（skill/mcp），name，desc，install_path，global_active，installed_at，enabled。
    10. memories：uuid，layer（core/profile/lessons/digest），title，content（Markdown），tags（JSON），status（active/pending/archived），source_task_uuid，use_count，last_used_at，created_at，updated_at。记忆提议与正式记忆同表，用status区分，不单独建提议表。
    11. usage_log：task_uuid，source_id，model，tokens_in，tokens_out，cost，created_at。每次LLM调用一行。成本看板从本表汇总。
    12. notifications：task_uuid，level（blocking/info/silent），title，body，status（sent/read），created_at。
    13. credentials：name，site，secret_encrypted，note。供凭据代理工具使用，密钥不进沙箱。

    会话目录布局：data/sessions/{session_uuid}/
    ├─ transcript.md          对话记录导出，每条消息后自动追加
    ├─ workspace/             沙箱挂载的工作目录，Agent产物落在这里
    └─ tasks/{task_uuid}/     每任务一个大文件产物的暂存（如有）
    同一会话内的多个任务共享workspace目录，与需求"每会话一个目录"一致；容器按任务创建但挂载同一workspace。

五、Agent执行引擎

    1. 任务的产生（懒创建）。用户在聊天框发消息，消息入库，启动一个Runner。若LLM本轮全程未调用任何工具、只回了文本，则本次是普通问答，不生成任务记录，界面上不出现状态灯。一旦LLM发起第一次工具调用，立刻创建task记录（status=running）并推送给前端显示状态灯。这样"聊天"和"任务"不需要用户手动区分，也不需要意图分类器。
    2. 若会话里存在awaiting状态的任务，用户的新消息默认视为对该任务的答复，路由给该Runner继续执行；除非用户显式点"新任务"。
    3. 单步循环。Runner伪代码：
    （1）组装上下文：系统提示词（核心人格 + 注入的active记忆，见第九节）+ 激活能力的索引（见第十节）+ 本会话最近消息窗口（超长时对最旧部分做压缩摘要）
    （2）向LLM网关发起流式请求，文本增量实时推WS；usage写入usage_log；本步写task_steps（type=llm_call）
    （3）若LLM返回tool_use：写task_steps（tool_call），执行工具，结果写task_steps（tool_result），回到（2）
    （4）若工具为ask_user：任务置awaiting，发阻塞级通知，Runner挂起（asyncio.Event等待），用户答复后写task_steps（user_reply），回到（2）
    （5）若LLM返回纯文本且无tool_use：任务完成，若此前创建了task则置done，发知会级通知
    （6）循环超过最大步数或总时长超限：任务置failed，通知用户，附已完成的中间结论
    4. 每个step先写库再执行。这样无论何时崩溃或强停，时间线都是完整的，这是"可回放"的基础。
    5. 强停。用户点停止：cancel对应的asyncio任务，销毁沙箱容器，task置stopped，时间线补一条note（"用户手动停止"）。已在途的LLM请求不再采纳结果。
    6. 崩溃恢复。后端重启时，扫描status=running/awaiting的任务：running的置failed（error="服务重启中断"），awaiting的保持awaiting（等确认状态不依赖进程存活，重启后仍可答复）。
    7. 并发控制。全局asyncio.Semaphore(并发上限)。超出的任务排队（status=queued），前端显示排队中。
    8. 工具错误的处理原则：工具执行失败不算任务失败，把错误文本作为工具结果还给LLM让它自己决定重试还是换路。只有LLM调用本身连续失败（触发网关降级仍无可用源）或超时才判任务失败。

六、工具系统

    工具分两个执行面，这是安全模型的核心：
    1. 沙箱面（在任务容器内执行）：bash（带单次超时）、read_file、write_file、list_dir。通过docker exec实现，工作目录限定/workspace。
    2. 后端面（在后端进程内执行，沙箱不可见内部细节）：
    （1）http_request：普通HTTP请求，不带任何凭据，给Agent查公开信息用
    （2）use_credential：按凭据名调用已保存凭据发请求，由后端完成签名/注入，请求和响应过一道大小限制，沙箱内代码全程接触不到密钥
    （3）ask_user：向用户提问/请求确认，参数含问题、可选的选项按钮列表
    （4）report：向任务时间线写一条备注，供用户观看进度
    3. 工具描述用JSON Schema生成，经适配器转成OpenAI/Anthropic各自的工具调用格式。
    4. Phase 3接入MCP：后端作为MCP client，把外部MCP server的工具经同一注册表暴露给Agent；MCP server以独立容器运行，不进任务沙箱。

七、运行沙箱

    1. 镜像：自建hanbot-sandbox镜像，基于python:3.12-slim，追加：curl、git、常用压缩解压、以及一个可配置的pip包清单（默认只装requests，清单在设置里改，改后自动重建镜像）。镜像随版本走，不做运行时安装，保证可复现。
    2. 每任务一容器。创建参数：挂载会话workspace为/workspace（rw），workdir=/workspace；用户1000非root；cap_drop=ALL；security_opt=no-new-privileges；pids_limit=256；memory上限可配；cpu配额默认1核；无privileged。
    3. 网络：Phase 1直接用默认bridge，允许出站（Agent查资料需要）。出口黑名单（如封内网段防SSRF）留到Phase 2，用独立的egress proxy容器实现。沙箱内不含任何API密钥（见第六节第2条）。
    4. 超时两级：单次bash调用默认120秒；整个任务默认30分钟。任一超时即停容器、任务置failed、发通知。
    5. 回收：任务结束（无论何种方式）容器即销毁。挂起的awaiting任务容器也销毁，答复后重新创建（workspace在宿主机，无状态丢失），这样不会留一堆空转容器占资源。

八、LLM接入与容灾

    1. 网关结构。统一入口gateway.chat(messages, tools, stream) → 返回内部统一事件流（text_delta / tool_call / usage）。两个适配器（openai_adapter、anthropic_adapter）负责：消息格式互转、工具schema互转、流式事件解析归一。模型切换时消息历史本来就是内部统一格式，换适配器即可，不存在格式漂移。
    2. 源健康判定。某源单次调用失败（429/5xx/超时/断连）立即重试一次；同源连续3次失败即标记degraded，冷却5分钟（可配），期间网关跳过它。额度用尽（402/429且响应指明quota）标记degraded并冷却到次日或用户手动恢复。认证失败（401/403）同样degraded，通知用户检查密钥。
    3. 选源策略。每次LLM调用前向网关要"当前源"：取优先级最高且status=ok的源。任务中途换源发生在步骤边界（两次LLM调用之间），符合需求"任务运行中只在当前源彻底不可用时才降级"。切换写task_steps（type=model_switch，含原因），前端时间线可见。
    4. 模型选择。全局设默认模型名；换源后若新源无同名模型，用该源models列表的第一个，并写进model_switch记录。
    5. 计费。每次调用的usage写usage_log，单价来自llm_sources.models配置，任务结束时汇总进tasks表。看板按日/按源/按模型/按任务出汇总，Phase 2实装界面。

九、记忆与自我进化

    1. 分层。core：人格与硬边界，只能用户在面板手改，Agent和记忆Agent都无权提议修改。profile：用户偏好与习惯。lessons：经验教训（某次失败怎么绕开的、某类任务该用什么流程）。digest：旧会话的摘要归档，主要供检索，注入优先级最低。
    2. 存储。正库在memories表（content是Markdown，本身即"文档"）；另设导出任务把active记忆定期快照到data/memory/目录按层分文件，双保险，也便于人工备份查看。这是"持久化成文档"的落点。
    3. 注入。任务启动时检索一次：core全量 + profile/lessons中与任务描述做关键词/标签匹配的条目（Phase 2先关键词，观察不够用再上sqlite-vec向量），按（匹配度、use_count、最近使用）综合排序，装入记忆注入预算（默认1500 token）为止，拼进系统提示词。被用到的条目use_count+1。不检索全量塞入，这是需求里"按一定策略组织"的具体化。
    4. 记忆Agent。APScheduler每日默认3:00跑一次（复盘时段可配）：取昨日新消息与新任务 + 当前active记忆，让LLM产出提议列表（严格JSON：新增条目/建议修订某条/建议归档某条，各附理由）。逐条写memories（status=pending）。同时做一份昨日会话的digest摘要写入digest层（digest不需要批准，它只是归档不是认知）。
    5. 批准流。待批准条目在记忆面板分栏展示，用户可批准（→active，下次注入生效）、驳回（→archived留痕）、或改完再批。用户也可直接在面板手写记忆（直接active）。全程没有任何未经批准的自我修改，符合"它提议、我批准"。
    6. 面板即信任面。所有active记忆对用户完全可见、可改、可删，这是与闭源产品拉开差距的地方，UI上要给它一级入口，不做埋藏。

十、能力系统

    1. 形态：第一阶段只支持SKILL.md式技能包。安装=后端从本地上传的zip或GitHub地址拉取，落到data/abilities/{name}/，登记abilities表。
    2. 装载方式（省token的关键设计）：激活的能力不全量注入提示词。任务启动时系统提示词里只放一张索引（每个技能一行：名字+一句话描述+文件路径），完整SKILL.md随会话目录只读挂载进沙箱（/skills/）。Agent判断需要时自己read_file读全文。这样装50个技能也不撑爆上下文。
    3. 激活两级：全局激活（abilities.global_active，进所有任务的索引）；会话激活（会话设置里临时开，只进该会话）。技能自带的脚本文件也在其目录里，沙箱可直接运行。
    4. MCP：Phase 3。后端MCP client连接独立容器运行的外部MCP server，其工具注册进统一工具表，同样走激活开关。

十一、通知与提醒

    1. 事件源：任务状态机迁移时产生通知（进入awaiting→blocking；done/failed/超时→info；普通step→silent只写时间线）。另有存储配额到90%的info通知。
    2. 通道与Phase：WS（页面在开时实时推，Phase 1）；浏览器Notification API（页面开着但不在前台，Phase 1）；ntfy（页面关了/手机端，Phase 2接入，自建ntfy容器，话题按级别分，blocking用high优先级）；邮件（通道抽象里预留实现位，不装也不影响）。
    3. 去重：同一任务同级别通知5分钟内不重发。用户在WS在线并已读的blocking通知，不再发ntfy（在线看过就不吵）。
    4. ntfy部署：docker容器一个，仅内网监听，由Caddy反代/{ntfy路径}对外，订阅需带登录态（Caddy转发校验），不搞公开topic。

十二、对外API

    REST（均以/api为前缀，cookie会话认证，SameSite=Strict + 自定义头防CSRF）：
    1. POST /auth/login、POST /auth/logout、GET /auth/session
    2. GET/POST /sessions、PATCH/DELETE /sessions/{uuid}（删除含目录，需confirm参数）
    3. GET /sessions/{uuid}/messages、POST /sessions/{uuid}/chat（发消息，返回可能产生的task_uuid）
    4. GET /tasks?session=、GET /tasks/{uuid}（含steps分页）、GET /tasks/{uuid}/steps
    5. POST /tasks/{uuid}/stop、POST /tasks/{uuid}/reply（答复确认）
    6. GET/PUT /settings
    7. GET/POST/PATCH/DELETE /sources、POST /sources/{id}/test
    8. GET /abilities、POST /abilities/install（zip上传或git url）、PATCH /abilities/{uuid}（激活开关）
    9. GET/POST/PATCH /memories（含pending条目）、POST /memories/{uuid}/approve、POST /memories/{uuid}/reject
    10. GET /usage/summary?range=7d&by=day|model|task
    11. GET /storage（配额与用量）、GET /backup/list、POST /backup/run、GET /backup/download/{file}
    12. 文件：GET /sessions/{uuid}/files（浏览workspace）、GET /sessions/{uuid}/files/download?path=（下载产物，路径校验限定在workspace内）

    WebSocket：GET /ws（认证后升级）。服务端→客户端事件（JSON，type字段区分）：
    message_delta（流式文本增量）、task_update（状态灯变更）、step_new（时间线新条目）、confirm_request（确认卡片）、notification（提醒）、storage_update。
    客户端→服务端：ping、task_stop、task_reply。

十三、网页端设计

    页面与路由：
    1. /login：登录页
    2. /：主布局。左栏会话列表（新建、搜索、删除）；中间聊天区；右侧可展开任务面板
    3. 聊天区：消息流（用户/Agent，Markdown+代码高亮），Agent消息内嵌任务卡片（状态灯+标题+当前动作一行字+展开时间线）、确认卡片（问题+按钮或输入框）、流式光标。会话内有awaiting任务时输入框旁提示"此消息将作为答复发送"
    4. 时间线：任务卡片展开后按step逐条显示，llm_call只显示摘要（模型+耗时+tokens），tool_call显示参数与结果（长内容折叠），model_switch高亮显示
    5. /settings/sources：源列表（优先级拖拽排序、连通性测试按钮、密钥只显示尾4位）
    6. /settings/general：系统提示词（含core记忆只读展示）、风格、各项默认值
    7. /abilities：已装能力列表、安装入口、两级激活开关
    8. /memory：记忆面板。顶部待批准区（红点提示数量），下方按四层分栏的active记忆，每条可看/改/删
    9. /usage：成本看板（趋势图+按模型/任务Top列表）
    10. /system：存储占用、备份列表与下载、一键备份

    实现要点：WS断线自动重连并拉取增量；流式渲染在delta批次rAF合并，避免每token一次setState；状态灯颜色即需求定义（蓝/黄/绿/红），排队中用蓝色加"排队"文案。

十四、Android端设计（Phase 3，Flutter）

    1. 与网页端共用同一套REST+WS，不加后端接口。登录用长期token（登录接口带remember参数返回token，存flutter_secure_storage），手机上不适合每次输密码。
    2. 状态管理Riverpod；网络dio（拦截器统一加token与401跳登录）；WS用web_socket_channel，前台保持连接。
    3. 通知：APP在前台走WS+应用内提醒；APP被杀或后台，靠ntfy兜底——Flutter端集成ntfy的长轮询订阅（Dart实现即可，几行HTTP），或直接引导用户装官方ntfy APP订阅自家服务器（两个方案都做：先支持官方ntfy APP当天可用，再在自研APP里内置订阅）。通知栏支持操作按钮（批准/拒绝）直接调task_reply REST接口，不用打开APP。
    4. 页面结构与网页端对齐：会话列表、聊天+任务卡片、时间线、记忆面板（手机上重点做好待批准的快捷批准）、设置。成本看板和文件浏览放次要入口。

十五、安全设计

    1. 登录：argon2id存密钥；同一IP连续失败5次锁15分钟；login_log留痕可查。
    2. 会话cookie：HttpOnly、SameSite=Strict、Secure；REST统一要求自定义头X-Requested-With作CSRF防御（跨站发起的简单请求带不上自定义头）。
    3. HTTPS：Caddy自动申请续期。注意：Let's Encrypt不签发纯IP证书，需要一个域名（见待定问题第1条）。
    4. 密钥保护：llm_sources与credentials的密钥字段AES-256-GCM加密落库，主密钥在deploy/.env（文件权限600，不进git），接口永不回显明文（尾4位除外）。沙箱内零密钥，见第六、七节。
    5. 容器面：沙箱容器按第七节加固。后端容器自身挂载docker.sock（管理沙箱需要），等于宿主机较高权限，这是单人自托管的已知取舍，缓解手段：后端容器非root运行、sock挂载只读不可行（需要写），接受风险但用防火墙和及时更新兜底。
    6. 主机面：ufw只开22（改默认端口、仅密钥登录）/80/443；fail2ban可选装（看一个IP疯狂打登录口时是否常见）；SSH禁密码登录。
    7. 输入限制：上传zip大小上限（默认50M）、bash输出截断（默认100K后截断）、http_request响应体截断，防单次调用撑爆上下文和磁盘。

十六、备份与运维

    1. 备份内容：data/整目录（数据库用sqlite的VACUUM INTO先出一致性快照再打包，避免tar到写一半的文件）。
    2. 每日备份：APScheduler触发backup.sh，产出data/backups/hanbot-YYYYMMDD.tar.gz，保留最近N份（默认14）自动清理，网页可查看列表、手动触发、下载。
    3. 恢复：停服务 → 解包覆盖data/ → 起服务。步骤写进deploy/README。
    4. 异地副本：单机部署最大的风险是整台机器没了。设计上提供下载，但要靠习惯把备份定期拽到本地一份；有对象存储（如OSS）的话加个rclone上传脚本的成本很低，留作可选配置。
    5. 日志：后端结构化日志按天滚动保留30天，含任务执行的关键审计事件（容器创建/销毁、强停、密钥代理调用）。
    6. 更新流程：git pull → docker compose build → up -d，数据库迁移用alembic（建表时就配好，别等第一次改表才补）。

十七、里程碑与任务拆解

    Phase 1（核心闭环，按依赖顺序）：
    M1 部署底座：compose（backend+caddy）跑通、登录、HTTPS上线。验收：手机浏览器能通过域名https登录进来。
    M2 配置底座：全部建表+alembic、settings与sources的CRUD、连通性测试按钮。验收：配上一个真实API源并测试通过。
    M3 Agent循环v1：LLM网关+单适配器、聊天流式、消息与llm_call落库、http_request工具（此阶段还没有沙箱，无bash）。验收：能流式问答，能问它"用http_request查某公开API然后总结"。
    M4 沙箱与任务态：hanbot-sandbox镜像、容器管理、bash/read/write/list工具、task懒创建+状态机+强停+时间线。验收：让它写个脚本统计workspace里的数据文件，全程时间线可回看。
    M5 确认闭环：ask_user、确认卡片、任务挂起/答复续跑、WS+浏览器通知（blocking级）。验收：完整跑一次"下指令→执行→等确认→答复→完成"。
    M6 界面完善：会话管理、任务列表与状态灯、时间线交互打磨、transcript导出。
    M7 系统管理：存储配额统计与展示、备份脚本与页面、登录锁定。
    M8 收尾上线：日志滚动、恢复演练（按文档真做一次恢复）、安全检查清单过一遍。

    Phase 2（记忆与容灾）：
    记忆Agent+每日复盘+记忆面板+注入检索；多源容灾与切换记录；成本看板；ntfy通道；能力本地安装+索引注入（SKILL.md）；alembic在M2就绪，本阶段起每个功能配测试。

    Phase 3（生态与移动端）：
    Flutter APP（先复用API，重点做ntfy通知与通知栏操作）；定时任务与条件触发（APScheduler对用户暴露配置界面，无会话也能起任务）；MCP外部服务器接入；多模态（视觉理解作为一个后端面工具实现，图片上传走消息附件）；能力市场完善（远程一键安装）。

十八、风险与对策

    1. 公网暴露面：整台机器只开三个端口，Web入口有登录+锁定，及时打安全更新。个人数据（会话、记忆）都在这台机器上，被入侵的代价高，这是自托管的固有代价，对策是备份异地化+最小暴露。
    2. 沙箱逃逸：容器隔离+资源限制+非root+cap全禁，执行的是AI生成代码，理论上仍可能有0day。对策：镜像极简（没有的东西无法利用）、不做多租户（只有自己的代码在里面跑）、出站异常流量在Phase 2的egress proxy里观测。
    3. 单机故障：每日备份+下载习惯/可选对象存储异地副本+ECS快照。
    4. LLM费用失控：每任务有步数与时长上限，usage_log逐笔记账；再加一个"单日预估费用超过阈值发info通知"的软闸（Phase 2）。
    5. 范围失控：以M8（Phase 1上线可用）为唯一目标，Phase 2/3的功能不在Phase 1的代码里"顺手预留"，只允许留文档（本文档即备忘）。

十九、待定问题

    1. 域名。HTTPS必须有域名（ACME不签IP证书），需要买一个（几十元/年，云厂商处注册即可），这是M1的前置条件。
    2. ECS规格：建议至少2核4G、40G系统盘。镜像+备份+若干会话产物，40G起步，跑起来后按实际增长再扩。
    3. 沙箱pip清单：默认只装requests，第一版上线后按实际用法增补。
    4. 复盘时段默认凌晨3:00，跑起来后看账单和效果再调。
    5. 邮件通道是否要启用：通道抽象已预留，什么时候想用什么时候填SMTP配置。
