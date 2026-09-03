FROM python:3.12-slim

WORKDIR /app

COPY server/requirements.txt server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt

COPY server/ server/
COPY web/ web/
COPY packs/ packs/

# The card library + crash snapshots live outside the app dir so a plain
# volume mount at /data is all persistence needs (§3.3, §6.4 of the spec).
ENV CARDBOX_DB_PATH=/data/cardbox.db
ENV CARDBOX_SNAPSHOT_DIR=/data/snapshots
RUN mkdir -p /data

WORKDIR /app/server
EXPOSE 8420

CMD ["uvicorn", "cardbox.app:app", "--host", "0.0.0.0", "--port", "8420"]
