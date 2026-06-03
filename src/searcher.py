#!/usr/bin/env python3
"""搜索下载模块 — 可信源 + 搜索引擎 + 域名评分 + 下载校验 + 捆绑检测"""

import hashlib
import re
import json
import threading
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set
from urllib.parse import urlparse, quote
from urllib.request import Request, urlopen

# ═══════════════════════════════════════════════
# 可信软件源数据库（从外部配置文件加载）
# ═══════════════════════════════════════════════

_CONFIG_FILE = Path(__file__).resolve().parent.parent / "config" / "software_sources.json"


def _load_config() -> dict:
    """从配置文件加载可信源和别名"""
    try:
        if _CONFIG_FILE.exists():
            with open(_CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {"软件列表": {}, "别名": {}}


def _build_trusted_sources() -> Dict[str, List[Dict]]:
    """从配置构建 TRUSTED_SOURCES 格式"""
    config = _load_config()
    # 域名 → 来源名映射
    domain_label = {
        "pc.qq.com": "腾讯软件中心",
        "github.com": "GitHub",
        "dingtalk.com": "钉钉官网",
        "google.com": "Google官网",
        "7-zip.org": "7-Zip官网",
        "code.visualstudio.com": "VS Code官网",
        "notepad-plus-plus.org": "Notepad++官网",
        "videolan.org": "VLC官网",
        "obsproject.com": "OBS官网",
        "desktop.telegram.org": "Telegram官网",
        "discord.com": "Discord官网",
        "python.org": "Python官网",
        "git-scm.com": "Git官网",
        "chiark.greenend.org.uk": "PuTTY官网",
        "wireshark.org": "Wireshark官网",
        "blender.org": "Blender官网",
        "gimp.org": "GIMP官网",
        "audacityteam.org": "Audacity官网",
        "ffmpeg.org": "FFmpeg官网",
        "nodejs.org": "Node.js官网",
        "voidtools.com": "Everything官网",
        "bandisoft.com": "Bandisoft官网",
        "geekuninstaller.com": "Geek Uninstaller官网",
        "daum.net": "PotPlayer官网",
        "oray.com": "向日葵官网",
        "todesk.com": "ToDesk官网",
        "163.com": "网易云音乐官网",
        "music.163.com": "网易云音乐官网",
        "wps.com": "WPS官网",
        "pan.baidu.com": "百度网盘官网",
    }
    sources: Dict[str, List[Dict]] = {}
    for name, urls in config.get("软件列表", {}).items():
        items = []
        for url in urls:
            from urllib.parse import urlparse
            domain = urlparse(url).netloc
            source = "可信源"
            for d, label in domain_label.items():
                if d in domain:
                    source = label
                    break
            items.append({"url": url, "source": source})
        sources[name] = items
    return sources


# 全局缓存，启动时加载一次
_TRUSTED_SOURCES = _build_trusted_sources()
_ALIAS_MAP = _load_config().get("别名", {})

# ── 模糊匹配别名 ──
ALIAS_MAP = {
    "wx": "微信", "weixin": "微信", "wechat": "微信",
    "tencent meeting": "腾讯会议", "tencentmeeting": "腾讯会议",
    "wecom": "企业微信", "wxwork": "企业微信",
    "code": "vscode", "visual studio code": "vscode",
    "7z": "7zip",
    "npp": "notepad++",
    "obs studio": "obs", "obs-studio": "obs",
    "tg": "telegram", "电报": "telegram",
    "git scm": "git", "gitbash": "git",
    "winpcap": "wireshark",
    "everything search": "everything",
    "geek uninstall": "geek uninstaller",
    "bandi zip": "bandizip",
    "pot player": "potplayer",
    "sunlogin": "向日葵", "sunlogin client": "向日葵",
    "远程控制": "向日葵",
    "远程桌面": "todesk",
    "netease": "网易云音乐", "cloudmusic": "网易云音乐",
    "baidunetdisk": "百度网盘",
}

# ── 捆绑/垃圾软件检测特征 ──
BUNDLE_SIGNATURES: List[Dict] = [
    # 文件名特征
    {"type": "filename", "patterns": [
        "2345", "hao123", "duba", "kingsoft", "金山", "猎豹",
        "腾讯电脑管家", "360安全卫士", "360软件管家",
        "拼多多", "快手", "头条", "抖音pc版",
    ]},
    # 域名特征
    {"type": "domain", "patterns": [
        "2345.com", "hao123.com", "duba.net",
        "360.cn", "360safe.com",
    ]},
    # 安装包名称（精确）
    {"type": "exact_name", "names": [
        "2345Explorer", "2345Pic", "2345Browser", "2345Pdf",
        "2345好压", "好压", "haozip",
        "电脑管家", "360安全卫士", "360杀毒",
    ]},
]

# ── 可信域名评分 ──
DOMAIN_SCORES = {
    "qq.com": 10, "weixin.qq.com": 10, "tencent.com": 10,
    "microsoft.com": 10, "google.com": 10, "dl.google.com": 10,
    "github.com": 8, "githubusercontent.com": 8,
    "apple.com": 10, "adobe.com": 10,
    "7-zip.org": 10, "7zip.org": 10,
    "notepad-plus-plus.org": 10, "obsproject.com": 10,
    "videolan.org": 10, "telegram.org": 10,
    "python.org": 10, "nodejs.org": 10,
    "blender.org": 10, "gimp.org": 10,
    "wireshark.org": 10, "voidtools.com": 10,
    "bandisoft.com": 10, "daum.net": 10,
    "oray.com": 10, "todesktop.com": 10,
    "ninite.com": 5, "chocolatey.org": 5,
    "126.net": 10, "music.126.com": 10,
    "baidu.com": 3, "pan.baidu.com": 8,
    "onlinedown.net": -3, "crsky.com": -5,
    "xitongcheng.com": -5, "downza.cn": -3,
    "2345.com": -20, "hao123.com": -20, "pc6.com": -5,
}


@dataclass
class SearchResult:
    name: str
    url: str
    snippet: str = ""
    source: str = ""
    score: int = 0
    size_hint: str = ""
    is_bundle: bool = False  # 是否是捆绑/垃圾包


def check_is_bundle(name: str, url: str) -> bool:
    """检查文件是否属于捆绑/垃圾软件"""
    domain = urlparse(url).netloc.lower()
    name_lower = name.lower()

    for sig in BUNDLE_SIGNATURES:
        if sig["type"] == "domain":
            for p in sig["patterns"]:
                if p in domain:
                    return True
        elif sig["type"] == "filename":
            for p in sig["patterns"]:
                if p.lower() in name_lower:
                    return True
        elif sig["type"] == "exact_name":
            for n in sig["names"]:
                if n.lower() == name_lower or name_lower.startswith(n.lower()):
                    return True
    return False


# ── 工具函数 ──

def _compute_sha256(file_path: Path) -> str:
    d = hashlib.sha256()
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            d.update(chunk)
    return d.hexdigest()


def _resolve_download_url(url: str) -> str:
    """追踪重定向，找到真正的下载链接"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        req = Request(url=url, headers=headers)
        req.method = 'HEAD'
        with urlopen(req, timeout=15) as resp:
            return resp.url
    except Exception:
        pass
    try:
        req = Request(url=url, headers=headers)
        with urlopen(req, timeout=15) as resp:
            return resp.url
    except Exception:
        return url


def _download_file(url: str, target_path: Path) -> None:
    domain = urlparse(url).netloc.lower()
    referer_map = {
        "dingtalk.com": "https://www.dingtalk.com/",
        "dtapp-pub.dingtalk.com": "https://page.dingtalk.com/",
        "page.dingtalk.com": "https://www.dingtalk.com/",
        "qq.com": "https://pc.qq.com/",
        "dldir1.qq.com": "https://pc.qq.com/",
        "dldir6.qq.com": "https://pc.qq.com/",
        "tencent.com": "https://meeting.tencent.com/",
        "google.com": "https://www.google.com/chrome/",
        "dl.google.com": "https://www.google.com/chrome/",
        "daumcdn.net": "https://potplayer.daum.net/",
        "126.net": "https://music.163.com/",
    }
    referer = "https://www.google.com/"
    for d, r in referer_map.items():
        if d in domain:
            referer = r
            break

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "Referer": referer,
        "Accept": "application/octet-stream, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    req = Request(url=url, headers=headers)
    with urlopen(req, timeout=120) as resp:
        with target_path.open("wb") as f:
            while True:
                b = resp.read(256 * 1024)
                if not b:
                    break
                f.write(b)


def _score_result(url: str, snippet: str = "") -> int:
    domain = urlparse(url).netloc.lower()
    score = 0
    for known_domain, s in DOMAIN_SCORES.items():
        if known_domain in domain or domain.endswith("." + known_domain):
            score += s
    snippet_lower = snippet.lower()
    bad_words = ["高速下载", "捆绑", "推广", "下载器", "插件包", "破解", "绿色版"]
    for w in bad_words:
        if w in snippet_lower:
            score -= 3
    good_words = ["官方", "正版", "正式版", "官網", "official", "stable", "release"]
    for w in good_words:
        if w in snippet_lower:
            score += 2
    return score


# ── 引擎 1：可信源数据库 ──

def _search_trusted(query: str) -> List[SearchResult]:
    q = query.lower().strip()
    results = []

    # 精确匹配
    for key, items in _TRUSTED_SOURCES.items():
        if q == key or (q in _ALIAS_MAP and _ALIAS_MAP[q].lower() == key):
            for item in items:
                results.append(SearchResult(
                    name=item["url"].split("/")[-1].split("?")[0],
                    url=item["url"],
                    snippet=f"可信源: {item['source']}",
                    source=item["source"],
                    score=10,
                ))
            break

    # 模糊匹配（如果精确匹配没结果）
    if not results:
        for key, items in _TRUSTED_SOURCES.items():
            if q in key or key in q:
                for item in items:
                    results.append(SearchResult(
                        name=item["url"].split("/")[-1].split("?")[0],
                        url=item["url"],
                        snippet=f"可信源: {item['source']}",
                        source=item["source"],
                        score=10,
                    ))

    return results


# ── 引擎 2：GitHub Releases ──

GITHUB_REPO_MAP = {
    "7zip": "ip7z/7zip", "7-zip": "ip7z/7zip",
    "notepad++": "notepad-plus-plus/notepad-plus-plus",
    "obs": "obsproject/obs-studio",
    "vlc": "videolan/vlc",
    "ffmpeg": "BtbN/FFmpeg-Builds",
    "blender": "blender/blender",
    "gimp": "GNOME/gimp",
    "audacity": "audacity/audacity",
    "git": "git-for-windows/git",
    "wireshark": "wireshark/wireshark",
    "aria2": "aria2/aria2",
}

def _search_github_releases(query: str) -> List[SearchResult]:
    q = query.lower().strip()
    if q in ALIAS_MAP:
        q = _ALIAS_MAP[q].lower()
    repo = GITHUB_REPO_MAP.get(q)
    if not repo:
        for key, r in GITHUB_REPO_MAP.items():
            if q in key or key in q:
                repo = r
                break
    if not repo:
        return []
    try:
        req = Request(
            url=f"https://api.github.com/repos/{repo}/releases/latest",
            headers={"User-Agent": "win-software-installer", "Accept": "application/vnd.github+json"},
        )
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        results = []
        for asset in data.get("assets", []):
            name = asset["name"]
            if name.endswith((".exe", ".msi")):
                sz = asset.get("size", 0)
                size_str = f"{sz // 1048576} MB" if sz > 0 else ""
                results.append(SearchResult(
                    name=name,
                    url=asset["browser_download_url"],
                    snippet=f"GitHub Release: {data.get('tag_name', 'latest')}",
                    source="GitHub",
                    score=8,
                    size_hint=size_str,
                ))
        return results
    except Exception:
        return []


# ── 引擎 3：DuckDuckGo ──

def _search_duckduckgo(query: str) -> List[SearchResult]:
    try:
        q = quote(f"{query} official download")
        url = f"https://html.duckduckgo.com/html/?q={q}"
        req = Request(url=url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml",
        })
        with urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        results = []
        for match in re.finditer(
            r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            html, re.DOTALL,
        ):
            href = match.group(1)
            title = re.sub(r"<[^>]+>", "", match.group(2)).strip()
            if any(ext in href.lower() for ext in [".exe", ".msi", ".zip", ".7z"]):
                is_bundle = check_is_bundle(title, href)
                results.append(SearchResult(
                    name=title[:60] if title else href.split("/")[-1],
                    url=href,
                    snippet="DuckDuckGo 搜索结果",
                    source="DuckDuckGo",
                    score=_score_result(href),
                    is_bundle=is_bundle,
                ))
        return results[:5]
    except Exception:
        return []


# ── 合并搜索 ──

def search_all(query: str) -> List[SearchResult]:
    engines = [
        ("可信源", _search_trusted),
        ("GitHub", _search_github_releases),
        ("DuckDuckGo", _search_duckduckgo),
    ]
    all_results = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(fn, query): name for name, fn in engines}
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                for r in fut.result():
                    r.source = name
                    if r.score == 0:
                        r.score = _score_result(r.url, r.snippet)
                    r.is_bundle = r.is_bundle or check_is_bundle(r.name, r.url)
                    all_results.append(r)
            except Exception:
                pass

    seen = set()
    ranked = []
    for r in sorted(all_results, key=lambda x: -x.score):
        if r.url not in seen:
            seen.add(r.url)
            ranked.append(r)
    return ranked[:10]


# ── 弹窗选择 ──

def show_selection_dialog(
    results: List[SearchResult],
    title: str = "选择下载源",
) -> Optional[SearchResult]:
    selected = [None]

    def on_select():
        sel = listbox.curselection()
        if sel:
            selected[0] = results[sel[0]]
        dialog.destroy()

    def on_cancel():
        dialog.destroy()

    dialog = tk.Toplevel()
    dialog.title(title)
    dialog.geometry("700x450")
    dialog.resizable(False, False)

    tk.Label(
        dialog, text="找到以下下载链接，请选择可信的：",
        font=("Microsoft YaHei", 11),
    ).pack(pady=(15, 5))

    frame = tk.Frame(dialog)
    frame.pack(fill="both", expand=True, padx=20, pady=5)

    listbox = tk.Listbox(frame, font=("Consolas", 10), selectmode=tk.SINGLE)
    scrollbar = tk.Scrollbar(frame, orient="vertical", command=listbox.yview)
    listbox.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    listbox.pack(side="left", fill="both", expand=True)

    for i, r in enumerate(results):
        sz = f" {r.size_hint}" if r.size_hint else ""
        bundle_tag = " ⚠️捆绑" if r.is_bundle else ""
        display = f"[{r.source}]{sz:>8} 评分:{r.score:+d}{bundle_tag}  {r.name[:50]}"
        listbox.insert(tk.END, display)

    if results:
        listbox.selection_set(0)
        listbox.activate(0)

    info_var = tk.StringVar()
    if results:
        info_var.set(f"URL: {results[0].url}")

    info_label = tk.Label(
        dialog, textvariable=info_var,
        font=("Consolas", 9), fg="#666666",
        wraplength=650, justify="left",
    )
    info_label.pack(pady=(5, 10), padx=20, fill="x")

    def on_select_item(evt):
        sel = listbox.curselection()
        if sel:
            r = results[sel[0]]
            info_var.set(f"URL: {r.url}")

    listbox.bind("<<ListboxSelect>>", on_select_item)

    btn_frame = tk.Frame(dialog)
    btn_frame.pack(pady=(5, 15))

    tk.Button(
        btn_frame, text="✅ 确认下载", font=("Microsoft YaHei", 11),
        bg="#0078d4", fg="white", padx=20, pady=4, command=on_select,
    ).pack(side="left", padx=10)

    tk.Button(
        btn_frame, text="取消", font=("Microsoft YaHei", 11),
        padx=20, pady=4, command=on_cancel,
    ).pack(side="left", padx=10)

    dialog.transient(dialog.master)
    dialog.grab_set()
    dialog.wait_window()
    return selected[0]


def search_and_select(query: str) -> Optional[str]:
    results = search_all(query)
    if not results:
        return None
    selected = show_selection_dialog(results, f"搜索: {query}")
    return selected.url if selected else None


# ── 下载（到 app 目录）──

def download_to_app(
    url: str,
    app_dir: Path,
    log_callback: Optional[Callable[[str], None]] = None,
) -> Optional[Path]:
    """下载文件到 app 目录（检测捆绑包）"""
    log = log_callback or (lambda msg: None)

    # 如果不是直接 exe 链接，先解析重定向
    resolved_url = url
    if not url.lower().endswith((".exe", ".msi", ".zip", ".7z")):
        log(f"解析下载链接: {url}")
        resolved_url = _resolve_download_url(url)
        if resolved_url != url:
            log(f"重定向到: {resolved_url}")

    filename = resolved_url.split("/")[-1].split("?")[0]
    if not filename or "." not in filename:
        filename = "download.exe"
    target = app_dir / filename

    # 默认检测捆绑
    is_bundle = check_is_bundle(filename, resolved_url)
    if is_bundle:
        log(f"⚠️ 检测到疑似捆绑/垃圾软件: {filename}")
        return None

    log(f"下载: {resolved_url}")
    try:
        _download_file(resolved_url, target)
        sha = _compute_sha256(target)
        log(f"✅ 下载完成: {target.name} | SHA256: {sha[:16]}...")
        return target
    except Exception as e:
        log(f"❌ 下载失败: {e}")
        return None


# ── 后台搜索 ──

def background_search(
    query: str,
    callback: Callable[[List[SearchResult]], None],
    error_callback: Optional[Callable[[str], None]] = None,
) -> threading.Thread:
    def _run():
        try:
            results = search_all(query)
            callback(results)
        except Exception as e:
            if error_callback:
                error_callback(str(e))
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t