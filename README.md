# 每日英语推送（方案一：PushPlus + GitHub Actions + DeepSeek API）

对应《人生计划书（2026-2030）》C.4.2。本仓库已经把脚本、词库、定时任务都准备好了，
你只需要照着下面的步骤走一遍，全程约 60 分钟，之后每天早上 7:00 微信自动收到学习卡片。

---

## 零、先确认你手上有什么

| 需要 | 说明 |
|---|---|
| 微信 | 用来扫码登录 PushPlus、接收推送 |
| 邮箱 | 注册 GitHub、Anthropic 各一个（可同一个） |
| AI API | DeepSeek（已有余额，无需充值）或 Anthropic Claude（需外币卡充 5 美元） |
| 电脑 | Windows 即可，本机已装好 Python 3.12 和 Git |

本目录已包含：

```
my-english-push/
├── push.py                      # 主脚本
├── vocab.json                   # 300 词词库（已按 C.5 生成，20 周 × 15 词）
├── last_run.txt                 # 保活用
├── .gitignore
└── .github/workflows/daily.yml  # 定时任务
```

---

## 步骤 ① 开通微信推送渠道（10 分钟）

1. 手机或电脑浏览器打开 **https://www.pushplus.plus**
2. 点右上角「登录」→ 出现二维码 → 用**微信扫码** → 授权登录
3. 登录后进入「一对一推送」页面，页面上有一串 32 位的 **token**（形如
   `a1b2c3d4e5f6...`），点复制，先粘到记事本里存着
4. 同一页面上有个「关注公众号」的二维码，**必须用微信关注它**（公众号名：pushplus 推送加）。
   不关注就收不到消息
5. 验证：在该页面点「发送测试消息」，微信里应立刻收到一条。收到 = 这一步成功

> 如果 PushPlus 打不开，备选是 Server 酱 https://sct.ftqq.com ，流程一样，
> 只是推送接口地址不同（见文末「换成 Server 酱」）。

---

## 步骤 ② 准备 AI 的 API Key

本脚本支持两家，**默认用 DeepSeek**（你已经有账号和余额，这一步基本可以跳过）。

### 方案 A：DeepSeek（推荐，你已有）

1. 打开 **https://platform.deepseek.com** → 左侧 **API keys**
2. 你已经有一个名为 `wuqin` 的 key。但页面只在创建时显示完整 key，
   列表里是 `sk-d1e47*****bd73` 这种打码形式。
   - 如果你当初存下来了 → 直接用
   - 如果没存 → 点 **创建 API key**，新建一个，**立刻完整复制**
3. 余额：你现在有 ¥8.62。本脚本用 `deepseek-v4-flash`，
   每天一次调用大约 1 分钱，**这点余额够用两年以上**，不用充值。
4. 顺手把「余额预警」开一下（用量信息页面那个黄色提示），余额低时会通知你。

> 顺带一提：DeepSeek 的高峰时段是周一至周五 9:00-12:00 和 14:00-18:00。
> 我们的推送定在早上 7:00，永远落在低价时段。

### 方案 B：Claude（备选）

1. 打开 **https://console.anthropic.com** 注册验证
2. **Plans / Billing** 充值，最低 5 美元
3. **API Keys** → **Create Key** → 立刻复制 `sk-ant-...`（只显示一次）

> ⚠️ **Claude 会员（Pro/Max）不包含 API 额度**，这是两套独立的账，必须单独充值。
> 会员每月附赠的 Agent SDK 额度也只能用于 Agent SDK / Claude Code Action，
> 不能用于本脚本这种普通 Messages API 调用。

### 怎么切换

`push.py` 顶部的 `PROVIDER`，或工作流里的 `PROVIDER` 环境变量：
- `deepseek` → 用 `DEEPSEEK_API_KEY`，模型 `deepseek-v4-flash`
  （想要更细致的内容可改成 `deepseek-v4-pro`，贵约 3 倍，一个月也就几毛钱）
- `claude` → 用 `ANTHROPIC_API_KEY`，模型 `claude-haiku-4-5`

> 安全提醒：key 等于你的钱包。绝不要发到微信群、不要写进代码、不要截图发人。
> （你刚才截图里那个打码的 key 是安全的，但以后发截图前记得确认一下。）

---

## 步骤 ③ 本地先跑通（15 分钟，强烈建议做）

先在自己电脑上确认脚本能出内容，再上传 GitHub。这样出错时好排查。

在本目录打开 PowerShell（在文件夹地址栏输入 `powershell` 回车），依次执行：

```powershell
$env:DEEPSEEK_API_KEY = "把你的sk-开头的密钥粘在这里"
$env:DRY_RUN = "1"
python push.py
```

- 屏幕上打印出一整张中英对照的学习卡片 = 成功
- 报 `缺少环境变量` = 上面第一行没执行成功，重来
- 报 `HTTP 401` = 密钥错了或多了空格
- 报 `HTTP 402` / 余额不足 = 需要充值

再测微信推送（去掉 DRY_RUN）：

```powershell
$env:DRY_RUN = "0"
$env:PUSHPLUS_TOKEN = "把你的pushplus token粘在这里"
python push.py
```

微信收到消息 = 全链路打通。

> 注意：`push.py` 里 `START_DATE = datetime.date(2026, 9, 1)`。
> 如果今天早于这个日期，脚本会打印「还没到起始日」直接退出。
> 想立刻测试，就把这一行改成今天的日期。

---

## 步骤 ④ 建 GitHub 仓库并上传（20 分钟）

1. 打开 **https://github.com** 注册账号（已有则登录）
2. 右上角 **+** → **New repository**
   - Repository name: `my-english-push`
   - 选 **Private**（私有，必须）
   - 其他都不勾（不要加 README，本地已经有了）
   - 点 **Create repository**
3. 创建后页面会显示一段命令，记下你的仓库地址，形如
   `https://github.com/你的用户名/my-english-push.git`
4. 回到本目录的 PowerShell，执行：

```powershell
git init
git add .
git commit -m "init"
git branch -M main
git remote add origin https://github.com/你的用户名/my-english-push.git
git push -u origin main
```

5. 第一次 push 会弹出浏览器窗口让你登录 GitHub 授权，点同意即可
6. 刷新 GitHub 页面，看到 push.py / vocab.json / .github 三样东西 = 上传成功

---

## 步骤 ⑤ 配置密钥（5 分钟）

在 GitHub 仓库页面：

**Settings** → 左侧 **Secrets and variables** → **Actions** → **New repository secret**

添加两条（一条一条加）：

| Name | Secret |
|---|---|
| `PUSHPLUS_TOKEN` | 第①步的 token |
| `DEEPSEEK_API_KEY` | 第②步的 DeepSeek key |

（如果你选了方案 B，则加 `ANTHROPIC_API_KEY`，并把工作流里的 `PROVIDER` 改成 `claude`）

名字必须**一字不差、全大写**，否则工作流读不到。加完后列表里能看到两条，值是隐藏的（正常）。

---

## 步骤 ⑥ 手动触发测试（10 分钟）

1. 仓库页面点 **Actions** 标签
2. 若提示 "Workflows aren't being run on this forked repository" 或需要确认，
   点绿色按钮 **I understand my workflows, go ahead and enable them**
3. 左侧点 **daily-english** → 右侧 **Run workflow** → 绿色 **Run workflow**
4. 等 30 秒刷新，出现一条运行记录。点进去看每一步的日志：
   - 全绿 ✅ 且微信收到消息 = **大功告成**
   - 红叉 ❌ 点开报错的那一步看日志，对照下面的排错表

之后每天北京时间早上 7:00 自动推送，你什么都不用管。

---

## 排错表

| 现象 | 原因 | 处理 |
|---|---|---|
| 日志 `缺少环境变量 DEEPSEEK_API_KEY` | Secret 名字写错 | 到 Settings → Secrets 检查拼写和大小写 |
| 日志 `HTTP 401` | API Key 无效 | 重新生成一个 Key，更新 Secret |
| 日志 `HTTP 402` 或提示余额不足 | 余额用完了 | 到 DeepSeek 平台充值 |
| 日志 `[推送失败] code 999` | PushPlus token 错，或没关注公众号 | 回步骤① 重做 |
| 全绿但微信没收到 | 没关注 pushplus 公众号 / 被折叠 | 微信里搜「pushplus 推送加」关注 |
| 「还没到起始日」 | 今天 < START_DATE | 改 push.py 里的 START_DATE |
| 保活提交那步失败 | 仓库写权限 | Settings → Actions → General → Workflow permissions → 选 **Read and write permissions** |
| 定时不准，晚了十几分钟 | GitHub 免费队列排队，正常现象 | 不用管 |

---

## 日常维护

- **每天**：只需要看微信、跟读。不需要碰代码
- **改推送时间**：编辑 `.github/workflows/daily.yml` 里的 cron。
  UTC = 北京时间 − 8 小时。想 6:30 推送就写 `'30 22 * * *'`
- **改每天词量**：`push.py` 里 `WORDS_PER_DAY`
- **加自己的词**：编辑 `vocab.json`，按同样格式加对象即可
- **换模型 / 换供应商**：`push.py` 顶部的 `PROVIDER` 和 `PROVIDERS` 字典。
  想要更细致的内容，DeepSeek 改 `deepseek-v4-pro`，Claude 改 `claude-sonnet-5`
- **改 prompt**：`push.py` 里 `build_prompt()` 函数。这是全套东西里最值得你花时间调的地方
- **改完怎么生效**：

```powershell
git add .
git commit -m "update"
git push
```

- **停一段时间**：Actions 页面 → daily-english → 右上 `...` → Disable workflow

---

## 换成 Server 酱（备选）

若用 sct.ftqq.com，把 `push.py` 里的 `push_wechat()` 换成：

```python
def push_wechat(title, content, token):
    import urllib.parse
    data = urllib.parse.urlencode({"title": title, "desp": content}).encode()
    with urllib.request.urlopen(f"https://sctapi.ftqq.com/{token}.send", data=data, timeout=60) as r:
        print(json.load(r))
```

Secret 名字不变，把值换成 Server 酱的 SendKey（`SCT...` 开头）即可。

---

## 最后一句

C.4 原文说得对：**工具是为习惯服务的。**
如果卡在任何一步超过一小时，先别管自动化，直接每天手动把 `build_prompt()` 里那段
prompt 复制给任意 AI 助手用——效果一样，先把每天 25 分钟的习惯建起来。
