# Aerie Import 耗时实测数据

> 生成时间: 2026-08-12 21:23:10
> 测量方法: `python -X importtime scripts/boot_trace_probe.py 2> importtime.log`
> Python: 3.14.3 (tags/v3.14.3:323c59a, Feb  3 2026, 16:04:56) [MSC v.1944 64 bit (AMD64)]
> 测量范围: 仅 import 阶段（不含运行时 ChromaDB 初始化、ONNX 模型加载、QQ 连接等业务初始化）

## 1. 总览

| 指标 | 数值 |
|---|---|
| Probe 总耗时 | **10.93 秒** |
| Import 条目数 | 1658 |
| 所有模块 self 累计 | 10557.0 ms ≈ 10.56 s |
| 最重导入链 | `core.companion` (7187.76 ms cumulative) |
| 自身耗时最大模块 | `numpy._core._multiarray_umath` (1117.51 ms self) |
| Probe 退出码 | 0 |

## 2. 重型依赖分类汇总

| 类别 | self 累计 (ms) | 模块数 | 占 self 总比 |
|---|---|---|---|
| numpy/pandas | 4149.0 | 400 | 39.3% |
| fastapi/uvicorn | 1458.0 | 81 | 13.8% |
| aerie_internal | 680.0 | 104 | 6.4% |
| pydantic | 233.0 | 68 | 2.2% |
| onnxruntime | 232.0 | 10 | 2.2% |
| httpx/requests | 104.0 | 42 | 1.0% |
| yaml/toml/dotenv | 85.0 | 22 | 0.8% |

## 3. Top 30 慢导入（按累计耗时 cumulative）

> cumulative = 自己 + 所有递归子模块的导入耗时

| # | 累计 (ms) | 自身 (ms) | 模块 |
|---|---|---|---|
| 1 | 7187.76 | 16.67 | `core.companion` |
| 2 | 6335.11 | 6.54 | `core.pipeline` |
| 3 | 6321.32 | 257.18 | `core.attachment_handler` |
| 4 | 5967.73 | 4.77 | `markitdown` |
| 5 | 5959.87 | 3.58 | `markitdown._markitdown` |
| 6 | 4025.08 | 6.51 | `markitdown.converters` |
| 7 | 3380.54 | 2.56 | `markitdown.converters._xlsx_converter` |
| 8 | 3372.78 | 8.71 | `pandas` |
| 9 | 3019.68 | 154.55 | `core.api_server` |
| 10 | 1695.53 | 21.14 | `magika` |
| 11 | 1674.39 | 3.66 | `magika.magika` |
| 12 | 1651.4 | 6.19 | `fastapi` |
| 13 | 1634.66 | 6.52 | `fastapi.applications` |
| 14 | 1541.02 | 12.78 | `fastapi.routing` |
| 15 | 1399.84 | 17.68 | `fastapi.params` |
| 16 | 1396.59 | 7.34 | `numpy` |
| 17 | 1312.93 | 3.38 | `pandas.core.api` |
| 18 | 1212.61 | 1001.23 | `fastapi.exceptions` |
| 19 | 1198.86 | 2.62 | `numpy.__config__` |
| 20 | 1196.24 | 0.23 | `numpy._core._multiarray_umath` |
| 21 | 1196.01 | 6.32 | `numpy._core` |
| 22 | 1136.15 | 6.11 | `numpy._core.multiarray` |
| 23 | 1126.11 | 1117.51 | `numpy._core._multiarray_umath` |
| 24 | 930.59 | 6.51 | `pandas.core.config_init` |
| 25 | 918.25 | 4.37 | `pandas.errors` |
| 26 | 913.88 | 0.21 | `pandas._libs.tslibs` |
| 27 | 913.68 | 4.39 | `pandas._libs` |
| 28 | 847.89 | 39.19 | `pandas._libs.interval` |
| 29 | 774.67 | 37.97 | `pandas._libs.hashtable` |
| 30 | 736.71 | 32.81 | `pandas._libs.missing` |

## 4. Top 20 自身耗时最重的模块（按 self time）

> self = 仅该模块自己（不含子模块）的导入耗时，反映该模块自身的初始化成本

| # | 自身 (ms) | 累计 (ms) | 模块 |
|---|---|---|---|
| 1 | 1117.51 | 1126.11 | `numpy._core._multiarray_umath` |
| 2 | 1001.23 | 1212.61 | `fastapi.exceptions` |
| 3 | 294.32 | 316.65 | `pyarrow.lib` |
| 4 | 257.18 | 6321.32 | `core.attachment_handler` |
| 5 | 154.55 | 3019.68 | `core.api_server` |
| 6 | 132.71 | 166.03 | `fastapi.openapi.models` |
| 7 | 129.68 | 129.68 | `onnxruntime.capi.onnxruntime_pybind11_state` |
| 8 | 104.92 | 104.92 | `main` |
| 9 | 99.08 | 165.04 | `weasyprint.text.ffi` |
| 10 | 82.17 | 219.96 | `onnxruntime.capi._pybind_state` |
| 11 | 79.12 | 79.12 | `watchfiles._rust_notify` |
| 12 | 64.9 | 92.38 | `pydoc` |
| 13 | 61.02 | 61.02 | `pyarrow._compute` |
| 14 | 59.23 | 97.81 | `numpy.random._generator` |
| 15 | 58.03 | 100.09 | `lxml.etree` |
| 16 | 51.14 | 51.14 | `numpy.random._common` |
| 17 | 48.53 | 99.67 | `numpy.random.bit_generator` |
| 18 | 45.59 | 88.29 | `cryptography.hazmat.bindings._rust` |
| 19 | 45.04 | 45.04 | `numpy.random.mtrand` |
| 20 | 44.99 | 322.17 | `pandas._libs.tslibs.offsets` |

## 5. 关键发现

- ⚠️ **Import 阶段本身就耗时 10.9 秒**，这是启动优化的隐形大头之一
- 🔴 Import 耗时 10.9s 已超过 Nielsen 10s 注意力极限
- 🔴 `numpy/pandas` 类 self 累计 4149.0 ms (4.1s)，强烈建议改为函数内懒加载
- ⚠️ `fastapi/uvicorn` 类 self 累计 1458.0 ms，可考虑懒加载
- ⚠️ `aerie_internal` 类 self 累计 680.0 ms，可考虑懒加载

## 6. 原始数据

- 完整日志: [importtime.log](file:///e:/Agent_reply/importtime.log)
- 探针脚本: [scripts/boot_trace_probe.py](file:///e:/Agent_reply/scripts/boot_trace_probe.py)
- 测量脚本: [scripts/boot_trace.ps1](file:///e:/Agent_reply/scripts/boot_trace.ps1)
- 解析脚本: [scripts/boot_trace_parser.py](file:///e:/Agent_reply/scripts/boot_trace_parser.py)
