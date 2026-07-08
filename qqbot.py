#!/usr/bin/env python3.11
import os, json, time, asyncio, re, random, traceback
import aiohttp, logging
from datetime import datetime, timedelta
from playwright.async_api import async_playwright
from urllib.parse import quote

# 加载 .env 文件（本地开发用）
ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(ENV_FILE):
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
_log = logging.getLogger("QQBot")

# ---------- 配置（全部从环境变量读取） ----------
BOT_APP_ID = os.getenv("BOT_APP_ID", "")
BOT_SECRET = os.getenv("BOT_SECRET", "")
DS_PHONE = os.getenv("DS_PHONE", "")
DS_PASSWORD = os.getenv("DS_PASSWORD", "")
OWNER_OPENID = os.getenv("OWNER_OPENID", "")
DATA_DIR = os.getenv("DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
os.makedirs(DATA_DIR, exist_ok=True)
STORAGE_STATE_FILE = os.path.join(DATA_DIR, "deepseek_state.json")
USAGE_FILE = os.path.join(DATA_DIR, "usage.json")
CHAT_LOG_FILE = os.path.join(DATA_DIR, "chat_history.json")
GROUP_ID_FILE = os.path.join(DATA_DIR, "group_id.txt")

# ---------- 全局变量 ----------
_usage = {"total_tokens": 0, "total_cost": 0.0, "calls": 0, "daily": {}}
if os.path.exists(USAGE_FILE):
    try:
        with open(USAGE_FILE) as f: _usage = json.load(f)
    except: pass

conversations = {}
if os.path.exists(CHAT_LOG_FILE):
    try:
        with open(CHAT_LOG_FILE) as f: conversations = json.load(f)
        _log.info("已加载 %d 个对话记录", len(conversations))
    except: pass

_token = {"v": "", "e": 0}
_seq = 0
_browser = None
_context = None
_page = None
_deepseek_ready = False
_chat_lock = asyncio.Lock()
_auto_chat = True
_last_morning_date = ""
_last_evening_date = ""
_last_report_date = ""
_morning_news_titles = set()
_last_chat_time = 0.0
_reminders = []
_game_mode = {}
_guess_num = {}
_story_mode = {}
_used_chengyu = {}
_target_group_id = ""        # 最后一次交互的群（动态）
_last_50min_time = time.time()

# 绑定群：定时任务和群发只对这个群生效（从文件读取，不变）
BOUND_GROUP_ID = ""
if os.path.exists(GROUP_ID_FILE):
    try:
        with open(GROUP_ID_FILE) as f:
            BOUND_GROUP_ID = f.read().strip()
        _log.info("✅ 绑定群ID: %s...", BOUND_GROUP_ID[:20])
    except: pass

# ---------- 表情映射 ----------
EMOTE_MAP = {
    "大笑": "14","呲牙": "13","偷笑": "20","得意": "4","害羞": "6","闭嘴": "7",
    "睡": "8","大哭": "9","尴尬": "10","发怒": "11","调皮": "12","惊讶": "0",
    "难过": "5","色": "21","抓狂": "15","吐": "16","憨笑": "25","可爱": "29",
    "白眼": "22","傲慢": "23","饥饿": "24","困": "26","惊恐": "27","流汗": "28",
    "奋斗": "30","咒骂": "31","疑问": "32","嘘": "33","晕": "34","折磨": "35",
    "衰": "36","骷髅": "37","敲打": "38","再见": "39","鼓掌": "261","干杯": "268",
    "强": "273","弱": "274","握手": "275","胜利": "276","抱拳": "277","勾引": "278",
    "拳头": "279","差劲": "280","爱你": "281","太阳": "169","月亮": "170",
    "赞": "315","耶": "296","OK": "308","好的": "309","加油": "314",
}
chengyu_list = ["一心一意","意气风发","发奋图强","强人所难","难能可贵","贵在坚持","持之以恒","横七竖八",
    "八仙过海","海阔天空","空前绝后","后来居上","上下其手","手到擒来","来日方长","长年累月",
    "月明星稀","稀世之宝","宝刀不老","老当益壮","壮志凌云","云淡风轻","轻而易举","举世无双",
    "双管齐下","下不为例","例行公事","事半功倍","倍道兼行","行云流水","水落石出","出人头地"]

# ---------- 基础工具函数 ----------
async def get_token():
    now = time.time()
    if _token["v"] and now < _token["e"]: return _token["v"]
    async with aiohttp.ClientSession() as s:
        async with s.post("https://bots.qq.com/app/getAppAccessToken",
            json={"appId":BOT_APP_ID,"clientSecret":BOT_SECRET}) as r:
            data = await r.json()
            _token["v"] = data["access_token"]
            _token["e"] = now + int(data["expires_in"]) - 120
            return _token["v"]

async def api_post(path, body):
    tok = await get_token()
    async with aiohttp.ClientSession() as s:
        async with s.post(f"https://api.sgroup.qq.com{path}", json=body,
            headers={"Authorization":f"QQBot {tok}"}) as r:
            return await r.text()

def _save_usage():
    try:
        with open(USAGE_FILE,"w") as f: json.dump(_usage,f,ensure_ascii=False)
    except: pass

_last_save = 0
def save_chat_history():
    global _last_save
    now = time.time()
    if now - _last_save < 30: return
    _last_save = now
    try:
        trimmed = {}
        for k,v in conversations.items():
            trimmed[k] = v[-30:] if len(v)>30 else v
        with open(CHAT_LOG_FILE,"w") as f: json.dump(trimmed,f,ensure_ascii=False)
    except: pass

def get_usage_report():
    today = datetime.now().strftime("%Y-%m-%d")
    return (f"今日消耗: {_usage['daily'].get(today,0):.4f}元\n"
            f"总调用次数: {_usage['calls']}\n"
            f"总Token数: {_usage['total_tokens']:,}\n"
            f"总费用: {_usage['total_cost']:.4f}元")

def convert_emotes(text):
    for name,eid in EMOTE_MAP.items():
        text = text.replace(f"[{name}]", f"<faceType=1,faceId=\"{eid}\",ext=\"\">")
    return text

# ---------- DeepSeek 交互核心 ----------
async def find_input_box(timeout=5000):
    """定位输入框，使用精确 placeholder"""
    selectors = [
        "textarea[placeholder='Message DeepSeek']",
        "textarea[placeholder*='Message']",
        "textarea[placeholder*='DeepSeek']",
        "textarea",
        "[contenteditable='true']",
        "div[role='textbox']"
    ]
    for sel in selectors:
        try:
            elem = await _page.wait_for_selector(sel, timeout=timeout)
            if elem:
                _log.info(f"✅ 找到输入框，选择器: {sel}")
                return elem
        except:
            continue
    # 兜底
    try:
        elem = await _page.evaluate_handle("""() => {
            const ta = document.querySelector('textarea:not([hidden])');
            if (ta) return ta;
            const ce = document.querySelector('[contenteditable="true"]:not([hidden])');
            return ce || null;
        }""")
        if elem:
            _log.info("✅ 通过JS兜底找到输入框")
            return elem.as_element()
    except:
        pass
    return None

async def enable_deep_think():
    """开启深度思考（增强版：多策略尝试）"""
    _log.info("🔍 尝试开启深度思考...")
    await _page.wait_for_timeout(3000)

    # 策略1：JS全局扫描所有可点击元素，找「深度思考」
    try:
        result = await _page.evaluate("""() => {
            const walk = document.querySelectorAll('button, [role="button"], div[class*="ds-"], span[class*="think"], label, a');
            for (const el of walk) {
                const t = (el.textContent || el.innerText || el.getAttribute('aria-label') || '').trim();
                if (t.includes('深度思考') || t.includes('DeepThink') || t === 'Deep Think') {
                    el.click();
                    return 'clicked:' + t.slice(0,30);
                }
            }
            // 也搜子元素
            for (const el of walk) {
                const t = (el.textContent || el.innerText || '').trim();
                if (t.includes('R1') && t.length <= 5) { el.click(); return 'clicked:R1'; }
            }
            return 'not_found';
        }""")
        _log.info("策略1 JS扫描: %s", result)
        if result.startswith("clicked"):
            await asyncio.sleep(0.8)
            return
    except Exception as e:
        _log.warning("策略1失败: %s", e)

    # 策略2：Playwright 选择器逐个试
    selectors_to_try = [
        "button:has-text('深度思考')",
        "text='深度思考'",
        "[class*='deepThink']",
        "[class*='deep-think']",
        "[class*='DeepThink']",
        "[data-testid*='deep-think']",
        "button:has-text('DeepThink')",
    ]
    for sel in selectors_to_try:
        try:
            elem = await _page.query_selector(sel)
            if elem:
                await elem.click()
                _log.info("✅ 深度思考已点击 (选择器: %s)", sel)
                await asyncio.sleep(0.8)
                return
        except:
            continue

    # 策略3：通过 URL 参数强制开启（部分版本支持）
    try:
        current_url = _page.url
        if "deepThink" not in current_url and "?" not in current_url.split("/")[-1]:
            await _page.goto(_page.url.split("?")[0] + "?deepThink=true", timeout=10000)
            _log.info("已尝试通过URL参数开启深度思考")
            await _page.wait_for_timeout(2000)
    except: pass

    _log.warning("⚠️ 所有策略均未找到深度思考按钮，可能UI已变更或已默认开启")

async def init_deepseek_browser():
    global _browser, _context, _page, _deepseek_ready
    if _deepseek_ready:
        return True

    if not DS_PHONE or not DS_PASSWORD:
        _log.error("未设置DS_PHONE或DS_PASSWORD")
        return False

    p = await async_playwright().start()
    _browser = await p.chromium.launch(
        headless=True,
        args=['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage']
    )

    storage_state = None
    if os.path.exists(STORAGE_STATE_FILE):
        with open(STORAGE_STATE_FILE, 'r') as f:
            storage_state = json.load(f)
        _log.info("已加载登录状态缓存")

    _context = await _browser.new_context(storage_state=storage_state)
    _page = await _context.new_page()
    await _page.goto("https://chat.deepseek.com/", timeout=30000)

    # 检查是否需要登录（中英文界面）
    async def is_login_page():
        try:
            # 检测登录页面元素
            selectors = [
                "text='Log in'", "text='登录'",
                "button:has-text('Log in')", "button:has-text('登录')",
                "input[placeholder*='Phone number']", "input[placeholder*='手机号']",
                "a:has-text('Login with password')", "a:has-text('密码登录')",
            ]
            for sel in selectors:
                if await _page.query_selector(sel): return True
            # 检测页面是否已显示聊天输入框（已登录）
            if await _page.query_selector("textarea"): return False
            body = await _page.inner_text("body")
            if "Login" in body or "登录" in body or "Sign in" in body: return True
        except: pass
        return False

    if await is_login_page():
        _log.info("检测到未登录，开始自动登录...")
        try:
            # 判断当前是否已经是密码表单（有 password input）
            has_pwd_form = await _page.query_selector("input[type='password']")
            if not has_pwd_form:
                # 点击密码登录切换按钮
                pwd_link = None
                for sel in [
                    ".ds-sign-in-form__social-link:has-text('Login with password')",
                    "text='Login with password'",
                    "div:has-text('Login with password')",
                ]:
                    pwd_link = await _page.query_selector(sel)
                    if pwd_link: break
                if pwd_link:
                    await pwd_link.click(force=True)
                    _log.info("已点击 'Login with password'")
                    await _page.wait_for_timeout(3000)
                else:
                    _log.warning("未找到密码登录切换按钮")

            # 等待密码输入框出现
            try:
                await _page.wait_for_selector("input[type='password']", timeout=10000)
                _log.info("密码表单已加载")
            except:
                _log.error("密码表单未加载")
                return False

            # 填手机号 / 邮箱
            phone_input = await _page.query_selector("input[type='text']") or await _page.query_selector("input[placeholder*='Phone number']") or await _page.query_selector("input[placeholder*='email']")
            if phone_input:
                await phone_input.fill(DS_PHONE)
                _log.info("手机号已填写")
            else:
                _log.error("未找到手机号输入框")
                return False

            # 填密码
            pwd_input = await _page.query_selector("input[type='password']")
            if pwd_input:
                await pwd_input.fill(DS_PASSWORD)
                _log.info("密码已填写")
            else:
                _log.error("未找到密码输入框")
                return False

            await _page.wait_for_timeout(500)

            # 点登录
            submit = None
            for sel in [
                "button:has-text('Log in')",
                "text='Log in'",
                ".ds-button:has-text('Log in')",
                "button[type='submit']",
            ]:
                submit = await _page.query_selector(sel)
                if submit: break
            if submit:
                await submit.click(force=True)
                _log.info("已点击登录")
            else:
                _log.error("未找到登录提交按钮")
                return False

            await _page.wait_for_timeout(5000)
            # 等待登录完成：找聊天输入框或消失登录按钮
            try:
                await _page.wait_for_selector("textarea", timeout=15000)
            except:
                pass

            if await is_login_page():
                _log.error("自动登录失败，仍然处于登录页面")
                return False
            _log.info("自动登录成功！")
        except Exception as e:
            _log.error("自动登录出错: %s", e)
            return False
    else:
        _log.info("已检测到登录状态，无需重新登录")

    # 保存登录状态
    storage = await _context.storage_state()
    with open(STORAGE_STATE_FILE, 'w') as f:
        json.dump(storage, f)
    _log.info("登录状态已保存")

    await _page.wait_for_timeout(3000)

    # 尝试开启深度思考
    await enable_deep_think()

    # 检查输入框是否可用，若不可用则刷新
    if not await find_input_box(timeout=3000):
        _log.warning("输入框未找到，刷新页面")
        await _page.reload()
        await _page.wait_for_timeout(3000)

    _deepseek_ready = True
    _log.info("DeepSeek浏览器初始化完成")
    return True

async def chat_with_deepseek_web(user_msg, conv_id):
    global _deepseek_ready, _page, _context
    async with _chat_lock:
        if not _deepseek_ready:
            ok = await init_deepseek_browser()
            if not ok:
                raise Exception("DeepSeek浏览器初始化失败")

        for attempt in range(2):
            try:
                input_elem = await find_input_box(timeout=5000)
                if not input_elem:
                    _log.warning("未找到输入框，刷新重试")
                    await _page.reload()
                    await _page.wait_for_timeout(3000)
                    continue

                await input_elem.fill("", timeout=2000)
                await input_elem.fill(user_msg, timeout=2000)

                # 发送
                send_btn = await _page.query_selector("button:has-text('发送')") or await _page.query_selector("button[aria-label='发送']")
                if send_btn:
                    await send_btn.click()
                else:
                    await input_elem.press("Enter")

                # 等待 DeepSeek 输出完全完成（包含深度思考）
                # 策略1: 等待「停止」按钮出现再消失（表示生成完毕）
                stop_appeared = False
                try:
                    await _page.wait_for_selector("button:has-text('停止')", timeout=10000)
                    stop_appeared = True
                    _log.info("停止按钮已出现，等待生成完成...")
                except:
                    _log.info("未检测到停止按钮")
                if stop_appeared:
                    try:
                        await _page.wait_for_selector("button:has-text('停止')", state='hidden', timeout=120000)
                        _log.info("停止按钮已消失，输出完成")
                    except:
                        _log.warning("等待停止按钮消失超时，继续提取")

                # 策略2: 等待输入框恢复可用 + 额外延迟确保深度思考渲染
                try:
                    await _page.wait_for_selector("textarea:not([disabled])", timeout=60000)
                except:
                    pass
                await asyncio.sleep(5)  # 深度思考答案需要更长时间渲染

                # 滚动到底部确保全部内容已渲染
                try:
                    await _page.evaluate("""() => { window.scrollTo(0, document.body.scrollHeight); }""")
                except: pass
                await asyncio.sleep(2)

                # === 提取完整回复：跳过思考过程，取最终答案 ===
                reply = None

                # 方法1: 优先取 DeepSeek 最终答案容器（不包含思考过程）
                try:
                    reply = await _page.evaluate("""() => {
                        // DeepSeek 答案主内容容器
                        const main = document.querySelector('[class*="ds-assistant-message-main-content"]');
                        if (main) {
                            return main.innerText.trim();
                        }
                        // 兜底：找所有 ds-markdown，取最后一个
                        const md = document.querySelectorAll('.ds-markdown, [class*="ds-markdown"]');
                        if (md.length > 0) {
                            return md[md.length - 1].innerText.trim();
                        }
                        return null;
                    }""")
                    if reply:
                        _log.info("方法1提取: %d 字符", len(reply))
                except Exception as e:
                    _log.warning("方法1提取失败: %s", e)

                # 方法2: 找到最后一个AI消息，跳过思考过程区块
                if not reply or len(reply) < 50:
                    try:
                        reply = await _page.evaluate("""() => {
                            const thinkLabels = ['思考过程', '深度思考', 'Thinking Process', 'Thinking', '已深度思考', '推理过程', 'Thought for', 'Found'];
                            const selectors = ['[class*="ds-message"]', '[class*="message"]', 'article'];
                            let messages = [];
                            for (const sel of selectors) {
                                messages = document.querySelectorAll(sel);
                                if (messages.length > 0) break;
                            }
                            let lastAssistant = null;
                            if (messages.length > 0) {
                                for (let i = messages.length - 1; i >= 0; i--) {
                                    const m = messages[i];
                                    if (m.querySelector('textarea')) continue;
                                    if ((m.innerText || '').length > 10) { lastAssistant = m; break; }
                                }
                            }
                            if (!lastAssistant) return null;
                            let fullText = lastAssistant.innerText || '';
                            
                            // 移除思考过程：从标签开始到"收起"
                            for (const label of thinkLabels) {
                                const idx = fullText.indexOf(label);
                                if (idx >= 0) {
                                    let cutIdx = fullText.indexOf('收起', idx);
                                    if (cutIdx > idx && cutIdx < idx + 500) {
                                        fullText = fullText.substring(0, idx) + fullText.substring(cutIdx + 2);
                                    } else {
                                        cutIdx = fullText.indexOf('\n\n', idx);
                                        if (cutIdx > idx) fullText = fullText.substring(0, idx) + fullText.substring(cutIdx);
                                    }
                                }
                            }
                            // 如果思考过程在开头（没标签的情况），尝试找到第一个有效格式标记
                            const markers = ['1.', '一、', '【今日头条】', '【晚间新闻】', '【全国天气】', '🌅', '北京', '中国'];
                            for (const m of markers) {
                                const idx = fullText.indexOf(m);
                                if (idx > 0 && idx < 500) {
                                    // 前面可能是思考过程，截掉
                                    if (fullText.substring(0, idx).includes('秒') || fullText.substring(0, idx).includes('web')) {
                                        fullText = fullText.substring(idx);
                                        break;
                                    }
                                }
                            }
                            return fullText.trim();
                        }""")
                        if reply:
                            _log.info("方法2提取: %d 字符", len(reply))
                    except Exception as e:
                        _log.warning("方法2提取失败: %s", e)

                # 方法3: 兜底——从整个 body 最后几个大段落取，并清理思考过程
                if not reply or len(reply) < 50:
                    try:
                        body = await _page.inner_text("body")
                        # 移除思考过程标签
                        for label in ['思考过程', '深度思考', 'Thinking Process', 'Thinking', '已深度思考']:
                            idx = body.find(label)
                            if idx >= 0:
                                cutIdx = body.find('收起', idx)
                                if cutIdx > idx: body = body[:idx] + '\n' + body[cutIdx+2:]
                        paragraphs = [p.strip() for p in body.split('\n\n') if len(p.strip()) > 50]
                        if paragraphs:
                            reply = paragraphs[-1]
                            _log.info("方法3提取: %d 字符", len(reply))
                    except: pass

                if not reply or len(reply) < 5:
                    raise Exception("无法提取完整回复")

                # 如果回复开头是用户消息内容（对话历史混在一起），截掉
                if len(user_msg) > 5 and reply.startswith(user_msg[:10]):
                    idx = reply.find(user_msg)
                    if idx >= 0:
                        reply = reply[idx + len(user_msg):].strip()

                # 清理多余空行
                reply = '\n'.join([l for l in reply.split('\n') if l.strip()])

                _log.info("最终回复: %d 字符", len(reply))

                # 记录对话（仅非临时任务）
                if conv_id not in ["_morning", "_evening", "_fun", "_auto", "_joke", "_eval", "_daily"]:
                    if conv_id not in conversations:
                        conversations[conv_id] = []
                    history = conversations[conv_id]
                    history.append({"role": "user", "content": user_msg})
                    history.append({"role": "assistant", "content": reply})
                    if len(history) > 30:
                        conversations[conv_id] = history[-30:]
                    save_chat_history()

                _usage["calls"] += 1
                _usage["total_tokens"] += 500
                today = datetime.now().strftime("%Y-%m-%d")
                _usage["daily"][today] = _usage["daily"].get(today, 0) + 0.0001
                _save_usage()

                return reply

            except Exception as e:
                _log.error("对话失败 (尝试 %d/2): %s", attempt+1, e)
                if attempt == 0:
                    _deepseek_ready = False
                    try:
                        await _page.close()
                    except: pass
                    ok = await init_deepseek_browser()
                    if not ok:
                        raise Exception("重新初始化浏览器失败")
                else:
                    raise

        raise Exception("多次尝试失败")

async def chat_with_ai(conv_id, user_msg, user_name=""):
    try:
        return await chat_with_deepseek_web(user_msg, conv_id)
    except Exception as e:
        error_msg = f"❌ AI请求失败: {str(e)}"
        diag = ""
        try:
            if _page:
                title = await _page.title()
                url = _page.url
                body = (await _page.inner_text("body"))[:200]
                diag = f"\n页面标题: {title}\nURL: {url}\n内容片段: {body}"
        except: pass
        if OWNER_OPENID:
            try:
                await api_post(f"/v2/users/{OWNER_OPENID}/messages", {"content":f"【错误报告】\n{error_msg}{diag}\n{traceback.format_exc()[-500:]}"})
            except: pass
        return error_msg

# ---------- 定时任务生成函数 ----------
async def generate_morning_report():
    prompt = (
        "请联网搜索最新新闻，提供至少10条今日头条（国内国际），每条用序号和简要标题。"
        "然后查询全国主要城市天气（北京、上海、广州、深圳、成都、重庆、武汉、杭州、南京、西安）以及犍为的天气，"
        "最后给出一句暖心提醒。"
        "格式要求：\n【今日头条】\n1. ...\n2. ...\n...\n【全国天气】\n北京：...\n上海：...\n...\n犍为：...\n【暖心提醒】...\n"
    )
    try:
        return await chat_with_deepseek_web(prompt, "_morning")
    except Exception as e:
        _log.error("生成早报失败: %s", e)
        return "早报生成失败，请稍后再试。"

async def generate_evening_report(morning_titles):
    exclude = morning_titles if morning_titles else []
    exclude_str = "，".join(exclude[:15]) if exclude else "无"
    prompt = (
        f"请联网搜索今天下午的最新新闻，给出不少于10条头条。"
        f"注意：以下早间新闻已经发过，请务必跳过、不要重复：{exclude_str}。"
        "如果今天的新闻总条数确实不足10条，给出所有能找到的即可，不必凑数。"
        "格式：\n【晚间新闻】\n1. ...\n2. ...\n..."
    )
    try:
        return await chat_with_deepseek_web(prompt, "_evening")
    except Exception as e:
        _log.error("生成晚报失败: %s", e)
        return "晚报生成失败，请稍后再试。"

async def generate_random_fun():
    prompts = [
        "讲一个有趣的冷笑话，20字左右。",
        "说一个逗人的段子，不超过30字。",
        "分享一个冷知识，有趣一点，不超过40字。",
        "用幽默的语气吐槽一下今天的生活，不超过30字。",
        "说一句励志但搞笑的话，不超过25字。",
        "用一句话讲一个反转小故事，有意思一点。",
        "说一句让人哭笑不得的人生哲理。",
        "讲一个互联网热梗或流行语，解释一下出处。",
        "用土味情话的方式说一句话。",
        "分享一个沙雕新闻标题（真实的），不超过40字。",
    ]
    try:
        reply = await chat_with_deepseek_web(random.choice(prompts), "_fun")
        if len(reply) > 100:
            reply = reply[:100] + "..."
        return reply
    except Exception as e:
        _log.error("生成趣味消息失败: %s", e)
        return "🤖 今天没什么想说的~"

# ---------- 其他功能函数 ----------
async def send_ws(ws, op, d):
    global _seq
    payload = {"op":op,"d":d}
    if _seq>0: payload["s"] = _seq
    await ws.send_str(json.dumps(payload))

async def heartbeat(ws, interval_ms):
    while True:
        await asyncio.sleep(interval_ms/1000.0)
        try: await send_ws(ws,1,int(time.time()*1000))
        except: break

def fortune():
    signs = [("大吉","今天你是天选之子！","🌟"),("吉","好运相伴，勇敢冲吧。","🍀"),("中吉","平平淡淡才是真。","😐"),("小吉","别太贪心，适可而止。","🤏"),("末吉","躺平休息，养精蓄锐。","🛋️"),("凶","建议请假一天。","💀")]
    lvl,tip,emoji = random.choice(signs)
    lucky = random.choice(["红色","蓝色","绿色","黑色","白色","黄色","紫色","橙色"])
    return f"{emoji} 运势：{lvl}\n{tip}\n幸运色：{lucky}"

async def translate(text):
    api_key = os.getenv("DS_API_KEY", "")
    if api_key:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post("https://api.deepseek.com/v1/chat/completions",
                    json={"model":"deepseek-chat","messages":[{"role":"user","content":f"将以下内容翻译为中文，只输出翻译结果：\n{text}"}],"temperature":0.3,"max_tokens":500},
                    headers={"Authorization":f"Bearer {api_key}"}, timeout=aiohttp.ClientTimeout(total=15)) as r:
                    data = await r.json()
                    return data["choices"][0]["message"]["content"].strip()
        except: pass
    return "翻译功能需要API Key或使用DeepSeek网页版暂时不支持"

async def add_reminder(text, uid):
    now = datetime.now()
    txt = text.replace("提醒", "").strip().lstrip("我").strip()
    m = re.search(r'(\d{1,2})[:：](\d{0,2})', txt)
    if m:
        h, minute = int(m.group(1)), int(m.group(2) or 0)
        target = now.replace(hour=h, minute=minute, second=0)
        if target <= now: target += timedelta(days=1)
        content = re.sub(r'\d{1,2}[:：]\d{0,2}','',txt).strip().strip("，,、")
        _reminders.append({"uid":uid,"time":target,"text":content or "提醒事项"})
        return f"⏰ 提醒已设置：{target.strftime('%H:%M')} -> {content or '提醒事项'}"
    m = re.search(r'(\d+)\s*分钟', txt)
    if m:
        delay = int(m.group(1))
        target = now + timedelta(minutes=delay)
        content = re.sub(r'\d+\s*分钟','',txt).strip().strip("，,、")
        _reminders.append({"uid":uid,"time":target,"text":content or "提醒事项"})
        return f"⏰ 提醒已设置：{target.strftime('%H:%M')} -> {content or '提醒事项'}"
    return "格式：提醒 15:30 开会 或 提醒 30分钟 喝水"

def check_reminders():
    now = datetime.now()
    triggered = [r for r in _reminders if r["time"]<=now]
    for r in triggered: _reminders.remove(r)
    return triggered

async def search_image(keyword):
    try:
        p = await async_playwright().start()
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-gpu'])
        page = await browser.new_page()
        await page.goto(f'https://cn.bing.com/images/search?q={quote(keyword)}&mkt=zh-CN&size=medium', timeout=15000)
        await page.wait_for_timeout(2000)
        imgs = await page.evaluate("""()=>{
            const results = [];
            document.querySelectorAll('img.mimg').forEach(img => {
                const src = img.src || img.getAttribute('data-src');
                if (src && src.startsWith('http') && !src.includes('bing.com/th')) {
                    results.push({url: src, w: img.naturalWidth || 0, h: img.naturalHeight || 0});
                }
            });
            results.sort((a,b) => (b.w*b.h) - (a.w*a.h));
            return results.slice(0, 3);
        }""")
        await browser.close()
        if imgs: return imgs[0]['url']
    except: pass
    return f"https://picsum.photos/seed/{random.randint(1,9999)}/400/300"

async def send_image_to(api_type, target_id, image_url):
    try:
        tok = await get_token()
        async with aiohttp.ClientSession() as s:
            async with s.post(f"https://api.sgroup.qq.com/v2/{api_type}/{target_id}/files",
                json={"file_type":1,"url":image_url}, headers={"Authorization":f"QQBot {tok}"}, timeout=aiohttp.ClientTimeout(total=15)) as r:
                up = await r.json()
                fi = up.get("file_info","")
                if not fi: return False
            async with s.post(f"https://api.sgroup.qq.com/v2/{api_type}/{target_id}/messages",
                json={"msg_type":7,"media":{"file_info":fi},"msg_id":""}, headers={"Authorization":f"QQBot {tok}"}, timeout=aiohttp.ClientTimeout(total=10)) as r2:
                return True
    except Exception as e:
        _log.error("图片发送失败: %s", e)
        return False

async def send_to_group(msg, group_id=None):
    gid = group_id or BOUND_GROUP_ID or os.getenv("LAST_GROUP_ID","")
    if gid and msg:
        await api_post(f"/v2/groups/{gid}/messages", {"content":msg,"msg_id":""})

# ---------- 消息分发 ----------
async def handle_dispatch(data):
    t = data.get("t","")
    d = data.get("d",{})
    if t == "READY":
        _log.info("机器人上线: %s", d.get("user",{}).get("username","?"))
    elif t == "C2C_MESSAGE_CREATE":
        uid = d.get("author",{}).get("user_openid","?")
        name = d.get("author",{}).get("username","")
        c = d.get("content","").strip()
        mid = d.get("id","")
        if not OWNER_OPENID:
            os.environ["OWNER_OPENID"] = uid
            try:
                with open(os.path.join(DATA_DIR, ".env"), "a") as f: f.write(f"\nOWNER_OPENID={uid}")
            except: pass

        if c in ["用量","查询用量","消费"]:
            await api_post(f"/v2/users/{uid}/messages", {"content":get_usage_report(),"msg_id":mid}); return
        if c == "关闭插话":
            global _auto_chat; _auto_chat = False
            await api_post(f"/v2/users/{uid}/messages", {"content":"好的，我闭嘴了 😶","msg_id":mid}); return
        if c == "开启插话":
            _auto_chat = True
            await api_post(f"/v2/users/{uid}/messages", {"content":"好的，我会随机冒泡 😉","msg_id":mid}); return
        if c.startswith("翻译") or c.startswith("翻译:"):
            txt = c.replace("翻译","",1).strip().lstrip(":").strip()
            result = await translate(txt)
            await api_post(f"/v2/users/{uid}/messages", {"content":f"翻译结果：\n{result}","msg_id":mid}); return
        if c in ["抽签","运势","运气"]:
            await api_post(f"/v2/users/{uid}/messages", {"content":fortune(),"msg_id":mid}); return
        if c in ["塔罗牌","占卜"]:
            cards = [("愚者","新开始，勇敢迈出第一步！","🌟"),("魔术师","你的创造力爆棚！","🎩"),("女祭司","相信直觉，答案就在心中。","🔮"),("皇帝","稳住，你是掌控者。","👑"),("恋人","今天浪漫气息浓厚。","💕"),("死神","结束意味着新开始。","⚰️"),("星星","希望在前方，保持信念。","✨"),("月亮","别过度思考，睡一觉再说。","🌙")]
            card,meaning,emoji = random.choice(cards)
            await api_post(f"/v2/users/{uid}/messages", {"content":f"{emoji} 你抽到了「{card}」\n{meaning}","msg_id":mid}); return
        if c.startswith("发图") or c.startswith("来张图"):
            kw = c.replace("发图","").replace("来张图","").strip() or "可爱"
            url = await search_image(kw)
            if url:
                ok = await send_image_to("users",uid,url)
                if not ok: await api_post(f"/v2/users/{uid}/messages", {"content":"图片发送失败 😅","msg_id":mid})
            else: await api_post(f"/v2/users/{uid}/messages", {"content":f"找不到「{kw}」的图片 😅","msg_id":mid})
            return
        if c in ["讲笑话","笑话","段子"]:
            reply = await chat_with_ai("_joke","讲一个搞笑短笑话或段子，不超过三句话。","")
            await api_post(f"/v2/users/{uid}/messages", {"content":reply,"msg_id":mid}); return
        if c.startswith("评价") or c.startswith("吐槽"):
            target = c[4:].strip() if c.startswith("评价") else c[5:].strip()
            reply = await chat_with_ai("_eval",f"用毒舌但不带恶意的语气，搞笑评价「{target}」，不超过两句话。","")
            await api_post(f"/v2/users/{uid}/messages", {"content":reply,"msg_id":mid}); return
        if c in ["帮助","功能","菜单","help"]:
            menu = "私聊命令：\n翻译 xxx | 运势 | 塔罗牌 | 笑话 | 发图 关键词\n提醒 15:30 喝水 | 提醒 30分钟 休息\n我的提醒 | 用量 | 群发 内容 | 关闭插话 / 开启插话"
            await api_post(f"/v2/users/{uid}/messages", {"content":menu,"msg_id":mid}); return
        if c.startswith("提醒"):
            result = await add_reminder(c,uid)
            await api_post(f"/v2/users/{uid}/messages", {"content":result,"msg_id":mid}); return
        if c in ["我的提醒","提醒列表"]:
            my = [r for r in _reminders if r["uid"]==uid]
            if my:
                lines = ["你的提醒："] + [f"{i}. {r['text']} -> {r['time'].strftime('%m-%d %H:%M')}" for i,r in enumerate(my,1)]
                await api_post(f"/v2/users/{uid}/messages", {"content":"\n".join(lines),"msg_id":mid})
            else: await api_post(f"/v2/users/{uid}/messages", {"content":"暂无提醒，发送「提醒 15:30 开会」来设置。","msg_id":mid})
            return
        if c.startswith("群发 "):
            msg = c[5:].strip()
            gid = os.getenv("LAST_GROUP_ID","")
            if not gid:
                await api_post(f"/v2/users/{uid}/messages", {"content":"还没有群ID，请先在群里@我一次。","msg_id":mid}); return
            await api_post(f"/v2/groups/{gid}/messages", {"content":msg,"msg_id":""})
            await api_post(f"/v2/users/{uid}/messages", {"content":f"已发送到群：{msg}","msg_id":mid}); return

        _log.info("[私聊] %s", c[:60])
        reply = await chat_with_ai(uid, c, name)
        await api_post(f"/v2/users/{uid}/messages", {"content":reply,"msg_id":mid})

    elif t == "AT_MESSAGE_CREATE":
        uid = d.get("author",{}).get("id","?")
        name = d.get("author",{}).get("username","")
        c = d.get("content","").strip()
        cid = d.get("channel_id",""); mid = d.get("id","")
        reply = await chat_with_ai(cid, c, name)
        await api_post(f"/channels/{cid}/messages", {"content":reply,"msg_id":mid})

    elif t == "GROUP_AT_MESSAGE_CREATE":
        uid = d.get("author",{}).get("member_openid","?")
        gid = d.get("group_openid","")
        name = d.get("author",{}).get("username","")
        raw = d.get("content","").strip()
        c = re.sub(r'<@!?\d+>', '', raw).strip()
        mid = d.get("id","")
        conv_id = f"group_{gid}"
        os.environ["LAST_GROUP_ID"] = gid
        global _target_group_id, BOUND_GROUP_ID
        _target_group_id = gid  # 记录最后一次交互的群
        if not BOUND_GROUP_ID:
            # 没有绑定群时才用第一个@的群作为绑定群
            BOUND_GROUP_ID = gid
            _log.info("自动绑定群ID: %s", gid)
            try:
                with open(GROUP_ID_FILE, "w") as f: f.write(gid)
            except: pass

        if c in ["帮助","菜单","功能","?"]:
            menu = "群聊命令（@我）：\n运势 | 塔罗牌 | 笑话 | 猜数字\n发图 关键词 | 评价/吐槽 xxx\n成语接龙 | 结束接龙 | 故事接龙 | 结束故事"
            await api_post(f"/v2/groups/{gid}/messages", {"content":menu,"msg_id":mid}); return
        if c in ["抽签","运势","运气"]:
            await api_post(f"/v2/groups/{gid}/messages", {"content":f"@{name} {fortune()}","msg_id":mid}); return
        if c in ["塔罗牌","占卜"]:
            cards = [("愚者","新开始，勇敢迈出第一步！","🌟"),("魔术师","你的创造力爆棚！","🎩"),("女祭司","相信直觉，答案就在心中。","🔮"),("皇帝","稳住，你是掌控者。","👑"),("恋人","今天浪漫气息浓厚。","💕"),("死神","结束意味着新开始。","⚰️"),("星星","希望在前方，保持信念。","✨"),("月亮","别过度思考，睡一觉再说。","🌙")]
            card,meaning,emoji = random.choice(cards)
            await api_post(f"/v2/groups/{gid}/messages", {"content":f"{emoji} @{name} 抽到了「{card}」\n{meaning}","msg_id":mid}); return
        if c in ["讲笑话","笑话","段子"]:
            reply = await chat_with_ai("_joke","讲一个搞笑短笑话或段子，不超过三句话。","")
            await api_post(f"/v2/groups/{gid}/messages", {"content":reply,"msg_id":mid}); return
        if c.startswith("发图") or c.startswith("来张图"):
            kw = c.replace("发图","").replace("来张图","").strip() or "可爱"
            url = await search_image(kw)
            if url: await send_image_to("groups",gid,url)
            else: await api_post(f"/v2/groups/{gid}/messages", {"content":f"找不到「{kw}」的图片 😅","msg_id":mid})
            return
        if c.startswith("评价") or c.startswith("吐槽"):
            target = c[4:].strip() if c.startswith("评价") else c[5:].strip()
            reply = await chat_with_ai("_eval",f"毒舌搞笑评价「{target}」，不超过两句话。","")
            await api_post(f"/v2/groups/{gid}/messages", {"content":reply,"msg_id":mid}); return

        if c == "猜数字":
            num = random.randint(1,100)
            _guess_num[gid] = {"num":num,"lo":1,"hi":100,"tries":0}
            await api_post(f"/v2/groups/{gid}/messages", {"content":"🤔 我想了一个1-100的数字，猜吧！","msg_id":mid}); return
        if gid in _guess_num and c.isdigit():
            g = _guess_num[gid]; guess = int(c); g["tries"]+=1
            if guess==g["num"]:
                await api_post(f"/v2/groups/{gid}/messages", {"content":f"🎉 恭喜！就是 {g['num']}! 用了 {g['tries']} 次。","msg_id":mid})
                del _guess_num[gid]
            elif guess<g["num"]:
                g["lo"]=max(g["lo"],guess)
                await api_post(f"/v2/groups/{gid}/messages", {"content":f"太小了！范围 {g['lo']}-{g['hi']}","msg_id":mid})
            else:
                g["hi"]=min(g["hi"],guess)
                await api_post(f"/v2/groups/{gid}/messages", {"content":f"太大了！范围 {g['lo']}-{g['hi']}","msg_id":mid})
            return

        if c == "成语接龙":
            _game_mode[gid] = "chengyu"
            _used_chengyu[gid] = set()
            starter = random.choice(chengyu_list)
            _used_chengyu[gid].add(starter)
            await api_post(f"/v2/groups/{gid}/messages", {"content":f"成语接龙开始！\n我：{starter}\n到你啦，以「{starter[-1]}」开头","msg_id":mid}); return
        if c == "结束接龙":
            _game_mode.pop(gid,None); _used_chengyu.pop(gid,None)
            await api_post(f"/v2/groups/{gid}/messages", {"content":"接龙结束！","msg_id":mid}); return
        if _game_mode.get(gid)=="chengyu" and len(c)==4:
            used = _used_chengyu.get(gid, set())
            if c in used:
                await api_post(f"/v2/groups/{gid}/messages", {"content":f"'{c}' 已经用过了！换一个","msg_id":mid}); return
            if c not in chengyu_list:
                await api_post(f"/v2/groups/{gid}/messages", {"content":f"'{c}' 不是成语吧？","msg_id":mid}); return
            used.add(c); _used_chengyu[gid] = used
            last = c[-1]
            nxt_words = [w for w in chengyu_list if w.startswith(last) and w not in used]
            if nxt_words:
                nxt = random.choice(nxt_words); used.add(nxt); _used_chengyu[gid] = used
                await api_post(f"/v2/groups/{gid}/messages", {"content":f"接得好！我来：{nxt}\n你的回合，以「{nxt[-1]}」开头","msg_id":mid})
            else:
                await api_post(f"/v2/groups/{gid}/messages", {"content":"你赢了！我接不下去了…","msg_id":mid})
                _game_mode.pop(gid,None)
            return

        if c == "故事接龙":
            _story_mode[gid] = "在一个月黑风高的夜晚……"
            await api_post(f"/v2/groups/{gid}/messages", {"content":f"故事接龙开始！\n{_story_mode[gid]}\n@我续写一句！ 说「结束故事」结束。","msg_id":mid}); return
        if c == "结束故事":
            story = _story_mode.pop(gid,"")
            await api_post(f"/v2/groups/{gid}/messages", {"content":f"故事完！\n{story}","msg_id":mid}); return
        if gid in _story_mode and len(c)>2:
            _story_mode[gid] += c
            await api_post(f"/v2/groups/{gid}/messages", {"content":f"收到！当前故事：\n{_story_mode[gid][:200]}……","msg_id":mid}); return

        _log.info("[群聊@] %s: %s", name or uid, c[:60])
        reply = await chat_with_ai(conv_id, c, name)
        await api_post(f"/v2/groups/{gid}/messages", {"content":reply,"msg_id":mid})

    elif t == "DIRECT_MESSAGE_CREATE":
        uid = d.get("author",{}).get("id","?")
        c = d.get("content","").strip()
        gid = d.get("guild_id",""); mid = d.get("id","")
        reply = await chat_with_ai(uid, c)
        await api_post(f"/dms/{gid}/messages", {"content":reply,"msg_id":mid})

# ---------- 定时任务主循环 ----------
async def daily_report_loop():
    global _last_morning_date, _last_evening_date, _last_report_date, _morning_news_titles, _last_50min_time
    while True:
        await asyncio.sleep(30)
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        gid = BOUND_GROUP_ID or os.getenv("LAST_GROUP_ID","")

        # 提醒
        triggered = check_reminders()
        for r in triggered:
            try:
                await api_post(f"/v2/users/{r['uid']}/messages", {"content":f"⏰ 提醒：{r['text']}","msg_id":""})
            except: pass

        # 早报 6:00
        if now.hour == 6 and _last_morning_date != today and gid:
            _last_morning_date = today
            _log.info("生成早报...")
            report = await generate_morning_report()
            # 提取标题用于去重
            titles = []
            for line in report.split('\n'):
                if re.match(r'^\d+[\.\s]', line.strip()):
                    titles.append(line.strip())
            _morning_news_titles = set(titles)
            if gid:
                await send_to_group(f"🌅 早安！\n\n{report}", gid)
            if OWNER_OPENID:
                await api_post(f"/v2/users/{OWNER_OPENID}/messages", {"content":f"早报已生成\n{report[:500]}..."})

        # 晚报 18:00
        if now.hour == 18 and _last_evening_date != today and gid:
            _last_evening_date = today
            _log.info("生成晚报...")
            morning_titles = list(_morning_news_titles) if _morning_news_titles else []
            report = await generate_evening_report(morning_titles)
            if gid:
                await send_to_group(f"🌆 晚间新闻\n\n{report}", gid)
            if OWNER_OPENID:
                await api_post(f"/v2/users/{OWNER_OPENID}/messages", {"content":f"晚报已生成\n{report[:500]}..."})

        # 每50分钟趣味消息
        if gid and (time.time() - _last_50min_time >= 50*60):
            _last_50min_time = time.time()
            _log.info("生成趣味消息...")
            fun_msg = await generate_random_fun()
            if fun_msg:
                await send_to_group(f"🤖 {fun_msg}", gid)

        # 用量日报 22:00
        if now.hour == 22 and _last_report_date != today:
            _last_report_date = today
            owner = os.getenv("OWNER_OPENID","")
            if owner:
                try:
                    await api_post(f"/v2/users/{owner}/messages", {"content":f"今日用量报告\n{get_usage_report()}","msg_id":""})
                except: pass

# ---------- 主程序 ----------
async def safe_main():
    try:
        ok = await init_deepseek_browser()
        if not ok:
            _log.error("DeepSeek浏览器初始化失败")
            if OWNER_OPENID:
                await api_post(f"/v2/users/{OWNER_OPENID}/messages", {"content":"❌ DeepSeek浏览器初始化失败"})
            return

        token = await get_token()
        asyncio.create_task(daily_report_loop())
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.sgroup.qq.com/gateway", headers={"Authorization":f"QQBot {token}"}) as r:
                gw = await r.json()
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(gw["url"]) as ws:
                _log.info("WebSocket 已连接")
                ht = None
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        op = data.get("op",-1); d = data.get("d",{})
                        global _seq; _seq = data.get("s",_seq)
                        if op==10:
                            await send_ws(ws,2,{"token":f"QQBot {token}","intents":(1<<30)|(1<<12)|(1<<25),"shard":[0,1],"properties":{}})
                            ht = asyncio.create_task(heartbeat(ws, d.get("heartbeat_interval",45000)))
                        elif op==0:
                            try:
                                await handle_dispatch(data)
                            except Exception as e:
                                err = traceback.format_exc()
                                _log.error("消息处理异常: %s", err)
                                if OWNER_OPENID:
                                    try:
                                        await api_post(f"/v2/users/{OWNER_OPENID}/messages", {"content":f"⚠️ 消息处理异常\n{str(e)[:200]}"})
                                    except: pass
                        elif op in (7,9):
                            _log.warning("需要重连..."); break
                    elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        break
                if ht: ht.cancel()
    except Exception as e:
        err = traceback.format_exc()
        _log.critical("主循环崩溃: %s", err)
        if OWNER_OPENID:
            try:
                await api_post(f"/v2/users/{OWNER_OPENID}/messages", {"content":f"💥 机器人崩溃\n{str(e)[:300]}"})
            except: pass

if __name__ == "__main__":
    _log.info("启动机器人...")
    asyncio.run(safe_main())