# 中越翻译工具（修复 + 语音版）

Flask 单页应用：中文 ⇄ 越南语翻译，术语优先保留，支持语音朗读和语音输入。

## 这次修了什么

### 1. 「不能翻译」的根因：空结果

上游模型 `hy3` 和 `deepseek-v4-flash` 都是会先「思考」的模型，思考消耗的
`reasoning_tokens` 也计入 `max_tokens`。原代码把 `max_tokens` 写死为 500，
思考一多就把额度用光，接口返回：

```
finish_reason = "length"
content       = ""          ← 空字符串
usage.completion_tokens_details.reasoning_tokens ≈ 500
```

原代码没有校验内容，直接把 `""` 当成译文缓存并返回 200，前端结果区就是一片空白。

**修复**：

- 请求体加 `"thinking": {"type": "disabled"}` 关闭思考（实测可用，速度从 8–13 秒降到 1.2–1.8 秒）；
- `max_tokens` 按输入长度动态计算（1024–8192），不再写死 500；
- 空内容视为失败：快速模型 → 默认模型 → 加大 token 再试，仍为空返回 **502**；
- 空结果不写缓存；缓存 key 去掉首尾空白；
- 新增 `direction` 白名单、5000 字长度限制、`/health`。

### 2. 术语替换产生的病句

词库里有单字术语 `开→Mở`、`关→Đóng / Tắt`、`下→Dưới`、`上→Trên`，
按子串替换会把「开关」拆成「Mở Đóng / Tắt」、把「下午」变成「Dưới 午」。

**修复**：只替换两个字符以上的术语；术语出现在句中时首字母小写、句首才大写；
`7:30`、`3.5`、`1,000` 这类数字不再被空格拆开。

### 3. 前端

页面改到 `templates/index.html`，并修复：

- 复制提示 `undefined`（缺 `copy_success` / `copy_fail` 文案）
- 切界面语言后「⚡ 缓存加速」徽章消失
- 「互换」只换方向、不交换文本
- 请求无超时、非 JSON 错误直接抛 `SyntaxError`
- 翻译中仍可复制、切换方向会留下旧结果
- 新增 🔊 朗读、🎤 语音输入

## 目录

```
web_translator.py        后端（Flask + 翻译 + 缓存）
templates/index.html     前端页面（含语音功能）
词库20260812.csv          术语表
requirements.txt
runtime.txt
gunicorn.py
```

## 本地运行

```bash
pip install -r requirements.txt
export TRANSLATE_API_KEY=你的密钥        # Windows: set TRANSLATE_API_KEY=...
python web_translator.py
# 打开 http://127.0.0.1:5000
```

## 部署到 Render

1. 把本目录推到 GitHub 仓库（注意 `templates/` 要一起提交）；
2. Render 的 Start Command 保持 `gunicorn web_translator:app`；
3. 在 Environment 里配置（可选，但强烈建议）：

| 变量 | 说明 |
|---|---|
| `TRANSLATE_API_KEY` | 腾讯云 MaaS 密钥，**必须轮换新密钥后再填** |
| `TRANSLATE_MODEL` | 默认模型，缺省 `hy3` |
| `TRANSLATE_FAST_MODEL` | 快速模型，缺省 `deepseek-v4-flash` |
| `SECRET_KEY` | Flask secret |

## 实测结果

修复前：10 条全新句子 3 条空；「下午三点开会，请准时参加」5 次全空。

修复后：

```
10 条：空结果 0 条，超过 5 秒 0 条，总耗时 14.8s（单条约 1.2–1.7 秒）
```

示例：

- `7:30验布机等所有设备不用关电源，只关电脑显示屏开关，关闭灯光`
  → `7:30 máy kiểm vải và tất cả thiết bị không cần tắt nguồn, chỉ tắt công tắc màn hình máy tính, tắt đèn`
- `这个订单的交期是下周五`
  → `Đơn hàng này có ngày giao hàng là thứ Sáu tuần sau`

## 安全提醒

- `API_CONFIG` 里的密钥已经随仓库/压缩包泄露，**请到腾讯云控制台作废并重新生成**，
  之后只用环境变量注入。
- `/clear_cache` 仍然没有鉴权（任何访客都能清空缓存），需要的话可以加 token 或从界面移除。

## 语音功能说明

- 朗读：浏览器 `speechSynthesis`，中→越用 `vi-VN`，越→中用 `zh-CN`；无越南语语音包时会提示。
- 语音输入：`SpeechRecognition`，Chrome / Edge 支持最好，Firefox 不支持会自动隐藏按钮。
- 都需要 HTTPS（Render 默认满足）。
