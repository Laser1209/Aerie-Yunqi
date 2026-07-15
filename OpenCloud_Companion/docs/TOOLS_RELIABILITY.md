# OpenCloud Companion — Tools 可靠性规范

> 适用：所有 `OpenCloud_Companion/tools/` 下的 Tool 子类
> 版本：Phase 7（2026-07-15 起强制）

## 1. 核心原则

> [!important] 错误可观测性优先
> 任何 `except Exception as e: logger.warning(f"...: {e}")` 必须确保 `e` 非空时仍能定位。
> 统一使用 `_format_error(e, prefix)` 工具函数，会自动添加 `err_type`。

## 2. 错误处理模板

### 2.1 必选模式

```python
from loguru import logger

# 推荐：使用统一工具函数
def _format_error(e: Exception, prefix: str) -> str:
    err_type = type(e).__name__
    err_msg = str(e) or "(无错误信息)"
    return f"{prefix} [{err_type}]: {err_msg}"

async def execute(self, ...):
    try:
        # ... 业务逻辑 ...
        return True, "ok"
    except ImportError as e:
        return False, _format_error(e, "依赖缺失")
    except Exception as e:
        # logger.exception 输出完整 traceback
        logger.exception(f"工具 X 失败: params=...")
        return False, _format_error(e, "执行失败")
```

### 2.2 禁止模式

```python
# ❌ 禁止：str(e) 可能为空
except Exception as e:
    logger.warning(f"失败: {e}")  # 若 e 是 ClientConnectorError，输出空白

# ❌ 禁止：吞掉异常
except Exception:
    pass

# ❌ 禁止：不带 traceback
except Exception as e:
    logger.info(f"error: {e}")
    return False
```

## 3. 超时与重试

| 工具类型 | 默认超时 | 重试策略 |
|---------|---------|---------|
| 网页工具（web_*） | 15s | 单次重试 + 2s 退避 |
| 本地工具 | N/A | 不重试 |
| AI API | 30s | 由 brain.py 三级容灾处理 |

## 4. 安全路径白名单

文件工具必须使用 `is_safe_path()` 校验（`tools/base.py`）。**禁止**添加任何绕过白名单的快捷方式。

```python
from tools.base import is_safe_path

if not is_safe_path(path):
    return False, f"安全限制：不允许访问 {path}"
```

## 5. 启动期自检 Checklist

> [!tip] Phase 7 强制项
> 1. AI 模型名必须存在（`brain.startup_check()` 自动校验）
> 2. `.env` 中三个 API key 至少有一个有效
> 3. `config/settings.yaml` 语法可被 yaml.safe_load 解析
> 4. NapCat WebSocket 端口可达（默认 3001）

如果 `brain.startup_check()` 输出 `⚠️ 模型不在可用列表`，**立即修改** `settings.yaml` 里的 model 字段，不要试图靠 fallback 兜底。

## 6. 常见错误码速查

| 错误 | 含义 | 处理 |
|-----|------|------|
| `siliconflow: 401` | 模型名不存在 / API key 失效 | 查 `startup_check` 输出 |
| `web_search 失败 [ClientConnectorError]` | DNS/网络层失败 | 检查网络 + 防火墙 |
| `web_search 失败 [ClientResponseError]: 403` | DDG 触发反爬 | 降级到 fetch_url 拿快照 |
| `web_search 失败: (无错误信息)` | Python 异常 `__str__` 为空 | 已修复：使用 `_format_error` |
| `addRoundedRect ... argument 1 has unexpected type 'QRect'` | PyQt6 类型错误 | 用 `QRectF(self.rect())` 包装 |
| `NameError: name 'X' is not defined` | 拼写错误 / 作用域 | 检查变量定义 |

## 7. 第三方 API 变更应对

### 7.1 DuckDuckGo HTML 端点
- 当前依赖：`https://html.duckduckgo.com/html/?q=...`
- 旧版 class：`result__snippet` / `result__url`
- 新版 class：`data-testid="result__snippet"` / `data-testid="result__a"`
- **应对**：`_parse_ddg_html()` 已实现三重降级（v1 → v2 → fallback）
- 若全部失败：返回 `"未找到关于「X」的结果"`，**不抛错**

### 7.2 wttr.in
- 端点：`https://wttr.in/{city}?format=%C+%t+%h+%w&lang=zh`
- 稳定性：⭐⭐⭐（偶发 503）
- 备选：和风天气 API（需要 key）

### 7.3 SiliconFlow 模型列表
- 完整列表：https://siliconflow.cn/models
- 常用推荐：
  - `Qwen/Qwen2.5-72B-Instruct`（中文旗舰）
  - `deepseek-ai/DeepSeek-V3`（推理强）
  - `google/gemma-2-9b-it`（轻量）
  - `google/gemma-2-27b-it`（中等）

## 8. 回归测试

每次修改 tools 后必须运行：

```bash
cd e:\Agent_reply\OpenCloud_Companion
python tests\test_tools_smoke.py
```

预期：14 个工具至少 11 个 `✅ OK`，网络相关 3 个可接受 `⚠️ NETWORK_FAIL`。

## 9. 监控告警建议（未来）

> [!note] 待办
> - [ ] 启动期若 3 个 provider 全部 ping 失败 → 桌面弹窗告警
> - [ ] web_search 连续 5 次失败 → 写入 `data/incidents/web_search.log`
> - [ ] todo DB 损坏 → 自动备份 + 告警
> - [ ] 每日 08:00 健康检查 cron 任务
