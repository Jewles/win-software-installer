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


INSTALLER_EXT = {'.exe', '.msi', '.msp'}


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


def guess_silent_args(ext: str) -> List[str]:
    """根据扩展名推断静默安装参数"""
    if ext == '.msi':
        return ['/quiet', '/norestart']
    if ext == '.msp':
        return ['/quiet']
    # .exe — 常见打包工具
    return ['/S']  # Inno Setup / NSIS 通用


def load_app_items(app_dir: Path) -> List[SoftwareItem]:
    """扫描 app/ 目录，列出可安装的软件包"""
    if not app_dir.exists():
        return []
    items: List[SoftwareItem] = []
    for f in sorted(app_dir.iterdir()):
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
            silent_args=guess_silent_args(ext),
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

    def install_single(self, item: SoftwareItem) -> Dict[str, Any]:
        """安装单个软件，返回结果字典"""
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
            args = item.silent_args
            cmd_display = redact_command([str(item.filepath), *args])
            self.log_callback(f"  命令: {cmd_display}")

            cp = run_install(item.filepath, args, 1200)
            result['exit_code'] = cp.returncode

            if cp.returncode == 0:
                result['status'] = 'success'
                self.log_callback(f"✓ [{item.name}] 安装成功")
            else:
                stderr = (cp.stderr or '').strip()
                result['error'] = f"exit={cp.returncode}, stderr={stderr[:200]}"
                self.log_callback(f"✗ [{item.name}] 安装失败: {result['error']}")
        except Exception as e:
            result['error'] = str(e)
            self.log_callback(f"✗ [{item.name}] 异常: {e}")

        result['finished_at'] = now_iso()
        return result
