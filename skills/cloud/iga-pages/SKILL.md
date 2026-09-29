---
name: iga-pages
description: IGA Pages 部署 / IGA Pages（未接入）
provider_hint: text
read_only: false
implemented: false
not_implemented_note: '未接入：IGA Pages 官方只提供控制台部署（模板 / ZIP 上传 / GitHub 导入），没有公开的 REST 或 CLI 契约；IGA 的 OpenAPI 只管边缘加速域名（CreateDomain），不能创建 Pages 项目'
---

# iga-pages / IGA Pages 部署

**状态：未接入（故意没做）**

## 为什么没做

查证结论（详见 `tmp/out/iga-pages-api-recon.md`）：

- IGA Pages（BytePlus IntelliEdge Global Accelerator 下的托管）官方文档**只有控制台流程**：
  从模板创建 / 上传 ZIP（≤1024MB）/ 导入 GitHub 仓库。项目名 2~31 位，仅小写字母数字连字符；
  加速区域仅 **Outside Chinese Mainland**。
- IGA 确实有公开 OpenAPI，但面向**边缘加速域名管理**
  （`POST https://iga.byteplusapi.com?Action=CreateDomain&Version=2025-05-01`，`ServiceType: page/ai/api/upload`），
  **不能**用来创建 Pages 项目或触发部署。
- 按项目纪律「查不到可靠文档就保持占位，不允许凭记忆编造接口」，这里**不提供 run.py 实现**。

## 现在能怎么做

需要在 IGA 上部署时，走**控制台**：登录 [BytePlus IGA 控制台](https://console.byteplus.com/iga)
→ Pages → Create project。若应用要调大模型，控制台里可开启 LLM 配置（接 ModelArk 或任意
OpenAI 兼容端点），平台会落成运行时环境变量 `BASE_URL` / `MODEL` / `API_KEY`。

静态站点想走命令行部署，用同族的 **`byted-bp-cdn-pagesdeploy`**（BytePlus Edge Pages，官方
CLI `@byteplus/nest`）——那是另一条产品线，有官方 CLI。

## 后续接入条件

若 BytePlus 开放 Pages 的 OpenAPI/CLI，可复用 `byted-bp-cdn-pagesdeploy` 的 CLI 适配层模式接入，
届时删掉本文件的 `implemented: false` 与 `not_implemented_note` 即可。

provider_hint: `text`
