# Aerie · 云栖 后端首轮代码审查报告

> 范围：Python 核心后端抽样（聚焦安全/稳定性高风险模块）
> 方法：逐行审查 + 全量静态扫描
> 复查对象：`core/database.py`、`core/prompt_injection.py`、`core/content_validator.py`、`core/windows_dpapi.py`，并抽样 `core/llm_caller.py`

---

## 总览

| 文件 | 行数 | 总体评价 | 主要问题 |
|------|------|----------|----------|
| `database.py` | 646 | 结构清晰但底层有隐患 | 🟡×2 💭×1 |
| `prompt_injection.py` | 465 | 防御思路完整，个别规则失效 | 🔴/🟡×2 💭×2 |
| `content_validator.py` | 237 | 整洁、可测、有指标 | 无阻塞项 💭×1 |
| `windows_dpapi.py` | 44 | 规范、安全、**范本级** | 无 |

---

## 1. `core/database.py`

🔴 **`execute()` 返回已失效的 cursor（潜在崩溃）**
第 572-574 行：
```python
def execute(self, sql, params=()):
    with self.connection() as conn:
        return conn.execute(sql, params)   # conn 在 with 退出时关闭
```
`with self.connection()` 退出即 `conn.close()`，返回的 `Cursor` 随后不可用。任何调用方 `db.execute(...)` 再迭代会报错。
**修复**：若需返回结果，内部 `fetchall()` 后返回列表；或要求调用方直接使用 `with db.connection() as c:`。

🟡 **`insert / update / delete` 用字符串拼接表名与列名**
第 580-599 行：`insert` 把 `data.keys()` 直接拼进 SQL，`update`/`delete` 的 `where` 也是裸字符串。若 `table`、列名或 `where` 含不可信输入，即构成 SQL 注入；即便内部调用，也极脆弱、难审计。
**建议**：表格/列名走白名单校验；`where` 只允许参数化，禁止外部传入裸 SQL。

💭 **并发吞吐**：`_conn_lock` 全局锁 + 每个操作新建连接 + autocommit，等价串行。正确性无误，但高并发下吞吐受限。可考虑连接池或按线程复用连接。

---

## 2. `core/prompt_injection.py`

🟡 **UNC 路径绕过正则已失效（转义错误）**
第 152 行：
```python
(r">\\\.\\|\\\\\.\\", 8.0),  # UNC path bypass
```
该 raw 字符串经转义后为 `>\\\.\|\\\.\\`，并非作者意图的 UNC 匹配（如 `\\.\`、`\\server\share`）。防御规则形同虚设。
**修复**：明确目标字符，例如 `(?:\\\\\.\\)|(?:\\\\[?]\\(?:[C-Z]\\).*)` 或按需重写；并补一条对抗样例单测。

🟡 **Base64 解码检测不安全**
第 195 行 `base64.b64decode(candidate + "===", validate=False)`：`validate=False` 会忽略非法字符，且随手补 `===` 的 padding 推断不稳；普通 UUID/ID 类字符串易被误判为注入，造成误报与不必要的拦截。
**建议**：用 `validate=True` + 正确的 padding 计算（或 `base64.b64decode(s, validate=True)` 失败即跳过）。

💭 **多语言混合判定阈值偏低**：`scripts_present >= 3` 即计 4.0 分；正常引用外语短语也会触发，属于误报而非阻断，可接受但建议降低权重或加白名单。

💭 **冗余 IGNORECASE**：`_match_patterns` 已 `text.lower()` 又传 `re.IGNORECASE`，无害但多余。

---

## 3. `core/content_validator.py`

✅ **值得肯定**：模块职责单一、文档完整、带 `_metrics` 指标与回退策略，并显式处理了 history 重复问题（191-193 行）。可作为团队范本。

💭 **单例 `get_content_validator`**：后续调用忽略 `brain` 参数（设计如此且已注释），但新读者易误以为可热替换 brain。建议在 docstring 中明确「首次调用后固定」。

---

## 4. `core/windows_dpapi.py`

✅ **范本级**：`protect_data/unprotect_data` 严格校验 `bytes` 类型，异常正确链式包装（`from exc`），平台/依赖缺失分别给出清晰错误。无问题。

---

## 5. `core/llm_caller.py`（抽样）

仅读取前 130 行：结构良好（`@dataclass LLMCallerResponse`、环境变量开关、provider 回退链）。但文件高达 114KB，重试与错误路径、超时、Token 计费逻辑尚未深查，**建议列为下一轮重点审查对象**（🔴 候选风险点：HTTP 超时、异常兜底、密钥轮询）。

---

## 优先修复顺序

1. `prompt_injection.py` 第 152 行正则（防御缺口，影响安全）。
2. `database.py` 的 `execute()` 返回值与 SQL 拼接（数据正确性/注入）。
3. 启动测试底座：先为 `database.py`、`prompt_injection.py` 写单测。

---
*审查基于静态走读与全量扫描；深层动态行为（并发、LLM 回退）需在下一轮结合日志与测试确认。*
