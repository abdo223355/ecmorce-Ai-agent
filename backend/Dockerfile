FROM python:3.12-slim
WORKDIR /app
RUN useradd -m -u 1000 app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY novacart_backend ./novacart_backend
COPY entrypoint.sh .
RUN mkdir -p /app/keys && chown -R app /app
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/health')"
ENTRYPOINT ["sh", "/app/entrypoint.sh"]
