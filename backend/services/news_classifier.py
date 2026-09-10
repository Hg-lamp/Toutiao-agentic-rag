"""新闻分类：把抓到的新闻落到项目现有的 9 个频道里。

分类体系直接沿用数据库 ``news_category`` 表：
头条 / 社会 / 国内 / 国际 / 娱乐 / 体育 / 军事 / 科技 / 财经

策略：
1. 每条新闻先按「来源频道」得到一个保底分类（RSS 频道本身就是分类好的，最可靠）；
2. 再用关键词打分做一次纠偏——只有当标题/摘要里出现了足够强的主题信号，
   并且该来源允许纠偏（综合类来源）时才改写分类。
"""

import re
from typing import Iterable, Optional

# 项目默认的频道顺序（同时也是新闻列表 tab 的顺序）
DEFAULT_CATEGORIES = [
    "头条", "社会", "国内", "国际", "娱乐", "体育", "军事", "科技", "财经",
]

# 各频道的关键词表。命中标题算 3 分，命中摘要算 1 分。
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "科技": [
        "科技", "芯片", "人工智能", "大模型", "机器人", "算法", "算力", "量子",
        "华为", "小米", "苹果公司", "特斯拉", "英伟达", "互联网", "开源", "操作系统",
        "手机", "折叠屏", "半导体", "光刻", "5G", "6G", "卫星互联网", "自动驾驶",
        "数据中心", "云计算", "元宇宙", "脑机", "基因编辑", "航天", "火箭", "空间站",
        "嫦娥", "天问", "神舟", "北斗", "AI", "GPT", "DeepSeek",
    ],
    "财经": [
        "股市", "A股", "港股", "美股", "基金", "债券", "汇率", "人民币", "美元",
        "GDP", "经济", "金融", "银行", "保险", "楼市", "房价", "房地产", "消费",
        "贸易", "关税", "出口", "进口", "上市", "IPO", "财报", "营收", "净利",
        "投资", "融资", "物价", "CPI", "就业", "失业", "税收", "财政", "央行",
        "降息", "加息", "黄金", "油价", "比特币", "市值",
    ],
    "体育": [
        "足球", "篮球", "NBA", "CBA", "世界杯", "欧洲杯", "奥运", "亚运", "联赛",
        "国足", "中超", "英超", "西甲", "乒乓球", "羽毛球", "网球", "游泳", "田径",
        "赛事", "冠军", "夺冠", "球员", "球队", "教练", "主帅", "金牌", "银牌",
        "全运会", "马拉松", "斯诺克", "F1", "转会",
    ],
    "娱乐": [
        "电影", "电视剧", "综艺", "明星", "歌手", "演员", "导演", "演唱会", "票房",
        "娱乐圈", "粉丝", "颁奖", "剧集", "热播", "首映", "单曲", "专辑", "偶像",
        "网红", "直播带货", "短剧", "音乐节", "红毯", "恋情", "官宣",
    ],
    "军事": [
        "军事", "军队", "军演", "导弹", "战机", "航母", "国防", "士兵", "演习",
        "武器", "武器库", "军工", "军机", "军舰", "军人", "海军", "空军", "陆军",
        "火箭军", "防空", "核潜艇", "核武器", "无人机作战", "阅兵", "驻军",
        "停火协议", "战况", "战区", "武装", "袭击", "空袭", "开火", "交火",
        "部队", "装备", "弹药", "坦克", "雷达", "维和", "退伍", "征兵", "边防",
    ],
    "国际": [
        "美国", "俄罗斯", "乌克兰", "日本", "韩国", "朝鲜", "欧盟", "联合国",
        "以色列", "伊朗", "叙利亚", "巴勒斯坦", "加沙", "黎巴嫩", "也门", "胡塞",
        "中东", "白宫", "北约", "总统", "首相", "外长", "外交部", "访华", "峰会",
        "制裁", "谈判", "德国", "法国", "英国", "印度", "巴西", "澳大利亚",
        "加拿大", "意大利", "越南", "泰国", "土耳其", "沙特", "阿富汗",
        "特朗普", "拜登", "普京", "泽连斯基", "海外", "国际", "全球",
    ],
    "社会": [
        "事故", "警方", "通报", "医院", "学校", "高考", "中考", "天气", "台风",
        "地震", "暴雨", "洪水", "山洪", "救援", "火灾", "交通", "车祸", "市民",
        "社区", "举报", "法院", "判决", "纠纷", "诈骗", "失联", "遇难", "身亡",
        "消防", "疫情", "疫苗", "医保", "养老", "食品安全", "塌方", "坠楼",
    ],
    "国内": [
        "国务院", "中央", "中共中央", "政策", "部署", "会议", "发改委", "教育部",
        "卫健委", "工信部", "财政部", "省委", "市委", "自治区", "乡村振兴", "改革",
        "规划", "政协", "人大", "十四五", "十五五", "总书记", "总理", "全国",
        "高铁", "铁路", "机场", "港珠澳", "长三角", "粤港澳", "京津冀",
    ],
}

# 「头条」是一个综合频道：只有强时事信号时才从综合来源切到具体频道
HEADLINE_CATEGORY = "头条"
_CATEGORY_ALIASES = {
    "要闻": "头条",
    "热点": "头条",
    "推荐": "头条",
    "国内新闻": "国内",
    "国际新闻": "国际",
    "社会新闻": "社会",
    "科技新闻": "科技",
    "财经新闻": "财经",
    "体育新闻": "体育",
    "娱乐新闻": "娱乐",
    "军事新闻": "军事",
}


def normalize_category_name(name: Optional[str]) -> str:
    """把来源里五花八门的频道名映射到项目频道名。"""
    if not name:
        return HEADLINE_CATEGORY
    name = name.strip()
    if name in DEFAULT_CATEGORIES:
        return name
    if name in _CATEGORY_ALIASES:
        return _CATEGORY_ALIASES[name]
    for category in DEFAULT_CATEGORIES:
        if category in name:
            return category
    return HEADLINE_CATEGORY


def score_categories(title: str, summary: str = "") -> dict[str, int]:
    """给各频道打分。"""
    title = title or ""
    summary = summary or ""
    scores: dict[str, int] = {}
    for category, keywords in CATEGORY_KEYWORDS.items():
        score = 0
        for keyword in keywords:
            if keyword in title:
                score += 3
            elif keyword in summary:
                score += 1
        if score:
            scores[category] = score
    return scores


def classify(
    title: str,
    summary: str = "",
    source_category: str = HEADLINE_CATEGORY,
    allow_override: bool = True,
    min_score: int = 3,
) -> str:
    """返回最终频道名。

    :param source_category: 来源自带的频道（保底分类）
    :param allow_override: 是否允许关键词纠偏（综合类来源为 True，频道类来源为 False）
    :param min_score: 纠偏所需的最低分，避免一两个词就把新闻带跑偏
    """
    fallback = normalize_category_name(source_category)
    if not allow_override:
        return fallback

    scores = score_categories(title, summary)
    if not scores:
        return fallback

    best_category, best_score = max(scores.items(), key=lambda kv: kv[1])
    if best_score < min_score:
        return fallback
    # 保底分类是具体频道且自己也拿到高分时，尊重来源的频道归属
    if fallback != HEADLINE_CATEGORY and scores.get(fallback, 0) >= best_score - 1:
        return fallback
    return best_category


_WORD_RE = re.compile(r"[\s\u3000·\-—_/|,，。.、:：;；!！?？\"“”'‘’()（）\[\]【】<>《》]+")
_PREFIX_RE = re.compile(r"^(视频|图集|图解|直播|组图|快讯|独家|重磅|热搜|关注|原创|专题|深度)[:：|｜]?\s*")


def clean_title(title: str) -> str:
    """清洗标题：去掉来源后缀、多余空白和常见前缀标签。"""
    if not title:
        return ""
    title = re.sub(r"<[^>]+>", "", title)
    title = title.replace("&nbsp;", " ").replace("\u3000", " ")
    title = re.sub(r"\s+", " ", title).strip()
    # 去掉 "标题 - 来源名" / "标题_来源名" 这类尾部
    title = re.sub(r"\s*[-–—_|｜]\s*[\u4e00-\u9fa5A-Za-z0-9]{2,12}$", "", title)
    title = _PREFIX_RE.sub("", title)
    return title.strip()[:250]


def title_fingerprint(title: str) -> str:
    """标题指纹：用于跨来源的近似重复判断。"""
    cleaned = _WORD_RE.sub("", clean_title(title or ""))
    return cleaned.lower()
