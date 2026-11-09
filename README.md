# KnowledgeFlow · 本地 RAG 文档知识库

一个可以在本机完整运行的 PDF 知识库问答系统：上传 PDF 后自动解析、切分、向量化并写入 ChromaDB；提问时先做语义检索，再把检索结果交给任意 OpenAI 兼容的云端服务的LLM生成带来源引用的回答。

后端为 FastAPI，前端为 Vue 3 + Vite，模型服务通过 OpenAI 兼容接口接入；默认配置下，文档、向量请求都在本机处理，问答在云端模型处理

## 环境要求

| 组件 | 本项目实测版本 | 检查命令 |
|---|---|---|
| Python | 3.13.13 | `backend\.venv\Scripts\python.exe --version` |
| Node.js | 24.18.0 | `node -v` |
| npm | 11.16.0 | `npm -v` |

## 快速开始

### 1. 配置模型服务（可选本地，端口 8081）

把 `backend/.env.example` 复制成 `backend/.env`，按下表填三个键：

| 键 | 云端填什么 | 本地填什么 |
|---|---|---|
| LLM_BASE_URL | https://<厂商>/v1 | http://127.0.0.1:8081/v1 |
| LLM_API_KEY | 你的真实 key | 任意值 |
| LLM_MODEL | <厂商模型 id> | <llama-server 的模型标识> |

本地方式需要自己先启动 llama-server（参数参考：`--host 127.0.0.1 --port 8081 -m <模型>.gguf`）；
云端方式不需要启动任何本地服务。

**成功标志**：完成第 2 步后，在页面上提一个问题，答案里出现 `[S1]` 这类引用。

### 2.后端（8000）

后端技术栈使用FastAPI，在backend目录下执行命令 `python -m venv .venv` 创建虚拟环境，再执行命令 `.\.venv\Scripts\python.exe -m pip install -r requirements.txt` 安装依赖，最后在backend执行命令 `.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir app` 启动后端

### 3.前端（5173）

前端技术栈使用Vue3+Vite，先执行`npm install`命令，安装前端相关依赖，然后在frontend根目录执行 `npm run dev` 即可启动前端