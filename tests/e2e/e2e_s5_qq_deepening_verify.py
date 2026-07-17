"""
Aerie v12.0 · S5 M5.6 QQ 深耕验证脚本
  语音优化 + 视频管理 + 大文件传输 + 主动消息 v2 + 状态管理
"""

import os
import sys
import json
import time
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.qq_deepening import (
    VoiceProcessor, VideoManager, LargeFileTransfer,
    ProactiveMessageV2, QQDeepening,
    MessagePriority, OnlineStatus, MediaType,
    OutgoingMessage, FileTransfer,
)


def main():
    passed = 0
    failed = 0
    issues = []

    def check(name, cond, detail=""):
        nonlocal passed, failed
        if cond:
            passed += 1
            print(f"  ✓ {name}  {detail}")
        else:
            failed += 1
            print(f"  ✗ {name}  {detail}")
            issues.append(name)

    print("=" * 60)
    print("Aerie v12.0 · S5 M5.6 QQ 深耕验证")
    print("  语音优化 + 视频管理 + 大文件传输 + 主动消息 v2")
    print("=" * 60)

    # ===== T1 枚举类型定义 =====
    print()
    check("T1 MessagePriority 4 级", len(MessagePriority) == 4)
    check("T2 OnlineStatus 5 种", len(OnlineStatus) == 5)
    check("T3 MediaType 4 类", len(MediaType) == 4)

    # ===== T4-T10 语音处理器 =====
    print()
    tmp_voice_dir = tempfile.mkdtemp(prefix="aerie_voice_test_")
    voice = VoiceProcessor(cache_dir=tmp_voice_dir)
    check("T4 VoiceProcessor 初始化", voice is not None)
    check("T5 缓存目录存在", Path(tmp_voice_dir).exists())
    check("T6 空缓存统计", voice.get_cache_stats()["total_files"] == 0)

    # 测试缓存键生成
    text1 = "你好，测试语音"
    key1 = voice._get_cache_key(text1, "default", 1.0)
    key2 = voice._get_cache_key(text1, "default", 1.0)
    check("T7 缓存键一致性", key1 == key2)
    key3 = voice._get_cache_key(text1, "other", 1.0)
    check("T8 不同 voice 键不同", key1 != key3)

    # 测试缓存写入和读取
    test_silk = Path(tmp_voice_dir) / "test.silk"
    test_silk.write_bytes(b"\x02#!SILK_V3\x00test_data")
    voice.cache_voice(text1, str(test_silk))
    cached_path = voice.get_cached(text1)
    check("T9 语音缓存命中", cached_path is not None and Path(cached_path).exists())
    check("T10 缓存统计更新", voice.get_cache_stats()["total_files"] == 1)

    # ===== T11-T15 视频管理器 =====
    print()
    tmp_video_dir = tempfile.mkdtemp(prefix="aerie_video_test_")
    video = VideoManager(temp_dir=tmp_video_dir)
    check("T11 VideoManager 初始化", video is not None)
    check("T12 视频临时目录存在", Path(tmp_video_dir).exists())

    # 测试获取视频信息（假文件）
    fake_video = Path(tmp_video_dir) / "test.mp4"
    fake_video.write_bytes(b"fake video data" * 1000)
    info = video.get_video_info(str(fake_video))
    check("T13 视频信息读取", info["name"] == "test.mp4")
    check("T14 视频大小获取", info["size"] > 0)
    check("T15 不存在文件报错", video.get_video_info("/nonexistent.mp4")["error"] == "文件不存在")

    # ===== T16-T22 大文件传输 =====
    print()
    lft = LargeFileTransfer(chunk_size=1024)  # 1KB chunks for test

    # 创建测试文件
    test_file = Path(tempfile.mkdtemp()) / "test_big.bin"
    test_file.write_bytes(b"A" * 5000)  # 5KB

    transfer = lft.create_transfer(str(test_file), 12345, "group")
    check("T16 FileTransfer 创建", transfer.file_id is not None)
    check("T17 文件大小正确", transfer.file_size == 5000)
    check("T18 初始状态 pending", transfer.status == "pending")
    check("T19 分块估算", lft.estimate_chunks(5000) == 5)

    # MD5 计算
    md5 = lft.calculate_md5(str(test_file))
    check("T20 MD5 计算", len(md5) == 32)

    # 模拟上传
    for i in range(12):  # 超过 10 次应该到 100%
        progress = lft.simulate_upload(transfer.file_id)
    check("T21 模拟上传完成", progress >= 1.0)
    t = lft.get_transfer(transfer.file_id)
    check("T22 上传状态 done", t.status == "done" and t.completed_at is not None)

    # ===== T23-T32 主动消息 v2 =====
    print()
    pm = ProactiveMessageV2(rate_limit_per_minute=100)

    # 添加消息
    msg_id1 = pm.add_text_private(10001, "测试私聊消息", MessagePriority.NORMAL)
    check("T23 添加私聊消息", len(msg_id1) == 16)

    msg_id2 = pm.add_text_group(20001, "测试群消息", MessagePriority.HIGH)
    check("T24 添加群消息", len(msg_id2) == 16)

    # 优先级队列：HIGH 应该在 NORMAL 前面
    stats = pm.get_queue_stats()
    check("T25 队列统计 queued=2", stats["queued"] == 2)
    check("T26 按优先级分布", stats["by_priority"].get("high", 0) == 1)

    # 获取到期消息
    due = pm.get_due_messages(max_count=10)
    check("T27 获取到期消息数=2", len(due) == 2)
    check("T28 HIGH 优先级在前", due[0].priority == MessagePriority.HIGH)

    # 标记发送结果
    pm.mark_sent(msg_id1, True, {"message_id": 123})
    pm.mark_sent(msg_id2, True, {"message_id": 456})
    check("T29 标记发送成功", pm.get_queue_stats()["success_count"] == 2)

    # 取消消息
    msg_id3 = pm.add_text_private(10001, "待取消消息")
    check("T30 取消消息前 queued=1", pm.get_queue_stats()["queued"] == 1)
    cancelled = pm.cancel_message(msg_id3)
    check("T31 取消消息成功", cancelled and pm.get_queue_stats()["queued"] == 0)

    # 发送历史
    history = pm.get_history(limit=5)
    check("T32 历史记录", len(history) == 2)

    # ===== T33-T38 QQDeepening 总控 =====
    print()
    tmp_voice2 = tempfile.mkdtemp(prefix="aerie_qd_voice_")
    tmp_video2 = tempfile.mkdtemp(prefix="aerie_qd_video_")
    qd = QQDeepening(
        voice_cache_dir=tmp_voice2,
        video_temp_dir=tmp_video2,
        rate_limit_per_minute=50,
    )
    check("T33 QQDeepening 初始化", qd is not None)
    check("T34 语音子模块存在", qd.voice is not None)
    check("T35 视频子模块存在", qd.video is not None)
    check("T36 主动消息子模块存在", qd.proactive is not None)
    check("T37 默认状态在线", qd.current_status == OnlineStatus.ONLINE)

    # 状态切换
    qd.set_status(OnlineStatus.DO_NOT_DISTURB)
    check("T38 状态切换成功", qd.current_status == OnlineStatus.DO_NOT_DISTURB)

    # ===== T39-T40 综合状态 =====
    summary = qd.get_status_summary()
    check("T39 综合状态包含所有模块",
          all(k in summary for k in
              ["online_status", "voice_cache", "has_ffmpeg",
               "proactive_queue", "active_transfers"]))
    check("T40 状态格式正确", summary["online_status"] == "dnd")

    # ===== 结果 =====
    print()
    print("=" * 60)
    print(f"结果: {passed}/{passed+failed} 通过")
    print("=" * 60)
    if failed == 0:
        print("\n🎉 M5.6 QQ 深耕全部通过！")
    else:
        print(f"\n⚠️  {failed} 项未通过: {issues}")

    # 清理临时目录
    import shutil
    for d in [tmp_voice_dir, tmp_video_dir, tmp_voice2, tmp_video2]:
        try:
            shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass

    return failed == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
