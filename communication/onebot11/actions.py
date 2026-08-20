"""OneBot11 协议动作定义（自研实现，与协议字符串一一对应）。

动作分两类：

- ``ACTION_*``：OneBot11 标准动作（go-cqhttp 兼容子集，覆盖本项目用到的全部能力）。
- ``EXT_*``  ：QQ 引擎扩展动作（引擎实现额外提供的接口，如收藏表情/戳一戳/语音转写）。

调用方传动作常量即可，无需硬编码字符串。扩展动作是否可用取决于
底层引擎的实现，调用失败时由调用方优雅降级。
"""

from __future__ import annotations

# ── OneBot11 标准动作（消息）─────────────────────────────
ACTION_SEND_MSG = "send_msg"                        # 发送消息（自动判断私聊/群聊）
ACTION_SEND_PRIVATE_MSG = "send_private_msg"        # 发送私聊消息
ACTION_SEND_GROUP_MSG = "send_group_msg"            # 发送群消息
ACTION_DELETE_MSG = "delete_msg"                    # 撤回消息
ACTION_GET_MSG = "get_msg"                          # 获取单条消息
ACTION_GET_FORWARD_MSG = "get_forward_msg"          # 获取合并转发消息
ACTION_SEND_LIKE = "send_like"                      # 点赞（QQ 引擎支持 friend_poke）

# ── OneBot11 标准动作（好友）─────────────────────────────
ACTION_GET_FRIEND_LIST = "get_friend_list"          # 获取好友列表
ACTION_GET_PROFILE = "get_profile"                  # 获取资料卡

# ── OneBot11 标准动作（群组）─────────────────────────────
ACTION_GET_GROUP_LIST = "get_group_list"            # 获取群列表
ACTION_GET_GROUP_INFO = "get_group_info"            # 获取群信息
ACTION_GET_GROUP_MEMBER_INFO = "get_group_member_info"
ACTION_GET_GROUP_MEMBER_LIST = "get_group_member_list"
ACTION_SET_GROUP_KICK = "set_group_kick"            # 踢出群成员
ACTION_SET_GROUP_BAN = "set_group_ban"              # 禁言
ACTION_SET_GROUP_WHOLE_BAN = "set_group_whole_ban"  # 全员禁言
ACTION_SET_GROUP_ADMIN = "set_group_admin"          # 设置管理员
ACTION_SET_GROUP_CARD = "set_group_card"            # 设置群名片
ACTION_SET_GROUP_NAME = "set_group_name"            # 设置群名
ACTION_SET_GROUP_LEAVE = "set_group_leave"          # 退群
ACTION_SEND_GROUP_SIGN = "send_group_sign"          # 群签到

# ── OneBot11 标准动作（文件/资源）────────────────────────
ACTION_GET_RECORD = "get_record"                    # 语音转格式下载
ACTION_GET_IMAGE = "get_image"                      # 图片本地化
ACTION_CAN_SEND_IMAGE = "can_send_image"
ACTION_CAN_SEND_RECORD = "can_send_record"
ACTION_OCR_IMAGE = "ocr_image"                      # 图片 OCR

# ── OneBot11 标准动作（系统）─────────────────────────────
ACTION_GET_LOGIN_INFO = "get_login_info"            # 获取登录账号信息
ACTION_GET_STATUS = "get_status"                    # 获取引擎运行状态
ACTION_GET_VERSION_INFO = "get_version_info"        # 获取引擎版本信息
ACTION_SET_RESTART = "set_restart"                  # 重启引擎
ACTION_CLEAN_CACHE = "clean_cache"                  # 清理缓存

# ── QQ 引擎扩展动作（消息）───────────────────────────────
EXT_SEND_POKE = "send_poke"                         # 戳一戳
EXT_FRIEND_POKE = "friend_poke"                     # 好友戳一戳
EXT_GROUP_POKE = "group_poke"                       # 群内戳一戳
EXT_GET_FRIEND_MSG_HISTORY = "get_friend_msg_history"   # 拉取好友历史消息
EXT_GET_RECENT_CONTACT = "get_recent_contact"           # 最近会话列表
EXT_MARK_PRIVATE_MSG_AS_READ = "mark_private_msg_as_read"
EXT_MARK_GROUP_MSG_AS_READ = "mark_group_msg_as_read"
EXT_SET_MSG_EMOJI_LIKE = "set_msg_emoji_like"       # 给消息点赞
EXT_TRANSLATE_EN2ZH = "translate_en2zh"             # 英文转中文
EXT_FETCH_PTT_TEXT = "fetch_ptt_text"               # 语音转文字
EXT_GET_MINI_APP_ARK = "get_mini_app_ark"           # 小程序卡片

# ── QQ 引擎扩展动作（表情/收藏）──────────────────────────
EXT_FETCH_CUSTOM_FACE = "fetch_custom_face"             # 拉取收藏表情 URL 列表
EXT_FETCH_CUSTOM_FACE_DETAIL = "fetch_custom_face_detail"  # 收藏表情详情（resId/md5）
EXT_ADD_CUSTOM_FACE = "add_custom_face"                 # 添加收藏表情
EXT_DELETE_CUSTOM_FACE = "delete_custom_face"           # 删除收藏表情
EXT_SET_CUSTOM_FACE_DESC = "set_custom_face_desc"       # 修改收藏表情描述
EXT_FETCH_EMOJI_LIKE = "fetch_emoji_like"

# ── QQ 引擎扩展动作（群组）───────────────────────────────
EXT_GET_GROUP_INFO_EX = "get_group_info_ex"         # 群信息（扩展字段）
EXT_GET_GROUP_DETAIL_INFO = "get_group_detail_info"
EXT_GET_GROUP_SHUT_LIST = "get_group_shut_list"     # 群禁言名单
EXT_SET_GROUP_SIGN = "set_group_sign"

# ── QQ 引擎扩展动作（在线文件 / 闪传）────────────────────
EXT_SEND_ONLINE_FILE = "send_online_file"
EXT_SEND_ONLINE_FOLDER = "send_online_folder"
EXT_GET_ONLINE_FILE_MSG = "get_online_file_msg"
EXT_RECEIVE_ONLINE_FILE = "receive_online_file"
EXT_REFUSE_ONLINE_FILE = "refuse_online_file"
EXT_CANCEL_ONLINE_FILE = "cancel_online_file"
EXT_CREATE_FLASH_TASK = "create_flash_task"
EXT_SEND_FLASH_MSG = "send_flash_msg"

# ── QQ 引擎扩展动作（状态/诊断）──────────────────────────
EXT_GET_PACKET_STATUS = "nc_get_packet_status"      # 协议包链路状态
EXT_GET_USER_STATUS = "nc_get_user_status"          # 账号在线状态
EXT_GET_RKEY = "nc_get_rkey"                        # 拉取 rkey（图片鉴权）
EXT_GET_CLIENTKEY = "get_clientkey"                 # 客户端 key

# ── 参数常用键（防手滑拼错）─────────────────────────────
PARAM_USER_ID = "user_id"
PARAM_GROUP_ID = "group_id"
PARAM_MESSAGE = "message"
PARAM_MESSAGE_ID = "message_id"
PARAM_FILE = "file"
PARAM_OUT_FORMAT = "out_format"
PARAM_COUNT = "count"
PARAM_MESSAGE_TYPE = "message_type"
PARAM_ECHO = "echo"
