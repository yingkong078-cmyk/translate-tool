# web_translator.py - 完整修复版
# 适用于 Render 部署

from flask import Flask, render_template_string, request, jsonify
import requests
import json
import re
import os
import pandas as pd

app = Flask(__name__)
app.secret_key = 'translator_secret_key_2024'

# ==================== 配置区域 ====================
API_CONFIG = {
    "base_url": "https://tokenhub-intl.tencentmaas.com/v1/chat/completions",
    "api_key": "sk-sTs3bBB3kfhfml7buWfciNuUnoedJLGc2s7BQj2xdKA63x9K",
    "default_model": "hy3"
}

# Excel词库文件路径
TERM_EXCEL_FILE = "词库20260812.xlsx"
# =================================================

# ==================== 语言资源 ====================
LANG = {
    "zh": {
        "title": "🌐 中越翻译工具",
        "subtitle": "用户术语强制保留 · 100%准确",
        "cn_to_vi": "中 → 越",
        "vi_to_cn": "越 → 中",
        "placeholder": "请输入要翻译的文本...",
        "translate_btn": "🚀 翻译",
        "clear_btn": "🗑️ 清空",
        "swap_btn": "🔄 互换",
        "output_placeholder": "翻译结果将显示在这里...",
        "status_ready": "✅ 就绪",
        "status_translating": "🔄 正在翻译...",
        "status_done": "✅ 翻译完成（用户术语已强制保留）",
        "status_clear": "✅ 已清空",
        "status_input_error": "⚠️ 请输入要翻译的文本",
        "term_count": "📚 已加载 {count} 条术语",
        "language": "🌐 界面语言:",
        "reload": "🔄 重新加载术语"
    },
    "vi": {
        "title": "🌐 Công cụ dịch Trung-Việt",
        "subtitle": "Giữ bắt buộc thuật ngữ · 100% chính xác",
        "cn_to_vi": "Trung → Việt",
        "vi_to_cn": "Việt → Trung",
        "placeholder": "Nhập văn bản cần dịch...",
        "translate_btn": "🚀 Dịch",
        "clear_btn": "🗑️ Xóa",
        "swap_btn": "🔄 Đổi chiều",
        "output_placeholder": "Kết quả dịch sẽ hiển thị ở đây...",
        "status_ready": "✅ Sẵn sàng",
        "status_translating": "🔄 Đang dịch...",
        "status_done": "✅ Dịch hoàn tất (đã giữ bắt buộc thuật ngữ)",
        "status_clear": "✅ Đã xóa",
        "status_input_error": "⚠️ Vui lòng nhập văn bản cần dịch",
        "term_count": "📚 Đã tải {count} thuật ngữ",
        "language": "🌐 Ngôn ngữ giao diện:",
        "reload": "🔄 Tải lại thuật ngữ"
    }
}
# =================================================

# ==================== 术语管理器 ====================
class TermManager:
    def __init__(self, excel_file=None):
        self.excel_file = excel_file or TERM_EXCEL_FILE
        self.terms = self.load_terms()
    
    def load_terms(self):
        default_terms = {
            "zh_to_vi": {},
            "vi_to_zh": {}
        }
        
        try:
            if os.path.exists(self.excel_file):
                df = pd.read_excel(self.excel_file)
                zh_col = None
                vi_col = None
                
                for col in df.columns:
                    col_lower = str(col).lower()
                    if '中文' in col_lower or '术语' in col_lower:
                        zh_col = col
                    if '越南' in col_lower or '翻译' in col_lower or 'vi' in col_lower:
                        vi_col = col
                
                if zh_col and vi_col:
                    for idx, row in df.iterrows():
                        zh = str(row[zh_col]).strip()
                        vi = str(row[vi_col]).strip()
                        if zh and vi and zh != 'nan' and vi != 'nan' and zh != '中文术语':
                            default_terms["zh_to_vi"][zh] = vi
                            if vi not in default_terms["vi_to_zh"]:
                                default_terms["vi_to_zh"][vi] = zh
                    
                    print(f"✅ 从Excel加载了 {len(default_terms['zh_to_vi'])} 条术语")
                    return default_terms
                else:
                    print("⚠️ Excel中未找到中文术语或越南语翻译列")
            else:
                print(f"⚠️ Excel文件不存在: {self.excel_file}")
        except Exception as e:
            print(f"⚠️ 加载Excel失败: {e}")
        
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
                "检查布": "kiểm tra vải"
            },
            "vi_to_zh": {}
        }
        
        for zh, vi in default_terms["zh_to_vi"].items():
            default_terms["vi_to_zh"][vi] = zh
        
        return default_terms
    
    def get_user_terms(self):
        return self.terms["zh_to_vi"]
    
    def get_user_terms_vi(self):
        return self.terms["vi_to_zh"]
    
    def get_all_terms(self):
        terms = []
        for zh, vi in self.terms["zh_to_vi"].items():
            terms.append((zh, vi, True))
        return terms


# ==================== 翻译器 ====================
class Translator:
    def __init__(self):
        self.term_manager = TermManager()
        self.api_key = API_CONFIG["api_key"]
        self.base_url = API_CONFIG["base_url"]
        self.default_model = API_CONFIG["default_model"]
    
    def _smart_replace_term_cn_to_vi(self, text, zh, vi):
        pattern = r'(?<![a-zA-Z\u00C0-\u024F])' + re.escape(zh) + r'(?![a-zA-Z\u00C0-\u024F])'
        replacement = f' {vi} '
        new_text = re.sub(pattern, replacement, text)
        new_text = re.sub(r' +', ' ', new_text)
        new_text = re.sub(r' ([,.;:!?])', r'\1', new_text)
        return new_text.strip()
    
    def _smart_replace_term_vi_to_cn(self, text, vi, zh):
        escaped_vi = re.escape(vi)
        pattern = r'(?<![a-zA-Z\u00C0-\u024F])' + escaped_vi + r'(?![a-zA-Z\u00C0-\u024F])'
        replacement = f' {zh} '
        new_text = re.sub(pattern, replacement, text)
        new_text = re.sub(r' +', ' ', new_text)
        new_text = re.sub(r' ([,.;:!?])', r'\1', new_text)
        return new_text.strip()
    
    def _clean_spaces(self, text):
        text = re.sub(r' +', ' ', text)
        text = re.sub(r' ([,.;:!?])', r'\1', text)
        text = re.sub(r'([,.;:!?]) ', r'\1 ', text)
        text = text.replace('，', ', ')
        text = re.sub(r'\s*,\s*', ', ', text)
        text = re.sub(r'\s*\.\s*', '. ', text)
        text = re.sub(r'\s*:\s*', ': ', text)
        text = re.sub(r'\s*;\s*', '; ', text)
        text = re.sub(r' +', ' ', text)
        return text.strip()
    
    def _translate_chinese_chars(self, text):
        text = text.replace('。', '. ')
        text = text.replace('，', ', ')
        text = text.replace('、', ', ')
        text = text.replace('：', ': ')
        text = text.replace('；', '; ')
        text = text.replace('？', '? ')
        text = text.replace('！', '! ')
        text = re.sub(r'等\s*', '... ', text)
        return text
    
    def _is_chinese_char(self, char):
        return '\u4e00' <= char <= '\u9fff'
    
    def _is_code_or_number(self, text):
        patterns = [
            r'^[A-Z0-9\-_]+$',
            r'^[A-Za-z0-9\-_]+$',
            r'^[0-9]+$',
        ]
        for pattern in patterns:
            if re.match(pattern, text.strip()):
                return True
        return False
    
    def _optimize_chinese_spacing(self, text):
        if not text:
            return text
        
        parts = text.split(' ')
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
        
        final_text = ' '.join(result)
        final_text = re.sub(r' +', ' ', final_text)
        final_text = re.sub(r' ([，。、：；！？])', r'\1', final_text)
        final_text = re.sub(r'([，。、：；！？]) ', r'\1', final_text)
        final_text = re.sub(r' ([,.;:!?])', r'\1', final_text)
        final_text = re.sub(r'([,.;:!?])([^ ])', r'\1 \2', final_text)
        
        return final_text.strip()
    
    def translate(self, text, direction="cn_to_vi"):
        if not text.strip():
            return "⚠️ 请输入要翻译的文本"
        
        processed_text = text
        replaced_terms = []
        
        if direction == "cn_to_vi":
            user_terms = self.term_manager.get_user_terms()
            
            if text in user_terms:
                return user_terms[text]
            
            sorted_terms = sorted(user_terms.items(), key=lambda x: len(x[0]), reverse=True)
            for zh, vi in sorted_terms:
                if zh in processed_text:
                    processed_text = self._smart_replace_term_cn_to_vi(processed_text, zh, f"【{vi}】")
                    replaced_terms.append((zh, vi))
            
            system_prompt = """你是一个专业的翻译助手，擅长中文和越南语之间的互译。
你特别擅长机械加工、制造业领域的专业术语翻译。

【重要规则】
1. 原文中用【】标记的词汇已经是翻译好的目标语言（越南语），请直接保留原样，不要修改。
2. 只翻译【】外的内容。
3. 所有中文字符都必须翻译成越南语，不能保留任何中文字符。"""
            
            user_prompt = f"请将以下中文文本翻译成越南语。\n\n原文：{processed_text}\n\n翻译："
            
        else:
            user_terms_vi = self.term_manager.get_user_terms_vi()
            
            if text in user_terms_vi:
                return user_terms_vi[text]
            
            sorted_terms = sorted(user_terms_vi.items(), key=lambda x: len(x[0]), reverse=True)
            for vi, zh in sorted_terms:
                if vi in processed_text:
                    processed_text = self._smart_replace_term_vi_to_cn(processed_text, vi, f"【{zh}】")
                    replaced_terms.append((vi, zh))
            
            system_prompt = """你是一个专业的翻译助手，擅长越南语和中文之间的互译。
你特别擅长机械加工、制造业领域的专业术语翻译。

【重要规则】
1. 原文中用【】标记的词汇已经是翻译好的目标语言（中文），请直接保留原样，不要修改。
2. 只翻译【】外的内容。
3. 产品代码、编号等应该保留原样，不要翻译。"""
            
            user_prompt = f"请将以下越南语文本翻译成中文。\n\n原文：{processed_text}\n\n翻译："
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        data = {
            "model": self.default_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.3,
            "max_tokens": 1000,
            "stream": False
        }
        
        try:
            response = requests.post(self.base_url, headers=headers, json=data, timeout=60)
            if response.status_code == 200:
                result = response.json()
                if "choices" in result and len(result["choices"]) > 0:
                    translation = result["choices"][0]["message"]["content"].strip()
                    if translation.startswith("翻译："):
                        translation = translation[3:].strip()
                    
                    translation = translation.replace("【", "").replace("】", "")
                    translation = self._clean_spaces(translation)
                    
                    if direction == "cn_to_vi":
                        translation = self._translate_chinese_chars(translation)
                    else:
                        translation = self._optimize_chinese_spacing(translation)
                    
                    return translation
                return f"❌ 响应格式异常"
            return f"❌ 翻译失败: HTTP {response.status_code}"
        except requests.exceptions.Timeout:
            return "❌ 请求超时"
        except requests.exceptions.ConnectionError:
            return "❌ 连接失败"
        except Exception as e:
            return f"❌ 翻译出错: {str(e)}"


# ==================== Flask路由 ====================
translator = Translator()

# HTML模板 - 完整版
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>中越翻译工具</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f0f4f8;
            padding: 20px;
            max-width: 500px;
            margin: 0 auto;
            min-height: 100vh;
        }
        .card {
            background: white;
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 16px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }
        .title { font-size: 24px; font-weight: bold; color: #4A90D9; text-align: center; }
        .subtitle { font-size: 12px; color: #888; text-align: center; margin-top: 4px; }
        .lang-switch {
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 10px;
            margin-top: 12px;
            padding: 8px 12px;
            background: #f5f7fa;
            border-radius: 8px;
        }
        .lang-btn {
            padding: 6px 18px;
            border: 2px solid #d9d9d9;
            border-radius: 6px;
            background: white;
            font-size: 14px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.3s;
        }
        .lang-btn.active {
            border-color: #4A90D9;
            background: #e8f0fe;
            color: #4A90D9;
        }
        .lang-btn:active { transform: scale(0.95); }
        .lang-label { font-size: 14px; color: #666; }
        .mode-switch {
            display: flex;
            gap: 10px;
            margin: 15px 0;
        }
        .mode-btn {
            flex: 1;
            padding: 12px;
            border: 2px solid #d9d9d9;
            border-radius: 8px;
            background: white;
            font-size: 16px;
            cursor: pointer;
            transition: all 0.3s;
            font-weight: normal;
        }
        .mode-btn.active {
            border-color: #4A90D9;
            background: #e8f0fe;
            color: #4A90D9;
            font-weight: bold;
        }
        .mode-btn:active { transform: scale(0.97); }
        textarea {
            width: 100%;
            padding: 12px;
            border: 2px solid #d9d9d9;
            border-radius: 8px;
            font-size: 16px;
            min-height: 100px;
            font-family: inherit;
            resize: vertical;
            transition: border-color 0.3s;
        }
        textarea:focus {
            outline: none;
            border-color: #4A90D9;
        }
        .btn {
            width: 100%;
            padding: 14px;
            border: none;
            border-radius: 8px;
            font-size: 18px;
            font-weight: bold;
            cursor: pointer;
            transition: all 0.3s;
        }
        .btn-primary {
            background: #4A90D9;
            color: white;
        }
        .btn-primary:active { background: #3a7bc8; transform: scale(0.98); }
        .btn-primary:disabled {
            background: #a0c4e8;
            cursor: not-allowed;
        }
        .btn-secondary {
            background: #f0f0f0;
            color: #333;
        }
        .btn-secondary:active { background: #e0e0e0; transform: scale(0.98); }
        .output {
            background: #f8f9fa;
            min-height: 100px;
            padding: 12px;
            border-radius: 8px;
            font-size: 16px;
            white-space: pre-wrap;
            word-wrap: break-word;
            border: 2px solid #e8e8e8;
        }
        .status {
            font-size: 14px;
            margin-top: 10px;
            padding: 8px 12px;
            border-radius: 6px;
        }
        .status-ready { color: #52c41a; background: #f6ffed; }
        .status-translating { color: #faad14; background: #fffbe6; }
        .status-done { color: #52c41a; background: #f6ffed; }
        .status-error { color: #ff4d4f; background: #fff2f0; }
        .row { display: flex; gap: 10px; }
        .row .btn { flex: 1; }
        .term-count {
            font-size: 12px;
            color: #888;
            margin-top: 8px;
        }
        .reload-btn {
            font-size: 12px;
            color: #4A90D9;
            background: none;
            border: none;
            cursor: pointer;
            text-decoration: underline;
            padding: 4px 8px;
        }
        .reload-btn:active { color: #3a7bc8; }
        @media (max-width: 400px) {
            body { padding: 10px; }
            .card { padding: 15px; }
            .title { font-size: 20px; }
            .lang-btn { padding: 4px 12px; font-size: 12px; }
        }
    </style>
</head>
<body>
    <div class="card">
        <div class="title" id="titleText">🌐 中越翻译工具</div>
        <div class="subtitle" id="subtitleText">用户术语强制保留 · 100%准确</div>
        <div class="lang-switch">
            <span class="lang-label" id="langLabel">🌐 界面语言:</span>
            <button class="lang-btn active" id="lang-zh" onclick="switchLang('zh')">中文</button>
            <button class="lang-btn" id="lang-vi" onclick="switchLang('vi')">Tiếng Việt</button>
            <button class="reload-btn" id="reloadBtn" onclick="reloadTerms()">🔄</button>
        </div>
    </div>
    
    <div class="card">
        <div class="mode-switch">
            <button class="mode-btn active" id="mode-cn" onclick="setMode('cn_to_vi')">
                <span id="modeCnLabel">中 → 越</span>
            </button>
            <button class="mode-btn" id="mode-vi" onclick="setMode('vi_to_cn')">
                <span id="modeViLabel">越 → 中</span>
            </button>
        </div>
        
        <textarea id="inputText" placeholder="请输入要翻译的文本..." rows="3"></textarea>
        <br><br>
        <button class="btn btn-primary" id="translateBtn" onclick="translateText()">
            <span id="translateBtnLabel">🚀 翻译</span>
        </button>
        <br><br>
        <div class="row">
            <button class="btn btn-secondary" id="clearBtn" onclick="clearAll()">
                <span id="clearBtnLabel">🗑️ 清空</span>
            </button>
            <button class="btn btn-secondary" id="swapBtn" onclick="swapMode()">
                <span id="swapBtnLabel">🔄 互换</span>
            </button>
        </div>
    </div>
    
    <div class="card">
        <div id="outputText" class="output">翻译结果将显示在这里...</div>
        <div id="status" class="status status-ready">✅ 就绪</div>
        <div class="term-count" id="termCount">📚 已加载 0 条术语</div>
    </div>

    <script>
        // ========== 语言资源 ==========
        const LANG = {
            "zh": {
                "title": "🌐 中越翻译工具",
                "subtitle": "用户术语强制保留 · 100%准确",
                "mode_cn": "中 → 越",
                "mode_vi": "越 → 中",
                "placeholder": "请输入要翻译的文本...",
                "translate": "🚀 翻译",
                "clear": "🗑️ 清空",
                "swap": "🔄 互换",
                "output_placeholder": "翻译结果将显示在这里...",
                "status_ready": "✅ 就绪",
                "status_translating": "🔄 正在翻译...",
                "status_done": "✅ 翻译完成（用户术语已强制保留）",
                "status_clear": "✅ 已清空",
                "status_input_error": "⚠️ 请输入要翻译的文本",
                "term_count": "📚 已加载 {count} 条术语",
                "lang_label": "🌐 界面语言:",
                "lang_zh": "中文",
                "lang_vi": "Tiếng Việt"
            },
            "vi": {
                "title": "🌐 Công cụ dịch Trung-Việt",
                "subtitle": "Giữ bắt buộc thuật ngữ · 100% chính xác",
                "mode_cn": "Trung → Việt",
                "mode_vi": "Việt → Trung",
                "placeholder": "Nhập văn bản cần dịch...",
                "translate": "🚀 Dịch",
                "clear": "🗑️ Xóa",
                "swap": "🔄 Đổi chiều",
                "output_placeholder": "Kết quả dịch sẽ hiển thị ở đây...",
                "status_ready": "✅ Sẵn sàng",
                "status_translating": "🔄 Đang dịch...",
                "status_done": "✅ Dịch hoàn tất (đã giữ bắt buộc thuật ngữ)",
                "status_clear": "✅ Đã xóa",
                "status_input_error": "⚠️ Vui lòng nhập văn bản cần dịch",
                "term_count": "📚 Đã tải {count} thuật ngữ",
                "lang_label": "🌐 Ngôn ngữ giao diện:",
                "lang_zh": "中文",
                "lang_vi": "Tiếng Việt"
            }
        };

        let currentLang = 'zh';
        let currentMode = 'cn_to_vi';
        let isTranslating = false;

        function switchLang(lang) {
            currentLang = lang;
            document.getElementById('lang-zh').className = 'lang-btn' + (lang === 'zh' ? ' active' : '');
            document.getElementById('lang-vi').className = 'lang-btn' + (lang === 'vi' ? ' active' : '');
            const t = LANG[lang];
            document.getElementById('titleText').textContent = t.title;
            document.getElementById('subtitleText').textContent = t.subtitle;
            document.getElementById('langLabel').textContent = t.lang_label;
            document.getElementById('modeCnLabel').textContent = t.mode_cn;
            document.getElementById('modeViLabel').textContent = t.mode_vi;
            document.getElementById('inputText').placeholder = t.placeholder;
            document.getElementById('translateBtnLabel').textContent = t.translate;
            document.getElementById('clearBtnLabel').textContent = t.clear;
            document.getElementById('swapBtnLabel').textContent = t.swap;
            const statusEl = document.getElementById('status');
            if (statusEl.className.includes('status-ready')) {
                statusEl.textContent = t.status_ready;
            }
            updateTermCount();
        }

        function setMode(mode) {
            currentMode = mode;
            document.getElementById('mode-cn').className = 'mode-btn' + (mode === 'cn_to_vi' ? ' active' : '');
            document.getElementById('mode-vi').className = 'mode-btn' + (mode === 'vi_to_cn' ? ' active' : '');
        }
        
        function swapMode() {
            setMode(currentMode === 'cn_to_vi' ? 'vi_to_cn' : 'cn_to_vi');
        }

        function updateStatus(text, type) {
            const statusEl = document.getElementById('status');
            statusEl.textContent = text;
            statusEl.className = 'status ' + type;
        }

        function updateTermCount() {
            fetch('/term_count')
                .then(response => response.json())
                .then(data => {
                    const t = LANG[currentLang];
                    document.getElementById('termCount').textContent = t.term_count.replace('{count}', data.count);
                })
                .catch(() => {});
        }

        function translateText() {
            if (isTranslating) return;
            const text = document.getElementById('inputText').value;
            const t = LANG[currentLang];
            if (!text.trim()) {
                document.getElementById('outputText').textContent = t.status_input_error;
                updateStatus(t.status_input_error, 'status-error');
                return;
            }
            isTranslating = true;
            const btn = document.getElementById('translateBtn');
            btn.disabled = true;
            btn.querySelector('span').textContent = '⏳ ' + (currentLang === 'zh' ? '翻译中...' : 'Đang dịch...');
            document.getElementById('outputText').textContent = '🔄 ' + (currentLang === 'zh' ? '翻译中...' : 'Đang dịch...');
            updateStatus(t.status_translating, 'status-translating');
            
            fetch('/translate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text: text, direction: currentMode })
            })
            .then(response => response.json())
            .then(data => {
                document.getElementById('outputText').textContent = data.result;
                if (data.error) {
                    updateStatus('❌ ' + data.error, 'status-error');
                } else {
                    updateStatus(t.status_done, 'status-done');
                }
            })
            .catch(error => {
                document.getElementById('outputText').textContent = '❌ ' + (currentLang === 'zh' ? '翻译失败: ' : 'Dịch thất bại: ') + error;
                updateStatus('❌ ' + (currentLang === 'zh' ? '翻译失败' : 'Dịch thất bại'), 'status-error');
            })
            .finally(() => {
                isTranslating = false;
                btn.disabled = false;
                btn.querySelector('span').textContent = t.translate;
            });
        }

        function clearAll() {
            const t = LANG[currentLang];
            document.getElementById('inputText').value = '';
            document.getElementById('outputText').textContent = t.output_placeholder;
            updateStatus(t.status_clear, 'status-ready');
        }

        function reloadTerms() {
            const t = LANG[currentLang];
            updateStatus('🔄 ' + (currentLang === 'zh' ? '正在重新加载术语...' : 'Đang tải lại thuật ngữ...'), 'status-translating');
            fetch('/reload_terms', { method: 'POST' })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        updateStatus('✅ ' + (currentLang === 'zh' ? '已重新加载 ' + data.count + ' 条术语' : 'Đã tải lại ' + data.count + ' thuật ngữ'), 'status-done');
                        updateTermCount();
                    } else {
                        updateStatus('❌ ' + (currentLang === 'zh' ? '重新加载失败: ' : 'Tải lại thất bại: ') + data.error, 'status-error');
                    }
                })
                .catch(error => {
                    updateStatus('❌ ' + (currentLang === 'zh' ? '重新加载失败' : 'Tải lại thất bại'), 'status-error');
                });
        }

        document.getElementById('inputText').addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                translateText();
            }
        });

        updateTermCount();
    </script>
</body>
</html>
"""


@app.route('/')
def index():
    term_count = len(translator.term_manager
