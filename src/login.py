# src/login.py
import asyncio
from playwright.async_api import async_playwright
import os
import json
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

COOKIES_FILE = os.getenv("COOKIES_FILE", "twitter_cookies.json")

async def login_and_save_cookies(username: str, password: str, cookies_file: str = COOKIES_FILE):
    async with async_playwright() as p:
        # 配置代理
        proxy_server = os.getenv('HTTP_PROXY') or os.getenv('http_proxy')
        
        browser = await p.chromium.launch(
            headless=False,
            proxy={"server": proxy_server} if proxy_server else None,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-setuid-sandbox'
            ]
        )
        
        context = await browser.new_context()
        page = await context.new_page()
        
        # 移除webdriver属性以避免被检测
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
            });
        """)

        print(">>> 打开登录页面，请在弹出浏览器中完成可能的额外验证（如验证码/2FA）")
        
        # 修改后的页面导航
        await page.goto("https://x.com/login", wait_until="domcontentloaded", timeout=60000)
        
        # 等待用户名输入框出现
        try:
            await page.wait_for_selector('input[name="text"]', timeout=30000)
            await page.fill('input[name="text"]', username)
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(2000)
        except Exception as e:
            print(f">>> 用户名输入失败: {e}")
            # 尝试其他可能的选择器
            try:
                await page.wait_for_selector('input[autocomplete="username"]', timeout=10000)
                await page.fill('input[autocomplete="username"]', username)
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(2000)
            except Exception as e2:
                print(f">>> 备用用户名选择器也失败: {e2}")

        # 等待密码输入框出现
        try:
            await page.wait_for_selector('input[name="password"]', timeout=10000)
            await page.fill('input[name="password"]', password)
            await page.keyboard.press("Enter")
        except Exception as e:
            print(f">>> 密码输入失败: {e}")
            # 尝试其他可能的选择器
            try:
                await page.wait_for_selector('input[autocomplete="current-password"]', timeout=10000)
                await page.fill('input[autocomplete="current-password"]', password)
                await page.keyboard.press("Enter")
            except Exception as e2:
                print(f">>> 备用密码选择器也失败: {e2}")

        print(">>> 请在浏览器中完成任何额外的交互以保证登录成功（等待 15~30 秒）")
        await page.wait_for_timeout(15000)

        # 检查是否登录成功
        try:
            # 等待可能的重定向或成功指标
            await page.wait_for_timeout(5000)
            
            cookies = await context.cookies()
            with open(cookies_file, "w", encoding="utf-8") as f:
                json.dump(cookies, f, ensure_ascii=False, indent=2)

            print(f">>> Cookies 已保存到 {cookies_file}")
        except Exception as e:
            print(f">>> 保存cookies时出错: {e}")

        await browser.close()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--cookies", default=COOKIES_FILE)
    args = parser.parse_args()
    asyncio.run(login_and_save_cookies(args.user, args.password, args.cookies))