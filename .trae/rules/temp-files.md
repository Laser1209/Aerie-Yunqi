# 临时文件与临时产出

## 约定

一次性脚本、探针、冒烟测试**一律不要放在仓库根目录**，统一放：

- **临时脚本** → `tmp/scripts/`
- **临时产出**（日志、JSON dump、报告、截图）→ `tmp/out/`

`tmp/` 整个目录已在 `.gitignore` 中，不会污染提交。

## 怎么写

脚本要能从仓库根直接运行，并在文件头写清用法：

```python
"""一句话说明这个脚本干什么。

从仓库根运行：python tmp/scripts/<name>.py
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]   # tmp/scripts/x.py → 仓库根
sys.path.insert(0, str(ROOT))

# …逻辑…

out = ROOT / "tmp" / "out" / "<name>.txt"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(report, encoding="utf-8")
print("-> " + str(out.relative_to(ROOT)))
```

要点：

- 用 `Path(__file__).resolve().parents[2]` 定位仓库根，**不要依赖当前工作目录**
- 产出写入 `tmp/out/`，并在结尾打印相对路径（便于回看）
- 不在根目录留下 `_probe*.py` / `_smoke*.py` / `_verify*.py` 这类文件

## 用完要做什么

- **临时的**（探针、一次性验证）：跑完就删，别长期堆积
- **值得保留的**（可复跑的冒烟/体检脚本）：留在 `tmp/scripts/`，
  并在回复里说明它可复跑；若某个脚本升级为长期资产，移到 `tools/` 或写成正式测试

## 不要做的事

- 不要把临时脚本提交进版本库
- 不要把产出写到 `logs/`（那是运行日志）或仓库根目录
- 不要在多个临时目录之间分散存放（只有 `tmp/scripts/` 与 `tmp/out/` 两处）
