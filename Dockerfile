FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY sentinel/ sentinel/
COPY config/ config/

RUN useradd -ms /bin/bash sentinel
USER sentinel

CMD ["python", "-m", "sentinel"]
