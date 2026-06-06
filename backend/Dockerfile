FROM python:3.12-slim

WORKDIR /app

# Install system deps for Playwright + pdfplumber
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir -e . --break-system-packages

# Install Playwright Chromium for JS-heavy scraping fallback
RUN playwright install chromium --with-deps

COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
