---
title: Phase 09 - Core 鍥剧墖璧勪骇
kind: phase
phase: Phase 09
status: done
progress_note: "2026-07-21: Core image assets are green for magic decode, pixel limit, metadata, dedupe, thumbnail serving, frontend/queue URL compatibility, reference-preserving orphan GC, and flag-off rollback."
tags: [aerie, phase, phase09]
---
# Phase 09锛欳ore 鍥剧墖璧勪骇
> [!info] 鎵ц杈圭晫
> 鍙寜鑾锋壒瀹炴柦璁″垝鎵ц锛涘綋鍓嶉樁娈垫湭閫氳繃楠屾敹鏃跺仠姝㈠悗缁樁娈点€?

## 鐩爣
榄旀暟/MIME銆佸昂瀵搞€丒XIF/GPS 娓呯悊銆佸搱甯屻€佺缉鐣ュ浘銆佸紩鐢ㄤ笌 GC锛涗繚鎸佸吋瀹广€佸彲瑙傛祴涓庡彲鍥炴粴銆?

## 闈炵洰鏍?
涓嶆暣浣撻噸鍐?Pipeline锛涗笉鍒犻櫎鏃ц〃鎴栨棫鏂囦欢锛涗笉鍒涘缓骞宠 v2锛涗笉澶嶅埗鐤戜技鍑嵁銆?

## 渚濊禆
- Phase 08
- [[05_Feature_Flag涓庡洖婊氱煩闃礭]銆乕[06_AI_Vibe_Coding鎵规瑙勭害]]

## 褰撳墠浠ｇ爜璇佹嵁
- [attachment_handler.py](file:///E:/Agent_reply/core/attachment_handler.py)
- [api_server.py](file:///E:/Agent_reply/core/api_server.py)
- [chat-uploader.js](file:///E:/Agent_reply/electron/src/renderer/js/chat-uploader.js)
- [pipeline.py](file:///E:/Agent_reply/core/pipeline.py)

## 鏂囦欢鑼冨洿
- 璁″垝淇敼鎴栨紨杩涳細`core/attachment_handler.py`銆乣core/api_server.py`銆乣electron/src/renderer/js/chat-uploader.js`
- 鏂版枃浠朵粎闄愯鍒掑垪鏄庣殑妯″潡銆佽縼绉诲拰娴嬭瘯銆?
- 鎵ц浠诲姟锛歔[Task 09-baseline]]

## 鏁版嵁/API 鍚堝悓
- Feature Flag锛歚image_assets_v1`銆?
- 榄旀暟/MIME銆佸昂瀵搞€丒XIF/GPS 娓呯悊銆佸搱甯屻€佺缉鐣ュ浘銆佸紩鐢ㄤ笌 GC銆?
- ID銆佺姸鎬併€乻equence銆佸箓绛夐敭鍜屾墍鏈夋潈杈圭晫蹇呴』鍙璁°€?
- 娑夊強杩佺Щ鏃舵敮鎸?backup銆乨ry-run銆乧hecksum銆佸箓绛夈€乧ursor銆佹柇鐐圭画璺戜笌瀹堟亽銆?

## TDD 姝ラ
1. 鍏堟柊澧炲け璐ユ祴璇曡鐩栦富璺緞銆佸紓甯歌矾寰勪笌鍥炴粴璺緞銆?
2. 瀹炵幇鏈€灏忓彉鏇翠娇娴嬭瘯閫氳繃锛屼繚鐣欏吋瀹归€傞厤鍣ㄣ€?
3. 杩愯鍙楀奖鍝嶆ā鍧楁祴璇曚笌瀹屾暣鍥炲綊銆?
4. 楠岃瘉 Flag 鍏抽棴銆佽縼绉?鍗忚鎭㈠鍜?Evidence 鑴辨晱銆?

## 楠屾敹
- [x] 浼墿灞曘€佸儚绱犵偢寮广€佺┛瓒娿€侀噸澶嶅浘鍜屽鍎?GC 閫氳繃
- [x] Feature Flag 鍏抽棴鎭㈠鏃ц矾寰勪笖涓嶄涪鏂版暟鎹?
- [x] 涓嶄骇鐢熼噸澶嶅壇浣滅敤銆佸巻鍙蹭覆绾挎垨鏁忔劅鍊兼硠婕?

## 鍥炴粴
鍏抽棴 `image_assets_v1`锛屾仮澶嶅浠芥垨鏃ц璺緞锛涗繚鐣欐柊琛ㄣ€佸厓鏁版嵁銆丱utbox銆佹棫琛ㄥ拰鏃ф枃浠躲€?

## 鎸囨爣
鎴愬姛鐜囥€佸欢杩熴€侀噸澶嶈鏁般€佸畧鎭掑樊寮傘€佹仮澶嶆椂闂村拰鍥炴粴鑰楁椂锛涚姝㈣褰曟秷鎭鍚?鍒朵汉鏁版嵁鎴栧嚑鏍稿寲鍒檯鎬с€?

## 鎻愪氦杈圭晫
鍙彁浜?Phase 09 鐩稿叧婧愮爜銆佹祴璇曘€佽縼绉讳笌鏂囨。锛涗笉娣峰叆鏃犲叧閲嶆瀯銆佹牸寮忓寲鎴栨瀯寤轰骇鐗┿€?

## Evidence
- [瀹炴柦璁″垝](file:///E:/Agent_reply/.trae/documents/Aerie_AI_Vibe_Coding_鍏ㄩ潰鍗囩骇瀹炴柦璁″垝.md)
- [attachment_handler.py](file:///E:/Agent_reply/core/attachment_handler.py)
- [api_server.py](file:///E:/Agent_reply/core/api_server.py)
- [chat-uploader.js](file:///E:/Agent_reply/electron/src/renderer/js/chat-uploader.js)
- [test_upload.py](file:///E:/Agent_reply/tests/test_upload.py)
- [[90_鍏ㄥ眬楠屾敹娓呭崟]] 路 [[92_鍥炴粴婕旂粌]]
- 2026-07-21: `pytest -q tests/test_upload.py` -> `11 passed, 4 warnings`; `pytest -q tests/test_upload.py tests/test_api.py tests/test_phase8_proactive_feedback.py tests/test_phase1_proactive_baseline.py` -> `62 passed, 4 warnings`; `python -m py_compile core/api_server.py core/attachment_handler.py` passed; `node --check electron/src/renderer/js/chat-uploader.js` passed.
- 2026-07-21: `pytest -q tests/test_upload.py tests/test_api.py tests/test_phase4_chat_request_service.py tests/test_phase4_api.py tests/test_phase8_proactive_feedback.py tests/test_phase1_proactive_baseline.py` -> `98 passed, 4 warnings`; `python -m py_compile core/api_server.py core/attachment_handler.py core/chat_request_service.py` passed; `node --check electron/src/renderer/js/chat.js` and `node --check electron/src/renderer/js/chat-uploader.js` passed.
