"""内置城市地点/活动数据（开箱即用，无需任何 API key）。

当百度地图不可用（未配置 BAIDU_MAP_AK，或 AK 的 IP 白名单未放行）时，
world_reality 用它填充附近地点与本地活动，保证软件发给任何人、零配置即可
获得世界背景素材（伊塔的重庆、用户所在城市等）。

数据为静态可维护清单，城市 key 与 world.location / weather.city 一致。
"""

from __future__ import annotations

from typing import Any

BUILTIN_CITY_DATA: dict[str, dict[str, list[dict[str, str]]]] = {
    # 伊塔所在城市（重点）：重庆复式公寓窗外的世界
    "重庆": {
        "nearby_places": [
            {"name": "洪崖洞", "tag": "景点"},
            {"name": "磁器口古镇", "tag": "景点"},
            {"name": "解放碑", "tag": "地标"},
            {"name": "长江索道", "tag": "景点"},
            {"name": "南山一棵树", "tag": "观景台"},
            {"name": "鹅岭二厂文创园", "tag": "文创"},
        ],
        "local_events": [
            {"title": "洪崖洞夜景灯光秀", "source": "本地活动"},
            {"title": "长江索道跨江体验", "source": "本地活动"},
            {"title": "山城步道 CityWalk", "source": "本地活动"},
            {"title": "两江夜游轮渡", "source": "本地活动"},
        ],
    },
    # 用户所在城市
    "济南": {
        "nearby_places": [
            {"name": "趵突泉", "tag": "景点"},
            {"name": "大明湖", "tag": "景点"},
            {"name": "千佛山", "tag": "景点"},
            {"name": "芙蓉街", "tag": "步行街"},
        ],
        "local_events": [
            {"title": "大明湖环湖夜跑", "source": "本地活动"},
            {"title": "趵突泉赏泉季", "source": "本地活动"},
        ],
    },
    "北京": {
        "nearby_places": [
            {"name": "故宫", "tag": "景点"},
            {"name": "天安门广场", "tag": "地标"},
            {"name": "颐和园", "tag": "景点"},
            {"name": "南锣鼓巷", "tag": "步行街"},
        ],
        "local_events": [
            {"title": "故宫特展", "source": "本地活动"},
            {"title": "什刹海夜游", "source": "本地活动"},
        ],
    },
    "上海": {
        "nearby_places": [
            {"name": "外滩", "tag": "地标"},
            {"name": "东方明珠", "tag": "地标"},
            {"name": "豫园", "tag": "景点"},
            {"name": "武康路", "tag": "街区"},
        ],
        "local_events": [
            {"title": "外滩灯光秀", "source": "本地活动"},
            {"title": "滨江夜跑", "source": "本地活动"},
        ],
    },
    "广州": {
        "nearby_places": [
            {"name": "广州塔", "tag": "地标"},
            {"name": "珠江夜游码头", "tag": "景点"},
            {"name": "沙面", "tag": "街区"},
            {"name": "北京路步行街", "tag": "步行街"},
        ],
        "local_events": [
            {"title": "珠江夜游", "source": "本地活动"},
            {"title": "沙面周末市集", "source": "本地活动"},
        ],
    },
    "深圳": {
        "nearby_places": [
            {"name": "莲花山公园", "tag": "公园"},
            {"name": "世界之窗", "tag": "景点"},
            {"name": "欢乐海岸", "tag": "商圈"},
            {"name": "大梅沙海滨", "tag": "景点"},
        ],
        "local_events": [
            {"title": "欢乐海岸音乐喷泉", "source": "本地活动"},
            {"title": "深圳湾骑行", "source": "本地活动"},
        ],
    },
    "杭州": {
        "nearby_places": [
            {"name": "西湖", "tag": "景点"},
            {"name": "灵隐寺", "tag": "景点"},
            {"name": "河坊街", "tag": "步行街"},
            {"name": "西溪湿地", "tag": "景点"},
        ],
        "local_events": [
            {"title": "西湖夜游船", "source": "本地活动"},
            {"title": "河坊街夜市", "source": "本地活动"},
        ],
    },
    "成都": {
        "nearby_places": [
            {"name": "宽窄巷子", "tag": "街区"},
            {"name": "锦里", "tag": "步行街"},
            {"name": "大熊猫繁育基地", "tag": "景点"},
            {"name": "春熙路", "tag": "商圈"},
        ],
        "local_events": [
            {"title": "锦里夜市", "source": "本地活动"},
            {"title": "人民公园喝茶发呆", "source": "本地活动"},
        ],
    },
    "西安": {
        "nearby_places": [
            {"name": "兵马俑", "tag": "景点"},
            {"name": "大雁塔", "tag": "景点"},
            {"name": "回民街", "tag": "步行街"},
            {"name": "西安城墙", "tag": "景点"},
        ],
        "local_events": [
            {"title": "大雁塔音乐喷泉", "source": "本地活动"},
            {"title": "城墙夜骑", "source": "本地活动"},
        ],
    },
    "武汉": {
        "nearby_places": [
            {"name": "黄鹤楼", "tag": "景点"},
            {"name": "东湖绿道", "tag": "公园"},
            {"name": "户部巷", "tag": "步行街"},
            {"name": "江汉路步行街", "tag": "步行街"},
        ],
        "local_events": [
            {"title": "东湖骑行", "source": "本地活动"},
            {"title": "江汉路夜市", "source": "本地活动"},
        ],
    },
    "南京": {
        "nearby_places": [
            {"name": "夫子庙", "tag": "景点"},
            {"name": "中山陵", "tag": "景点"},
            {"name": "玄武湖", "tag": "公园"},
            {"name": "总统府", "tag": "景点"},
        ],
        "local_events": [
            {"title": "夫子庙秦淮夜游", "source": "本地活动"},
            {"title": "玄武湖环湖散步", "source": "本地活动"},
        ],
    },
    "天津": {
        "nearby_places": [
            {"name": "五大道", "tag": "街区"},
            {"name": "古文化街", "tag": "步行街"},
            {"name": "天津之眼", "tag": "地标"},
        ],
        "local_events": [
            {"title": "海河夜游", "source": "本地活动"},
            {"title": "古文化街庙会", "source": "本地活动"},
        ],
    },
    "苏州": {
        "nearby_places": [
            {"name": "拙政园", "tag": "景点"},
            {"name": "平江路", "tag": "街区"},
            {"name": "金鸡湖", "tag": "公园"},
            {"name": "山塘街", "tag": "步行街"},
        ],
        "local_events": [
            {"title": "平江路夜行", "source": "本地活动"},
            {"title": "金鸡湖音乐喷泉", "source": "本地活动"},
        ],
    },
    "长沙": {
        "nearby_places": [
            {"name": "橘子洲", "tag": "景点"},
            {"name": "岳麓山", "tag": "景点"},
            {"name": "太平街", "tag": "步行街"},
            {"name": "五一广场", "tag": "商圈"},
        ],
        "local_events": [
            {"title": "橘子洲焰火", "source": "本地活动"},
            {"title": "太平街夜市", "source": "本地活动"},
        ],
    },
    "青岛": {
        "nearby_places": [
            {"name": "栈桥", "tag": "景点"},
            {"name": "八大关", "tag": "街区"},
            {"name": "崂山", "tag": "景点"},
            {"name": "五四广场", "tag": "地标"},
        ],
        "local_events": [
            {"title": "栈桥看海鸥", "source": "本地活动"},
            {"title": "五四广场灯光秀", "source": "本地活动"},
        ],
    },
    "昆明": {
        "nearby_places": [
            {"name": "滇池", "tag": "景点"},
            {"name": "石林", "tag": "景点"},
            {"name": "翠湖", "tag": "公园"},
            {"name": "云南民族村", "tag": "景点"},
        ],
        "local_events": [
            {"title": "翠湖喂海鸥", "source": "本地活动"},
            {"title": "滇池环湖骑行", "source": "本地活动"},
        ],
    },
    "厦门": {
        "nearby_places": [
            {"name": "鼓浪屿", "tag": "景点"},
            {"name": "环岛路", "tag": "街区"},
            {"name": "曾厝垵", "tag": "街区"},
            {"name": "南普陀寺", "tag": "景点"},
        ],
        "local_events": [
            {"title": "环岛路骑行", "source": "本地活动"},
            {"title": "鼓浪屿漫步", "source": "本地活动"},
        ],
    },
    "郑州": {
        "nearby_places": [
            {"name": "二七纪念塔", "tag": "地标"},
            {"name": "河南博物院", "tag": "景点"},
            {"name": "嵩山少林寺", "tag": "景点"},
        ],
        "local_events": [
            {"title": "河南博物院特展", "source": "本地活动"},
        ],
    },
    "合肥": {
        "nearby_places": [
            {"name": "包公园", "tag": "景点"},
            {"name": "三河古镇", "tag": "景点"},
            {"name": "逍遥津公园", "tag": "公园"},
        ],
        "local_events": [
            {"title": "逍遥津公园散步", "source": "本地活动"},
        ],
    },
    "南昌": {
        "nearby_places": [
            {"name": "滕王阁", "tag": "景点"},
            {"name": "八一广场", "tag": "地标"},
            {"name": "绳金塔", "tag": "景点"},
        ],
        "local_events": [
            {"title": "滕王阁夜游", "source": "本地活动"},
        ],
    },
    "太原": {
        "nearby_places": [
            {"name": "晋祠", "tag": "景点"},
            {"name": "山西博物院", "tag": "景点"},
            {"name": "柳巷", "tag": "步行街"},
        ],
        "local_events": [
            {"title": "柳巷夜市", "source": "本地活动"},
        ],
    },
    "兰州": {
        "nearby_places": [
            {"name": "中山桥", "tag": "地标"},
            {"name": "白塔山", "tag": "景点"},
            {"name": "黄河母亲雕像", "tag": "地标"},
            {"name": "正宁路小吃街", "tag": "步行街"},
        ],
        "local_events": [
            {"title": "正宁路夜市", "source": "本地活动"},
            {"title": "黄河边散步", "source": "本地活动"},
        ],
    },
    "乌鲁木齐": {
        "nearby_places": [
            {"name": "红山公园", "tag": "公园"},
            {"name": "国际大巴扎", "tag": "商圈"},
            {"name": "天山天池", "tag": "景点"},
        ],
        "local_events": [
            {"title": "大巴扎夜市", "source": "本地活动"},
        ],
    },
}


def builtin_places(city: str) -> list[dict[str, Any]]:
    """返回城市内置附近地点；未知城市返回空列表。"""
    data = BUILTIN_CITY_DATA.get(str(city or "").strip())
    if not data:
        return []
    return [dict(item) for item in data.get("nearby_places", [])]


def builtin_local_events(city: str) -> list[dict[str, Any]]:
    """返回城市内置本地活动；未知城市返回空列表。"""
    data = BUILTIN_CITY_DATA.get(str(city or "").strip())
    if not data:
        return []
    return [dict(item) for item in data.get("local_events", [])]
