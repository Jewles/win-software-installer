#!/usr/bin/env python3
"""软件安装程序 — 核心模块：自动扫描、静默安装"""

import hashlib
import json
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen

# ── 捆绑/垃圾软件检测特征 ──
BUNDLE_SIGNATURES = [
    {"type": "domain", "patterns": [
        "2345.com", "hao123.com", "duba.net",
        "360.cn", "360safe.com",
    ]},
    {"type": "filename", "patterns": [
        "2345", "hao123", "duba", "kingsoft", "金山",
        "猎豹", "腾讯电脑管家", "360安全卫士", "360软件管家",
        "拼多多", "快手", "头条", "抖音pc版",
    ]},
    {"type": "exact_name", "names": [
        "2345Explorer", "2345Pic", "2345Browser", "2345Pdf",
        "2345好压", "好压", "haozip",
        "电脑管家", "360安全卫士", "360杀毒",
    ]},
]


def check_is_bundle(name: str, filename: str = "") -> bool:
    """检查文件是否属于捆绑/垃圾软件"""
    name_lower = name.lower()
    target = filename.lower() if filename else name_lower

    for sig in BUNDLE_SIGNATURES:
        if sig["type"] == "filename":
            for p in sig["patterns"]:
                if p.lower() in target:
                    return True
        elif sig["type"] == "exact_name":
            for n in sig["names"]:
                if n.lower() == name_lower or name_lower.startswith(n.lower()):
                    return True
    return False


INSTALLER_EXT = {'.exe', '.msi', '.msp'}


# 各类型安装包可尝试的静默参数列表（按优先级自动重试）
SILENT_ARGS_POOL = {
    '.exe': [
        ['/S'],         # Inno Setup / NSIS
        ['/SILENT'],    # Inno Setup 另一种写法
        ['/VERYSILENT'],# Inno Setup 完全静默
        ['/QB'],        # InstallShield 基本静默
    ],
    '.msi': [['/quiet', '/norestart']],
    '.msp': [['/quiet']],
}


@dataclass
class SoftwareItem:
    name: str                  # 取文件名去除扩展名
    filename: str              # 原始文件名
    filepath: Path             # 完整路径
    installer_type: str        # exe / msi
    silent_args: List[str]     # 静默参数（配置或自动推断）
    selected: bool = True      # 默认勾选


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def compute_sha256(file_path: Path) -> str:
    d = hashlib.sha256()
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            d.update(chunk)
    return d.hexdigest()


def download_file(url: str, target_path: Path) -> None:
    req = Request(url=url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=120) as resp:
        with target_path.open("wb") as f:
            while True:
                b = resp.read(256 * 1024)
                if not b:
                    break
                f.write(b)


def run_install(installer_path: Path, silent_args: List[str], timeout_seconds: int) -> subprocess.CompletedProcess:
    cmd = [str(installer_path), *silent_args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_seconds, check=False)


def redact_command(cmd: List[str]) -> str:
    return " ".join(shlex.quote(x) for x in cmd)


def guess_silent_args(ext: str, filename: str = '') -> List[str]:
    """根据扩展名推断静默安装参数（仅返回第一个候选参数）"""
    pool = SILENT_ARGS_POOL.get(ext, [])
    return list(pool[0]) if pool else []


def load_app_items(app_dir: Path) -> List[SoftwareItem]:
    """递归扫描目录（含子目录），列出可安装的软件包"""
    if not app_dir.exists():
        return []
    items: List[SoftwareItem] = []
    for f in sorted(app_dir.rglob('*')):
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        if ext not in INSTALLER_EXT:
            continue
        name = f.stem
        items.append(SoftwareItem(
            name=name,
            filename=f.name,
            filepath=f,
            installer_type='msi' if ext == '.msi' else 'exe',
            silent_args=guess_silent_args(ext, f.name),
        ))
    return items


class InstallRunner:
    """安装执行器"""

    def __init__(self, cache_dir: Path, log_callback=None, progress_callback=None):
        self.cache_dir = cache_dir
        self.log_callback = log_callback or (lambda msg: None)
        self.progress_callback = progress_callback or (lambda cur, total: None)
        ensure_dir(cache_dir)

    def download_once(self, url: str, target: Path) -> str:
        """下载文件，返回 SHA256"""
        self.log_callback(f"  下载 {url}")
        download_file(url, target)
        sha = compute_sha256(target)
        self.log_callback(f"  下载完成 ({target.name}) SHA256: {sha}")
        return sha

    def _try_install(self, item: SoftwareItem, args: List[str]) -> subprocess.CompletedProcess:
        """执行一次安装尝试"""
        cmd_display = redact_command([str(item.filepath), *args])
        self.log_callback(f"  命令: {cmd_display}")
        return run_install(item.filepath, args, 1200)

    def _show_manual_install_dialog(self, item: SoftwareItem, last_error: str) -> None:
        """弹窗通知用户手动安装"""
        try:
            import tkinter.messagebox as mb
            mb.showwarning(
                title=f"{item.name} 安装失败",
                message=(
                    f"{item.name} 自动安装没成功，请手动安装一下~\n\n"
                    f"安装包位置:\n{item.filepath}\n\n"
                    f"最后一次错误: {last_error}"
                )
            )
        except Exception:
            pass  # 没 GUI 环境就不弹

    def install_single(self, item: SoftwareItem) -> Dict[str, Any]:
        """安装单个软件，返回结果字典

        1. 先检测是否是捆绑/垃圾软件
        2. 用默认参数安装
        3. 失败 → 尝试 SILENT_ARGS_POOL 中其他参数（.exe 有多个候选）
        4. 全失败 → 弹窗让用户手动安装
        """
        result: Dict[str, Any] = {
            'name': item.name,
            'status': 'failed',
            'path': str(item.filepath),
            'error': None,
            'exit_code': None,
            'started_at': now_iso(),
            'finished_at': None,
        }
        try:
            self.log_callback(f"▶ [{item.name}] 开始安装")

            # ── 捆绑检测 ──
            if check_is_bundle(item.name, item.filename):
                msg = f"检测到疑似捆绑/垃圾软件: {item.name}"
                self.log_callback(f"  ✗ {msg}")
                result['error'] = msg
                result['status'] = 'blocked_bundle'
                try:
                    import tkinter.messagebox as mb
                    mb.showwarning(
                        "已阻止安装",
                        f"{item.name}\n\n此软件被检测为疑似捆绑/垃圾软件，已阻止安装。"
                    )
                except Exception:
                    pass
                result['finished_at'] = now_iso()
                return result

            ext = item.filepath.suffix.lower()
            args_pool = SILENT_ARGS_POOL.get(ext, [item.silent_args])
            last_error: Optional[str] = None

            for idx, args in enumerate(args_pool):
                tag = "首次" if idx == 0 else f"重试({idx + 1})"
                self.log_callback(f"  [{tag}] 尝试静默安装")
                cp = self._try_install(item, args)
                result['exit_code'] = cp.returncode

                if cp.returncode == 0:
                    result['status'] = 'success'
                    self.log_callback(f"✓ [{item.name}] 安装成功")
                    break
                else:
                    stderr = (cp.stderr or '').strip()
                    last_error = f"exit={cp.returncode}, args={' '.join(args)}"
                    self.log_callback(f"✗ [{item.name}] {tag}失败: {last_error}")

            if result['status'] != 'success':
                result['error'] = last_error
                self.log_callback(f"✗ [{item.name}] 所有静默参数都试过了，放弃自动安装")
                self._show_manual_install_dialog(item, last_error or "未知错误")

        except Exception as e:
            result['error'] = str(e)
            self.log_callback(f"✗ [{item.name}] 异常: {e}")

        result['finished_at'] = now_iso()
        return result