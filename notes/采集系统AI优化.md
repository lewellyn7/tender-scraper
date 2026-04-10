# 采集系统 AI 智能化优化方案

> **编制角色：** AI 工程师  
> **编制时间：** 2026-04-07  
> **系统现状：** 基于 asyncio + Playwright 的政府采购/工程建设信息采集系统，当前使用 `ConcurrencyScheduler` 实现基础并发调度  

---

## 📊 现状分析

### 现有架构
```
┌─────────────────────────────────────────────────────────┐
│  ConcurrencyScheduler (并发调度器)                       │
│  ├── SafetyLevel 分组 (READ_ONLY/WRITE/DANGER)           │
│  ├── Priority Queue (优先级 1-10)                         │
│  ├── Semaphore 控制 (10/3/1)                             │
│  └── Retry + Timeout                                     │
├─────────────────────────────────────────────────────────┤
│  Crawler Layer                                           │
│  ├── CQGGZYCrawlerV3 (重庆工程建设)                      │
│  └── CCGPCrawlerV3 (重庆政府采购)                        │
├─────────────────────────────────────────────────────────┤
│  Browser Layer: StealthBrowser (反检测)                  │
└─────────────────────────────────────────────────────────┘
```

### 当前不足
| 维度 | 当前状态 | 差距 |
|------|---------|------|
| 调度 | 固定优先级，静态配置 | 无自适应、无学习 |
| 异常 | 被动重试，无预测 | 无模式识别、无自动诊断 |
| 质量 | 无评估体系 | 无完整性/准确性/时效性打分 |
| 扩容 | 人工配置 | 无预测、无弹性 |
| 查询 | 无 | 完全缺失 |

---

## 一、智能调度与优先级算法

### 1.1 动态优先级引擎

**现状：** 任务优先级由提交时静态指定，无法根据运行时状态调整。

**优化方案：**

```
优先级_score = w1×信息时效性 + w2×来源可靠性 + w3×采集成本 + w4×历史成功率 + w5×用户需求强度
```

| 因子 | 说明 | 权重 w |
|------|------|--------|
| 信息时效性 | 招标截止前 N 小时，权重指数上升 | 0.25 |
| 来源可靠性 | 站点可用性历史均值 | 0.20 |
| 采集成本 | 预估耗时/带宽占用 | 0.15 |
| 历史成功率 | 该站点/类型近 7 天成功率 | 0.20 |
| 用户需求强度 | 被查询频率/订阅数 | 0.20 |

**实现：**
```python
class DynamicPriorityEngine:
    def __init__(self, weights: dict = None):
        self.weights = weights or {
            'timeliness': 0.25, 'reliability': 0.20,
            'cost': 0.15, 'success_rate': 0.20, 'demand': 0.20
        }
        self.success_tracker = defaultdict(list)  # {source: [bool × N]}
        self.cost_estimator = CostEstimator()
        self.demand_tracker = DemandTracker()

    async def compute_priority(self, task: CrawlTask) -> float:
        t = await self.timeliness_factor(task)      # 指数上升曲线
        r = await self.reliability_factor(task)     # 滑动平均
        c = await self.cost_factor(task)            # 归一化成本
        s = await self.success_rate_factor(task)     # 滑动平均
        d = await self.demand_factor(task)          # 查询频率

        return (self.weights['timeliness'] * t +
                self.weights['reliability'] * r +
                self.weights['cost'] * c +
                self.weights['success_rate'] * s +
                self.weights['demand'] * d)

    async def timeliness_factor(self, task: CrawlTask) -> float:
        """招标截止前 24h 权重快速上升"""
        hours_left = (task.deadline - datetime.now()).total_seconds() / 3600
        if hours_left <= 0: return 1.0
        return 1 - np.exp(-hours_left / 48)  # 渐变上升曲线
```

### 1.2 自适应采集间隔

**问题：** 固定 `asyncio.sleep(2)` 造成资源浪费或采集不足。

**优化：** 基于站点响应特征的自适应间隔。

```python
class AdaptiveIntervalManager:
    """根据站点响应特征自动调整采集间隔"""

    def __init__(self):
        self.response_times: deque = deque(maxlen=100)  # 每站点 100 条
        self.error_rates: deque = deque(maxlen=50)

    async def get_interval(self, source: str) -> float:
        recent = list(self.response_times)[-20:]
        if not recent:
            return 2.0  # 默认

        avg_rt = np.mean(recent)
        std_rt = np.std(recent)

        # 响应稳定 → 可缩小间隔
        # 响应波动大 → 扩大间隔保护
        cv = std_rt / avg_rt if avg_rt > 0 else 1.0

        base = avg_rt / 1000  # 毫秒→秒
        interval = base * (1 + cv)  # 波动系数

        return max(0.5, min(interval, 30.0))  # 夹紧 [0.5s, 30s]
```

### 1.3 调度优化路线图

| 阶段 | 功能 | 收益 |
|------|------|------|
| **Phase 1** | 动态优先级替代静态优先级 | 关键信息采集及时性 +40% |
| **Phase 2** | 自适应间隔 + 反频率检测 | 采集成功率 +25%，被封率 -60% |
| **Phase 3** | 多源协同调度（避免同站点并发） | 站点可用性 +30% |
| **Phase 4** | 强化学习调度（AlphaGo-style） | 最优采集策略自动发现 |

---

## 二、异常检测与自动恢复

### 2.1 异常模式库

**现状：** 重试策略为指数退避，盲目且低效。

**优化：** 建立异常分类引擎，针对性处理。

```python
class AnomalyClassifier:
    """采集异常分类"""

    PATTERNS = {
        'rate_limit': {
            'signals': ['status_429', 'retry_after', 'rate limit exceeded'],
            'action': 'backoff_long',  # 长退避 (5-15min)
            'notify': False
        },
        'ban': {
            'signals': ['status_403', 'captcha', 'ip blocked', 'access denied'],
            'action': 'switch_proxy',  # 切换代理/站点
            'notify': True
        },
        'network_timeout': {
            'signals': ['timeout', 'connection reset', 'network unreachable'],
            'action': 'retry_quick',   # 短重试 (10-30s)
            'notify': False
        },
        'data_parse_error': {
            'signals': ['selector mismatch', 'null field', 'parse exception'],
            'action': 'adapt_selector',  # 切换备选选择器
            'notify': True
        },
        'server_error': {
            'signals': ['status_500', 'status_502', 'status_503'],
            'action': 'wait_and_retry',  # 等待恢复
            'notify': False
        }
    }

    def classify(self, error: Exception, context: dict) -> AnomalyType:
        msg = str(error).lower()
        status = context.get('http_status', 0)

        for anomaly_type, pattern in self.PATTERNS.items():
            if any(s in msg for s in pattern['signals']) or \
               (anomaly_type == 'rate_limit' and status == 429):
                return AnomalyType(anomaly_type, pattern['action'], pattern['notify'])
        return AnomalyType('unknown', 'retry_quick', False)
```

### 2.2 自动恢复状态机

```
                    ┌──────────────┐
                    │   IDLE       │
                    └──────┬───────┘
                           │ 任务到达
                           ▼
              ┌────────────────────────┐
         ┌───▶│    RUNNING             │
         │    └────────┬───────────────┘
         │            │ 异常检测
         │            ▼
         │    ┌─────────────────┐
         │    │ CLASSIFY_ANOMALY│
         │    └────────┬────────┘
         │             │
    重试 │             │ 类型判断
    耗尽 │             ▼
  ┌─────┐ │   ┌────────────────┐    ┌────────────────┐
  │FAIL │◀─┤   │ 选择恢复策略    │───▶│ AUTOMATED_HEAL │
  └─────┘ │   └────────────────┘    └────────────────┘
          │         │ 不可恢复
          │         ▼
          │    ┌──────────┐
          └────│ HALT     │
               │ + 告警    │
               └──────────┘
```

### 2.3 健康度仪表盘指标

```python
HEALTH_METRICS = {
    # 采集层
    'crawl_success_rate':      '采集成功率 (目标 > 95%)',
    'crawl_avg_latency_ms':   '平均采集延迟 (目标 < 2000ms)',
    'crawl_items_per_hour':    '采集吞吐量 (目标持续增长)',

    # 异常层
    'anomaly_detection_rate':  '异常检测覆盖率 (目标 100%)',
    'self_heal_rate':          '自愈率 (目标 > 80%)',
    'false_positive_rate':     '误判率 (目标 < 5%)',

    # 反爬层
    'ban_escape_rate':         '封禁逃脱率 (目标 > 90%)',
    'proxy_rotation_quality':  '代理质量 (有效率 > 85%)',
}
```

---

## 三、数据质量评估

### 3.1 质量评分体系

每个采集任务输出质量分 (0-100)：

```python
@dataclass
class DataQualityScore:
    completeness: float   # 字段完整率 (缺失字段扣分)
    accuracy: float       # 格式准确性 (正则校验)
    timeliness: float     # 时效性 (采集距发布时长)
    consistency: float    # 跨源一致性 (多站交叉验证)
    overall: float        # 加权总分

    def to_dict(self) -> dict:
        return {
            'completeness': round(self.completeness, 2),
            'accuracy': round(self.accuracy, 2),
            'timeliness': round(self.timeliness, 2),
            'consistency': round(self.consistency, 2),
            'overall': round(self.overall, 2)
        }

class DataQualityEvaluator:
    """数据质量评估器"""

    FIELD_REQUIREMENTS = {
        'title': r'.{5,200}',           # 标题 5-200 字
        'deadline': r'\d{4}-\d{2}-\d{2}',  # 日期格式
        'amount': r'[\d,]+(?:\.\d+)?', # 金额
        'contact_phone': r'1[3-9]\d{9}',# 手机号
        'url': r'^https?://',           # URL
    }

    def evaluate(self, tender: TenderInfoV3) -> DataQualityScore:
        completeness = self._calc_completeness(tender)
        accuracy = self._calc_accuracy(tender)
        timeliness = self._calc_timeliness(tender)
        consistency = self._calc_consistency(tender)

        overall = (
            completeness * 0.30 +
            accuracy * 0.30 +
            timeliness * 0.25 +
            consistency * 0.15
        )

        return DataQualityScore(completeness, accuracy, timeliness, consistency, overall)

    def _calc_consistency(self, tender: TenderInfoV3) -> float:
        """
        跨源一致性：同一项目多站点采集后比对
        如：重庆工程建设网 + 市政府采购网 同时采集
        """
        # 查找同一项目的其他来源记录
        siblings = self.cross_source_lookup(tender.project_id)
        if not siblings:
            return 1.0  # 无交叉源，默认满分

        match_count = 0
        total_checks = 3  # 金额、截止日、项目名

        for s in siblings:
            if self._field_match(tender.amount, s.amount, tolerance=0.01):
                match_count += 1
            if self._date_match(tender.deadline, s.deadline):
                match_count += 1

        return match_count / total_checks
```

### 3.2 质量反馈闭环

```
采集完成 → 质量评估 → 不合格 → 标记优先重新采集
              ↓
         合格 → 入库 + 记录质量档案
              ↓
         长期监控 → 站点质量排名 → 调度权重调整
```

### 3.3 质量路线图

| 阶段 | 功能 | 收益 |
|------|------|------|
| **Phase 1** | 字段完整性自动校验 + 格式正则 | 脏数据 -70% |
| **Phase 2** | 时效性评分（发布时间→采集时间窗口） | 滞后数据 -50% |
| **Phase 3** | 跨源一致性交叉验证 | 错误数据 -40% |
| **Phase 4** | 质量预测（采集前评估是否值得采集） | 资源浪费 -30% |

---

## 四、预测性扩容

### 4.1 需求预测模型

**背景：** 政府采购/工程建设信息有明显周期性（工作日高峰、月末/年末高峰、节假日低谷）。

```python
class DemandForecaster:
    """基于时间序列的需求预测"""

    def __init__(self):
        self.model = None  # 轻量模型 (ARIMA / Prophet / LSTM)
        self.training_data: deque = deque(maxlen=365)  # 一年数据

    async def predict(self, horizon_hours: int = 24) -> List[float]:
        """预测未来 N 小时采集任务量"""
        if len(self.training_data) < 30:
            return [self._baseline()] * horizon_hours  # 数据不足用基线

        features = self._build_features()
        predictions = self.model.predict(horizon_hours)
        return predictions.tolist()

    def _build_features(self) -> np.ndarray:
        """构建特征：小时/星期/月份/节假日/站点权重"""
        now = datetime.now()
        return np.array([
            now.hour / 24.0,           # 小时特征
            now.weekday() / 6.0,       # 周特征
            now.month / 12.0,          # 月特征
            self._is_holiday(now),     # 节假日
            self._is_month_end(now),   # 月末效应
        ])
```

### 4.2 自动弹性扩缩容

```python
class PredictiveScaler:
    """
    预测性扩容控制器

    策略：
    - 当前负载 > 预测峰值 80% → 提前扩容
    - 当前负载 < 预测谷值 20% → 缩容节省资源
    - 异常事件（大规模项目发布）→ 紧急扩容
    """

    def __init__(self, scheduler: ConcurrencyScheduler):
        self.scheduler = scheduler
        self.forecaster = DemandForecaster()
        self.current_capacity = 10  # 当前配置并发数
        self.min_capacity = 3
        self.max_capacity = 50

    async def adjust(self):
        predicted = await self.forecaster.predict(horizon_hours=1)
        peak_next_hour = max(predicted)

        # 负载预测
        predicted_load = peak_next_hour / self.current_capacity

        if predicted_load > 0.8:
            await self._scale_up()
        elif predicted_load < 0.2:
            await self._scale_down()

    async def _scale_up(self):
        new_capacity = min(self.current_capacity + 5, self.max_capacity)
        logger.info(f"[Scaler] 扩容: {self.current_capacity} → {new_capacity}")
        self._apply_capacity(new_capacity)
        self.current_capacity = new_capacity

    async def _scale_down(self):
        new_capacity = max(self.current_capacity - 3, self.min_capacity)
        logger.info(f"[Scaler] 缩容: {self.current_capacity} → {new_capacity}")
        self._apply_capacity(new_capacity)
        self.current_capacity = new_capacity
```

### 4.3 扩容路线图

| 阶段 | 功能 | 收益 |
|------|------|------|
| **Phase 1** | 基于时间窗口的简单预测（均值/峰值） | 资源浪费 -30% |
| **Phase 2** | ARIMA 短期预测 + 自动调参 | 任务积压 -50% |
| **Phase 3** | Prophet 节假日/周期建模 | 峰谷平滑 |
| **Phase 4** | 多站点协同调度（全局最优） | 整体效率 +25% |

---

## 五、自然语言查询接口

### 5.1 架构设计

```
用户自然语言
     │
     ▼
┌─────────────────┐
│ NLU Parser      │  ← 意图识别 + 实体抽取
│ (LLM / 规则混合) │
└────────┬────────┘
         │ structured_query
         ▼
┌─────────────────┐
│ Query Rewriter  │  ← 同义词扩展 / 纠错 / 范围修正
└────────┬────────┘
         │ optimized_query
         ▼
┌─────────────────┐
│ Search Engine   │  ← 全文检索 / 向量检索
│ (Elasticsearch  │
│  / SQLite FTS)  │
└────────┬────────┘
         │ results
         ▼
┌─────────────────┐
│ Result Ranker   │  ← 相关性 + 质量分 + 时效性
└────────┬────────┘
         │ ranked_results
         ▼
┌─────────────────┐
│ Response FMT    │  ← LLM 总结 / 格式化输出
└────────┬────────┘
         │
         ▼
      最终回答
```

### 5.2 核心实现

```python
class NaturalLanguageQueryEngine:
    """自然语言查询引擎"""

    def __init__(self, db: SQLiteDB, llm: LLMClient):
        self.db = db
        self.llm = llm
        self.intent_patterns = self._load_intent_patterns()

    async def query(self, nl_input: str, user_id: str = None) -> QueryResponse:
        # Step 1: NLU 解析
        parsed = await self._parse_intent(nl_input)

        # Step 2: 查询改写
        rewritten = await self._rewrite_query(parsed)

        # Step 3: 执行检索
        results = await self.db.search(
            keywords=rewritten['keywords'],
            filters=rewritten['filters'],
            limit=rewritten.get('limit', 20)
        )

        # Step 4: 质量过滤
        results = [r for r in results if r.quality_score > 0.6]

        # Step 5: 排序
        ranked = self._rank_results(results, parsed)

        # Step 6: 格式化
        return await self._format_response(ranked, parsed)

    async def _parse_intent(self, text: str) -> ParsedQuery:
        """意图识别 + 实体抽取"""
        prompt = f"""从以下查询中提取信息：
        查询：「{text}」
        提取：信息类型(招标公告/中标结果/采购意向)、地区、时间范围、金额区间、关键词

        输出 JSON："""

        raw = await self.llm.generate(prompt)
        return ParsedQuery(**json.loads(raw))

    async def _rewrite_query(self, parsed: ParsedQuery) -> dict:
        """查询改写：同义词扩展 + 拼写纠正"""
        keywords = set(parsed.keywords)

        # 同义词扩展
        for kw in list(keywords):
            synonyms = self.synonym_dict.get(kw, [])
            keywords.update(synonyms)

        return {
            'keywords': list(keywords),
            'filters': {
                'info_type': parsed.info_type,
                'region': parsed.region,
                'time_range': parsed.time_range,
                'amount_range': parsed.amount_range,
            },
            'limit': parsed.limit or 20
        }

    async def _format_response(
        self, results: List[TenderInfo], parsed: ParsedQuery
    ) -> QueryResponse:
        """响应格式化"""

        if not results:
            return QueryResponse(
                answer="未找到符合条件的招标信息",
                items=[], total=0
            )

        # 构建摘要
        summary_parts = []
        if parsed.info_type:
            summary_parts.append(f"找到 {len(results)} 条{parsed.info_type}")
        if parsed.time_range:
            summary_parts.append(f"时间范围：{parsed.time_range}")

        answer = "。".join(summary_parts) + f"，最相关的一条：{results[0].title}"

        return QueryResponse(
            answer=answer,
            items=results[:10],  # 返回 Top 10
            total=len(results),
            filters_applied=parsed.dict()
        )
```

### 5.3 查询示例

| 用户输入 | 解析结果 | 生成的 SQL/Filters |
|---------|---------|-------------------|
| "最近一周重庆的招标公告" | info_type=招标公告, region=重庆, time_range=7d | `WHERE region='重庆' AND type='招标公告' AND publish_date > NOW()-7d` |
| "金额超过 500 万的采购项目" | amount_range=(500万, ∞) | `WHERE amount > 5000000 AND type='采购公告'` |
| "有没有关于智慧城市的项目" | keywords=[智慧城市] | `WHERE title LIKE '%智慧城市%' OR content LIKE '%智慧城市%'` |

### 5.4 查询接口路线图

| 阶段 | 功能 | 技术方案 |
|------|------|---------|
| **Phase 1** | 关键词 + 结构化过滤查询 | SQLite FTS5 / Elasticsearch |
| **Phase 2** | 自然语言解析（LLM 抽取实体） | GPT-4o-mini / Qwen |
| **Phase 3** | 向量语义检索（相似项目发现） | ChromaDB / Qdrant |
| **Phase 4** | 多轮对话 + 主动推荐 | LLM 对话 + 知识图谱 |

---

## 六、实施优先级与依赖关系

```
Phase 1 (1-2周) ─────────────────────────────────┐
├─ 动态优先级引擎                                  │ 所有后续功能
├─ 异常分类器 + 基础自愈                          │ 的基础设施
└─ 数据质量基础校验                               │
      │                                           ▼
      │                        Phase 2 (2-3周) ──────────────────────┐
      │                        ├─ 自适应采集间隔                          │
      │                        ├─ 预测性扩容（简单版）                     │
      │                        └─ 质量评分体系                            │
      │                                   │                              │
      │                                   ▼                              │
      │                        Phase 3 (3-4周) ──────────────────┐
      │                        ├─ 自然语言查询接口（规则版）           │
      │                        ├─ 健康度仪表盘                         │
      │                        └─ 预测性扩容（ARIMA）                │
      │                                   │                          │
      │                                   ▼                          │
      │                        Phase 4 (4-6周) ─────────────────┐
      │                        ├─ LLM 驱动的 NLU 解析             │
      │                        ├─ 强化学习调度                     │
      │                        └─ 向量语义检索                     │
      │                                                        │
      └────────────────────────────────────────────────────────┘
```

---

## 七、关键指标 (KPIs)

| 指标 | 当前基线 | Phase 2 目标 | Phase 4 目标 |
|------|---------|-------------|-------------|
| 采集成功率 | ~85% | > 95% | > 99% |
| 自愈率 | 0% | > 60% | > 90% |
| 数据质量分 | 无 | > 75/100 | > 90/100 |
| 查询响应时间 | N/A | < 2s | < 0.5s |
| 资源利用率 | 固定 100% | 动态 60-100% | 动态 40-100% |

---

*本方案为 AI 工程师系统性分析输出，待审批后逐步实施。*
