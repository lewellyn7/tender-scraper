#!/usr/bin/env python3
"""
清洗 content_preview 字段，去掉导航/页脚噪音

清洗模式:
- 以 "APP下载" 开头：截取到 "信息时间" 之前
- 含 "当前位置" 面包屑：去掉 "当前位置： 首页 > ... > 信息时间：[日期] 字号: ..." 整段
- 含 "字号:"：截断到 "字号:" 之前
- 含 "我要打印 关闭"：截断到 "我要打印 关闭" 之前
- 末尾含 "版权所有"：截断
- 末尾含 "百度统计"：截断
- 清洗后长度 < 30：保留原值（避免空化）
"""
import re
import psycopg2
from psycopg2.extras import execute_batch

PWD = 'root123'
conn = psycopg2.connect(host='postgres', user='root', password=PWD, dbname='tender_scraper')
cur = conn.cursor()

# 1. 找出所有受污染的记录
print("=" * 60)
print("扫描受污染的 content_preview...")
cur.execute("""
  SELECT id, content_preview
  FROM projects_cqggzy
  WHERE content_preview IS NOT NULL
    AND content_preview != ''
    AND (
      content_preview LIKE 'APP下载%'
      OR content_preview LIKE '%当前位置%'
      OR content_preview LIKE '%字号%'
      OR content_preview LIKE '%我要打印%'
      OR content_preview LIKE '%版权所有%'
      OR content_preview LIKE '%百度统计%'
    )
""")
rows = cur.fetchall()
print(f"找到 {len(rows)} 条受污染的记录")

# 2. 清洗函数
def clean(text):
    if not text:
        return text
    original = text
    # 模式 1：以 "APP下载" 开头，去掉 "APP下载 公众号 ... 关于我们" 前缀
    if text.startswith('APP下载'):
        # 先截到 "信息时间" 或 "字号:" 之前（去掉面包屑 + 标题块）
        m = re.search(r'信息时间[：:]', text)
        if not m:
            m = re.search(r'字号[：:]', text)
        if m:
            # text[:m.start()] 含 "APP下载 ... 关于我们 当前位置： 首页 > ... > 项目名"
            # 项目名在 当前位置 ... 之后才出现 — 保留最后一段项目名
            head = text[:m.start()]
            # 在 head 中找 "关于我们"（导航结束标志）
            m_nav = re.search(r'关于我们\s*$', head)
            if not m_nav:
                m_nav = re.search(r'当前位置[：:]', head)
            if m_nav:
                # head[:m_nav.end()] = "APP下载 ... 关于我们" 或 "当前位置：之前"
                # head[m_nav.end():] = 面包屑
                # 取面包屑最后一段（项目名）作为正文
                breadcrumb = head[m_nav.end():].strip()
                if breadcrumb:
                    # 面包屑如 "> 交易信息 > 工程招投标 > 项目名"
                    last_part = re.split(r'[>＞]', breadcrumb)[-1].strip()
                    if last_part and len(last_part) > 4:
                        text = last_part
                    else:
                        text = breadcrumb
                else:
                    text = ''
            else:
                text = head
        else:
            # 没有 信息时间/字号 - 找 "当前位置" 后取面包屑
            m = re.search(r'当前位置[：:]', text)
            if m:
                breadcrumb = text[m.end():].strip()
                if breadcrumb:
                    text = re.split(r'[>＞]', breadcrumb)[-1].strip()
    
    # 模式 2：含 "字号:" - 截断到 "字号" 之前
    text = re.sub(r'\s*字号[：:].*$', '', text, flags=re.DOTALL)
    # 模式 3：含 "我要打印 关闭" - 截断
    text = re.sub(r'\s*我要打印\s*关闭.*$', '', text, flags=re.DOTALL)
    # 模式 4：含 "版权所有" - 截断
    text = re.sub(r'\s*版权所有.*$', '', text, flags=re.DOTALL)
    # 模式 5：含 "百度统计" - 截断
    text = re.sub(r'\s*百度统计.*$', '', text, flags=re.DOTALL)
    # 模式 6：含 "主办单位" - 截断
    text = re.sub(r'\s*主办单位.*$', '', text, flags=re.DOTALL)
    # 模式 7：含 "国家部委网站 行业相关网站" - 截断
    text = re.sub(r'\s*国家部委网站.*$', '', text, flags=re.DOTALL)
    
    # 模式 8：去掉子菜单列表（重复出现的页面菜单项）
    # 工程招投标: "招标公告 邀标信息 答疑补遗 中标候选人公示 中标结果公示 合同签订基本信息公示 合同变更基本信息公示 相关公告 终止公告"
    # 政府采购:   "采购公告 单一来源公示 答疑变更 采购结果公告"
    submenu_patterns = [
        r'\s+招标公告\s+邀标信息\s+答疑补遗\s+中标候选人公示.*$',
        r'\s+采购公告\s+单一来源公示\s+答疑变更\s+采购结果公告.*$',
        r'\s+采购公告\s+单一来源公示\s+变更公告\s+采购结果公告.*$',
    ]
    for pat in submenu_patterns:
        text = re.sub(pat, '', text, flags=re.DOTALL)
    
    # 模式 9：处理 "项目名 项目名 子菜单" 结构 - 找重复项目名后的子菜单位置
    # 如果 text 含同名重复，去掉第二次出现后的子菜单
    # 例: "忠县乌杨...答疑补遗文件 忠县乌杨...答疑补遗文件 招标公告 邀标信息..."
    # 这种"项目名 项目名 子菜单" 模式: 找第二次 "项目名" 之后到 "子菜单" 之前
    submenu_start = re.search(r'\s+(招标公告|采购公告)\s+(邀标信息|单一来源公示)\s', text)
    if submenu_start:
        # 看 submenu_start 之前是否有重复项目名
        before = text[:submenu_start.start()]
        # 找 before 末尾的"项目名"
        # 简单方法：直接截到 submenu_start 之前 + 保留一些正文（取 submenu_start 之前 30 字符）
        text = before.rstrip()
    
    # 标准化空白
    text = re.sub(r'[\s\u3000]+', ' ', text).strip()
    
    return text

# 3. 处理每条
updates = []
no_change = 0
shorter = 0
for row_id, cp in rows:
    cleaned = clean(cp)
    if cleaned != cp and len(cleaned) >= 30:
        updates.append((cleaned, row_id))
        shorter += 1
    elif cleaned == cp:
        no_change += 1
    else:
        # 清洗后太短 - 保留原值（标记但不更新）
        no_change += 1

print(f"\n准备更新 {len(updates)} 条 ({no_change} 条无变化或太短)")

# 4. 展示样本
print("\n=== 清洗样本 (前 5 条) ===")
for new_cp, row_id in updates[:5]:
    cur.execute("SELECT content_preview FROM projects_cqggzy WHERE id = %s", (row_id,))
    old_cp = cur.fetchone()[0]
    print(f"id={row_id}")
    print(f"  OLD: {old_cp[:120]}")
    print(f"  NEW: {new_cp[:120]}")
    print()

# 5. 批量 UPDATE
if updates:
    print(f"\n=== 执行批量 UPDATE ({len(updates)} 条) ===")
    try:
        execute_batch(
            conn.cursor(),
            "UPDATE projects_cqggzy SET content_preview = %s WHERE id = %s",
            updates,
            page_size=200,
        )
        conn.commit()
        print(f"✅ 成功更新 {len(updates)} 条")
    except Exception as e:
        conn.rollback()
        print(f"❌ UPDATE 失败: {e}")

# 6. 验证
print("\n=== 清洗后统计 ===")
cur.execute("SELECT COUNT(*) FROM projects_cqggzy WHERE content_preview LIKE 'APP下载%'")
print(f"  仍以 APP下载 开头: {cur.fetchone()[0]}")
cur.execute("SELECT COUNT(*) FROM projects_cqggzy WHERE content_preview LIKE '%当前位置%'")
print(f"  仍含 当前位置: {cur.fetchone()[0]}")
cur.execute("SELECT COUNT(*) FROM projects_cqggzy WHERE content_preview LIKE '%字号%'")
print(f"  仍含 字号: {cur.fetchone()[0]}")

cur.close()
conn.close()
print("\n✅ 完成")
