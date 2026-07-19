---
title: Task 09-baseline
tags: [aerie, task, phase09, image]
kind: task
task_id: TASK-09-001
phase: Phase 09
subsystem: image
status: planned
priority: P0
dependencies: ["TASK-08-001"]
risk: high
decision_required: false
feature_flag: image_assets_v1
migration: true
files: ["core/attachment_handler.py", "electron/src/renderer/js/chat-uploader.js"]
acceptance_ids: ["A-09-01", "A-09-02"]
rollback_ready: false
owner: image-team
evidence: ["file:///E:/Agent_reply/core/attachment_handler.py", "file:///E:/Agent_reply/electron/src/renderer/js/chat-uploader.js"]
---
# Task 09-baseline
> [!todo] Phase 09
> 魔数/MIME、尺寸、EXIF/GPS 清理、哈希、缩略图、引用与 GC；验收目标：伪扩展、像素炸弹、穿越、重复图和孤儿 GC 通过。

- [ ] 先提交失败测试证据
- [ ] 完成最小实现与兼容路径
- [ ] 验证 `image_assets_v1` 关闭后的旧路径
- [ ] 记录脱敏 Evidence、指标与守恒结果
- [ ] 完成回滚演练并更新 `rollback_ready`

## 链接
[[Phase 09]] · [[90_全局验收清单]] · [[92_回滚演练]]
