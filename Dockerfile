FROM python:3.11-slim

# Базовые пакеты
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates tzdata && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Установим зависимости отдельно для кеша
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код и ассеты
COPY app.py ./app.py
COPY assets ./assets

# Не запускаем как root
RUN useradd -m appuser
USER appuser

EXPOSE 8000
ENV PYTHONUNBUFFERED=1

# Быстрый стек: uvloop + httptools уже в uvicorn[standard]
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", \
     "--loop", "uvloop", "--http", "httptools", "--workers", "10"]
