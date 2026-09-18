FROM python:3.12-slim
# 基础镜像的发布日期会滞后于 Debian 安全更新：构建时先装上已发布的安全修复，
# 否则镜像漏洞门禁会被“上游镜像落后”而非本仓库的决策所驱动。
# 代价是镜像不再只由 tag 决定；可复现性通过 SBOM 与镜像摘要保留。
RUN apt-get update \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md /app/
COPY src /app/src
COPY alembic.ini /app/alembic.ini
COPY alembic /app/alembic
RUN pip install --no-cache-dir .
ENV PYTHONUNBUFFERED=1
CMD ["uvicorn", "returnops.main:app", "--host", "0.0.0.0", "--port", "8000"]
