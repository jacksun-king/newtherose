#!/usr/bin/env python3

import os, re, sys, time, requests
from seleniumbase import SB

# 环境变量 
EMAIL = os.environ.get("EMAIL") or ""            # 邮箱   
PASSWORD = os.environ.get("PASSWORD") or ""      # 密码
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN") or ""  # tg通知 bot token
TG_CHAT_ID = os.environ.get("TG_CHAT_ID") or ""      # tg通知 chat_id id

# 目标服务器面板地址
SERVER_URL = os.environ.get("SERVER_URL") or "https://panel.therose.cloud/server/b4335b9c"

BASE_URL = "https://client.therose.cloud/login"

# logo 图片路径
LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.png")

# --- 代理配置 ---
IS_PROXY = os.environ.get('IS_PROXY', 'false').lower() == 'true'
PROXY_SERVER = os.environ.get('PROXY_SERVER') or "socks5://127.0.0.1:1080"
REQUESTS_PROXIES = {"http": PROXY_SERVER, "https": PROXY_SERVER} if IS_PROXY else None

# 检查必要变量
if not EMAIL or not PASSWORD:
    print("❌ 请设置环境变量 EMAIL 和 PASSWORD")
    sys.exit(1)

# 获取当前出口IP（失败返回 None）
def get_current_ip(proxy_server=None):
    proxies = {"http": proxy_server, "https": proxy_server} if (proxy_server and IS_PROXY) else Noneip_apis = ["https://api.ip.sb/ip", "https://ifconfig.me/ip", "https://api.ipify.org"]
    for api in ip_apis:
        try:
            resp = requests.get(api, proxies=proxies, timeout=15)
            if resp.status_code == 200:
                return resp.text.strip()
        except Exception as e:
            print(f"⚠️ 通过 {api} 获取出口IP失败: {e}")
    return None

# 代理健康检查：重试多次，全部失败说明代理不可用
def check_proxy_health(retries=3, interval=10):
    for i in range(retries):
        ip = get_current_ip(PROXY_SERVER)
        if ip:
            return ip
        print(f"⚠️ 代理连通性检查失败（第 {i + 1}/{retries} 次），{interval} 秒后重试...")
        time.sleep(interval)
    return None

# 点击续期按钮
def click_extend_button(sb):
    selectors = [
        'span:contains("Extend")',
        'button:contains(title="Extend")',
    ]
    for sel in selectors:
        try:
            if sb.find_element(sel, timeout=40):
                print(f"✅ 找到按钮，选择器: {sel}")
                sb.uc_click(sel, timeout=100)
                print("✅ 点击成功")
                return True, {}
        except:
            continue
    try:
        btn = sb.find_element('button:contains("Extend")', timeout=2)
        sb.driver.execute_script("arguments[0].click();", btn)
        print("✅ 通过 JavaScript 点击成功")
        return True, {}
    except Exception as e:
        err = str(e)
        # 服务商只有到期前半小时才会显示 Extend 按钮
        not_time = "was not found" in err or "NoSuchElement" in err
        return False, {"error": err, "not_time": not_time}

# 检查续期是否成功
def check_renewal_success(sb):
    success_selectors = [
        '.alert-success',
        '.alert.alert-success',
        'div[role="alert"].alert-success',
        'div.alert-success',
        'span:contains("successfully purchased")',
        'div:contains("successfully purchased")'
    ]
    
    print("⏳ 等待5秒检查续期结果...")
    time.sleep(5)
    
    for selector in success_selectors:
        try:
            element = sb.find_element(selector, timeout=2)
            if element:
                text = element.text
                print(f"✅ 发现成功提示！选择器: {selector}")
                return True, text
        except:
            continue
    
    try:
        page_source = sb.get_page_source()
        if "successfully purchased" in page_source.lower():
            print("✅ 页面源码中发现 'successfully purchased' 关键词")
            return True, "服务器已成功续期"
    except:
        pass
    
    return False, "未检测到续期成功提示"

# 发送tg通知
def send_tg(token, chat_id, message):
    if not token or not chat_id:
        return
    message = f"【TheRose Cloud】\n{message}"

    if os.path.exists(LOGO_PATH):
        url = f"https://api.telegram.org/bot{token}/sendPhoto"
        try:
            with open(LOGO_PATH, "rb") as f:
                resp = requests.post(
                    url,
                    data={"chat_id": chat_id, "caption": message},
                    files={"photo": f},
                    timeout=15,
                    proxies=REQUESTS_PROXIES,
                )
            if resp.status_code == 200:
                print("📨 Telegram 通知已发送（带 logo）")
                return
            else:
                print(f"⚠️ 带 logo 发送失败，回退为纯文字: {resp.text}")
        except Exception as e:
            print(f"⚠️ 带 logo 发送异常，回退为纯文字: {e}")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(url, json={"chat_id": chat_id, "text": message}, timeout=10, proxies=REQUESTS_PROXIES)
        if resp.status_code == 200:
            print("📨 Telegram 通知已发送")
        else:
            print(f"❌ Telegram 发送失败: {resp.text}")
    except Exception as e:
        print(f"❌ Telegram 发送异常: {e}")

# 获取 Turnstile token（读取 cf-turnstile-response 隐藏域的值）
def get_turnstile_token(sb):
    try:
        # UC 模式底层是 CDP Runtime.evaluate，不能用裸 return，必须包成 IIFE
        return sb.execute_script(
            "(function(){"
            "var el = document.querySelector('[name=\"cf-turnstile-response\"]');"
            "if (!el) { return '__NO_ELEMENT__'; }"
            "return el.value || '';"
            "})()"
        )
    except Exception as e:
        print(f"⚠️ 读取 token 异常: {e}")
        return ""

# 轮询等待 Turnstile token 生成，最多等 max_wait 秒
def wait_turnstile_token(sb, max_wait=30):
    for i in range(max_wait):
        token = get_turnstile_token(sb)
        if token == "__NO_ELEMENT__":
            if i % 5 == 0:
                print(f"⚠️ 页面上没有 cf-turnstile-response 隐藏域（widget 未渲染？），已等待 {i} 秒...")
        elif token:
            print(f"✅ Turnstile token 已生成（长度 {len(token)}，前10位: {token[:10]}...）")
            return token
        elif i % 5 == 0:
            print(f"⏳ token 仍为空，已等待 {i} 秒...")
        time.sleep(1)
    print("❌ 等待超时，Turnstile token 始终未生成（验证未真正通过）")
    return ""

# 处理 Turnstile：鼠标点击与键盘 Tab+空格两种方式交替尝试
def solve_turnstile(sb, attempt=0):
    try:
        # 先把 widget 滚动到视口内，避免 pyautogui 坐标偏差
        sb.execute_script(
            "(function(){"
            "var el = document.querySelector('.cf-turnstile, [name=\"cf-turnstile-response\"]');"
            "if (el) { el.scrollIntoView({block: 'center'}); }"
            "})()"
        )
        time.sleep(1)
    except Exception:
        pass
    try:
        if attempt % 2 == 0:
            sb.uc_gui_click_captcha()
            print("🛡 已尝试 uc_gui_click_captcha（鼠标坐标点击）")
        else:
            sb.uc_gui_handle_captcha()
            print("🛡 已尝试 uc_gui_handle_captcha（键盘 Tab+空格）")
    except Exception as e:
        print(f"⚠️ 处理 Turnstile 异常: {e}")

# 打开登录页并等待表单出现（带重试，防止代理不稳导致页面加载失败直接崩溃）
def open_login_page(sb, retries=3):
    for i in range(retries):
        print(f"🌐 打开登录页面...(第 {i + 1}/{retries} 次)")
        try:
            sb.open(BASE_URL)
            sb.wait_for_ready_state_complete()
            sb.sleep(2)
            if sb.is_element_visible('#login_form_email'):
                return True
            print(f"⚠️ 页面已打开但未见登录表单，当前 URL: {sb.get_current_url()}")
            sb.save_screenshot(f"login_page_error_{i + 1}.png")
        except Exception as e:
            print(f"⚠️ 打开登录页异常: {e}")
            try:
                sb.save_screenshot(f"login_page_error_{i + 1}.png")
            except Exception:
                pass
        time.sleep(5)
    return False

# 登录流程
def login(sb, email, password):
    if not open_login_page(sb):
        print("❌ 登录页面加载失败（多为代理不通或被 CF 整页拦截，见截图）")
        return False, "PAGE_LOAD_FAILED"

    print("📧 填写邮箱...")
    sb.type('#login_form_email', email, timeout=10)
    print("🔑 填写密码...")
    sb.type('#login_form_password', password, timeout=10)
    time.sleep(1) 
    print("🛡 处理 Turnstile...")
    solve_turnstile(sb, attempt=0)

    print("⏳ 等待验证 token 生成...")
    token = wait_turnstile_token(sb, max_wait=25)

    for attempt in range(5):
        # token 为空则先重新处理 Turnstile（交替鼠标/键盘方式），不要盲目点登录
        if not token:
            print(f"🛡 token 为空，重新处理 Turnstile...(第 {attempt + 1} 次)")
            solve_turnstile(sb, attempt=attempt + 1)
            token = wait_turnstile_token(sb, max_wait=20)
            if not token:
                sb.save_screenshot(f"turnstile_empty_{attempt + 1}.png")
                continue

        print(f"🔑 点击登录按钮...(第 {attempt + 1} 次)")
        try:
            sb.uc_click('button:contains("Sign in")')
        except Exception as e:
            print(f"⚠️ 点击异常: {e}")

        for _ in range(5):
            current_url = sb.get_current_url()
            if "panel" in current_url:
                print("✅ 登录成功，已跳转到 Dashboard")
                return True, current_url
            time.sleep(1)

        try:
            err_selectors = ['.alert-danger', 'div[role="alert"].alert-danger', '.text-danger']
            for sel in err_selectors:
                if sb.is_element_visible(sel):
                    err_text = sb.get_text(sel)
                    print(f"❌ 登录出现错误提示: {err_text}")
                    sb.save_screenshot("login_failed.png")
                    return False, sb.get_current_url()
        except Exception:
            pass
        # 提交失败后 token 可能已被消耗/过期，重新读取，为空则下一轮会重新触发验证
        token = get_turnstile_token(sb)
        if token == "__NO_ELEMENT__":
            token = ""
        print(f"⚠️ 未跳转（当前 token: {'有，长度' + str(len(token)) if token else '空'}），准备重试...")

    print(f"❌ 登录失败，当前 URL: {sb.get_current_url()}")
    sb.save_screenshot("login_failed.png")
    return False, sb.get_current_url()

# 执行重启服务器操作
def reboot_server(sb, url):
    print(f"🔄 准备进入服务器面板进行重启: {url}")
    try:
        sb.open(url)
        sb.wait_for_ready_state_complete()
        time.sleep(5) # 给面板一点时间加载状态
        
        # ==========================================
        # 1. 处理控制面板需要独立登录的情况
        # ==========================================
        if sb.is_element_visible('input[type="password"]'):
            print("🔒 检测到控制面板需要独立登录，正在尝试自动输入账号密码...")
            try:
                # 输入账号 (兼容不同的输入框 name 属性)
                if sb.is_element_visible('input[name="user"]'):
                    sb.type('input[name="user"]', EMAIL)
                elif sb.is_element_visible('input[type="text"]'):
                    sb.type('input[type="text"]', EMAIL)
                
                # 输入密码
                sb.type('input[type="password"]', PASSWORD)
                time.sleep(1)
                
                # 尝试处理人机验证 (如果存在)
                try:
                    sb.uc_gui_click_captcha()
                except Exception:
                    pass # 如果没有验证码或点击报错，则直接跳过
                
                time.sleep(3) 
                
                # 点击登录按钮
                try:
                    sb.click('button:contains("Login")')
                except Exception:
                    sb.click('button[type="submit"]')
                    
                time.sleep(8) # 等待登录完成并跳转
            except Exception as e:
                print(f"⚠️ 自动登录控制面板发生错误: {e}")
        
        # ==========================================
        # 2. 检查是否被重定向到主页，如果是则强制返回详情页
        # ==========================================
        current_url = sb.get_current_url()
        if "/server/" not in current_url:
            print("🔀 检测到停留在主列表页，正在强制进入目标服务器控制台...")
            sb.open(url)
            sb.wait_for_ready_state_complete()
            time.sleep(6)

        # ==========================================
        # 3. 寻找并点击“重启”按钮
        # ==========================================
        reboot_selectors = [
            'button[data-action="restart"]',
            'button i.fa-redo',
            'button i.fa-sync'
        ]
        
        btn_clicked = False
        
        # 方案A: 通过常规 CSS 选择器点击
        for sel in reboot_selectors:
            try:
                if sb.is_element_visible(sel):
                    print(f"✅ 找到重启按钮，选择器: {sel}")
                    sb.uc_click(sel)
                    btn_clicked = True
                    break
            except Exception:
                continue
                
        # 方案 B: 降级方案（JS 直接定位右上角的中间按钮）
        if not btn_clicked:
            print("⚠️ 未能通过常规选择器找到按钮，正在使用 JavaScript 定位中间的重启按钮...")
            try:
                btn_clicked = sb.driver.execute_script("""
                    const buttons = document.querySelectorAll('div.flex.items-center button, div.items-center button');
                    
                    // 1. 先尝试通过特征匹配
                    for (let btn of buttons) {
                        if (btn.getAttribute('data-action') === 'restart' || 
                            btn.innerHTML.includes('fa-redo') || 
                            btn.innerHTML.includes('fa-sync')) {
                            btn.click();
                            return true;
                        }
                    }
                    
                    // 2. 如果特征匹配失败，直接点击三个按钮中的中间那一个 (索引为 1)
                    if (buttons.length >= 3) {
                        buttons[1].click(); 
                        return true;
                    } else if (buttons.length >= 2) {
                        // 如果只有两个按钮，通常是 启动 和 重启，重启在最后
                        buttons[buttons.length - 1].click();
                        return true;
                    }
                    return false;
                """)
                if btn_clicked:
                    print("✅ 通过 JavaScript 成功点击了中间的重启按钮")
            except Exception as ex:
                print(f"⚠️ JS 降级点击失败: {ex}")
                
        # ==========================================
        # 4. 验证结果
        # ==========================================
        if btn_clicked:
            print("⏳ 等待重启命令发送...")
            time.sleep(3)
            return True, "已成功发送重启指令"
        else:
            return False, "页面上未检测到重启按钮"
            
    except Exception as e:
        # 这个 except 捕获最外层 try 的异常，防止语法错误
        return False, f"重启操作发生异常: {e}"

# 主流程
def main():
    print("🚀 启动浏览器")

    if IS_PROXY:
        print(f"⚙️ 代理已启用: {PROXY_SERVER}")
        # 代理健康检查：代理不通就没必要继续跑，直接通知并退出
        current_ip = check_proxy_health(retries=3, interval=10)
        if not current_ip:
            msg = "❌ 代理连通性检查失败（多次无法通过代理访问外网），本次任务终止，请检查代理节点。"
            print(msg)
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg)
            sys.exit(1)
    else:
        print("🌐 直连模式（未使用代理）")
        current_ip = get_current_ip() or "获取失败"

    print(f"🎯 当前出口IP: {current_ip}")

    sb_kwargs = {"uc": True, "headless": False}
    if IS_PROXY:
        sb_kwargs["proxy"] = PROXY_SERVER

    with SB(**sb_kwargs) as sb:
        success, url = login(sb, EMAIL, PASSWORD)
        
        if not success:
            if url == "PAGE_LOAD_FAILED":
                msg = "❌ 登录页面加载失败（代理不稳或被 CF 拦截），本次跳过，详见运行截图。"
            else:
                msg = "❌ 登录失败，请检查账号密码或验证码拦截情况。"
            print(msg)
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg)
            return
        
        print("📄 开始续期流程...")
        ok, info = click_extend_button(sb)
        
        # 续期逻辑
        if not ok:
            if info.get("not_time"):
                msg_renewal = "⏳ 未到续期时间，Extend 按钮尚未出现（一般到期前半小时开放），本次跳过。"
            else:
                msg_renewal = f"❌ 续期失败，未找到 Extend 按钮 ({info.get('error')})。"
            print(msg_renewal)
        else:
            time.sleep(1)
            try:
                button = sb.find_element('button:contains("Order now")', timeout=5)
                if button:
                    print("🛒 点击 Order now 按钮...")
                    sb.uc_click('button:contains("Order now")')
                else:
                    msg_renewal = "❌ 续期异常，未找到 Order now 按钮。"
                    print(msg_renewal)
            except Exception as e:
                msg_renewal = f"❌ 点击 Order now 发生错误: {e}。"
                print(msg_renewal)
            
            print("🔍 检查续期结果...")
            renewal_success, renewal_msg = check_renewal_success(sb)
            if renewal_success:
                msg_renewal = f"✅ 续期成功！{renewal_msg}"
                sb.save_screenshot("renewal_success.png")
            else:
                msg_renewal = f"❌ 续期可能失败: {renewal_msg}"
                sb.save_screenshot("renewal_failed.png")
            print(msg_renewal)

        # 重启逻辑 (与续期独立，均会执行)
        print("🔄 开始检查并执行服务器重启...")
        reboot_ok, reboot_msg = reboot_server(sb, SERVER_URL)
        
        if reboot_ok:
            msg_reboot = f"✅ 自动重启成功: {reboot_msg}"
            sb.save_screenshot("reboot_success.png")
        else:
            msg_reboot = f"⚠️ 重启失败: {reboot_msg}"
            sb.save_screenshot("reboot_failed.png")
        print(msg_reboot)
        
        # 汇总发送通知
        final_msg = f"{msg_renewal}\n---\n{msg_reboot}"
        send_tg(TG_BOT_TOKEN, TG_CHAT_ID, final_msg)

    print("🏁 脚本执行完毕")

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        # 全局兜底：任何未捕获异常都发TG 通知，避免静默崩溃
        err_msg = f"❌ 脚本发生未预期异常: {e}"
        print(err_msg)
        send_tg(TG_BOT_TOKEN, TG_CHAT_ID, err_msg)
        sys.exit(1)
