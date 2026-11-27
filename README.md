# KnowledgeFlow · 部门知识库试点

同一个站点可以服务多个部门，但每次上传、检索和问答都只针对一个**已授权知识库**。Vue 3 + FastAPI；PDF 原件、任务和发布记录用 SQLite 持久化；本地 BGE 编码，每个知识库独立使用 Chroma collection。适合单服务器内部试点，不是多副本高可用部署。

## 本机运行（PowerShell）

项目开发环境为 Python 3.13、Node 24。下面的命令从仓库根目录开始；已有虚拟环境和依赖时可跳过安装。**已有 `.env` 不要覆盖。**

```powershell
cd backend
python -m venv .venv  # 仅首次、且 .venv 不存在时
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python.exe -m app.manage init
```

`init` 仅首次创建访问配置；打印财务管理、人事管理、财务只读三个**独立随机令牌**，仅显示一次，不会覆盖已有账号。不要把令牌放进 Git、URL 或截图。默认配置在 `backend/data/enterprise/access.json`，只存令牌的 SHA-256 摘要。接入真实数据前请收紧操作系统目录权限、分别安全分发令牌，或换用下文的 SSO。

1. 本地准备 `BAAI/bge-small-zh-v1.5` 的 Hugging Face 缓存。在线构建机可先运行 `.\.venv\Scripts\hf.exe download BAAI/bge-small-zh-v1.5`；离线服务器需预置同一缓存。应用仅从本地加载，不在首个业务请求中下载模型。
2. 两个初始知识库均为 `local_only`。启动你信任的、**不转发云端**的本地兼容推理服务，在 `backend/.env` 填 `LOCAL_LLM_BASE_URL=http://127.0.0.1:8081/v1` 与正确的 `LOCAL_LLM_MODEL`；如服务需要，另填 `LOCAL_LLM_API_KEY`。没有本地生成模型仍可入库和搜索，但不能完成有证据的问答。旧的 `LLM_*` **不会**作为本地模式的后备。
3. 准备前端并启动：

```powershell
cd ..\frontend
npm ci
cd ..
.\start_all.bat
```

用浏览器打开 `http://localhost:5173`。输入令牌 → 选知识库 → 上传带文本的 PDF（≤10 MiB）→ 等待“已发布”后提问。刷新后试点令牌需要重新输入；切库/退出会清空原工作区的消息和引用。可用两个浏览器窗口分别验证财务、人事账号，用财务只读账号验证无法写入。

## 授权与数据边界

- 每个 KB 配置为 `{"name":"财务制度","policy":"local_only","readers":["finance-read"],"writers":["finance-write"]}`。用户组与读/写角色均由服务端配置；写角色包含读权限。可用 `RAG_ACCESS_FILE` 指定配置文件绝对路径。更改后对下一次请求生效，建议原子替换文件。缺失/无效配置拒绝访问；撤销试点令牌可移除对应用户。不要复用已退役 KB 的 ID 给另一个部门。
- `local_only`：查询改写和答案生成只连接显式配置的回环推理地址，不走环境代理，不跟随重定向，不回退云端。应用只能约束自己的连接，机密部署还应限制推理服务自身的外联。
- `approved_cloud`：**仅在业务允许外发后**，由管理员把指定 KB 的策略改为此值，并配置 `LLM_BASE_URL`（显式 HTTPS）、`LLM_MODEL`、`LLM_API_KEY`。如果打开页面时显示“仅本地”，但策略随后变更，页面会拒绝这次问答并提示刷新确认，不会静默外发。此库的问题可用于改写，命中的正文、文件名、页码可用于生成；其他库仍使用自己的策略。未知库、无权库或不存在的目标文档不会触发模型调用。
- 旧 `backend/data/chroma` **不会被读取、迁移或删除**。不猜测旧文档归属；请确认授权后用原 PDF 上传到对应的新库。原 `/api/chat`、`/api/search`、`/api/documents` 不再对外提供。

## 部署与 SSO

- 使用 `npm run build` 生成前端静态资源。生产站点同源提供页面和 `/api/`；开发时 Vite 将其代理到后端。不要把开发服务器或 Uvicorn `--reload` 直接暴露给员工。
- **单进程**启动：从 `backend` 运行 `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1`（使用本项目虚拟环境）。`RAG_DATA_DIR` 可指向专用持久卷，默认 `backend/data/enterprise`。进程锁防止两个内嵌 Chroma 写入器共享数据目录。不要跨主机挂共享目录或启动多副本；扩容前先拆独立向量服务与队列。
- SSO 模式：Nginx + oauth2-proxy 或等效企业网关负责 TLS、OIDC 登录和会话。网关必须验证身份，**覆盖** `X-RAG-User` / `X-RAG-Groups`，注入独立的 `X-RAG-Gateway-Key`，且后端不能从客户端直连。组值是可信的、逗号分隔的组标识，必须与配置匹配。后端设 `RAG_AUTH_MODE=proxy`，`RAG_GATEWAY_KEY` 使用密码管理器生成的至少 32 个随机 ASCII 字符；此模式不接受试点令牌。无需把真实员工写进 `users`；映射 IdP 组即可。改变这些环境变量后重启服务。
- `deploy/nginx-sso.conf.example` 是网关模板，不包含真实证书或密钥。在身份提供方注册回调 `https://<站点>/oauth2/callback`，配置 oauth2-proxy 的 issuer、client ID/secret、允许的组织、组声明、Secure/HttpOnly 会话 Cookie、`--reverse-proxy=true` 和 `--set-xauthrequest=true`，确认 `/oauth2/auth` 确实返回用户和组。上线前用本组织真实 IdP 验收登录、组撤销、会话过期和退出。API 的非只读 HTTP 方法在此模式还需 `X-RAG-Request: 1`（前端已发送）；不要给跨域站点开放 CORS。
- `/api/health` 是存活检查；`/api/ready` 检查访问策略、模型路由配置、SQLite、工作线程、本地 BGE 加载与向量存储心跳，依赖不可用返回 503。**不**对生成模型发起付费探测。请求日志含请求 ID、身份、知识库、状态和耗时；检索/入库/模型调用另记录阶段耗时，模型有上报时记录 token，不记录问题、答案或片段正文。生产环境不要打开第三方 SDK 的正文调试日志。
- 文件以服务账号可读的形式持久化。磁盘/备份加密、保留期、入口限流、推理服务出口限制及恢复演练需按企业策略配置。做一致性备份的简单方式是停掉该实例后备份整个数据目录（目录数据库、向量、配置），单独保管模型缓存与密钥，再在隔离位置恢复并跑抽检。

## 入库与接口约定

试点模式使用 `Authorization: Bearer <令牌>`。`GET /api/session` 返回本人的授权 KB 与权限。以下相对路径都以 `/api/kbs/{kb_id}` 为前缀：

| 接口 | 权限 | 行为 |
|---|---|---|
| `GET /documents?limit=50&offset=0` | 读 | 分页返回当前已发布版本，由文档目录查询，不遍历所有片段。 |
| `POST /documents/upload` | 写 | multipart 字段 `file`；原件与任务提交后返回 `202` 和 `job_id`、`document_id`。 |
| `GET /jobs/{job_id}` / `POST /jobs/{job_id}/retry` | 读 / 写 | 查询 `queued/running/ready/failed`；重试失败任务。 |
| `POST /search` | 读 | `{"query":"报销期限","top_k":5}`，可指定 `document_id`；只检索本库已发布版本。 |
| `POST /chat` | 读 | `{"question":"报销期限是多久？"}`；选择本库模型，改写失败回到原问题。资料按优先级装入上下文，引用编号无效或缺失则拒答。 |
| `DELETE /documents/{document_id}` | 写 | 下线文档、删除原件记录、持久化安排清理所有版本的向量。 |

同一库内相同 PDF 字节去重，即使改名也返回原任务；不同知识库互不去重。同名不同内容生成新版本，旧版本在新索引全部写完前仍然可检索；失败不会覆盖旧版。未发布片段不进入搜索。进程重启自动重排中断任务，确定性块 ID 避免重复。历史内容的重复上传不隐式回滚当前版本。只支持文字 PDF，无 OCR；按页/段/句切分，目标约 350 个 embedding token，来源保留页码和版本。

## 回归测试和质量基线

从 `backend` 运行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
# 可选：同一条双部门集成测试换成真实的本地 BGE；生成端依然拦截，无云调用。
$env:RAG_TEST_REAL_BGE='1'
.\.venv\Scripts\python.exe -m pytest -q tests/test_enterprise.py::test_two_department_workflow
Remove-Item Env:RAG_TEST_REAL_BGE
```

测试只使用临时目录和合成材料。`evaluation/cases.example.jsonl` 给出标注格式，不是企业业务成绩。建议业务方准备 50–100 个脱敏问题，覆盖制度编号、跨页、历史版本和无答案问题；先把对应的脱敏 PDF 放进专用评测库。用只读试点身份，把令牌通过环境变量 `RAG_EVAL_TOKEN` 注入，不要放在命令行参数中：

```powershell
.\.venv\Scripts\python.exe -m app.evaluate evaluation/cases.example.jsonl --kb finance --k 5
# 加 --answers 才测生成；获准云端的库还必须显式加 --allow-cloud。
```

输出正确页命中率 Hit@K、首个正确页倒数排名 MRR@K；测生成时另报无答案题的拒答率及答案引用正确页的比例。引用页正确不等于结论得到原文支持，需抽样人工核对。不要在没有业务基线的情况下把演示数据的结果当作上线阈值。

## 网站 AI 客服

客户入口为 `/support/`，员工入口仍是 `/`；生产构建分别输出两份 HTML。客服默认关闭，不会读取或发布财务、人事等内部资料。

**首次启用（从 `backend` 运行）：**

```powershell
.\.venv\Scripts\python.exe -m app.manage init-support
```

该命令可创建客服专用配置，也可在已有的有效配置上添加专用 `customer-help` 库和 `customer-agent` 坐席。已有账号和授权不变；不会自动公开任何文档，重复执行不会重置密码。请保存首次打印的坐席令牌；企业 SSO 下将实际坐席组配置为该库的 `writers`。客服查询和人工工单不使用员工登录令牌。

1. **准备客服资料。** 启动开发服务（根目录 `start_all.bat`）。用坐席身份打开 `http://localhost:5173/`，进入「客户帮助中心」，上传已经过审核的业务 PDF（如使用说明、售后政策）。入库成功后打开「进入客服坐席台 → 对客资料」，填写客户可见标题并确认发布。发布的是**完整文档的这个版本**，不要上传客户档案或订单明细。换版需重新审核，撤下/删除后不再参与新的客户问答，已交付的答案不能撤回。
2. **从客户角度试用。** 无需登录，打开 `http://localhost:5173/support/`。AI 只检索对客发布的当前版本，返回回答和可核对的标题、页码、短摘录；最近两条客户提问只用于理解追问，刷新后聊天清空。无资料、模型无法回答或引用无效时可改走人工，不会自动创建工单。默认用 `LOCAL_LLM_*`；如果管理员将专用库改为 `approved_cloud`，访客必须显式同意才向指定云模型发送问题、最近提问和相关公开资料。没有配置生成模型也可以测试人工流程。
3. **验证人工转接。** 客户点击「转人工」，编辑问题、同意交给坐席并提交。坐席在「待回复」中填写答复并结单，客户到「工单进度」刷新查看。不是实时聊天，不会自动查询订单、执行退款或发送邮件/短信。只提交用户确认的描述，不附完整聊天记录。查询必须持有私密随机凭证，工单号不能代替；浏览器仅在本标签页的会话存储记住凭证，支持另行复制保存。服务端只存凭证摘要。工单自创建起 30 天内可查，到期不可查；启动或新建工单时删除过期的数据库记录（不代表底层介质安全擦除），备份另设保留期。
4. **正式部署。** 为客户设置独立域名和 TLS，仅开放 `/support/`、静态资源以及四个 `/api/customer/` 路由。模板在 `deploy/nginx-customer.conf.example`；员工站点继续使用 SSO。应用按来源及实例限额，最多并发两个客服推理请求。只信任本机反向代理设置的客户端地址，不对公网开放后端端口。多副本需将限流改为共享实现。不要记录请求正文、授权头或工单查询凭证；公开模型需独立设置服务商预算。用真实脱敏咨询校验正确率、拒答和人工处理时间后再放量。
