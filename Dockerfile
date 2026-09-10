# ==================== 第一阶段：依赖安装 ====================
FROM python:3.12-slim AS builder

WORKDIR /app

# 安装构建依赖，并将 Python 依赖安装到独立目录。
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    default-libmysqlclient-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m pip install --no-cache-dir --prefix=/install -r requirements.txt


# ==================== 第二阶段：运行镜像 ====================
FROM python:3.12-slim

WORKDIR /app

# Python 服务日志直接输出到容器日志，并避免生成字节码文件。
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# 只复制运行时依赖，避免把构建工具带入最终镜像。
COPY --from=builder /install /usr/local

COPY . .

# 创建上传目录
RUN mkdir -p backend/uploads

# 暴露端口
EXPOSE 8000

# 容器编排可据此判断 API 是否已经启动。
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/', timeout=3)"

# 启动命令
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]