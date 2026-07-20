---
title: Task 09-baseline
tags: [aerie, task, phase09, image]
kind: task
task_id: TASK-09-001
phase: Phase 09
subsystem: image
status: done
progress_note: "2026-07-21: image upload baseline is green for magic decode, pixel limit, metadata, dedupe, thumbnail serving, frontend/queue attachment compatibility, reference-preserving orphan GC, and flag-off rollback."
priority: P0
dependencies: ["TASK-08-001"]
risk: high
decision_required: false
feature_flag: image_assets_v1
migration: true
files: ["core/attachment_handler.py", "core/api_server.py", "electron/src/renderer/js/chat-uploader.js", "tests/test_upload.py"]
acceptance_ids: ["A-09-01", "A-09-02"]
rollback_ready: true
owner: image-team
evidence: ["file:///E:/Agent_reply/core/attachment_handler.py", "file:///E:/Agent_reply/core/api_server.py", "file:///E:/Agent_reply/electron/src/renderer/js/chat-uploader.js", "file:///E:/Agent_reply/tests/test_upload.py"]
---
# Task 09-baseline
> [!todo] Phase 09
> 榄旀暟/MIME銆佸昂瀵搞€丒XIF/GPS 娓呯悊銆佸搱甯屻€佺缉鐣ュ浘銆佸紩鐢ㄤ笌 GC锛涢獙鏀剁洰鏍囷細浼墿灞曘€佸儚绱犵偢寮广€佺┛瓒娿€侀噸澶嶅浘鍜屽鍎?GC 閫氳繃銆?

- [x] 鍏堟彁浜ゅけ璐ユ祴璇曡瘉鎹?
- [x] 瀹屾垚鏈€灏忓疄鐜颁笌鍏煎璺緞
- [x] 楠岃瘉 `image_assets_v1` 鍏抽棴鍚庣殑鏃ц矾寰?
- [x] 璁板綍鑴辨晱 Evidence銆佹寚鏍囦笌瀹堟亽缁撴灉
- [x] 瀹屾垚鍥炴粴婕旂粌骞舵洿鏂?`rollback_ready`

## 閾炬帴
[[Phase 09]] 路 [[90_鍏ㄥ眬楠屾敹娓呭崟]] 路 [[92_鍥炴粴婕旂粌]]

## Evidence
- 2026-07-21: `pytest -q tests/test_upload.py tests/test_api.py tests/test_phase4_chat_request_service.py tests/test_phase4_api.py tests/test_phase8_proactive_feedback.py tests/test_phase1_proactive_baseline.py` -> `98 passed, 4 warnings`.
- 2026-07-21: `python -m py_compile core/api_server.py core/attachment_handler.py core/chat_request_service.py` passed; `node --check electron/src/renderer/js/chat.js` and `node --check electron/src/renderer/js/chat-uploader.js` passed.
