# -*- coding: utf-8 -*-
"""
每日英语推送脚本
流程：算出今天该学哪几个词 -> 调 Claude 生成学习卡片 -> 推送到微信(PushPlus)

本地测试:
    set DRY_RUN=1           (只打印，不推送微信)
    python push.py
"""
import os
import sys
import json
import datetime
import urllib.request
import urllib.error

# ---------------- 可调参数 ----------------
START_DATE    = datetime.date(2026, 9, 1)  # 学习起始日，改成你真正开始的那天
WORDS_PER_DAY = 3                          # 每天新词数量
REVIEW_DAYS   = 3                          # 复习前几天的词
MAX_TOKENS    = 2000

# 用哪家的 AI: "deepseek" 或 "claude"
PROVIDER = os.environ.get("PROVIDER", "deepseek")

PROVIDERS = {
    "deepseek": {
        "url":     "https://api.deepseek.com/chat/completions",
        "model":   "deepseek-v4-flash",     # 更强可换 deepseek-v4-pro（贵约 3 倍）
        "env":     "DEEPSEEK_API_KEY",
    },
    "claude": {
        "url":     "https://api.anthropic.com/v1/messages",
        "model":   "claude-haiku-4-5",
        "env":     "ANTHROPIC_API_KEY",
    },
}
# -----------------------------------------

DRY_RUN = os.environ.get("DRY_RUN") == "1"


def load_words():
    with open("vocab.json", encoding="utf-8") as f:
        data = json.load(f)
    return [w["en"] + " (" + w["zh"] + ")" for w in data]


def pick_today(words, day_n):
    total = len(words)
    i = (day_n * WORDS_PER_DAY) % total
    todays = words[i:i + WORDS_PER_DAY]
    if len(todays) < WORDS_PER_DAY:                 # 跨到词库末尾时回绕
        todays += words[:WORDS_PER_DAY - len(todays)]
    back = REVIEW_DAYS * WORDS_PER_DAY
    reviews = words[max(0, i - back):i]
    return todays, reviews


def build_prompt(todays, reviews):
    return f"""你是一位专门辅导中国建筑智能化工程师的英语私教。
学员背景：暖通空调专业，8 年楼宇自控与数字孪生经验，
正在参与新加坡东部医院智慧医院项目，需要用英语开技术会议。
英语水平：大学四级，能认基础词，无口语能力。

今天的 {len(todays)} 个新词：{todays}
需要复习的词：{reviews}

请生成今日学习卡片，严格按以下格式，总字数控制在 500 字以内：

【今日 {len(todays)} 词】
逐个给出：单词 / 音标 / 中文 / 一个来自智慧建筑或新加坡医院项目的真实工作例句（中英对照）

【场景对话】
写一段 4 轮的项目会议对话（中英对照），必须自然用上今天这几个词，
场景从以下随机选：冷站节能讨论 / 设备接入调试 / 项目进度会 / 与顾问的技术澄清

【昨日回顾】
把需要复习的词做成 3 道中译英填空题，答案放在最后

【今日一句】
一句会议高频表达，中英对照，标注使用场景

只输出卡片内容本身，不要任何开场白或结束语。"""


def call_ai(prompt):
    cfg = PROVIDERS.get(PROVIDER)
    if cfg is None:
        raise SystemExit(f"PROVIDER 只能是 {list(PROVIDERS)}，当前是 {PROVIDER!r}")
    api_key = os.environ.get(cfg["env"])
    if not api_key:
        raise SystemExit(f"缺少环境变量 {cfg['env']}")

    if PROVIDER == "deepseek":
        # DeepSeek 是 OpenAI 兼容格式
        body = {
            "model": cfg["model"],
            "max_tokens": MAX_TOKENS,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        headers = {
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
        }
    else:
        body = {
            "model": cfg["model"],
            "max_tokens": MAX_TOKENS,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    req = urllib.request.Request(
        cfg["url"], data=json.dumps(body).encode("utf-8"), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            resp = json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")
        raise SystemExit(f"[调用 {PROVIDER} 失败] HTTP {e.code}: {detail}")

    if PROVIDER == "deepseek":
        return resp["choices"][0]["message"]["content"]
    return resp["content"][0]["text"]


def push_wechat(title, content, token):
    payload = json.dumps({
        "token": token,
        "title": title,
        "content": content.replace("\n", "<br>"),
        "template": "html",
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://www.pushplus.plus/send",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        resp = json.load(r)
    if resp.get("code") != 200:
        raise SystemExit(f"[推送失败] {resp}")
    print("[推送成功]", resp.get("msg"))


def main():
    today = datetime.date.today()
    day_n = (today - START_DATE).days
    if day_n < 0:
        # 测试用：设 FORCE_DAY=1 可在起始日之前强制按第 1 天跑
        force = os.environ.get("FORCE_DAY")
        if not force:
            print(f"还没到起始日 {START_DATE}，今天不推送。"
                  f"（测试可设 FORCE_DAY=1）")
            return
        day_n = int(force) - 1

    words = load_words()
    todays, reviews = pick_today(words, day_n)
    week_no = day_n // 7 + 1
    print(f"Day {day_n + 1} (第 {week_no} 周) 今日词：{todays}")

    content = call_ai(build_prompt(todays, reviews))

    title = f"英语打卡 Day {day_n + 1}"
    if DRY_RUN:
        print("=" * 40)
        print(title)
        print(content)
        print("=" * 40)
        print("(DRY_RUN 模式，未推送微信)")
        return

    token = os.environ.get("PUSHPLUS_TOKEN")
    if not token:
        raise SystemExit("缺少环境变量 PUSHPLUS_TOKEN")
    push_wechat(title, content, token)


if __name__ == "__main__":
    sys.exit(main())
