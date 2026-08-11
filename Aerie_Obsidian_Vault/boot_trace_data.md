# Aerie Import 耗时实测数据

> 生成时间: 2026-08-11 17:56:22
> 测量方法: `python -X importtime scripts/boot_trace_probe.py 2> importtime.log`
> Python: 3.14.3 (tags/v3.14.3:323c59a, Feb  3 2026, 16:04:56) [MSC v.1944 64 bit (AMD64)]
> 测量范围: 仅 import 阶段（不含运行时 ChromaDB 初始化、ONNX 模型加载、QQ 连接等业务初始化）

## 1. 总览

| 指标 | 数值 |
|---|---|
| Probe 总耗时 | **7.89 秒** |
| Import 条目数 | 1653 |
| 所有模块 self 累计 | 7511.0 ms ≈ 7.51 s |
| 最重导入链 | `core.companion` (4989.1 ms cumulative) |
| 自身耗时最大模块 | `numpy._core._multiarray_umath` (863.44 ms self) |
| Probe 退出码 | 0 |

## 2. 重型依赖分类汇总

| 类别 | self 累计 (ms) | 模块数 | 占 self 总比 |
|---|---|---|---|
| numpy/pandas | 2733.0 | 400 | 36.4% |
| fastapi/uvicorn | 777.0 | 81 | 10.3% |
| aerie_internal | 574.0 | 101 | 7.6% |
| pydantic | 232.0 | 68 | 3.1% |
| onnxruntime | 182.0 | 10 | 2.4% |
| httpx/requests | 71.0 | 42 | 0.9% |
| yaml/toml/dotenv | 50.0 | 22 | 0.7% |

## 3. Top 30 慢导入（按累计耗时 cumulative）

> cumulative = 自己 + 所有递归子模块的导入耗时

| # | 累计 (ms) | 自身 (ms) | 模块 |
|---|---|---|---|
| 1 | 4989.1 | 7.55 | `core.companion` |
| 2 | 4414.15 | 4.07 | `core.pipeline` |
| 3 | 4403.8 | 175.35 | `core.attachment_handler` |
| 4 | 4143.5 | 2.92 | `markitdown` |
| 5 | 4139.09 | 2.73 | `markitdown._markitdown` |
| 6 | 2707.95 | 4.04 | `markitdown.converters` |
| 7 | 2309.63 | 213.6 | `core.api_server` |
| 8 | 2177.76 | 1.72 | `markitdown.converters._xlsx_converter` |
| 9 | 2171.92 | 5.1 | `pandas` |
| 10 | 1227.9 | 6.45 | `magika` |
| 11 | 1221.45 | 2.07 | `magika.magika` |
| 12 | 1011.44 | 3.67 | `numpy` |
| 13 | 954.96 | 4.74 | `fastapi` |
| 14 | 942.49 | 5.18 | `fastapi.applications` |
| 15 | 912.73 | 1.26 | `numpy.__config__` |
| 16 | 911.47 | 0.1 | `numpy._core._multiarray_umath` |
| 17 | 911.37 | 3.41 | `numpy._core` |
| 18 | 885.79 | 8.74 | `fastapi.routing` |
| 19 | 874.72 | 2.71 | `numpy._core.multiarray` |
| 20 | 869.53 | 863.44 | `numpy._core._multiarray_umath` |
| 21 | 853.05 | 2.81 | `pandas.core.api` |
| 22 | 800.35 | 9.99 | `fastapi.params` |
| 23 | 670.76 | 483.04 | `fastapi.exceptions` |
| 24 | 666.73 | 3.61 | `pandas.core.config_init` |
| 25 | 661.64 | 2.74 | `pandas.errors` |
| 26 | 658.9 | 0.23 | `pandas._libs.tslibs` |
| 27 | 658.67 | 2.64 | `pandas._libs` |
| 28 | 621.09 | 19.33 | `pandas._libs.interval` |
| 29 | 580.57 | 22.87 | `pandas._libs.hashtable` |
| 30 | 557.7 | 19.52 | `pandas._libs.missing` |

## 4. Top 20 自身耗时最重的模块（按 self time）

> self = 仅该模块自己（不含子模块）的导入耗时，反映该模块自身的初始化成本

| # | 自身 (ms) | 累计 (ms) | 模块 |
|---|---|---|---|
| 1 | 863.44 | 869.53 | `numpy._core._multiarray_umath` |
| 2 | 483.04 | 670.76 | `fastapi.exceptions` |
| 3 | 213.6 | 2309.63 | `core.api_server` |
| 4 | 203.35 | 262.51 | `weasyprint.text.ffi` |
| 5 | 176.43 | 188.09 | `pyarrow.lib` |
| 6 | 175.35 | 4403.8 | `core.attachment_handler` |
| 7 | 91.78 | 91.78 | `onnxruntime.capi.onnxruntime_pybind11_state` |
| 8 | 90.82 | 117.1 | `fastapi.openapi.models` |
| 9 | 78.34 | 174.05 | `onnxruntime.capi._pybind_state` |
| 10 | 63.16 | 285.03 | `pandas._libs.tslibs.timestamps` |
| 11 | 57.62 | 57.62 | `main` |
| 12 | 45.52 | 80.11 | `cryptography.hazmat.bindings._rust` |
| 13 | 43.47 | 55.39 | `pydoc` |
| 14 | 43.41 | 43.41 | `watchfiles._rust_notify` |
| 15 | 42.13 | 42.13 | `pyarrow._compute` |
| 16 | 33.28 | 33.28 | `_cffi_backend` |
| 17 | 32.77 | 55.38 | `lxml.etree` |
| 18 | 30.81 | 137.35 | `pyarrow.compute` |
| 19 | 30.32 | 88.96 | `pandas._libs.tslibs.timezones` |
| 20 | 29.86 | 59.47 | `charset_normalizer.cd` |

## 5. 关键发现

- ⚠️ **Import 阶段本身就耗时 7.9 秒**，这是启动优化的隐形大头之一
- 🔴 `numpy/pandas` 类 self 累计 2733.0 ms (2.7s)，强烈建议改为函数内懒加载
- ⚠️ `fastapi/uvicorn` 类 self 累计 777.0 ms，可考虑懒加载
- ⚠️ `aerie_internal` 类 self 累计 574.0 ms，可考虑懒加载

## 6. 原始数据

- 完整日志: [importtime.log](file:///e:/Agent_reply/importtime.log)
- 探针脚本: [scripts/boot_trace_probe.py](file:///e:/Agent_reply/scripts/boot_trace_probe.py)
- 测量脚本: [scripts/boot_trace.ps1](file:///e:/Agent_reply/scripts/boot_trace.ps1)
- 解析脚本: [scripts/boot_trace_parser.py](file:///e:/Agent_reply/scripts/boot_trace_parser.py)
