FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY argus/ argus/
COPY config/ config/

RUN useradd -ms /bin/bash argus
USER argus

CMD ["python", "-m", "argus"]
