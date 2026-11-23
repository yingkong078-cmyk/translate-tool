# web_translator.py - 修复版
#
# 修复的核心问题：
#   上游模型 hy3 / deepseek-v4-flash 都是「会思考」的模型，会先消耗 reasoning tokens。
#   原代码把 max_tokens 固定为 500，思考一多就把额度用光，返回的 content 是空字符串
#   （finish_reason=length，usage.completion_tokens_details.reasoning_tokens≈500）。
#   原代码没有校验空内容，直接把 "" 当成译文缓存并返回 200，前端就显示一片空白。
#
# 本版的改动：
#   1. 请求体加 "thinking": {"type": "disabled"}，关闭思考，速度从 8-13 秒降到 1.5-3 秒；
#   2. max_tokens 按输入长度动态计算（1024 ~ 8192），不再写死 500；
#   3. 空内容视为失败：快速模型失败换默认模型，再失败返回 502，绝不返回空字符串；
#   4. 空结果不写缓存；缓存 key 去掉首尾空白；
#   5. 校验 direction、文本长度；新增 /health；
#   6. 页面拆到 templates/index.html（带朗读、语音输入），这里只负责接口。

from flask import Flask, Response, request, jsonify

import csv
import os
import re
from collections import OrderedDict
from datetime import datetime, timedelta

import requests


app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "translator_secret_key_2024")

# 页面文件位置：优先 templates/index.html，其次根目录 index.html。
# 这样无论把页面放在哪个位置都能打开，避免因为少传一个文件夹导致首页 500。
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PAGE_CANDIDATES = [
    os.path.join(BASE_DIR, "templates", "index.html"),
    os.path.join(BASE_DIR, "index.html"),
]
_page_cache = {"path": None, "mtime": None, "html": None}


# ==================== 配置区域 ====================
# ⚠️ 密钥原来直接写死在代码里，已经随仓库/压缩包泄露，请到腾讯云控制台轮换一个新的。
# 轮换后把新密钥配到 Render 的环境变量 TRANSLATE_API_KEY，不要再次提交到仓库。
API_CONFIG = {
    "base_url": os.environ.get(
        "TRANSLATE_BASE_URL",
        "https://tokenhub-intl.tencentmaas.com/v1/chat/completions",
    ),
    "api_key": os.environ.get(
        "TRANSLATE_API_KEY",
        "sk-sTs3bBB3kfhfml7buWfciNuUnoedJLGc2s7BQj2xdKA63x9K",
    ),
    "default_model": os.environ.get("TRANSLATE_MODEL", "hy3"),
    "fast_model": os.environ.get("TRANSLATE_FAST_MODEL", "deepseek-v4-flash"),
}

# CSV 词库文件路径（用绝对路径，避免工作目录不同导致加载不到）
TERM_CSV_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "词库20260812.csv"
)

# 单次请求最多接受的字数
MAX_INPUT_CHARS = 5000


class TranslationError(Exception):
    """翻译服务没有拿到有效内容时抛出，路由层会转成 502。"""


# ==================== 翻译缓存 ====================
class TranslationCache:
    """翻译缓存 - 减少重复 API 调用（LRU + 过期时间，不缓存空结果）"""

    def __init__(self, max_size=200, expire_minutes=30):
        self.cache = OrderedDict()
        self.max_size = max_size
        self.expire_minutes = expire_minutes

    def get(self, key):
        item = self.cache.get(key)
        if not item:
            return None

        value, timestamp = item

        # 过期
        if datetime.now() - timestamp >= timedelta(minutes=self.expire_minutes):
            self.cache.pop(key, None)
            return None

        # 空值一律视为未命中
        if not value:
            self.cache.pop(key, None)
            return None

        self.cache.move_to_end(key)
        return value

    def set(self, key, value):
        if not value:
            return
        if key in self.cache:
            self.cache.pop(key, None)
        elif len(self.cache) >= self.max_size:
            self.cache.popitem(last=False)
        self.cache[key] = (value, datetime.now())

    def clear(self):
        self.cache.clear()

    def get_size(self):
        return len(self.cache)


translation_cache = TranslationCache(max_size=200, expire_minutes=30)


# ==================== 术语管理器 ====================
class TermManager:
    def __init__(self, csv_file=None):
        self.csv_file = csv_file or TERM_CSV_FILE
        self.terms = self.load_terms()
    
    def load_terms(self):
        terms = {
            "zh_to_vi": {},
            "vi_to_zh": {}
        }
        
        try:
            if os.path.exists(self.csv_file):
                with open(self.csv_file, 'r', encoding='utf-8-sig') as f:
                    reader = csv.reader(f)
                    zh_col = None
                    vi_col = None
                    
                    for row in reader:
                        if not row:
                            continue
                        
                        if len(row) >= 2:
                            first_col = row[0].strip() if row[0] else ''
                            if '中文' in first_col or '术语' in first_col:
                                zh_col = 0
                                vi_col = 1
                                continue
                        
                        if zh_col is not None and vi_col is not None:
                            if len(row) > max(zh_col, vi_col):
                                zh = row[zh_col].strip() if zh_col < len(row) else ''
                                vi = row[vi_col].strip() if vi_col < len(row) else ''
                                if zh and vi and zh != '中文术语' and '中文' not in zh:
                                    terms["zh_to_vi"][zh] = vi
                                    if vi not in terms["vi_to_zh"]:
                                        terms["vi_to_zh"][vi] = zh
                
                print(f"✅ 从CSV加载了 {len(terms['zh_to_vi'])} 条术语")
            else:
                print(f"⚠️ CSV文件不存在: {self.csv_file}")
        except Exception as e:
            print(f"⚠️ 加载CSV失败: {e}")
        
        if len(terms["zh_to_vi"]) == 0:
            print("📚 使用内置默认术语")
            default_terms = {
                "zh_to_vi": {
                    "车床": "máy tiện",
                    "铣床": "máy phay",
                    "磨床": "máy mài",
                    "钻床": "máy khoan",
                    "数控机床": "máy CNC",
                    "加工中心": "trung tâm gia công",
                    "冲床": "máy dập",
                    "注塑机": "máy ép nhựa",
                    "粗加工": "gia công thô",
                    "精加工": "gia công tinh",
                    "热处理": "xử lý nhiệt",
                    "表面处理": "xử lý bề mặt",
                    "焊接": "hàn",
                    "装配": "lắp ráp",
                    "调试": "hiệu chỉnh",
                    "公差": "dung sai",
                    "粗糙度": "độ nhám",
                    "合格品": "sản phẩm đạt yêu cầu",
                    "不合格品": "sản phẩm không đạt",
                    "返工": "làm lại",
                    "报废": "loại bỏ",
                    "防护罩": "tấm chắn bảo vệ",
                    "紧急停止": "dừng khẩn cấp",
                    "安全操作规程": "quy trình vận hành an toàn",
                    "劳保用品": "đồ bảo hộ lao động",
                    "开机": "khởi động máy",
                    "关机": "tắt máy",
                    "检查": "kiểm tra",
                    "更换": "thay thế",
                    "清洁": "vệ sinh",
                    "加油": "tra dầu",
                    "注意": "chú ý",
                    "危险": "nguy hiểm",
                    "缝头压痕": "đầu may ép",
                    "批次号": "số lô hàng",
                    "稀密路": "đường dày ngang thưa",
                    "染色不匀": "nhuộm màu không đều",
                    "条影": "đường ảnh",
                    "安排": "Sắp xếp",
                    "包装": "đóng gói",
                    "请优先": "xin ưu tiên",
                    "提明细": "Lấy chi tiết",
                    "品种": "chủng loại",
                    "布": "vải",
                    "验布": "kiểm vải",
                    "检查布": "kiểm tra vải",
                    "万国旗": "Cờ màu",
                    "撤明细": "rút chi tiết"
                },
                "vi_to_zh": {}
            }
            for zh, vi in default_terms["zh_to_vi"].items():
                default_terms["vi_to_zh"][vi] = zh
            return default_terms
        
        return terms
    
    def get_user_terms(self):
        return self.terms["zh_to_vi"]
    
    def get_user_terms_vi(self):
        return self.terms["vi_to_zh"]
    
    def get_term_count(self):
        return len(self.terms["zh_to_vi"])


# ==================== 翻译器 ====================
class Translator:
    def __init__(self):
        self.term_manager = TermManager()
        self.api_key = API_CONFIG["api_key"]
        self.base_url = API_CONFIG["base_url"]
        self.default_model = API_CONFIG["default_model"]
        self.fast_model = API_CONFIG["fast_model"]

    def get_term_count(self):
        return self.term_manager.get_term_count()

    # ---------- 术语替换 ----------
    def _smart_replace_term_cn_to_vi(self, text, zh, vi):
        """把命中的中文术语换成【越南语】，并按位置调整首字母大小写。"""
        pattern = r"(?<![a-zA-Z\u00C0-\u024F])" + re.escape(zh) + r"(?![a-zA-Z\u00C0-\u024F])"

        def repl(match):
            value = vi
            if value:
                before = match.string[: match.start()].rstrip()
                at_sentence_start = (not before) or before[-1] in "。！？.!?"
                value = (value[0].upper() + value[1:]) if at_sentence_start else (value[0].lower() + value[1:])
            return f" 【{value}】 "

        new_text = re.sub(pattern, repl, text)
        new_text = re.sub(r" +", " ", new_text)
        new_text = re.sub(r" ([,.;:!?])", r"\1", new_text)
        return new_text.strip()

    def _smart_replace_term_vi_to_cn(self, text, vi, zh):
        escaped_vi = re.escape(vi)
        pattern = r"(?<![a-zA-Z\u00C0-\u024F])" + escaped_vi + r"(?![a-zA-Z\u00C0-\u024F])"
        new_text = re.sub(pattern, f" 【{zh}】 ", text)
        new_text = re.sub(r" +", " ", new_text)
        new_text = re.sub(r" ([,.;:!?])", r"\1", new_text)
        return new_text.strip()

    def _apply_terms(self, text, direction):
        """把命中的术语替换成 【目标语言】，交给模型原样保留。"""
        if direction == "cn_to_vi":
            user_terms = self.term_manager.get_user_terms()
            replace = self._smart_replace_term_cn_to_vi
        else:
            user_terms = self.term_manager.get_user_terms_vi()
            replace = self._smart_replace_term_vi_to_cn

        processed_text = text
        replaced_terms = []

        sorted_terms = sorted(user_terms.items(), key=lambda x: len(x[0]), reverse=True)
        for source, target in sorted_terms:
            # 单字术语（开/关/下/上）会在「开关」「下午」「关闭」这类复合词里误替换，
            # 例如「开关」被拆成「Mở Đóng / Tắt」，所以只替换两个字符以上的术语。
            if not source or len(source) < 2:
                continue
            if source not in processed_text:
                continue

            processed_text = replace(processed_text, source, target)
            replaced_terms.append((source, target))

        return processed_text, replaced_terms

    # ---------- 文本清理 ----------
    def _clean_spaces(self, text):
        text = re.sub(r" +", " ", text)
        text = re.sub(r" ([,.;:!?])", r"\1", text)
        text = text.replace("，", ", ")
        # 数字里的逗号/点/冒号不要拆开（7:30、3.5、1,000）
        text = re.sub(r"\s*,\s*(?!\d)", ", ", text)
        text = re.sub(r"(?<!\d)\.(?!\d)", ". ", text)
        text = re.sub(r"(?<!\d)\s*:\s*", ": ", text)
        text = re.sub(r"\s*;\s*", "; ", text)
        text = re.sub(r" +", " ", text)
        return text.strip()

    def _translate_chinese_chars(self, text):
        text = text.replace("。", ". ")
        text = text.replace("，", ", ")
        text = text.replace("、", ", ")
        text = text.replace("：", ": ")
        text = text.replace("；", "; ")
        text = text.replace("？", "? ")
        text = text.replace("！", "! ")
        text = re.sub(r"等\s*", "... ", text)
        return text

    def _is_chinese_char(self, char):
        return "\u4e00" <= char <= "\u9fff"

    def _is_code_or_number(self, text):
        patterns = [
            r"^[A-Z0-9\-_]+$",
            r"^[A-Za-z0-9\-_]+$",
            r"^[0-9]+$",
        ]
        for pattern in patterns:
            if re.match(pattern, text.strip()):
                return True
        return False

    def _optimize_chinese_spacing(self, text):
        if not text:
            return text
        parts = text.split(" ")
        result = []
        i = 0
        while i < len(parts):
            current = parts[i]
            if self._is_code_or_number(current):
                result.append(current)
                i += 1
                continue
            has_chinese = any(self._is_chinese_char(c) for c in current)
            if has_chinese:
                combined = current
                j = i + 1
                while j < len(parts):
                    next_part = parts[j]
                    if self._is_code_or_number(next_part):
                        break
                    if any(self._is_chinese_char(c) for c in next_part):
                        combined += next_part
                        j += 1
                    else:
                        break
                result.append(combined)
                i = j
            else:
                result.append(current)
                i += 1
        final_text = " ".join(result)
        final_text = re.sub(r" +", " ", final_text)
        final_text = re.sub(r" ([，。、：；！？])", r"\1", final_text)
        final_text = re.sub(r"([，。、；！？]) ", r"\1", final_text)
        final_text = re.sub(r" ([,.;:!?])", r"\1", final_text)
        final_text = re.sub(r"([,.;:!?])([^ ])", r"\1 \2", final_text)
        return final_text.strip()

    # ---------- 提示词 ----------
    def _build_prompt(self, direction, processed_text):
        if direction == "cn_to_vi":
            system_prompt = """你是一个专业的翻译助手，擅长中文和越南语之间的互译。
你特别擅长机械加工、制造业领域的专业术语翻译。

【重要规则】
1. 原文中用【】标记的词汇已经是翻译好的目标语言（越南语），请直接保留原样，不要修改。
2. 只翻译【】外的内容。
3. 所有中文字符都必须翻译成越南语，不能保留任何中文字符。
4. 只输出译文本身，不要解释、不要加引号、不要输出「翻译：」这样的前缀。"""
            user_prompt = f"请将以下中文文本翻译成越南语。\n\n原文：{processed_text}\n\n翻译："
        else:
            system_prompt = """你是一个专业的翻译助手，擅长越南语和中文之间的互译。
你特别擅长机械加工、制造业领域的专业术语翻译。

【重要规则】
1. 原文中用【】标记的词汇已经是翻译好的目标语言（中文），请直接保留原样，不要修改。
2. 只翻译【】外的内容。
3. 产品代码、编号等应该保留原样，不要翻译。
4. 只输出译文本身，不要解释、不要加引号、不要输出「翻译：」这样的前缀。"""
            user_prompt = f"请将以下越南语文本翻译成中文。\n\n原文：{processed_text}\n\n翻译："

        return system_prompt, user_prompt

    # ---------- 调用模型 ----------
    def _max_tokens(self, text):
        """按输入长度给输出留够 token（关闭思考后，预算基本都给译文）。"""
        return max(1024, min(8192, len(text) * 4))

    def _call_api(self, system_prompt, user_prompt, use_fast_model=False, max_tokens=1024):
        model = self.fast_model if use_fast_model else self.default_model

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.3,
            "max_tokens": max_tokens,
            "stream": False,
            # 关键：关闭「思考」。不关的话 reasoning_tokens 会把 max_tokens 吃光，
            # content 变成空字符串（finish_reason=length），前端就显示空白。
            "thinking": {"type": "disabled"},
        }

        try:
            response = requests.post(
                self.base_url, headers=headers, json=payload, timeout=(10, 90)
            )
        except Exception as exc:
            print(f"[API] {model} 请求异常: {exc}")
            return None

        # 个别模型/网关不认识 thinking 字段时会返回 400，去掉该字段再试一次
        if response.status_code == 400:
            payload.pop("thinking", None)
            try:
                response = requests.post(
                    self.base_url, headers=headers, json=payload, timeout=(10, 90)
                )
            except Exception as exc:
                print(f"[API] {model} 请求异常: {exc}")
                return None

        if response.status_code != 200:
            print(f"[API] {model} HTTP {response.status_code}: {(response.text or '')[:200]}")
            return None

        try:
            data = response.json()
        except Exception:
            print(f"[API] {model} 返回的不是 JSON: {(response.text or '')[:200]}")
            return None

        choices = data.get("choices") or []
        if not choices:
            print(f"[API] {model} 没有 choices: {str(data)[:200]}")
            return None

        choice = choices[0]
        message = choice.get("message") or {}
        content = (message.get("content") or "").strip()
        finish_reason = choice.get("finish_reason")
        usage = data.get("usage") or {}
        reasoning_tokens = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")

        if not content:
            print(
                f"[API] {model} 返回空内容 finish_reason={finish_reason} "
                f"reasoning_tokens={reasoning_tokens}"
            )
            return None

        if finish_reason == "length":
            print(f"[API] {model} 输出被截断（finish_reason=length），max_tokens={max_tokens}")

        return content

    # ---------- 译文后处理 ----------
    def _postprocess(self, translation, direction):
        text = (translation or "").strip()

        # 去掉模型可能加的前缀和 markdown 代码块
        text = re.sub(r"^翻译\s*[:：]\s*", "", text)
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
            text = re.sub(r"\s*```$", "", text)

        text = text.replace("【", "").replace("】", "")
        text = self._clean_spaces(text)

        if direction == "cn_to_vi":
            text = self._translate_chinese_chars(text)
        else:
            text = self._optimize_chinese_spacing(text)

        return text.strip()

    # ---------- 翻译入口 ----------
    def translate(self, text, direction="cn_to_vi"):
        """返回 (译文, 是否缓存命中)。拿不到有效译文时抛 TranslationError。"""
        text = (text or "").strip()
        if not text:
            raise TranslationError("请输入要翻译的文本")

        cache_key = f"{direction}:{text}"
        cached_result = translation_cache.get(cache_key)
        if cached_result:
            return cached_result, True

        # 整句就是术语时直接返回
        exact_terms = (
            self.term_manager.get_user_terms()
            if direction == "cn_to_vi"
            else self.term_manager.get_user_terms_vi()
        )
        if text in exact_terms:
            result = exact_terms[text]
            translation_cache.set(cache_key, result)
            return result, False

        processed_text, replaced_terms = self._apply_terms(text, direction)
        if replaced_terms:
            print(f"🔄 替换了 {len(replaced_terms)} 个用户术语")

        system_prompt, user_prompt = self._build_prompt(direction, processed_text)
        max_tokens = self._max_tokens(text)

        # 第一次用快速模型
        translation = self._call_api(
            system_prompt, user_prompt, use_fast_model=True, max_tokens=max_tokens
        )
        # 空结果/失败 → 换默认模型
        if not translation:
            print("🔄 快速模型没有返回内容，改用默认模型")
            translation = self._call_api(
                system_prompt, user_prompt, use_fast_model=False, max_tokens=max_tokens
            )
        # 仍然为空 → 给更大的 token 预算再试一次
        if not translation:
            print("🔄 默认模型没有返回内容，最后一次尝试（更大 token 预算）")
            translation = self._call_api(
                system_prompt,
                user_prompt,
                use_fast_model=False,
                max_tokens=min(8192, max_tokens * 2),
            )
        if not translation:
            raise TranslationError("翻译服务暂时没有返回内容，请稍后重试")

        result = self._postprocess(translation, direction)
        if not result:
            raise TranslationError("翻译结果为空，请重试")

        translation_cache.set(cache_key, result)
        return result, False


# ==================== Flask 路由 ====================
translator = Translator()


def load_page_html():
    """读取页面文件并缓存（文件修改后自动重新加载）。"""
    for path in PAGE_CANDIDATES:
        if not os.path.exists(path):
            continue
        mtime = os.path.getmtime(path)
        if _page_cache["path"] != path or _page_cache["mtime"] != mtime:
            with open(path, "r", encoding="utf-8") as handle:
                _page_cache["html"] = handle.read()
            _page_cache["path"] = path
            _page_cache["mtime"] = mtime
        return _page_cache["html"]
    return None


@app.route("/")
def index():
    html = load_page_html()
    if html is None:
        return (
            "<h1>缺少页面文件 index.html</h1>"
            "<p>请把 index.html（或 templates/index.html）一起部署到仓库。</p>",
            500,
        )
    # 只替换术语数量这一处占位符，不依赖 Jinja，页面放哪个目录都能用
    html = html.replace("{{ term_count }}", str(translator.get_term_count()))
    return Response(html, mimetype="text/html")


@app.route("/translate", methods=["POST"])
def translate():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    direction = (data.get("direction") or "cn_to_vi").strip()

    if direction not in ("cn_to_vi", "vi_to_cn"):
        return jsonify({"error": "无效的翻译方向", "result": ""}), 400

    if not text:
        return jsonify({"error": "请输入要翻译的文本", "result": "⚠️ 请输入要翻译的文本"}), 400

    if len(text) > MAX_INPUT_CHARS:
        return jsonify(
            {"error": f"文本过长，请分段翻译（最多 {MAX_INPUT_CHARS} 字）"}
        ), 413

    try:
        result, cache_hit = translator.translate(text, direction)
    except TranslationError as exc:
        app.logger.warning("翻译失败: %s | text=%r", exc, text[:80])
        return jsonify({"error": str(exc)}), 502
    except Exception:
        app.logger.exception("翻译异常")
        return jsonify({"error": "翻译出错，请稍后重试"}), 500

    payload = {"result": result}
    if cache_hit:
        payload["cache_hit"] = True
    return jsonify(payload)


@app.route("/cache_info")
def cache_info():
    return jsonify({"size": translation_cache.get_size()})


@app.route("/clear_cache", methods=["POST"])
def clear_cache():
    translation_cache.clear()
    return jsonify({"success": True})


@app.route("/term_count")
def term_count():
    return jsonify({"count": translator.get_term_count()})


@app.route("/health")
def health():
    return jsonify({"ok": True, "terms": translator.get_term_count()})


if __name__ == "__main__":
    print("=" * 50)
    print("🌐 中越翻译工具 Web版（修复版）")
    print("=" * 50)
    print(f"📚 已加载 {translator.get_term_count()} 条术语")
    print("⚡ 缓存已启用: 最大 200 条, 过期 30 分钟")
    print(f"🚀 快速模型: {translator.fast_model} / 默认模型: {translator.default_model}")
    print("=" * 50)
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
