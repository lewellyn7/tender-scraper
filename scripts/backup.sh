#!/bin/bash
# PostgreSQL + ChromaDB 备份脚本
# 用法：./scripts/backup.sh [backup_name]

set -e
BACKUP_NAME=${1:-"backup_$(date +%Y%m%d_%H%M%S)"}
BACKUP_DIR="./backups/$BACKUP_NAME"
mkdir -p "$BACKUP_DIR"

echo "[$(date)] Starting backup: $BACKUP_NAME"

# 1. PostgreSQL 备份
echo "[$(date)] Backing up PostgreSQL..."
docker compose exec -T postgres pg_dump -U root -d tender_scraper -F c -f /tmp/pg_backup.dump 2>/dev/null || \
  docker compose exec postgres pg_dump -U root -d tender_scraper -F c -f /tmp/pg_backup.dump
docker compose cp postgres:/tmp/pg_backup.dump "$BACKUP_DIR/pg_backup.dump"
echo "[$(date)] PostgreSQL backup: $BACKUP_DIR/pg_backup.dump"

# 2. ChromaDB 备份 (Docker volume)
echo "[$(date)] Backing up ChromaDB..."
docker run --rm \
  -v tender-scraper_scraper-data:/source \
  -v "$BACKUP_DIR/chromadb":/backup \
  alpine tar czf /backup/chromadb.tar.gz -C /source chromadb
echo "[$(date)] ChromaDB backup: $BACKUP_DIR/chromadb.tar.gz"

# 3. SQLite 备份
echo "[$(date)] Backing up SQLite..."
cp ./config/tender_scraper.db "$BACKUP_DIR/tender_scraper.db" 2>/dev/null || echo "SQLite not found"
echo "[$(date)] SQLite backup: $BACKUP_DIR/tender_scraper.db"

# 4. 清理旧备份 (保留最近 7 个)
echo "[$(date)] Cleaning old backups..."
ls -t "$BACKUP_DIR" | tail -n +8 | xargs -I {} rm -rf "$BACKUP_DIR/{}" 2>/dev/null || true

echo "[$(date)] Backup complete: $BACKUP_DIR"
echo "Backup contents:"
ls -lh "$BACKUP_DIR"
