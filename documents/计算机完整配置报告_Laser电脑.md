---
title: 计算机完整配置报告 - Laserの电脑
date: 2026-07-15
tags:
  - system-config
  - hardware
  - dev-environment
  - windows
  - lenovo-legion
aliases:
  - 系统配置报告
  - Laser电脑配置
  - 开发环境配置
cssclasses:
  - system-report
status: complete
---

# 计算机完整配置报告 — Laserの电脑

> [!abstract] 文档概述
> 本文档为 Lenovo 82RC（联想拯救者系列）笔记本的完整硬件、软件及开发环境配置报告。生成日期：2026-07-15。

---

## 一、硬件配置

### 1.1 系统概览

| 项目 | 详情 |
|------|------|
| **品牌/型号** | Lenovo 82RC（联想拯救者系列笔记本） |
| **BIOS 版本** | J2CN40WW（发布日期：2022-04-15） |
| **主板型号** | Lenovo LNVNB161216（SDK0T76479 WIN） |

### 1.2 处理器 (CPU)

| 项目 | 详情 |
|------|------|
| **型号** | 12th Gen Intel Core i7-12700H |
| **架构** | Alder Lake-H（6P 性能核 + 8E 能效核） |
| **核心数** | 14 核 |
| **线程数** | 20 线程 |
| **基准频率** | 2.30 GHz |
| **最大加速频率** | 4.70 GHz（标称） |
| **L2 缓存** | 11,776 KB (~11.5 MB) |
| **L3 缓存** | 24,576 KB (24 MB) |
| **厂商** | GenuineIntel |

> [!tip] i7-12700H 异构架构
> 6 个性能核 (P-Core) + 8 个能效核 (E-Core)，总计 14 核 20 线程。P-Core 支持超线程，E-Core 不支持。Windows 11 线程调度器可智能分配任务到不同核心类型。

### 1.3 内存 (RAM)

| 项目 | 详情 |
|------|------|
| **总容量** | **16 GB** (16,962,281,472 字节) |
| **类型** | DDR5 |
| **频率** | 4800 MHz |
| **配置** | 双通道 2 × 8 GB |

| 插槽 | 厂商 | 型号 | 容量 | 频率 |
|------|------|------|------|------|
| DIMM 1 | Micron Technology | MTC4C10163S1SC48BA1 | 8 GB | 4800 MT/s |
| DIMM 2 | Micron Technology | MTC4C10163S1SC48BA1 | 8 GB | 4800 MT/s |

### 1.4 显卡 (GPU)

| 项目 | 详情 |
|------|------|
| **独立显卡** | NVIDIA GeForce RTX 3050 Ti Laptop GPU |
| **显存** | 4 GB GDDR6 |
| **驱动版本** | 32.0.15.9579 (Game Ready 595.79) |
| **驱动日期** | 2026-03-04 |
| **集成显卡** | Intel Iris Xe Graphics (i7-12700H 集成，MUX 切换模式) |

> [!info] MUX Switch
> 该笔记本支持 MUX 独显直连切换，可通过 Legion Zone 控制中心在混合输出与独显直连之间切换。

### 1.5 存储设备

| 盘符 | 物理型号 | 容量 | 已用 | 可用 | 文件系统 | 接口 |
|------|----------|------|------|------|----------|------|
| **C:** | Samsung MZVLB512HBJQ-000L2 | 256.40 GB | 222.39 GB | ==34.01 GB== | NTFS | NVMe PCIe |
| **D:** | Samsung MZVLB512HBJQ-000L2 | 280.58 GB | 220.98 GB | 59.60 GB | NTFS | NVMe PCIe |
| **E:** | SKHynix HFS512GEJ9X115N | 174.65 GB | 150.46 GB | ==24.19 GB== | NTFS | NVMe PCIe |
| **F:** | SKHynix HFS512GEJ9X115N | 218.32 GB | 215.94 GB | ==2.38 GB== | NTFS | NVMe PCIe |

> [!warning] 存储空间告急
> - **物理盘 1**: Samsung PM991a 512 GB NVMe SSD
> - **物理盘 2**: SK Hynix 512 GB NVMe SSD
> - **总容量**: ~954 GB | **总可用**: ~120 GB
> - C 盘仅剩 34 GB，E 盘仅剩 24 GB，F 盘仅剩 2.38 GB —— **建议尽快清理或扩容！**

### 1.6 显示器

| 项目 | 详情 |
|------|------|
| **面板型号** | CSO1509（京东方/华星光电 15.6" IPS） |
| **分辨率** | 2560 × 1440（2K QHD） |
| **刷新率** | 165 Hz |
| **物理尺寸** | 34 cm × 19 cm（约 15.6 英寸） |
| **色彩** | 100% sRGB（典型值） |

### 1.7 音频设备

| 设备 | 厂商 | 状态 |
|------|------|------|
| Realtek High Definition Audio (SST) | Realtek | 正常 |
| NVIDIA High Definition Audio | NVIDIA | 正常 |
| NVIDIA Virtual Audio Device (WDM) | NVIDIA | 正常 |
| Nahimic Easy Surround Device | Nahimic | 正常 |
| Nahimic Mirroring Device | Nahimic | 正常 |
| SteelSeries Sonar Virtual Audio Device | SteelSeries ApS | 正常 |

### 1.8 网络适配器

| 适配器 | 厂商 | 类型 | 速率 | MAC 地址 | 状态 |
|--------|------|------|------|-----------|------|
| Realtek PCIe GbE Family Controller | Realtek | 有线以太网 | 1 Gbps | 9C-2D-CD-48-BF-70 | 已连接 |
| Intel Wi-Fi 6E AX211 160MHz | Intel | 无线 Wi-Fi 6E | — | 7C-B5-66-A2-EB-1C | 已断开 |
| Bluetooth Device (PAN) | — | 蓝牙 | — | 7C-B5-66-A2-EB-20 | 已断开 |
| TAP-Windows Adapter V9 | — | 虚拟 VPN | — | 00-FF-FB-DB-5E-F3 | 已断开 |
| VMware Virtual Adapter VMnet1 | VMware | 虚拟网络 | 100 Mbps | 00-50-56-C0-00-01 | 已连接 |
| VMware Virtual Adapter VMnet8 | VMware | 虚拟网络 | 100 Mbps | 00-50-56-C0-00-08 | 已连接 |

---

## 二、操作系统配置

| 项目 | 详情 |
|------|------|
| **操作系统** | ==Windows 11 专业版 25H2== |
| **版本号** | 10.0.26200 |
| **构建信息** | 26100.1.amd64fre.ge_release.240331-1435 |
| **架构** | 64 位 (x64) |
| **HAL 版本** | 10.0.26100.1 |
| **系统区域** | zh-CN（中文，简体，中国） |
| **用户语言** | zh-CN |
| **时区** | (UTC+08:00) 北京，重庆，香港特别行政区，乌鲁木齐 |
| **主机名** | Laserの电脑 |

---

## 三、网络配置详情

### 3.1 活跃连接 — 有线以太网

| 项目 | 详情 |
|------|------|
| **IPv4 地址** | ==192.168.10.7== |
| **子网掩码** | 255.255.255.0 |
| **默认网关** | 192.168.10.1 |
| **DHCP 服务器** | 192.168.10.1 |
| **DNS 服务器** | 192.168.10.1 |
| **DNS 后缀** | wifi |
| **DHCP 租约** | 2026-07-15 05:26 ~ 2026-07-16 05:26 |
| **节点类型** | 混合 |
| **IP 路由** | 已禁用 |
| **WINS 代理** | 已禁用 |

### 3.2 虚拟网络

| 适配器 | IPv4 地址 | 子网掩码 | 网关 | 说明 |
|--------|-----------|----------|------|------|
| VMware VMnet1 | 169.254.49.79 (APIPA) | 255.255.0.0 | — | 仅主机模式 |
| VMware VMnet8 | 169.254.121.24 (APIPA) | 255.255.0.0 | — | NAT 模式 |

> [!bug] VMware 虚拟网卡警告
> VMnet1 和 VMnet8 均使用 APIPA 自动配置地址（169.254.x.x），说明 VMware DHCP 服务可能未正常启动或虚拟网络未正确配置。

---

## 四、驱动版本信息

| 驱动 | 版本 | 日期 | 状态 |
|------|------|------|------|
| NVIDIA GeForce RTX 3050 Ti | 32.0.15.9579 (595.79) | 2026-03-04 | OK |
| NVIDIA HD Audio | 1.4.5.7 | — | — |
| NVIDIA Virtual Audio | 4.65.0.12 | — | — |
| NVIDIA PhysX | 9.23.1019 | — | — |
| NVIDIA FrameView | 1.6.10929 | — | — |
| NVIDIA FrameView SDK | 1.7.12227 | — | — |
| NVIDIA App | 11.0.7.247 | — | — |
| Realtek 网卡 | 系统内置 | — | — |
| Realtek HD Audio (SST) | 系统内置 | — | — |

---

## 五、开发环境配置

### 5.1 开发工具链版本

| 工具 | 版本 | 路径 | 状态 |
|------|------|------|------|
| **Node.js** | v24.14.1 | `D:\nodejs\` | 正常 |
| **npm** | 11.11.0 | `D:\nodejs\node_modules\npm\` | 正常 |
| **Python** | 3.14.3 | `C:\Python314\` | 正常 |
| **pip** | 26.1.2 | `C:\Users\Administrator\AppData\Roaming\Python\Python314\site-packages\pip` | 正常 |
| **Java (JDK)** | 17.0.1 LTS (Oracle) | `C:\Program Files\Common Files\Oracle\Java\javapath` | 正常 |
| **Java (JDK)** | 17.0.8.1 (Microsoft OpenJDK) | `C:\Program Files\Microsoft\jdk-17.0.8.101-hotspot\` | 正常 |
| **Git** | 2.54.0 | `C:\Program Files\Git\cmd\` | 正常 |
| **Git LFS** | 3.7.1 | `C:\Program Files\Git LFS\` | 正常 |
| **Docker** | 29.4.3 | — | ⚠️ 守护进程未运行 |
| **Go** | 未安装 | — | ❌ 未找到 |
| **.NET SDK** | 未安装 | — | ❌ 未找到 |

> [!warning] 缺少 .NET SDK
> 系统安装了多个 .NET Runtime（3.1/6.0/8.0/10.0），但未安装 .NET SDK。如需进行 .NET 开发，请安装对应 SDK。

> [!warning] Docker Desktop 未启动
> Docker 29.4.3 已安装但守护进程未运行。启动 Docker Desktop 后方可使用。

### 5.2 PATH 环境变量结构

```
优先级 1 (Trae IDE 注入):
  ~\.trae-cn\tools\trae-gopls\current
  ~\.trae-cn\sdks\versions\node\current

优先级 2 (开发工具):
  C:\Program Files\Common Files\Oracle\Java\javapath
  C:\Python314\Scripts\; C:\Python314\
  C:\Program Files\Microsoft\jdk-17.0.8.101-hotspot\bin
  C:\Program Files\dotnet\

优先级 3 (系统):
  C:\WINDOWS\system32; C:\WINDOWS
  C:\WINDOWS\System32\Wbem
  C:\WINDOWS\System32\WindowsPowerShell\v1.0\
  C:\WINDOWS\System32\OpenSSH\

优先级 4 (三方工具):
  C:\ProgramData\chocolatey\bin (Chocolatey)
  D:\nodejs\ (Node.js)
  C:\Program Files\Git\cmd (Git)
  C:\Program Files\Git LFS (Git LFS)
  C:\Program Files\Docker\Docker\resources\bin (Docker CLI)
  C:\Program Files (x86)\NVIDIA Corporation\PhysX\Common (NVIDIA PhysX)
  C:\Program Files\NVIDIA Corporation\NVIDIA App\NvDLISR (NVIDIA)

优先级 5 (用户应用):
  D:\Huawei\DevEco Studio\bin (DevEco Studio)
  C:\Users\Administrator\AppData\Roaming\npm (npm global)
  D:\soft\Microsoft VS Code\bin (VS Code)
  C:\Users\Administrator\AppData\Local\Programs\Ollama (Ollama)
  C:\Users\Administrator\.local\bin
  d:\Trae CN\bin (Trae CN IDE)

优先级 6 (系统工具):
  E:\pcsuite\ (手机助手)
  C:\Users\Administrator\AppData\Local\Microsoft\WindowsApps
  C:\Users\Administrator\AppData\Local\GitHubDesktop\bin
```

> [!warning] 路径冲突风险
> `C:\Program Files\Common Files\Oracle\Java\javapath` 在 PATH 中优先级高于 `C:\Program Files\Microsoft\jdk-17.0.8.101-hotspot\bin`，意味着 CLI 中使用 `java` 命令时默认调用 Oracle JDK 17.0.1（而非较新的 Microsoft OpenJDK 17.0.8.1）。

### 5.3 Node.js 全局包

| 包名 | 版本 | 用途 |
|------|------|------|
| **agent-browser** | 0.31.1 | 浏览器自动化 CLI |
| **cordova** | 13.0.0 | 跨平台移动应用框架 |
| **defuddle** | 0.19.1 | 网页内容提取工具 |
| **eas-cli** | 20.0.0 | Expo Application Services CLI |
| **typescript** | 6.0.3 | TypeScript 编译器 |

**npm 全局配置:**

| 配置项 | 值 |
|--------|-----|
| prefix | `C:\Users\Administrator\AppData\Roaming\npm` |

### 5.4 Python 环境

**已安装的主要包（前 30 项）:**

| 包名 | 版本 | 用途 |
|------|------|------|
| Flask | 2.3.3 | Web 框架 |
| Flask-Cors | 4.0.0 | 跨域支持 |
| anthropic | 0.86.0 | AI SDK |
| altair | 6.1.0 | 数据可视化 |
| coverage | 7.14.1 | 代码覆盖率 |
| cryptography | 48.0.0 | 加密库 |
| flatbuffers | 25.12.19 | 序列化 |
| fonttools | 4.63.0 | 字体工具 |
| diskcache | 5.6.3 | 磁盘缓存 |
| filelock | 3.29.4 | 文件锁 |
| absl-py | 2.4.0 | Google 工具库 |
| annotated-types | 0.7.0 | 类型注解 |
| anyio | 4.13.0 | 异步 I/O |
| attrs | 26.1.0 | 类装饰器 |
| certifi | 2026.2.25 | SSL 证书 |
| cffi | 2.0.0 | C 外部函数接口 |
| charset-normalizer | 3.4.6 | 字符编码检测 |
| click | 8.4.1 | CLI 工具 |
| contourpy | 1.3.3 | 等值线计算 |
| cycler | 0.12.1 | 循环样式 |
| distro | 1.9.0 | Linux 发行版信息 |
| docstring_parser | 0.17.0 | 文档字符串解析 |
| blinker | 1.9.0 | 信号库 |
| cachelib | 0.13.0 | 缓存库 |

### 5.5 Git 全局配置

| 配置项 | 值 |
|--------|-----|
| user.name | ==Laser1209== |
| user.email | 3489352115@qq.com |
| filter.lfs.clean | git-lfs clean -- %f |
| filter.lfs.smudge | git-lfs smudge -- %f |
| filter.lfs.process | git-lfs filter-process |
| filter.lfs.required | true |
| safe.directory | * |

> [!note] safe.directory 配置
> `safe.directory=*` 通配符配置允许所有目录的 Git 操作，这在开发环境中方便但降低了安全性。建议在正式环境中改用具体路径。

### 5.6 系统环境变量（关键项）

| 变量名 | 值 | 说明 |
|--------|-----|------|
| AI_AGENT | TRAE | AI 代理标识 |
| LANG | zh_CN.UTF-8 | 语言环境 |
| JAVA_HOME | 未设置 | ⚠️ 建议手动设置 |
| NODE_HOME | 未设置 | Node.js 路径未显式设置 |
| PYTHON_HOME | 未设置 | Python 路径未显式设置 |
| ANDROID_HOME | 未设置 | Android SDK 未配置 |
| GOPATH | 未设置 | Go 工作区未配置 |
| DOCKER_HOST | 未设置 | Docker 守护进程未连接 |
| GIT_LFS_PATH | C:\Program Files\Git LFS | Git LFS 路径 |
| GIT_ASKPASS | d:\Trae CN\...\askpass.sh | Trae IDE Git 凭据助手 |

> [!bug] 关键环境变量缺失
> `JAVA_HOME`、`ANDROID_HOME` 等标准开发变量未设置。虽然当前通过 PATH 仍可正常使用相关工具，但某些构建工具（如 Gradle、Maven、React Native）依赖这些变量。

### 5.7 Docker 环境

| 项目 | 状态 |
|------|------|
| Docker Desktop 版本 | 4.74.0 |
| Docker CLI 版本 | 29.4.3 |
| 守护进程状态 | ❌ 未运行 |

---

## 六、已安装主要软件清单

### 6.1 开发工具

| 软件 | 版本 | 用途 |
|------|------|------|
| IntelliJ IDEA | 2025.1.1.1 | Java/多语言 IDE |
| Visual Studio 2019 Build Tools | 16.11.53 | C++ 编译工具链 |
| Trae CN (VS Code Fork) | — | AI 增强编辑器 |
| 微信开发者工具 | 2.01.2510290 | 微信小程序开发 |
| DevEco Studio | 243.24978.46.36 | 鸿蒙应用开发 |
| Docker Desktop | 4.74.0 | 容器化平台 |
| Ollama | — | 本地 LLM 运行 |
| Navicat Premium | 17.3.10 | 数据库管理 |
| WinSCP | 6.5.6 | SFTP/FTP 客户端 |
| WinRAR | 7.12 | 压缩工具 |

### 6.2 设计 & 创意

| 软件 | 版本 |
|------|------|
| Adobe Photoshop | 2025 (26.0.0.26) |
| Adobe After Effects | 2022 (22.0) |
| Adobe Premiere Pro | 2022 (22.0) |
| Blender | — |
| FontCreator | 15.0.0.2927 |
| FL Studio | 21.0.3 |

### 6.3 社交通讯

| 软件 | 版本 |
|------|------|
| 微信 | 4.1.11.54 |
| QQ | 9.9.31.49738 |
| 腾讯会议 | 3.43.21.403 |
| 网易云音乐 | 3.1.35.205293 |

### 6.4 游戏 & 游戏平台

| 软件 | 版本 |
|------|------|
| Steam（多款游戏） | — |
| EA App | 13.566.0.6079 |
| Epic Online Services | 4.1.0 |
| WeGame | — |
| 完美世界竞技平台 | 1.0.26070912 |

### 6.5 系统工具 & 驱动

| 软件 | 版本 |
|------|------|
| Google Chrome | 150.0.7871.115 |
| Microsoft Edge | 150.0.4078.65 |
| Microsoft Office LTSC 2024 | 16.0.17932.20842 |
| Legion Zone | 2.0.26.6085 |
| 联想电脑管家 | 5.1.190.5202 |
| NVIDIA App | 11.0.7.247 |
| Logitech G502 Driver | 1.0.0.40 |
| SteelSeries GG | 110.0.0 |
| Clash Verge | 2.4.9 |
| Watt Toolkit | 3.0.1620.0 |
| 雷神加速器 | 11.99.0.9 |
| Radmin VPN | 2.0.9 |
| 5EClient | 8.2.6 |
| 阿里云客户端 | 2.3.0 |
| 百度网盘 | 8.5.5 |
| EV录屏 | 4.2.4 |
| 哔哩哔哩直播姬 | 7.58.0.10625 |

---

## 七、当前项目结构

```
E:\WeChat_Agent_Smart_Auto_reply\
├── documents/                          (文档目录)
│   └── 计算机完整配置报告_Laser电脑.md  (本文件)
├── .uploads/                           (上传文件)
├── WeChat_Smart_Auto_Reply_Implementation_Plan.md  (实现计划)
├── .gitignore                          (Git 忽略规则)
└── .git/                               (Git 仓库)
```

---

## 八、配置完整性验证

### 8.1 配置健康检查

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 操作系统激活 | ✅ | Windows 11 Pro 25H2 正常 |
| 显卡驱动 | ✅ | NVIDIA 595.79，日期较新 |
| 内存双通道 | ✅ | 2×8GB DDR5 @ 4800MHz 正常 |
| 存储剩余空间 | ❌ | C/E/F 盘均严重不足 |
| 网络连通性 | ✅ | 以太网正常，DHCP 正常 |
| Wi-Fi 连接 | ⚠️ | Wi-Fi 6E 适配器已断开 |
| VMware 网络 | ⚠️ | VMnet 使用 APIPA，DHCP 可能异常 |
| Java 开发环境 | ⚠️ | 双 JDK 共存，JAVA_HOME 未设 |
| Node.js 开发环境 | ✅ | v24.14.1 + npm 11.11.0 正常 |
| Python 开发环境 | ✅ | 3.14.3 + pip 26.1.2 正常 |
| Git 环境 | ✅ | 2.54.0 + LFS 3.7.1 正常 |
| Docker 环境 | ❌ | 已安装但守护进程未运行 |
| Go 环境 | ❌ | 未安装 |
| .NET SDK | ❌ | 未安装（有 Runtime 无 SDK） |
| Android SDK | ❌ | 未安装，ANDROID_HOME 未设置 |

### 8.2 风险与建议

> [!danger] 高优先级
> - **磁盘空间严重不足**: C 盘仅剩 34 GB，F 盘仅剩 2.38 GB —— 随时可能影响系统运行和软件安装。建议清理临时文件、移动大文件到外置存储。
> - **JAVA_HOME 未设置**: 部分 Java 构建工具可能无法正常工作。

> [!warning] 中优先级
> - **VMware 虚拟网络异常**: VMnet1/8 使用 APIPA 地址，虚拟机可能无法正常上网。
> - **Docker 未启动**: 容器化开发和测试无法进行。
> - **PATH 中双 JDK 冲突**: Oracle JDK 17.0.1 优先级高于 Microsoft OpenJDK 17.0.8.1。

> [!tip] 建议改进
> - 安装 Go（如需 Go 开发）
> - 安装 .NET SDK（与现有 Runtime 配套）
> - 设置 ANDROID_HOME（如需移动端开发）
> - 设置 JAVA_HOME 指向主用 JDK
> - 清理磁盘空间或添加外置存储
> - 启动 Docker Desktop（如需使用）

---

## 九、综合评估

| 维度 | 评分 | 评价 |
|------|------|------|
| **CPU 性能** | ★★★★★ | i7-12700H 14核20线程，性能强劲 |
| **内存容量** | ★★★☆☆ | 16GB DDR5 日常够用，大型项目偏紧 |
| **GPU 性能** | ★★★★☆ | RTX 3050 Ti 4GB，入门光追 + CUDA |
| **存储空间** | ★★☆☆☆ | 总可用仅 ~120 GB，急需清理 |
| **显示素质** | ★★★★★ | 2K 165Hz 高刷屏，色彩优秀 |
| **网络配置** | ★★★★☆ | 千兆有线 + Wi-Fi 6E 齐全 |
| **系统版本** | ★★★★★ | Windows 11 25H2，非常前沿 |
| **开发环境** | ★★★★☆ | 覆盖 Java/Python/Node.js/C++/小程序，配置较全 |
| **总体评分** | ★★★★☆ | 均衡的高性能开发本，存储是软肋 |

---

> [!quote] 总结
> 这台拯救者 82RC 配置均衡 —— i7-12700H + RTX 3050 Ti + 2K 165Hz 屏，开发与游戏兼顾。开发环境覆盖了 Java、Python、Node.js、C++、微信小程序、鸿蒙等多条技术栈，工具链较完整。主要短板是存储空间告急（总可用仅约 120 GB），以及部分开发环境变量和 SDK 缺失。建议优先清理磁盘空间并补全环境变量配置。
>
> — 报告自动生成于 2026-07-15，Trae AI Agent
