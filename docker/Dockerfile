FROM python:3.12-slim

# Отключаем интерактивный дисплей matplotlib (нет GUI в контейнере)
ENV MPLBACKEND=Agg \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# requirements.txt лежит в docker/ — пути COPY относительны build-context (корень проекта)
COPY docker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Создаём непривилегированного пользователя и передаём ему каталог с данными
RUN addgroup --system obd && adduser --system --ingroup obd obd \
    && mkdir -p /data && chown obd:obd /data

USER obd

# Данные монтируются снаружи: docker run -v /path/to/csvs:/data ...
VOLUME ["/data"]

ENTRYPOINT ["python", "analyze_obd.py"]
CMD ["--help"]
