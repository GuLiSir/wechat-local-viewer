from pathlib import Path
import os

# 基础路径
BASE_DIR = Path(__file__).resolve().parent.parent.parent


def _load_dotenv(path: Path) -> None:
    """极简 .env 加载器：KEY=VALUE，# 注释，支持引号包裹；不覆盖已存在的环境变量。

    必须在读取任何 os.getenv 配置之前调用（仓库根目录 .env）。
    """
    if not path.exists():
        return
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip()
            if val and val[0] in "\"'" and val[-1:] == val[0]:
                val = val[1:-1]
            elif " #" in val:
                val = val.split(" #", 1)[0].strip()
            if key and key not in os.environ:
                os.environ[key] = val
    except Exception:
        pass


DOTENV_TEMPLATE = """# ============================================================
# 微信本地查看器 · 配置（由程序在首次启动时自动生成）
# 本文件与仓库根目录的 .env.example 保持一致，可对照修改。
# 注意：前端「设置」面板里填的配置优先级高于本文件；改完需重启后端。
# ============================================================

# ---- LLM（OpenAI 兼容协议）----
# 支持任意 OpenAI 兼容服务，示例：
#   DeepSeek   https://api.deepseek.com/v1        deepseek-chat
#   OpenAI     https://api.openai.com/v1          gpt-4o-mini
#   硅基流动   https://api.siliconflow.cn/v1      Qwen/Qwen3-8B
#   MiniMax    https://api.minimaxi.com/v1        MiniMax-M3.1-Flash-Preview（国内站）
#   Ollama     http://localhost:11434/v1         qwen2.5:7b（无需 API Key）
LLM_BASE_URL=
LLM_API_KEY=
LLM_MODEL=

# ---- AI 分析窗口 ----
# 模型上下文窗口（tokens），用于自动计算每批可容纳多少消息：
# 输入预算 = LLM_CONTEXT_TOKENS - LLM_MAX_TOKENS - 8000（按 1 字符 ≈ 1 token 保守估算）；
# 超过预算时自动分批分析后汇总
LLM_CONTEXT_TOKENS=200000
# 最多分析最近多少条消息（总窗口上限，仅统计文本类消息；图片/视频等不参与分析）
LLM_MAX_MESSAGES=10000
# 单次分析/汇总的输出上限（tokens）。推理模型的思考也计入此预算，
# 过小会导致长报告被截断
LLM_MAX_TOKENS=16000

# ---- 服务端口（可选）----
# WCVIEWER_PORT=18787
"""


def _ensure_dotenv(path: Path) -> None:
    """首次启动时生成 .env 模板（已存在则不覆盖）"""
    if path.exists():
        return
    try:
        path.write_text(DOTENV_TEMPLATE, encoding="utf-8")
    except Exception:
        pass


_ensure_dotenv(BASE_DIR / ".env")
_load_dotenv(BASE_DIR / ".env")

# 解密数据目录：
# - 首选 .decrypted/（隐藏目录，历史约定）
# - 若不存在则回退 decrypted/（无点）—— wcdb-key-tool 的 --output 默认值是相对路径 "decrypted"，
#   在查看项目根目录跑解密时会直接输出到这里，无需再手工复制。
_DOT_DIR = BASE_DIR / ".decrypted"
_PLAIN_DIR = BASE_DIR / "decrypted"
if _DOT_DIR.exists() and any(_DOT_DIR.iterdir()):
    DECRYPTED_DIR = _DOT_DIR
else:
    DECRYPTED_DIR = _PLAIN_DIR

IMAGES_DIR = BASE_DIR / ".images"
CACHE_DIR = BASE_DIR / ".cache"
TMP_DIR = BASE_DIR / ".tmp"
LOGS_DIR = TMP_DIR / "logs"

# 确保目录存在
CACHE_DIR.mkdir(exist_ok=True)
TMP_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)
IMAGES_DIR.mkdir(exist_ok=True)

# 数据库路径
DB_PATH = CACHE_DIR / "app.db"

# API 配置（默认 18787；8765/5173/8080 易冲突且 Windows 上部分被保留）
API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("WCVIEWER_PORT") or os.getenv("API_PORT") or "18787")

# 媒体静态文件挂载
MEDIA_DIR = IMAGES_DIR

# 微信 FileStorage 媒体缓存目录（可选，含个人账号路径，敏感）。
# 通过环境变量 WECHAT_MEDIA_CACHE_DIR 配置；未配置时为 None，后端跳过该候选目录。
_wechat_media_cache = os.getenv("WECHAT_MEDIA_CACHE_DIR", "").strip()
WECHAT_MEDIA_CACHE_DIR = Path(_wechat_media_cache) if _wechat_media_cache else None