FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 TIMEZONE=Asia/Karachi
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY today_trader ./today_trader
# settings, picks journal and .env live in /data so they survive restarts
WORKDIR /data
ENV PYTHONPATH=/app
VOLUME ["/data"]
ENTRYPOINT ["python", "-m", "today_trader"]
CMD ["bot", "majors", "XAUUSD", "BTCUSDT", "ETHUSDT", "-i", "1m", "--picks-from", "all", "--picks-every", "5", "--top", "3", "--min-winrate", "0.6"]
