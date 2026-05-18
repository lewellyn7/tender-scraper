#!/bin/bash
# 修复 cqggzy 'tmp' 标题：从详情页提取真实标题

DB_HOST=$(docker exec tender-scraper-web env | grep DB_HOST | cut-d= -f2)
DB_PORT=$(docker exec tender-scraper-web env | grep DB_PORT | cut-d= -f2)
DB_USER=$(docker exec tender-scraper-web env | grep DB_USER | cut-d= -f2)
DB_PASS=$(docker exec tender-scraper-web env | grep DB_PASSWORD | cut-d= -f2)
DB_NAME=$(docker exec tender-scraper-web env | grep DB_NAME | cut-d= -f2)

echo "连接信息: host=$DB_HOST port=$DB_PORT db=$DB_NAME"

# 获取所有待修复URL
URLS=$(docker exec tender-scraper-postgres psql -U root tender_scraper -t -c "SELECT url FROM projects_cqggzy WHERE title LIKE '待修复-%'")

echo "找到 $(echo "$URLS" | wc -l) 条待修复记录"

for url in $URLS; do
    url=$(echo $url | tr -d ' \n')
    # 用 curl 抓取 raw HTML，提取真实标题
    real_title=$(curl -s "$url" | grep -o '<h3 class="article-title">[^<]*</h3>' | head -1 | sed 's/<[^>]*>//g')
    
    if [ -n "$real_title" ] && [ "$real_title" != "tmp" ]; then
        # 修复标题
        docker exec tender-scraper-postgres psql -U root tender_scraper -c "UPDATE projects_cqggzy SET title = '\$real_title' WHERE url = '\$url' AND title LIKE '待修复-%'" 2>/dev/null
        echo "✅ $real_title"
    else
        # 尝试从 full_content 恢复
        restored=$(docker exec tender-scraper-postgres psql -U root tender_scraper -t -c "SELECT LEFT(full_content, 100) FROM projects_cqggzy WHERE url = '\$url'" 2>/dev/null | head -1 | xargs)
        echo "❌ 无法获取: $url"
    fi
done