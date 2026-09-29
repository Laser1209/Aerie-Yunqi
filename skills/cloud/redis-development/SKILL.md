---
name: redis-development
description: Redis 开发 / Redis
provider_hint: text
read_only: true
kind: instruction
triggers:
- 用 Redis 存
- Redis 数据结构
- Redis 缓存设计
- Redis 查得慢
- Redis 向量检索
- Redis 语义缓存
- Redis 建模
- Redis 性能优化
---

# Redis 开发（redis-development）

当你需要用 Redis 做数据建模、缓存、向量检索或语义缓存，并且关心性能与内存占用时走这份流程。产出应当是一份**键设计 + 结构选型 + 索引/向量方案 + TTL 策略**的落地方案，而不是一句"用 Redis 缓存一下"。

## 铁律

1. **先定访问模式，再选数据结构**：是单值读取、按字段更新、去重计数、还是按分数取范围——这决定了 String / Hash / Set / ZSet / List / Stream 的取舍，选错后面只能靠应用层拼补。
2. **key 必须带命名空间前缀**：写成 `app:entity:id:field`，避免裸 key 污染整个 keyspace，也让 SCAN 能按前缀批量清理。
3. **生产禁用 KEYS 与 FLUSHALL**：Redis 单线程，KEYS 是 O(N) 会阻塞全部请求，一律改用 SCAN 游标迭代。
4. **主动拆大 key / 热 key**：单 value 超过 10KB、集合元素超过 5000 就考虑分片，否则一次操作就把整个实例卡住。
5. **缓存一律设 TTL**：除有明确理由的永久数据，全部 EXPIRE；没有过期的缓存内存只会涨不会降。
6. **向量检索走 RediSearch 向量索引**：不要把全量向量拉到应用层算相似度，那等于把 Redis 当成文件存储。

## 步骤

1. **列访问场景**：逐条写清"谁读、谁写、频率、数据量、返回形态（单值 / 列表 / 排序 / 范围）"。
2. **按场景选结构**：对象整体读写用 Hash；排行榜、按时间戳排序用 ZSet；去重与标签集合用 Set；消息队列用 Stream 而不是 List 轮询。
3. **定 key 与淘汰策略**：统一前缀命名，为每类 key 标注过期时间与淘汰策略（如 volatile-lru）。
4. **建索引**：需要按字段过滤或全文检索时，用 `FT.CREATE` 建 RediSearch 索引并声明字段类型，避免全量 SCAN。
5. **做向量检索**：写入时把 embedding 存进 HASH 字段，索引声明 `VECTOR` 类型并选 HNSW 或 FLAT，查询用 KNN 返回 top-k。
6. **做语义缓存**：把问题向量做 key、答案做 value，先向量近邻查是否已有近似命中，命中直接返回，降低 LLM 调用。
7. **上线前压测与观测**：用 `redis-cli --latency` 看延迟、`INFO memory` 看碎片率、`SLOWLOG` 抓慢命令。

## 输出形态

```
## 数据模型
| key 模板 | 结构 | 字段 | TTL | 淘汰策略 |

## 索引 / 向量方案
- 索引名 / 字段 / 距离度量 / 算法（HNSW 或 FLAT）

## 语义缓存策略
- 相似度阈值 / 命中后的处理

## 风险
- 大 key、热 key、内存增长点 → 对应处理
```

## 反面例子（不要这样）

- 一句"加个 Redis 缓存"就上手，没有 key 命名、没有 TTL。
- 用 KEYS 做线上扫描，用 List 轮询当消息队列。
- 把 embedding 全量拉到 Python 里用 numpy 暴力算余弦相似度。
- 为了省事所有数据塞进一个大 Hash，每次更新都要搬运整块。
