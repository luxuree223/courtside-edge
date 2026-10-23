FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY static ./static
RUN useradd --create-home courtside && mkdir /data && chown courtside:courtside /data
USER courtside
ENV EDGE_DB_PATH=/data/edge.sqlite3 EDGE_REQUIRE_AUTH=1 EDGE_AUTO_SYNC=1 EDGE_SEED_BETS=0
EXPOSE 8080
CMD ["python","-m","uvicorn","app.main:app","--host","0.0.0.0","--port","8080","--proxy-headers"]
