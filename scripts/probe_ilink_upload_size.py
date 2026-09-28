"""iLink 出站体积梯度探测 —— 定位"第一个发不出去的档位"（计划 §2.2 / 附录 C）。

**为什么需要它**

微信侧出站体积**没有公开上限**、失败时**不返回错误码**（§2.2.2）。所以
"278 MB 的 PPT 到底能不能发"这个问题只能靠实测回答 —— 猜不出来。

**它做什么**

用真凭据（与生产同一份）+ 真接收方，按梯度造假文件，走**与生产完全相同**的
``getuploadurl → CDN PUT`` 链路，逐档记录：

* ``getuploadurl`` 是否成功、返回的 ``ciphertext_length``；
* CDN 上传的耗时与失败形态（读超时 / HTTP 4xx / 5xx / 其它异常）；
* 成功档位的耗时曲线（决定生产侧媒体上传超时要设多少）。

**它不做什么**

* **不发消息**（不上 ``sendmessage``）→ 不会往微信里刷一堆测试文件；
* 不落盘明文、不打印 token（只打印前 6 位做凭据核对）。

**代价**：``getuploadurl`` 与 CDN 上传会**真实消耗配额**，这无法避免（也正是必须实测的原因）。

用法::

    python scripts/probe_ilink_upload_size.py --to-user <wx_id>
    python scripts/probe_ilink_upload_size.py --to-user <wx_id> --sizes 1,10,50,200 --out probe.json

凭据来源：``data/ilink_credentials.json``（应用内扫码登录后生成的同一份）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from communication.ilink.client import ILinkClient  # noqa: E402
from communication.ilink.media import ILinkMediaTransfer  # noqa: E402
from communication.ilink.models import MediaType  # noqa: E402
from core.ilink_credentials import ILinkCredentialsStore  # noqa: E402

# 造假文件时的分块大小：避免为了一档 278 MiB 在内存里拼一个同样大的 bytes。
_CHUNK_BYTES = 1 << 20  # 1 MiB


def _make_probe_file(path: Path, size_bytes: int) -> int:
    """生成一个 size_bytes 大小的随机文件（分块写，内存占用恒定）。"""
    written = 0
    with path.open("wb") as handle:
        while written < size_bytes:
            chunk = min(_CHUNK_BYTES, size_bytes - written)
            handle.write(secrets.token_bytes(chunk))
            written += chunk
    return written


async def probe_one(
    client: ILinkClient,
    transfer: ILinkMediaTransfer,
    to_user: str,
    size_mib: float,
) -> dict:
    """跑一档：造文件 → 加密 → getuploadurl → CDN 上传。**不发消息**。"""
    size_bytes = int(size_mib * 1024 * 1024)
    handle, raw_path = tempfile.mkstemp(suffix=".bin", prefix="ilink_probe_")
    path = Path(raw_path)
    row: dict = {"size_mib": size_mib, "requested_bytes": size_bytes}
    try:
        row["actual_bytes"] = _make_probe_file(path, size_bytes)
    except Exception as exc:  # noqa: BLE001
        path.unlink(missing_ok=True)
        return {**row, "result": "LOCAL_WRITE_FAILED", "detail": f"{type(exc).__name__}: {exc}"}

    started = time.monotonic()
    try:
        media = await transfer.upload(
            client,
            path,
            to_user_id=to_user,
            media_type=int(MediaType.FILE),
        )
        row["getuploadurl"] = "ok"
        row["ciphertext_bytes"] = int(media.ciphertext_length)
        row["result"] = "UPLOAD_OK"
    except httpx.ReadTimeout:
        # 生产侧的 45s 读超时就是死在这里：区分"慢"与"不支持"正是本脚本的目的之一。
        row["result"] = "READ_TIMEOUT"
    except httpx.WriteTimeout:
        row["result"] = "WRITE_TIMEOUT"
    except httpx.HTTPStatusError as exc:
        row["result"] = f"HTTP_{exc.response.status_code}"
        row["detail"] = exc.response.text[:200]
    except Exception as exc:  # noqa: BLE001
        row["result"] = type(exc).__name__
        row["detail"] = str(exc)[:200]
    finally:
        row["elapsed_sec"] = round(time.monotonic() - started, 1)
        path.unlink(missing_ok=True)
    return row


def _print_summary(rows: list[dict]) -> None:
    print("\n=== 汇总 ===")
    print(f"{'档位':>10}  {'结果':<18} {'耗时':>8}  {'密文':>12}")
    for row in rows:
        ciphertext = row.get("ciphertext_bytes")
        print(
            f"{row['size_mib']:>8} MiB  {row.get('result', '?'):<18} "
            f"{row.get('elapsed_sec', '')!s:>7}s  "
            f"{(f'{ciphertext / (1 << 20):.1f} MiB' if ciphertext else '-'):>12}"
        )
    failures = [r for r in rows if r.get("result") != "UPLOAD_OK"]
    if failures:
        first = failures[0]
        print(
            f"\n第一个失败档位：{first['size_mib']} MiB（{first.get('result')}）"
            f"\n建议安全上限取其 60~70% ≈ {first['size_mib'] * 0.65:.0f} MiB"
        )
    else:
        print("\n全档通过：安全上限至少是最大档位。")


async def main() -> int:
    parser = argparse.ArgumentParser(description="iLink 出站体积梯度探测（只上传，不发消息）")
    parser.add_argument("--to-user", required=True, help="接收方 wx id（即 from_user_id）")
    parser.add_argument(
        "--sizes",
        default="1,5,10,25,50,100,200,278",
        help="梯度（MiB，逗号分隔）；278 是本次事件里那份 PPT 的大小",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="单档读/写超时（秒）。探测用宽松超时，避免把「慢」误判成「不支持」",
    )
    parser.add_argument("--out", default="", help="把逐档结果写成 JSON")
    args = parser.parse_args()

    credentials = ILinkCredentialsStore().load()
    if credentials is None:
        print("未找到 iLink 凭据（data/ilink_credentials.json），请先在应用内完成扫码登录。")
        return 2
    print(f"凭据：base_url={credentials.base_url} token={credentials.bot_token[:6]}…")
    print(f"接收方：{args.to_user}    单档超时：{args.timeout}s    不发送消息（只上传到 CDN）")

    # httpx 顶层 timeout 设大，但客户端每次请求显式传 DEFAULT_TIMEOUT —— 探测必须绕过
    # 生产读超时，才能真正看出"平台收不收"，而不是"我们等不等得住"。
    timeout = httpx.Timeout(connect=10.0, read=args.timeout, write=args.timeout, pool=10.0)

    rows: list[dict] = []
    async with httpx.AsyncClient(timeout=timeout) as http:
        client = ILinkClient(credentials.base_url, credentials.bot_token, http)
        transfer = ILinkMediaTransfer(http, Path("data") / "ilink_media_probe")
        for size_mib in (float(item) for item in args.sizes.split(",") if item.strip()):
            row = await probe_one(client, transfer, args.to_user, size_mib)
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)

    _print_summary(rows)
    if args.out:
        out_path = Path(args.out)
        out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n逐档结果已写入 {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
