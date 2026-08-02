FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app
COPY requirements.txt ./

# `playwright install --with-deps` uses Ubuntu package names (ttf-unifont, ...)
# that don't exist on Debian slim. Install the Debian runtime libs explicitly,
# then fetch ONLY the chromium browser (no --with-deps) into a world-readable
# path so the non-root `shot` user can launch it at runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libnss3 libnspr4 libdbus-1-3 libglib2.0-0 \
        libatk1.0-0 libatk-bridge2.0-0 libatspi2.0-0 \
        libcups2 libdrm2 libgbm1 libasound2 \
        libx11-6 libxcb1 libxext6 libxfixes3 libxdamage1 libxrandr2 \
        libxcomposite1 libxkbcommon0 libxshmfence1 \
        libpango-1.0-0 libcairo2 \
        fonts-liberation fonts-unifont \
    && pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install chromium-headless-shell \
    && chmod -R a+rX /ms-playwright \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY shot.py ./

RUN useradd -m -u 1000 shot && chown -R shot:shot /app
USER shot

CMD ["python", "shot.py"]
