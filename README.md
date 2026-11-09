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

### 1.模型服务

将云端模型的信息填写在backend目录下的.env文件中，先复制一份.env.example文件，然后按照里面的三个键填写模型信息，然后把文件名改为.env

### 2.后端（8000）

后端技术栈使用FastAPI，在backend目录下执行命令 `python -m venv .venv` 创建虚拟环境并激活虚拟环境，再执行命令 `.\.venv\Scripts\python.exe -m pip install -r requirements.txt` 安装依赖，最后在backend执行命令 `.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir app` 启动后端

### 3.前端（5173）

前端技术栈使用Vue3+Vite，先执行`npm install`命令，安装前端相关依赖，然后在frontend根目录执行 `npm run dev` 即可启动前端