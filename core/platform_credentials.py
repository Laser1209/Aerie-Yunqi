"""平台凭证目录 —— 需要用户自备账号的第三方平台。

与 `core/api_server.py` 里的「功能 API」(`_FEATURE_APIS`) 只在语义分组上不同：
两者共用同一套 `/api/env/feature-apis` 读写与热加载链路。

**这里同时是「去哪儿配」的唯一事实来源**：

- 设置页按它渲染凭证卡片（key / name / desc / how_to / tutorial / fields）；
- `core/capability_catalog.py` 按 `fields[].env_key` 反查它，得到这条环境变量
  该去设置页哪一块填 —— 不再另写一张映射表（写两处必然漂移）。

字段名一律取自对应 `skills/cloud/<skill>/run.py` 里已声明的环境变量，不在这里另造名字。
完整接入还需要的字段（如 TOS 的 SK / Endpoint / Bucket、抖音支付的私钥与证书序列号）
在该 skill 落地真实 SDK 调用时一并补齐。

> 不在此列的两种情况：凭据由官方 CLI 自己持有（mediakit / BytePlus Pages），
> 或能力未接入（IGA Pages）。给它们留一个填不进任何东西的密钥框 = 瞎指路。
"""
from __future__ import annotations

PLATFORM_CREDENTIALS: list[dict] = [
    {
        "key": "notion",
        "name": "Notion",
        "desc": "notion-research / notion-knowledge-capture / notion-meeting-intelligence / notion-spec-to-impl 共用同一份凭据；填写后到「MCP 服务器」里开启 Notion 即可让模型真正读写你的工作区",
        "tutorial": "https://app.notion.com/developers/tokens",
        "how_to": "开发者门户创建个人访问令牌（ntn_ 开头）→ 填入下方。旧版「内部集成」令牌（secret_ 开头）也可用，但需要在目标页面的「连接」里逐个授权",
        "fields": [{"env_key": "NOTION_TOKEN", "label": "Personal Access Token", "secret": True}],
    },
    {
        "key": "tianyancha",
        "name": "天眼查",
        "desc": "企业主体信息 / 股东 / 司法风险等结构化商查数据",
        "tutorial": "https://open.tianyancha.com/",
        "how_to": "注册开放平台 → 申请接口权限 → 在「我的接口」里取 Token",
        "fields": [{"env_key": "TIANYAN_TOKEN", "label": "API Token", "secret": True}],
    },
    {
        "key": "seedream",
        "name": "火山 Seedream 文生图",
        "desc": "高质量文生图（多风格、多尺寸）",
        "tutorial": "https://console.volcengine.com/ark",
        "how_to": "火山方舟控制台 → 开通 Seedream 模型 → 创建 API Key",
        "fields": [{"env_key": "SEEDREAM_KEY", "label": "Ark API Key", "secret": True}],
    },
    {
        "key": "seedance",
        "name": "火山 Seedance 文生视频",
        "desc": "文生视频 / 图生视频与参考视频",
        "tutorial": "https://console.volcengine.com/ark",
        "how_to": "火山方舟控制台 → 开通 Seedance 模型 → 创建 API Key",
        "fields": [{"env_key": "SEEDANCE_KEY", "label": "Ark API Key", "secret": True}],
    },
    {
        "key": "volcengine_tos",
        "name": "火山引擎对象存储 TOS",
        "desc": "对象上传 / 下载 / 签名 URL / 列举。需先 pip install tos",
        "tutorial": "https://console.volcengine.com/iam/keymanage/",
        "how_to": "控制台「访问密钥」取 AK/SK；Endpoint 与 Region 对应桶所在地域（如 tos-cn-beijing.volces.com / cn-beijing）",
        "fields": [
            {"env_key": "TOS_ACCESS_KEY", "label": "Access Key ID", "secret": True},
            {"env_key": "TOS_SECRET_KEY", "label": "Secret Access Key", "secret": True},
            {"env_key": "TOS_REGION", "label": "Region", "secret": False},
            {"env_key": "TOS_ENDPOINT", "label": "Endpoint", "secret": False},
            {"env_key": "TOS_BUCKET", "label": "默认 Bucket", "secret": False},
        ],
    },
    {
        "key": "alipay",
        "name": "支付宝开放平台",
        "desc": "当面付 / JSAPI / App 支付下单与查单。涉及真实资金，建议先在沙箱验证",
        "tutorial": "https://open.alipay.com/",
        "how_to": "创建网页/移动应用 → 取 APPID（商户私钥、支付宝公钥在接入 SDK 时补齐）",
        "fields": [{"env_key": "ALIPAY_APP_ID", "label": "APPID", "secret": False}],
    },
    {
        "key": "douyinpay",
        "name": "抖音支付",
        "desc": "APP / JSAPI / H5 / Native 支付下单与查单",
        "tutorial": "https://pay.douyin.com/",
        "how_to": "抖音支付商家平台开通后取商户号（AppID、私钥、证书序列号在接入 SDK 时补齐）",
        "fields": [{"env_key": "DOUYINPAY_MCH_ID", "label": "商户号 MchId", "secret": False}],
    },
    {
        "key": "douyin_interactive",
        "name": "抖音互动空间发布",
        "desc": "上传 zip + icon 创建 / 更新互动空间应用",
        "tutorial": "https://developer.open-douyin.com/",
        "how_to": "开放平台创建应用后取 OpenID（ClientKey / ClientSecret 在接入 API 时补齐）",
        "fields": [{"env_key": "DOUYIN_OPEN_ID", "label": "OpenID", "secret": False}],
    },
]


def credential_for_env(env_key: str) -> dict | None:
    """按环境变量名反查凭证条目（供「去哪儿配」使用）。"""
    target = str(env_key or "").strip()
    if not target:
        return None
    for entry in PLATFORM_CREDENTIALS:
        for field in entry.get("fields", []):
            if field.get("env_key") == target:
                return entry
    return None


def credential_where(env_key: str) -> str:
    """把环境变量名翻译成「设置页 → 哪一块」的可读指引；查不到返回空串。"""
    entry = credential_for_env(env_key)
    if entry is None:
        return ""
    return f"设置页 → 平台凭证 → {entry['name']}"
