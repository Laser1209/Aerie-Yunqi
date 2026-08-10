
## image2 API 使用文档

Base URL：`https://image2.inian.one/v1`

×[开始使用](https://image2.inian.one/api-access#docs-start)[文生图](https://image2.inian.one/api-access#docs-generation)[图生图](https://image2.inian.one/api-access#docs-edits)[响应与计费](https://image2.inian.one/api-access#docs-response)[余额与用量](https://image2.inian.one/api-access#docs-query)[错误与限制](https://image2.inian.one/api-access#docs-errors)**01 · AUTHENTICATION**### 开始使用

在本页面创建 API Key。所有 `/v1` 请求通过 Bearer Key 鉴权，网页与 API 使用同一用户余额。

模型**gpt-image-2**

并发**5**

图片保留**6 小时**

URL 有效期**15 分钟**

```
Authorization: Bearer sk-img2_你的APIKey
Idempotency-Key: 每个业务任务的唯一标识
```

建议每次调用都传入 8～128 位的 `Idempotency-Key`。网络重试时保持同一个值，可以避免重复生成和重复扣费。

**02 · TEXT TO IMAGE**### 文生图

`POST /v1/images/generations`，请求体为 `application/json`。

| 参数                | 类型    | 规则                                          |
| ------------------- | ------- | --------------------------------------------- |
| `prompt`          | string  | 必填，1～8000 字符                            |
| `model`           | string  | 可选，当前为 gpt-image-2                      |
| `size`            | string  | 默认 1024x1024；边长 512～4096 且为 64 的倍数 |
| `n`               | integer | 当前只能为 1                                  |
| `response_format` | string  | url 或 b64_json                               |
| `user`            | string  | 可选，调用方业务标识，最多 128 字符           |

**cURL**复制

```
curl https://image2.inian.one/v1/images/generations \
  -H "Authorization: Bearer $IMAGE2_API_KEY" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: task-0001" \
  -d '{
    "model": "gpt-image-2",
    "prompt": "一只戴宇航头盔的橘猫，电影感光影",
    "size": "1024x1024",
    "n": 1,
    "response_format": "url"
  }'
```

**03 · IMAGE TO IMAGE**### 图生图

`POST /v1/images/edits`，请求体为 `multipart/form-data`。支持 1～4 张参考图，单张不超过 12 MB、5000 万像素，格式为 PNG、JPEG 或 WebP。

| 参数                    | 类型    | 规则                     |
| ----------------------- | ------- | ------------------------ |
| `image` / `image[]` | file    | 必填，最多 4 张          |
| `prompt`              | string  | 必填，描述修改或融合要求 |
| `model`               | string  | 可选，当前为 gpt-image-2 |
| `size`                | string  | 输出尺寸，默认 1024x1024 |
| `n`                   | integer | 当前只能为 1             |
| `response_format`     | string  | url 或 b64_json          |

**多参考图 cURL**复制

```
curl https://image2.inian.one/v1/images/edits \
  -H "Authorization: Bearer $IMAGE2_API_KEY" \
  -H "Idempotency-Key: edit-task-0001" \
  -F "model=gpt-image-2" \
  -F "prompt=使用第一张图的主体和第二张图的背景风格" \
  -F "size=1024x1024" \
  -F "response_format=url" \
  -F "image[]=@subject.png" \
  -F "image[]=@background.webp"
```

不要手动填写 multipart boundary。相同幂等 Key 重试时，参数和每张参考图的内容必须保持一致。

**04 · RESPONSE**### 响应与计费

文生图与图生图返回相同结构。计费按输出尺寸档位计算，与参考图数量无关。

```
{
  "created": 1784516400,
  "data": [{ "url": "https://image2.inian.one/v1/images/.../content?..." }],
  "billing": {
    "transaction_id": "...",
    "tier": "1k",
    "charged": "0.05",
    "balance": "1.45"
  }
}
```

1K**0.05**

2K**0.07**

4K**0.13**

请求开始前原子预扣；上游超时、无有效图片、图片处理或保存失败时自动退款。响应头包含 `X-Request-Id`、扣费交易 ID、扣费金额和剩余余额。

**05 · ACCOUNT**### 余额与用量

`GET /v1/balance`当前余额和 1K/2K/4K 价格

`GET /v1/usage?limit=50`当前用户最近 API 请求、状态、费用和耗时

`GET /v1/models`可用模型列表

**06 · ERRORS**### 错误与限制

| HTTP | 常见 code                                       | 含义                                          |
| ---- | ----------------------------------------------- | --------------------------------------------- |
| 400  | `invalid_prompt` / `image_count_limit`      | 参数或参考图数量不正确                        |
| 401  | `invalid_api_key`                             | API Key 缺失或无效                            |
| 402  | `insufficient_balance`                        | 余额不足，未调用上游                          |
| 403  | `api_key_revoked`                             | Key 已撤销或过期                              |
| 409  | `idempotency_conflict`                        | 相同幂等 Key 的请求内容不同                   |
| 429  | `rate_limit_exceeded` / `concurrency_limit` | 每 Key 60 次/小时、每用户 120 次/小时、并发 5 |
| 502  | `upstream_error` / `no_image`               | 上游失败，预扣金额自动退款                    |

错误响应使用 `{ "error": { "message", "type", "param", "code" } }`。排查问题时请提供响应头中的 `X-Request-Id`，不要提供完整 API Key。
