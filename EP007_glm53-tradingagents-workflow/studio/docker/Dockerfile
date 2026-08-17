# TradingAgents Studio 独立镜像
FROM python:3.10-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai \
    STUDIO_CONFIG=/etc/studio/studio.yaml \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY docker/entrypoint.sh /entrypoint.sh
RUN pip install --no-cache-dir . && sed -i "s/$//" /entrypoint.sh && chmod +x /entrypoint.sh

# 数据落点：/data/studio（SQLite + 导出物），原项目数据卷只读挂在 /data/ta
VOLUME ["/data/studio"]

ENTRYPOINT ["/entrypoint.sh"]
CMD ["cron"]
