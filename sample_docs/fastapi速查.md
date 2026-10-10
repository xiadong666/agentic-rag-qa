# FastAPI 开发速查（示例知识库）

FastAPI 是一个基于 Python 类型提示的现代 Web 框架，支持异步路由与自动生成 OpenAPI 文档。

## 路由与参数

使用装饰器定义路由：`@app.get("/items/{item_id}")`。路径参数写在花括号中，查询参数直接写在函数签名里。依赖注入通过 `Depends` 实现，可用于鉴权、数据库会话等场景。

## 请求与响应模型

FastAPI 深度集成了 Pydantic v2。定义一个继承 `BaseModel` 的类作为请求体，框架会自动完成 JSON 解析、字段校验和类型转换，校验失败时返回 422。响应模型用 `response_model=` 指定，可自动过滤多余字段。

## 文件上传

上传接口需要安装 `python-multipart`。`UploadFile` 以流式方式读取文件，应该分块写入磁盘而不是一次性 `read()` 到内存，避免大文件撑爆内存。同时要做扩展名白名单与大小限制。

## 异步与性能

路由函数可以声明为 `async def`，配合 `asyncio` 处理 IO 密集任务；CPU 密集操作应丢给线程池（`asyncio.to_thread`），避免阻塞事件循环。生产环境使用 uvicorn 多 worker 或 gunicorn 启动。

## 部署

开发环境：`uvicorn app.main:app --reload`。生产环境推荐 Docker 打包，多进程运行，并用 Nginx 反向代理；注意配置 CORS、限流、密钥管理与健康检查端点。
