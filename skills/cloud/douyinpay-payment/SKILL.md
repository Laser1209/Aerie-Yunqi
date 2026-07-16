---
name: douyinpay-payment
description: 抖音支付 / DouyinPay
provider_hint: text
read_only: false
---

# douyinpay-payment / 抖音支付

抖音支付 APP/JSAPI/H5/Native 支付下单与查单。

## 入参
- `out_order_no`：核心入参（见具体 run.py）
- 其余键透传至底层模块

## 出参
- 成功：`{"status": "ok", "pay_status": ...}`
- 依赖缺失：`{"status": "stub", "error": "..."}`
- 异常：`{"status": "error", "error": "..."}`

## 凭据
- 环境变量：`DOUYINPAY_MCH_ID`（缺失时返 stub）

## 安全
- read_only = `false`，由 SkillLoader 强制
- run.py 不主动调子进程 / shell，依赖底层模块自管安全
- 路径解析走项目根白名单

provider_hint: `text`
