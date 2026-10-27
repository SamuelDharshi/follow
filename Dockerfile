FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY follow follow
COPY docs docs
ENV FOLLOW_DB=/data/follow.db FOLLOW_EXPORT_DIR=/data/export
