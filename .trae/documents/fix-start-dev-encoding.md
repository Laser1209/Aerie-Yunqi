# Fix: start-dev.bat 编码乱码

## Summary

`start-dev.bat` 中的中文 echo/注释在 UTF-8 编码下被 cmd.exe 以 GBK 错误解析，导致乱码和 "不是内部或外部命令" 报错。修复方案：所有中文文本替换为英文，移除不必要的 `chcp 65001`。

## Current State

- 文件编码：UTF-8（无 BOM），Windows cmd.exe 按系统默认 GBK 解析
- `chcp 65001` 只影响终端输出，不影响 cmd 读取脚本的编码
- 中文 echo（L4, L11, L14, L19, L25）和中文 `::` 注释（L10, L18, L24）被错误解析为命令
- 最终 `npm start` 正常执行，所以 Electron 启动了，问题只是前半段的乱码输出

## Proposed Changes

### 文件：`e:\Agent_reply\start-dev.bat`

**What**：将所有中文文本替换为等价英文，移除 `chcp 65001`

**Why**：ASCII 字符在任何编码下一致，消除编码不匹配风险。项目规范（`tools/restart.bat`）已建立纯英文 echo 模式。

**How**：

| 行号 | 原文 | 改为 |
|------|------|------|
| L2 | `chcp 65001 >nul` | 删除此行 |
| L4 | `echo  Aerie · 云栖 v9.0 — 开发启动脚本` | `echo  Aerie (Yunqi) v9.0 — Dev Startup` |
| L10 | `:: Check Python dependencies` | 保持不变（已是英文） |
| L11 | `echo [1/3] 检查 Python 依赖...` | `echo [1/3] Checking Python dependencies...` |
| L14 | `echo 正在安装缺失依赖...` | `echo Installing missing dependencies...` |
| L18 | `:: Kill any leftover Python processes` | 保持不变（已是英文） |
| L19 | `echo [2/3] 清理旧进程...` | `echo [2/3] Cleaning up old processes...` |
| L24 | `:: Start Electron (which auto-starts Python backend)` | 保持不变（已是英文） |
| L25 | `echo [3/3] 启动 Electron...` | `echo [3/3] Starting Electron...` |

## Assumptions & Decisions

- 英文 echo 足以传达启动进度（项目惯例）
- 移除 `chcp 65001` 不影响功能（项目 memory 已记录上次修复采用同样做法）
- 此修改不涉及业务流程，只影响终端输出显示

## Verification

1. 直接双击 `start-dev.bat`，确认不再出现乱码和"不是内部或外部命令"报错
2. 确认三步进度 echo 正常显示英文
3. 确认 Electron 正常启动
