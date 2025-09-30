# src/scraper.py
import os
import json
import time
import random
import re
from typing import List, Dict, Optional
from bs4 import BeautifulSoup

from config import CONFIG, random_sleep_ms

# lazy imports for optional libs
try:
    import requests
except Exception:
    requests = None

# ---------- helper ----------
def _text_to_int(s: Optional[str]) -> int:
    if not s:
        return 0
    s = s.strip().upper().replace(",", "")
    m = re.match(r"([0-9,.]+)([KM]?)", s)
    if not m:
        try:
            return int(re.sub(r"[^\d]", "", s) or 0)
        except:
            return 0
    num, suf = m.groups()
    try:
        n = float(num)
    except:
        return 0
    if suf == "K":
        n *= 1_000
    elif suf == "M":
        n *= 1_000_000
    return int(n)

# ---------- Scraper ----------
class Scraper:
    """
    Dual-mode scraper:
      1) requests -> nitter.net (lightweight, preferred)
      2) Playwright with saved cookies (fallback; more robust)
    """

    def __init__(self, username: str, limit: int = 20):
        self.username = username.lstrip("@")
        self.limit = limit
        print(self.limit)
        # prefer nitter frontend (less likely to trigger X detection)
        # you may replace with another public nitter instance if nitter.net rate-limits.
        self.nitter_base = f"https://nitter.net/{self.username}"
        self.cookies_file = CONFIG.get("COOKIES_FILE", "twitter_cookies.json")
        self.proxy = CONFIG.get("PROXY") or None

    # ----------------- Mode 1: requests (nitter) -----------------
    def scrape_with_requests(self) -> Optional[List[Dict]]:
        if requests is None:
            print("requests 未安装，跳过 requests 模式")
            return None

        print(">>> 使用 requests（nitter）模式抓取（更轻量、优先）")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }
        proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None

        url = self.nitter_base
        retries = 0
        max_retries = CONFIG.get("MAX_REQUEST_RETRIES", 3)
        backoff = 1.0
        while retries <= max_retries:
            try:
                resp = requests.get(url, headers=headers, timeout=CONFIG.get("REQUEST_TIMEOUT", 15), proxies=proxies)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    tweets = []
                    # nitter structure: each tweet is in div.timeline-item (may vary across instances)
                    items = soup.find_all("div", class_="timeline-item")
                    if not items:
                        # some nitter instances use 'tweet' class
                        items = soup.find_all("div", class_="tweet")
                    for item in items[: self.limit]:
                        # content
                        c_el = item.find("div", class_="tweet-content")
                        if not c_el:
                            c_el = item.find("div", attrs={"class": re.compile("tweet-content|content")})
                        text = c_el.get_text(" ", strip=True) if c_el else ""
                        # stats: find numbers in the item
                        likes = retweets = replies = 0
                        # nitter often puts stats in div.tweet-meta or div.tweet-stats
                        stats = item.find_all("span", class_=re.compile("icon|tweet-stat|stat"))
                        if not stats:
                            stats = item.find_all("a", href=re.compile("/(?:likes|replies|retweets)"))
                        # fallback: find any number-like strings in item footer
                        footer_texts = " ".join([s.get_text(" ", strip=True) for s in item.find_all(["span","a"])])
                        # try simple number extraction heuristics
                        nums = re.findall(r"([0-9]+(?:[,\.][0-9]+)?[KMkm]?)", footer_texts)
                        if nums:
                            # assign last three to replies/retweets/likes if available
                            n = [ _text_to_int(x) for x in nums ]
                            if len(n) >= 3:
                                replies, retweets, likes = n[:3]
                            elif len(n) == 2:
                                retweets, likes = n[:2]
                            elif len(n) == 1:
                                likes = n[0]
                        tweets.append({
                            "id": None,
                            "url": None,
                            "date": None,
                            "username": self.username,
                            "content": text,
                            "likeCount": likes,
                            "replyCount": replies,
                            "retweetCount": retweets
                        })
                    # gentle pause to mimic human browsing
                    time.sleep(random_sleep_ms())
                    if tweets:
                        return tweets
                    # no tweets found -> probably blocked or structure changed
                    print("!!! requests 模式未解析到推文，可能被限制或 nitter 结构不同")
                    return None
                else:
                    print(f"!!! requests 返回状态: {resp.status_code}")
                    if resp.status_code in (429, 403):
                        # likely rate-limited or blocked -> backoff and fallback
                        raise Exception(f"HTTP {resp.status_code}")
                    # other statuses -> retry
                    retries += 1
                    time.sleep(backoff)
                    backoff *= 2
            except Exception as e:
                retries += 1
                print(f"!!! requests 异常: {e}，正在重试 {retries}/{max_retries}")
                time.sleep(backoff)
                backoff *= 2
        print(">>> requests 模式重试结束，未能成功")
        return None

    # ----------------- Mode 2: Playwright + cookies (fallback/robust) -----------------
    async def scrape_with_playwright(self) -> Optional[List[Dict]]:
        print(">>> 使用 Playwright 模式抓取（需要已保存 cookies，若无会尝试无 cookie 模式）")
        from playwright.async_api import async_playwright
        retries = 0
        max_retries = CONFIG.get("MAX_PLAYWRIGHT_RETRIES", 2)
        backoff = 2
        proxy = os.getenv("HTTP_PROXY", None)  # 从环境变量读取代理
        launch_args = {"headless": True}
        if proxy:
            launch_args["proxy"] = {"server": proxy}

        # 进度文件（JSON Lines），每抓到一条就写入，方便中断恢复
        prog_dir = "examples"
        os.makedirs(prog_dir, exist_ok=True)
        prog_path = os.path.join(prog_dir, f"{self.username}_progress.jsonl")

        # 读取已有进度以便去重（resume）
        seen_keys = set()
        if os.path.exists(prog_path):
            try:
                with open(prog_path, "r", encoding="utf-8") as fr:
                    for ln in fr:
                        try:
                            o = json.loads(ln)
                            key = o.get("url") or o.get("content") or o.get("text")
                            if key:
                                seen_keys.add(key)
                        except Exception:
                            continue
                print(f">>> 已加载进度文件，已去重 {len(seen_keys)} 条（{prog_path}）")
            except Exception as e:
                print(f"!!! 读取进度文件失败：{e}")

        while retries <= max_retries:
            try:
                async with async_playwright() as p:
                    browser = await p.chromium.launch(**launch_args)
                    context = await browser.new_context()

                    # load cookies if exist
                    if os.path.exists(self.cookies_file):
                        try:
                            with open(self.cookies_file, "r", encoding="utf-8") as f:
                                cookies = json.load(f)
                            await context.add_cookies(cookies)
                            print(f">>> 已加载 cookies：{self.cookies_file}")
                        except Exception as e:
                            print(f"!!! 加载 cookies 失败：{e}")

                    page = await context.new_page()
                    # set user agent / headers
                    await page.set_extra_http_headers({"Accept-Language": "en-US,en;q=0.9"})
                    await page.goto(
                        f"https://x.com/{self.username}",
                        timeout=60000,
                        wait_until="domcontentloaded"
                    )
                    await page.wait_for_timeout(4000)  # 等待页面元素渲染

                    collected = []
                    start = time.time()
                    prev_seen_size = len(seen_keys)
                    no_new_rounds = 0  # 如果连续若干轮没有新条目则提前退出

                    # helper: parse number strings like "4.6K", "1,234", "16"
                    def _parse_num_str(s: str) -> int:
                        if not s:
                            return 0
                        t = s.strip().replace(",", "").upper()
                        try:
                            if t.endswith("K"):
                                return int(float(t[:-1]) * 1000)
                            if t.endswith("M"):
                                return int(float(t[:-1]) * 1000000)
                            return int(float(t))
                        except:
                            # fallback: extract digits
                            m = re.search(r"([0-9]+(?:[.,][0-9]+)?[KMkm]?)", s)
                            return _text_to_int(m.group(1)) if m else 0

                    # 滚动直到达到 limit 或超时或无新内容若干轮
                    while len(collected) < self.limit and no_new_rounds < 20:
                        articles = await page.query_selector_all("article")
                        for art in articles:
                            try:
                                # 尝试获取推文 URL（作为首选去重键）
                                url = None
                                try:
                                    link = await art.query_selector('a[href*="/status/"]')
                                    if link:
                                        href = await link.get_attribute("href")
                                        if href:
                                            url = href if href.startswith("http") else "https://x.com" + href
                                except:
                                    url = None

                                # 获取文本：优先 data-testid='tweetText'，否则 div[lang]
                                text = None
                                try:
                                    content_el = await art.query_selector("div[data-testid='tweetText']")
                                    if content_el:
                                        text = (await content_el.inner_text()).strip()
                                except:
                                    text = None
                                if not text:
                                    try:
                                        lang_el = await art.query_selector("div[lang]")
                                        if lang_el:
                                            text = (await lang_el.inner_text()).strip()
                                    except:
                                        text = None
                                if not text:
                                    continue

                                # 选择一个唯一 key 用于去重（优先 url）
                                key = url or text
                                if key in seen_keys:
                                    continue

                                # --- 尝试读取三个交互数（优先 selector，再 fallback aria-label） ---
                                reply = retweet = like = None

                                # 优先直接选中 span（常见结构： button[data-testid="reply"] span ）
                                try:
                                    r_el = await art.query_selector('button[data-testid="reply"] span')
                                    if r_el:
                                        rtxt = (await r_el.inner_text()).strip()
                                        if rtxt:
                                            reply = _parse_num_str(rtxt)
                                except:
                                    pass

                                try:
                                    rt_el = await art.query_selector('button[data-testid="retweet"] span')
                                    if rt_el:
                                        rttxt = (await rt_el.inner_text()).strip()
                                        if rttxt:
                                            retweet = _parse_num_str(rttxt)
                                except:
                                    pass

                                try:
                                    l_el = await art.query_selector('button[data-testid="like"] span')
                                    if l_el:
                                        ltxt = (await l_el.inner_text()).strip()
                                        if ltxt:
                                            like = _parse_num_str(ltxt)
                                except:
                                    pass

                                # fallback: 解析 role=group 或 aria-label（你提供的 DOM 片段中 aria-label 列出: "4 replies, 9 reposts, 16 likes, ..."）
                                if (reply is None or retweet is None or like is None):
                                    try:
                                        group_el = await art.query_selector('[role="group"][aria-label], [aria-label*="replies"], div[aria-label*="replies"]')
                                        if group_el:
                                            al = (await group_el.get_attribute("aria-label")) or ""
                                            # 更精确地根据关键词提取
                                            m_reply = re.search(r'([0-9.,KMkm]+)\s+replies?', al, re.I)
                                            m_repost = re.search(r'([0-9.,KMkm]+)\s+(?:reposts?|reposts?|repost|retweets?)', al, re.I)
                                            m_retweet = re.search(r'([0-9.,KMkm]+)\s+repost', al, re.I)  # some labels use 'repost'
                                            m_like = re.search(r'([0-9.,KMkm]+)\s+likes?', al, re.I)
                                            # assign if found and field still None
                                            if reply is None and m_reply:
                                                reply = _parse_num_str(m_reply.group(1))
                                            if retweet is None:
                                                # prefer repost match then retweet match
                                                if m_repost:
                                                    retweet = _parse_num_str(m_repost.group(1))
                                                elif m_retweet:
                                                    retweet = _parse_num_str(m_retweet.group(1))
                                            if like is None and m_like:
                                                like = _parse_num_str(m_like.group(1))
                                    except:
                                        pass

                                # 最终归一化为整数（None -> 0）
                                reply = int(reply or 0)
                                retweet = int(retweet or 0)
                                like = int(like or 0)

                                item = {
                                    "id": None,
                                    "url": url,
                                    "date": None,
                                    "username": self.username,
                                    "content": text,
                                    "likeCount": like,
                                    "replyCount": reply,
                                    "retweetCount": retweet
                                }

                                # 立即追加写入进度文件（JSON Lines），避免中断丢失
                                try:
                                    with open(prog_path, "a", encoding="utf-8") as fw:
                                        fw.write(json.dumps(item, ensure_ascii=False) + "\n")
                                        fw.flush()
                                except Exception as e:
                                    print(f"!!! 写入进度文件失败: {e}")

                                collected.append(item)
                                seen_keys.add(key)

                                if len(collected) >= self.limit:
                                    break
                            except Exception:
                                # 跳过该 article
                                continue

                        # 判断本轮是否有新条目，若无则计数（避免无限滚动）
                        if len(seen_keys) == prev_seen_size:
                            no_new_rounds += 1
                        else:
                            prev_seen_size = len(seen_keys)
                            no_new_rounds = 0

                        # 滚动加载更多并随机等待以模拟人工行为
                        await page.evaluate("window.scrollBy(0, window.innerHeight * 0.9)")
                        await page.wait_for_timeout(int(random_sleep_ms() * 1000))

                    await browser.close()
                    if collected:
                        return collected[: self.limit]
                    else:
                        print("!!! Playwright 未解析到推文，可能页面结构变更或 cookies 无效")
                        return None
            except Exception as e:
                retries += 1
                print(f"!!! Playwright 抓取异常: {e}，重试 {retries}/{max_retries}，等待 {backoff}s")
                time.sleep(backoff)
                backoff *= 2
        print(">>> Playwright 模式重试结束，未能成功")
        return None



    # ----------------- Automatic mode -----------------
    async def scrape(self) -> List[Dict]:
        # 1) requests-first, if returns plausible results -> use them
        try:
            res = 0
            if res and len(res) > 0:
                # if counts present (non-zero) -> prefer
                has_counts = any((r.get("likeCount") or r.get("replyCount") or r.get("retweetCount")) for r in res)
                if has_counts:
                    return res
                # else we may want more reliable counts — fallthrough to Playwright
                print(">>> requests 模式返回但互动计数缺失，准备回退 Playwright（若可用）")
        except Exception as e:
            print(f"!!! requests 模式异常：{e}")

        # 2) fallback to Playwright (uses cookies if provided)
        res2 = await self.scrape_with_playwright()
        if res2:
            return res2

        # 3) final fallback: return whatever requests returned (even if missing counts) or empty list
        print(">>> 所有模式均失败或未能获取完整数据，返回空结果或 requests 的部分结果（如果有）")
        final = res if 'res' in locals() and res else []
        return final
