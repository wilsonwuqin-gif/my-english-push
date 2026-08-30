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
import hashlib
import json
import asyncio
import datetime
import urllib.request
import urllib.error

# ---------------- 可调参数 ----------------
# GitHub Actions 的机器是 UTC 时区。cron 在 UTC 23:00 触发时北京已是次日早 7 点，
# 但机器上的 date.today() 还停在前一天，直接用会导致 Day 编号错一天。
BEIJING = datetime.timezone(datetime.timedelta(hours=8))

START_DATE    = datetime.date(2026, 8, 30)  # 学习起始日 = 第 1 天（北京时间）
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

请生成今日学习卡片。全文用纯文本，禁止使用任何 Markdown 符号
（不要星号、井号、反引号、横线分隔符）。严格按以下八节输出，
每节的标记必须原样写出，包括方括号，标记单独占一行：

正文部分每一行都必须以一个「行标记 + 竖线」开头，不得有例外。
可用的行标记只有以下几种，含义固定：
  W| 单词行，格式为  W|单词|音标|中文    音标要带前后斜杠
  E| 英文行
  C| 中文行
  T| 小标题行（例如对话的场景名）
  D| 对话行，格式为  D|说话人|英文句
  Q| 题目行
  K| 答案行
  U| 补充说明行（例如使用场景）

[S1]今日 {len(todays)} 词
每个词写三行：先 W| 行，再 E| 行给一个来自智慧建筑或新加坡医院项目的
真实工作英文例句，再 C| 行给该例句的中文翻译。

[S2]场景对话
先一行 T| 写场景名，场景从以下随机选：冷站节能讨论 / 设备接入调试 /
项目进度会 / 与顾问的技术澄清。
然后写 4 轮对话，每轮两行：D|说话人|英文句，紧跟 C|该句中文。
对话必须自然用上今天这几个词。

[S3]昨日回顾
把需要复习的词做成 3 道中译英填空题，每题一行 Q|，
最后把三题答案写成一行 K|。若今日无复习词，只写一行 C|今日无复习词。

[S4]今日一句
三行：E|英文句，C|中文，U|使用场景说明。
内容是一句会议高频表达。

以上四节合计控制在 500 字以内。
下面四节是给语音朗读用的，不计入字数，必须完整输出、不可省略。
朗读稿必须是纯文本：不要音标、不要括号注释、不要序号编号，
句子之间用句号分隔，让语音停顿自然。

[A1]
朗读第一节。每个新词按「英文词。英文词。中文意思。英文例句。英文例句。」
的顺序写，英文部分重复两遍便于跟读。

[A2]
朗读第二节。把场景对话的英文部分完整读一遍，中文不读。

[A3]
朗读第三节。把三道填空题的正确英文答案句各读两遍。若今日无复习词，写一句
No review today.

[A4]
朗读第四节。今日一句的英文，重复两遍。

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


SEC_RE = re.compile(r"\[(S[1-4]|A[1-4])\]")


def parse_sections(raw):
    """把 AI 输出切成 4 个正文小节和 4 段朗读稿。
    返回 ([(小节标题, 小节正文), ...], [朗读稿, ...])"""
    parts = SEC_RE.split(raw)      # [前言, 'S1', 内容, 'S2', 内容, ...]
    d = {}
    for i in range(1, len(parts) - 1, 2):
        d[parts[i]] = parts[i + 1].strip()

    sections, scripts = [], []
    for n in range(1, 5):
        body = d.get(f"S{n}", "")
        if body:
            head, _, rest = body.partition("\n")
            sections.append((head.strip(), rest.strip()))
        scripts.append(d.get(f"A{n}", ""))

    if not sections:               # 兜底：AI 没按格式输出就整段推送
        print("[切分] 未识别到分节标记，按整段处理")
        sections = [("今日内容", raw.strip())]
        scripts = [""]
    return sections, scripts


def make_audio(script, day_n, idx):
    """给第 idx 节生成 mp3，返回相对路径；失败返回 None（不影响文字推送）"""
    if not (ENABLE_AUDIO and script.strip()):
        return None
    try:
        import edge_tts
    except ImportError:
        print("[音频] 未安装 edge-tts，跳过")
        return None

    os.makedirs(AUDIO_DIR, exist_ok=True)
    # 文件名带内容哈希：内容变了文件名就变，URL 也就变了。
    # 否则同名文件被 jsDelivr 缓存后，改了内容 CDN 仍返回旧音频，
    # 会出现「文字是今天的、声音是上次的」。
    sig = hashlib.sha1(
        (script + VOICE + SPEECH_RATE).encode("utf-8")).hexdigest()[:8]
    stem = f"day-{day_n + 1:03d}-{idx}"
    path = f"{AUDIO_DIR}/{stem}-{sig}.mp3"

    if os.path.exists(path):                 # 内容没变就不用重新合成
        print(f"[音频] 第 {idx} 节内容未变，沿用 {path}")
        return path

    for old_file in glob.glob(f"{AUDIO_DIR}/{stem}-*.mp3"):
        os.remove(old_file)                  # 清掉同一节的旧哈希版本

    async def _run():
        tts = edge_tts.Communicate(script, VOICE, rate=SPEECH_RATE)
        await tts.save(path)

    try:
        asyncio.run(_run())
    except Exception as e:
        print(f"[音频] 第 {idx} 节生成失败：{e}")
        return None

    print(f"[音频] 第 {idx} 节 {len(script)} 字 -> {path}"
          f"（{os.path.getsize(path) // 1024} KB）")
    return path


def cleanup_audio():
    """按天分组，只保留最近 KEEP_AUDIO_DAYS 天的 mp3"""
    def day_of(f):
        m = re.search(r"day-(\d+)-", os.path.basename(f))
        return int(m.group(1)) if m else None

    files = glob.glob(f"{AUDIO_DIR}/day-*.mp3")
    days = {d for d in (day_of(f) for f in files) if d is not None}
    keep = set(sorted(days)[-KEEP_AUDIO_DAYS:])
    for f in files:
        d = day_of(f)
        if d is not None and d not in keep:
            os.remove(f)
            print(f"[音频] 清理旧文件 {f}")


def audio_url(path):
    """jsDelivr CDN 链接（国内访问比 GitHub 原生链接快）"""
    return f"https://cdn.jsdelivr.net/gh/{GH_REPO}@main/{path}"


# ---------------- 排版样式（改这里就能调颜色字号） ----------------
# 原则：普通文字不指定颜色，继承页面本身的文字色，
#      这样浅色/深色模式都自动正确。只有强调色才写死。
#
# 强调色用「中间调」，在白底和黑底上都看得清；
# 下面的 <style> 再针对深色模式换成更亮的版本（用 !important 覆盖行内样式）。
ACCENT = {
    "word": "#D93F3F",   # 单词：红
    "dlg":  "#3D8BD4",   # 对话英文：蓝
    "key":  "#B07A2E",   # 今日一句：棕
}
ACCENT_DARK = {
    "word": "#FF7A7A",
    "dlg":  "#7FBEFF",
    "key":  "#E3B461",
}

CSS = {
    "head":   "font-size:17px;font-weight:700;margin:22px 0 10px",
    "word":   f"font-size:17px;font-weight:700;color:{ACCENT['word']}",
    "phon":   "font-size:15px;opacity:.75",       # 音标：淡一点，不指定颜色
    "wzh":    "font-size:16px;font-weight:700",   # 词义：加粗，继承颜色
    "en":     "font-size:15px",
    "zh":     "font-size:15px",
    "topic":  "font-size:15px;opacity:.75",
    "dlg":    f"font-size:15px;font-weight:700;color:{ACCENT['dlg']}",
    "spk":    "font-size:15px;opacity:.75",
    "key":    f"font-size:15px;font-weight:700;color:{ACCENT['key']}",
    "note":   "font-size:15px",
}

STYLE_BLOCK = (
    "<style>"
    "@media (prefers-color-scheme: dark){"
    f".w{{color:{ACCENT_DARK['word']}!important}}"
    f".d{{color:{ACCENT_DARK['dlg']}!important}}"
    f".k{{color:{ACCENT_DARK['key']}!important}}"
    "}"
    "</style>"
)
# ------------------------------------------------------------------


def esc(t):
    return (t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def render_line(line, sec_idx):
    """把一行带标记的文本渲染成 HTML。sec_idx 从 0 起，用于区分【今日一句】"""
    code, _, rest = line.partition("|")
    code = code.strip()
    f = [p.strip() for p in rest.split("|")]

    if code == "W" and len(f) >= 3:
        return (f'<p style="margin:14px 0 2px">'
                f'<span class="w" style="{CSS["word"]}">{esc(f[0])}</span>&nbsp;'
                f'<span style="{CSS["phon"]}">{esc(f[1])}</span>&nbsp;'
                f'<span style="{CSS["wzh"]}">{esc(f[2])}</span></p>')
    if code == "D" and len(f) >= 2:
        return (f'<p style="margin:6px 0 0">'
                f'<span style="{CSS["spk"]}">{esc(f[0])}:&nbsp;</span>'
                f'<span class="d" style="{CSS["dlg"]}">{esc(f[1])}</span></p>')
    if code == "E":
        if sec_idx == 3:
            return f'<p class="k" style="margin:2px 0;{CSS["key"]}">{esc(f[0])}</p>'
        return f'<p style="margin:2px 0;{CSS["en"]}">{esc(f[0])}</p>'
    if code == "C":
        return f'<p style="margin:2px 0;{CSS["zh"]}">{esc(f[0])}</p>'
    if code == "T":
        return f'<p style="margin:2px 0;{CSS["topic"]}">{esc(f[0])}</p>'
    if code in ("Q", "K", "U"):
        return f'<p style="margin:4px 0;{CSS["note"]}">{esc(f[0])}</p>'
    # 没有标记或标记不认识：原样输出，保证内容不丢
    return f'<p style="margin:4px 0;{CSS["note"]}">{esc(line)}</p>'


def build_html(sections, paths):
    """把小节和音频拼成 HTML：每节标题后面挂一个播放条，
    正文就在下面，播放时不离开当前页面。"""
    out = [STYLE_BLOCK]
    for i, (head, body) in enumerate(sections):
        out.append(f'<p style="{CSS["head"]}">【{esc(head)}】</p>')
        p = paths[i] if i < len(paths) else None
        if p:
            out.append(
                f'<audio controls preload="none" style="width:100%;height:34px"'
                f' src="{audio_url(p)}">你的浏览器不支持音频播放</audio>')
        for line in body.splitlines():
            if line.strip():
                out.append(render_line(line.strip(), i))
    return "".join(out)


def push_wechat(title, content, token):
    # 内容已经是 HTML（含 <audio> 播放条），用 html 模板原样渲染
    template = os.environ.get("PUSH_TEMPLATE", "html")
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
    today = datetime.datetime.now(BEIJING).date()      # 按北京时间算，不用 UTC
    day_n = (today - START_DATE).days
    print(f"[日期] 北京时间 {today}，起始日 {START_DATE}")
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
    if not raw.strip():
        raise SystemExit("[错误] AI 返回内容为空，请检查 API 状态")

    sections, scripts = parse_sections(raw)
    print(f"[切分] {len(sections)} 个小节：" +
          " / ".join(f"{h}({len(b)}字)" for h, b in sections))

    paths = [make_audio(scripts[i] if i < len(scripts) else "", day_n, i + 1)
             for i in range(len(sections))]
    cleanup_audio()

    with open(CARD_CACHE, "w", encoding="utf-8") as f:
        json.dump({"day_n": day_n, "sections": sections, "paths": paths},
                  f, ensure_ascii=False)
    return sections, paths


def do_send(day_n, sections, paths):
    title = f"英语打卡 Day {day_n + 1}"
    n_audio = sum(1 for p in paths if p)
    print(f"[发送] {len(sections)} 个小节，{n_audio} 段音频")
    if not sections:
        raise SystemExit("[错误] 待发送内容为空，中止（不发空消息）")
    card = build_html(sections, paths)

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
        do_send(d["day_n"], d["sections"], d["paths"])
        return

    sections, paths = do_generate(day_n)
    if mode != "generate":
        do_send(day_n, sections, paths)


if __name__ == "__main__":
    sys.exit(main())
