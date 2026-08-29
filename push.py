# -*- coding: utf-8 -*-
"""
每日英语推送脚本
流程：算出今天该学哪几个词 -> 调 Claude 生成学习卡片 -> 推送到微信(PushPlus)

本地测试:
    set DRY_RUN=1           (只打印，不推送微信)
    python push.py
"""
import os
import re
import sys
import glob
import json
import asyncio
import datetime
import urllib.request
import urllib.error

# ---------------- 可调参数 ----------------
START_DATE    = datetime.date(2026, 9, 1)  # 学习起始日，改成你真正开始的那天
WORDS_PER_DAY = 3                          # 每天新词数量
REVIEW_DAYS   = 3                          # 复习前几天的词
MAX_TOKENS    = 4000

# ---- 音频朗读 ----
ENABLE_AUDIO    = True
VOICE           = "en-US-AvaMultilingualNeural"   # 多语种音色，中英混读自然
                  # 备选：zh-CN-XiaoxiaoNeural（女声偏中文）
                  #       en-US-BrianMultilingualNeural（男声）
SPEECH_RATE     = "-10%"       # 语速，初学者放慢一点。正常写 "+0%"
KEEP_AUDIO_DAYS = 7            # 仓库里只保留最近几天的 mp3
AUDIO_DIR       = "audio"
GH_REPO         = os.environ.get("GH_REPO", "wilsonwuqin-gif/my-english-push")
CARD_CACHE      = "card_cache.txt"   # generate 与 send 两步之间传递内容

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

请生成今日学习卡片，严格按以下格式。
前四节（卡片正文）控制在 500 字以内；
第五节【朗读稿】不计入这个字数，必须完整输出，不可省略：

【今日 {len(todays)} 词】
逐个给出：单词 / 音标 / 中文 / 一个来自智慧建筑或新加坡医院项目的真实工作例句（中英对照）

【场景对话】
写一段 4 轮的项目会议对话（中英对照），必须自然用上今天这几个词，
场景从以下随机选：冷站节能讨论 / 设备接入调试 / 项目进度会 / 与顾问的技术澄清

【昨日回顾】
把需要复习的词做成 3 道中译英填空题，答案放在最后

【今日一句】
一句会议高频表达，中英对照，标注使用场景

【朗读稿】
这一段是给语音朗读用的，必须是纯文本，规则如下：
- 不要任何 Markdown 符号、不要音标、不要括号注释、不要序号编号
- 每个新词按「英文词。英文词。中文意思。英文例句。英文例句。」的顺序写，
  英文部分重复两遍便于跟读
- 然后把场景对话的英文部分完整读一遍，中文不读
- 最后读今日一句的英文，重复两遍
- 句子之间用句号分隔，让语音停顿自然

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
            # DeepSeek 思考模式默认开启且 effort=high，会把 max_tokens
            # 全部消耗在思维链上导致正文为空。这类格式化写作不需要思考。
            "thinking": {"type": "disabled"},
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
        choice = resp["choices"][0]
        usage  = resp.get("usage", {})
        print(f"[AI] finish_reason={choice.get('finish_reason')} "
              f"tokens={usage.get('completion_tokens')}/{MAX_TOKENS}")
        return choice["message"].get("content") or ""
    return resp["content"][0]["text"]


def split_script(raw):
    """把【朗读稿】从卡片里剥离出来，返回 (展示用卡片, 朗读稿)"""
    m = re.search(r"【朗读稿】", raw)
    if not m:
        return raw, ""
    card   = raw[:m.start()].rstrip()
    script = raw[m.end():].strip()
    # 兜底：如果切完正文是空的（【朗读稿】出现在开头等异常情况），
    # 宁可把整段原文推给你，也不能推一条空消息
    if not card:
        print("[切分] 剥离后正文为空，改用原始全文")
        card = raw.strip()
    return card, script


def make_audio(script, day_n):
    """用 edge-tts 生成 mp3，返回文件相对路径；失败返回 None（不影响文字推送）"""
    if not ENABLE_AUDIO:
        print("[音频] ENABLE_AUDIO 为 False，跳过")
        return None
    if not script:
        print("[音频] AI 未输出【朗读稿】一节，无内容可朗读，跳过")
        return None
    print(f"[音频] 朗读稿 {len(script)} 字，开始合成…")
    try:
        import edge_tts
    except ImportError:
        print("[音频] 未安装 edge-tts，跳过")
        return None

    os.makedirs(AUDIO_DIR, exist_ok=True)
    path = f"{AUDIO_DIR}/day-{day_n + 1:03d}.mp3"

    async def _run():
        tts = edge_tts.Communicate(script, VOICE, rate=SPEECH_RATE)
        await tts.save(path)

    try:
        asyncio.run(_run())
    except Exception as e:
        print(f"[音频] 生成失败，跳过：{e}")
        return None

    size = os.path.getsize(path)
    print(f"[音频] 已生成 {path}（{size // 1024} KB）")
    cleanup_audio()
    return path


def cleanup_audio():
    """只保留最近 KEEP_AUDIO_DAYS 个 mp3，避免仓库无限膨胀"""
    files = sorted(glob.glob(f"{AUDIO_DIR}/day-*.mp3"))
    for old in files[:-KEEP_AUDIO_DAYS]:
        os.remove(old)
        print(f"[音频] 清理旧文件 {old}")


def audio_url(path):
    """jsDelivr CDN 链接（国内访问比 GitHub 原生链接快）"""
    return f"https://cdn.jsdelivr.net/gh/{GH_REPO}@main/{path}"


def push_wechat(title, content, token):
    # AI 输出的是 Markdown。markdown 模板能正确渲染 **加粗** 和链接；
    # 如果微信里显示效果不理想，设环境变量 PUSH_TEMPLATE=html
    template = os.environ.get("PUSH_TEMPLATE", "markdown")
    if template == "html":
        content = content.replace("\n", "<br>")
    payload = json.dumps({
        "token": token,
        "title": title,
        "content": content,
        "template": template,
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


def resolve_day():
    today = datetime.date.today()
    day_n = (today - START_DATE).days
    if day_n < 0:
        # 测试用：设 FORCE_DAY=1 可在起始日之前强制按第 1 天跑
        force = os.environ.get("FORCE_DAY")
        if not force:
            print(f"还没到起始日 {START_DATE}，今天不推送。"
                  f"（测试可设 FORCE_DAY=1）")
            return None
        day_n = int(force) - 1
    return day_n


def do_generate(day_n):
    """调 AI 生成卡片 + 生成音频，结果写入 CARD_CACHE"""
    words = load_words()
    todays, reviews = pick_today(words, day_n)
    print(f"Day {day_n + 1} (第 {day_n // 7 + 1} 周) 今日词：{todays}")

    raw = call_ai(build_prompt(todays, reviews))
    print(f"[AI] 返回 {len(raw)} 字")
    card, script = split_script(raw)
    print(f"[切分] 正文 {len(card)} 字 / 朗读稿 {len(script)} 字")
    if not card:
        raise SystemExit("[错误] AI 返回内容为空，请检查 API 状态")
    path = make_audio(script, day_n)

    with open(CARD_CACHE, "w", encoding="utf-8") as f:
        json.dump({"day_n": day_n, "card": card, "audio": path},
                  f, ensure_ascii=False)
    return card, path


def do_send(day_n, card, path):
    title = f"英语打卡 Day {day_n + 1}"
    print(f"[发送] 正文 {len(card)} 字，音频 {path or '无'}")
    if not card.strip():
        raise SystemExit("[错误] 待发送内容为空，中止（不发空消息）")
    if path:
        card += "\n\n---\n🎧 [点此收听今日朗读](" + audio_url(path) + ")"

    if DRY_RUN:
        print("=" * 40)
        print(title)
        print(card)
        print("=" * 40)
        print("(DRY_RUN 模式，未推送微信)")
        return

    token = os.environ.get("PUSHPLUS_TOKEN")
    if not token:
        raise SystemExit("缺少环境变量 PUSHPLUS_TOKEN")
    push_wechat(title, card, token)


def main():
    # 用法：
    #   python push.py            本地测试，生成+推送一条龙
    #   python push.py generate   只生成内容和音频（工作流第 1 步）
    #   python push.py send       读取已生成的内容并推送（工作流第 3 步）
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"

    day_n = resolve_day()
    if day_n is None:
        return

    if mode == "send":
        if not os.path.exists(CARD_CACHE):
            raise SystemExit(f"找不到 {CARD_CACHE}，请先运行 generate")
        with open(CARD_CACHE, encoding="utf-8") as f:
            d = json.load(f)
        do_send(d["day_n"], d["card"], d.get("audio"))
        return

    card, path = do_generate(day_n)
    if mode != "generate":
        do_send(day_n, card, path)


if __name__ == "__main__":
    sys.exit(main())
