from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware

from dotenv import load_dotenv

# 加载 .env 文件到环境变量（必须在导入其他模块之前）
load_dotenv()

from backend.routers import news, favorite, users, history, ai_chat
from backend.services.news_scheduler import start_scheduler, stop_scheduler
from backend.utils.exception_handler import register_exception_handlers


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动实时新闻调度器，关闭时优雅停止。

    调度器是后台常驻任务，不会阻塞启动流程
    （首次抓取在后台跑，接口立即可用）。
    """
    await start_scheduler()
    try:
        yield
    finally:
        await stop_scheduler()


app = FastAPI(lifespan=lifespan)

#注册异常处理器
register_exception_handlers(app)
#跨域资源共享是一种浏览器安全机制。
# 用于允许运行在一个源的web应用，通过浏览器向另一个源的服务器发起跨域HTTP请求，并在服务器授权的前提下获取资源
#同源条件：协议，域名，端口
origins=[
    "http://localhost",
    "http://localhost:8080",
    "http://localhost:3000",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],#允许所有源
    allow_credentials=True,#允许带cookie
    allow_methods=["*"],#允许的请求方法
    allow_headers=["*"],#允许的请求头
)



#挂载
app.include_router(news.router)
app.include_router(users.router)
app.include_router(favorite.router)
app.include_router(history.router)
app.include_router(ai_chat.router)

# 挂载静态文件目录（头像上传）
import os
uploads_dir = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(uploads_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")

@app.get("/")
async def root():
    return {"message": "Hello World"}


if __name__=='__main__':
    import uvicorn
    uvicorn.run("main:app",reload=True,host="localhost",port=8000)
