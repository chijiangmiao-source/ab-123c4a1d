# 束线联锁 ioco 静止输出复核服务（仅依赖 Python 标准库）
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    IOCO_HOST=0.0.0.0 \
    IOCO_PORT=8080

WORKDIR /srv

# 应用代码、测试与 verify 脚本一并打入镜像
COPY app/ ./app/
COPY tests/ ./tests/
COPY verify/ ./verify/

# 构建检查：全部源码可编译
RUN python -m compileall -q app tests verify

EXPOSE 8080

# 容器内健康检查（不依赖 curl，使用标准库）
HEALTHCHECK --interval=5s --timeout=3s --start-period=3s --retries=10 \
  CMD python -c "import os,urllib.request,sys; \
url='http://127.0.0.1:%s/healthz' % os.environ.get('IOCO_PORT','8080'); \
sys.exit(0 if urllib.request.urlopen(url,timeout=2).status==200 else 1)"

CMD ["python", "-m", "app.server"]
