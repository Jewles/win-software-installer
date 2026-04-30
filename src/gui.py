#!/usr/bin/env python3
"""安装程序 GUI — 现代风格（ttk + 自定义配色）"""

import sys
import threading
from pathlib import Path
from tkinter import (
    Tk, Canvas, BooleanVar, StringVar,
    filedialog, messagebox, scrolledtext,
)
from tkinter import ttk

from src.core import load_app_items, SoftwareItem, InstallRunner


# ── 配色方案 ──
COLOR = {
    'bg':           '#f5f5f7',
    'surface':      '#ffffff',
    'card_border':  '#e5e5ea',
    'text':         '#1d1d1f',
    'text_sec':     '#86868b',
    'accent':       '#0071e3',
    'accent_hover': '#0061c9',
    'success':      '#34c759',
    'danger':       '#ff3b30',
}

FONT = ('-apple-system', 'Helvetica Neue', 'Segoe UI', 'sans-serif')


def _apply_theme():
    """全局 ttk 样式"""
    from tkinter import ttk
    style = ttk.Style()
    style.theme_use('clam')

    # 按钮
    style.configure('Primary.TButton',
                    font=(FONT[1], 11, 'bold'),
                    foreground='white',
                    background=COLOR['accent'],
                    bordercolor=COLOR['accent'],
                    lightcolor=COLOR['accent'],
                    darkcolor=COLOR['accent'],
                    focuscolor='none',
                    padding=(16, 8))
    style.map('Primary.TButton',
              background=[('active', COLOR['accent_hover'])])

    style.configure('TButton',
                    font=(FONT[1], 11),
                    foreground=COLOR['text'],
                    background=COLOR['surface'],
                    bordercolor=COLOR['card_border'],
                    lightcolor=COLOR['surface'],
                    darkcolor=COLOR['surface'],
                    focuscolor='none',
                    padding=(12, 6))
    style.map('TButton',
              background=[('active', '#f0f0f2')])

    # 复选框
    style.configure('TCheckbutton',
                    font=(FONT[1], 11),
                    background=COLOR['bg'],
                    foreground=COLOR['text'],
                    focuscolor='none')

    # 标签
    style.configure('TLabel',
                    font=(FONT[1], 11),
                    background=COLOR['surface'],
                    foreground=COLOR['text'])
    style.configure('Secondary.TLabel',
                    font=(FONT[1], 9),
                    background=COLOR['surface'],
                    foreground=COLOR['text_sec'])
    style.configure('Title.TLabel',
                    font=(FONT[1], 14, 'bold'),
                    background=COLOR['surface'],
                    foreground=COLOR['text'])

    # 输入框
    style.configure('TEntry',
                    font=(FONT[1], 11),
                    fieldbackground=COLOR['surface'],
                    foreground=COLOR['text'],
                    bordercolor=COLOR['card_border'],
                    padding=(8, 6))

    # 滚动条
    style.configure('Vertical.TScrollbar',
                    background=COLOR['card_border'],
                    troughcolor=COLOR['bg'],
                    bordercolor=COLOR['bg'],
                    arrowcolor=COLOR['text_sec'])


class RoundedFrame(ttk.Frame):
    """卡片容器（用 Canvas 画圆角背景）"""
    def __init__(self, master, radius=12, **kwargs):
        super().__init__(master, **kwargs)
        self.radius = radius
        self._canvas = Canvas(self, highlightthickness=0, bg=COLOR['bg'])
        self._canvas.pack(fill='both', expand=True)
        # 后续内容画在 canvas 上
        self._inner = None

    def add_inner(self):
        self._inner = ttk.Frame(self._canvas)
        self._canvas.create_window((0, 0), window=self._inner, anchor='nw')
        return self._inner

    def render_bg(self, w, h):
        self._canvas.delete('bg')
        self._canvas.create_rounded_rectangle(
            0, 0, w, h, radius=self.radius,
            fill=COLOR['surface'], outline=COLOR['card_border'], tags='bg'
        )

    def pack(self, **kwargs):
        super().pack(**kwargs)
        self.update_idletasks()
        self.render_bg(self.winfo_width(), self.winfo_height())
        self.bind('<Configure>', lambda e: self.render_bg(e.width, e.height))


class InstallGUI:
    def __init__(self, root: Tk):
        self.root = root
        self.root.title('软件安装助手')
        # 图标
        ico_path = Path(__file__).resolve().parent.parent / 'ico' / 'app.ico'
        if ico_path.exists():
            try:
                self.root.iconbitmap(str(ico_path))
            except Exception:
                pass

        self.root.configure(bg=COLOR['bg'])
        self.root.minsize(700, 520)
        self.root.geometry('780x600')

        _apply_theme()
        style = ttk.Style()

        base = Path.cwd()
        self._app_dir_var = StringVar(self.root, str(base / 'app'))
        self._cache_dir_var = StringVar(self.root, str(base / 'cache'))
        self._items: list[SoftwareItem] = []
        self._check_vars: dict[str, BooleanVar] = {}
        self._running = False

        self._build_ui()
        self._load_and_refresh()

    def _build_ui(self):
        style = ttk.Style()
        # ── 顶层容器 ──
        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill='both', expand=True)

        # ── 标题 ──
        title_frame = ttk.Frame(outer)
        title_frame.pack(fill='x', pady=(0, 12))
        ttk.Label(title_frame, text='软件安装助手',
                  style='Title.TLabel').pack(side='left')

        # ── 卡片: 路径设置 ──
        path_card = ttk.LabelFrame(outer, text='路径设置', padding=12)
        path_card.pack(fill='x', pady=(0, 12))

        row1 = ttk.Frame(path_card)
        row1.pack(fill='x', pady=3)
        ttk.Label(row1, text='安装包:', width=8).pack(side='left')
        ttk.Entry(row1, textvariable=self._app_dir_var).pack(side='left', fill='x', expand=True, padx=4)
        ttk.Button(row1, text='浏览', command=lambda: self._pick_dir(self._app_dir_var)).pack(side='right')

        row2 = ttk.Frame(path_card)
        row2.pack(fill='x', pady=3)
        ttk.Label(row2, text='缓存:', width=8).pack(side='left')
        ttk.Entry(row2, textvariable=self._cache_dir_var).pack(side='left', fill='x', expand=True, padx=4)
        ttk.Button(row2, text='浏览', command=lambda: self._pick_dir(self._cache_dir_var)).pack(side='right')

        # ── 卡片: 软件列表 ──
        list_card = ttk.LabelFrame(outer, text='待安装软件', padding=8)
        list_card.pack(fill='both', expand=True, pady=(0, 12))

        # 刷新行
        top_row = ttk.Frame(list_card)
        top_row.pack(fill='x', pady=(0, 6))
        ttk.Button(top_row, text='刷新扫描', command=self._load_and_refresh).pack(side='left')
        ttk.Label(top_row, text='勾选要安装的软件 → 点击开始安装',
                  style='Secondary.TLabel').pack(side='left', padx=10)

        # 滚动列表
        list_canvas = Canvas(list_card, highlightthickness=0, bg=COLOR['surface'])
        scrollbar = ttk.Scrollbar(list_card, orient='vertical', command=list_canvas.yview)
        self._scroll_frame = ttk.Frame(list_canvas)

        self._scroll_frame.bind(
            '<Configure>',
            lambda e: list_canvas.configure(scrollregion=list_canvas.bbox('all'))
        )
        list_canvas.create_window((0, 0), window=self._scroll_frame, anchor='nw')
        list_canvas.configure(yscrollcommand=scrollbar.set)

        list_canvas.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        # Windows 滚轮
        def _on_mw(event):
            list_canvas.yview_scroll(int(-event.delta / 120), 'units')
        list_canvas.bind_all('<MouseWheel>', _on_mw)
        # Linux 滚轮
        list_canvas.bind_all('<Button-4>', lambda e: list_canvas.yview_scroll(-1, 'units'))
        list_canvas.bind_all('<Button-5>', lambda e: list_canvas.yview_scroll(1, 'units'))

        # ── 底部操作栏 ──
        bottom = ttk.Frame(outer)
        bottom.pack(fill='x')

        self._select_all_var = BooleanVar(value=True)
        ttk.Checkbutton(bottom, text='全选/取消', variable=self._select_all_var,
                        command=self._toggle_all).pack(side='left')

        ttk.Button(bottom, text='仅模拟', command=self._mock_only).pack(side='right', padx=4)
        ttk.Button(bottom, text='开始安装', style='Primary.TButton',
                   command=self._start_install).pack(side='right', padx=4)

        # ── 日志 ──
        log_card = ttk.LabelFrame(outer, text='日志', padding=6)
        log_card.pack(fill='x', pady=(0, 0))
        self._log_area = scrolledtext.ScrolledText(
            log_card, height=5, font=('Menlo', 10), wrap='word',
            bg=COLOR['surface'], fg=COLOR['text'],
            relief='flat', borderwidth=0,
            highlightbackground=COLOR['card_border'],
            highlightcolor=COLOR['card_border'],
            highlightthickness=1,
        )
        self._log_area.pack(fill='x')

    # ── 交互 ──
    def _pick_dir(self, var):
        d = filedialog.askdirectory(initialdir=var.get())
        if d:
            var.set(d)
            self._load_and_refresh()

    def _load_and_refresh(self):
        self._log('扫描安装包...')
        app_dir = Path(self._app_dir_var.get())
        self._items = load_app_items(app_dir)

        for w in self._scroll_frame.winfo_children():
            w.destroy()
        self._check_vars.clear()

        if not self._items:
            ttk.Label(self._scroll_frame,
                      text='未找到安装包，将 .exe/.msi 放入 app 目录').pack(pady=30)
            self._log('未找到安装包')
            return

        for item in self._items:
            var = BooleanVar(value=True)
            self._check_vars[item.filename] = var
            row = ttk.Frame(self._scroll_frame)
            row.pack(fill='x', padx=4, pady=2)

            size_str = self._fmt_size(item.filepath.stat().st_size)
            type_tag = 'MSI' if item.installer_type == 'msi' else 'EXE'

            ttk.Checkbutton(row, variable=var).pack(side='left')
            ttk.Label(row, text=item.name, font=(FONT[1], 11, 'bold'),
                      width=20, anchor='w').pack(side='left')
            ttk.Label(row, text=item.filename,
                      style='Secondary.TLabel').pack(side='left', padx=6)
            ttk.Label(row, text=f'[{type_tag}]',
                      foreground=COLOR['accent'],
                      background=COLOR['surface']).pack(side='left')
            ttk.Label(row, text=size_str,
                      style='Secondary.TLabel').pack(side='right')

            # 分割线
            ttk.Separator(self._scroll_frame, orient='horizontal').pack(fill='x', pady=1)

        self._log(f'扫描完成，{len(self._items)} 个安装包')

    def _toggle_all(self):
        v = self._select_all_var.get()
        for var in self._check_vars.values():
            var.set(v)

    def _log(self, msg: str):
        self._log_area.insert('end', msg + '\n')
        self._log_area.see('end')
        self.root.update_idletasks()

    @staticmethod
    def _fmt_size(b: int) -> str:
        for unit in ('B', 'KB', 'MB', 'GB'):
            if b < 1024:
                return f'{b:.0f} {unit}'
            b //= 1024
        return f'{b:.1f} TB'

    def _get_selected(self):
        return [it for it in self._items
                if self._check_vars.get(it.filename, BooleanVar()).get()]

    def _start_install(self):
        if self._running:
            messagebox.showwarning('提示', '正在运行中...')
            return
        sel = self._get_selected()
        if not sel:
            messagebox.showwarning('提示', '请至少勾选一个软件')
            return
        if sys.platform != 'win32':
            messagebox.showwarning('提示', '非 Windows 系统')
            return
        self._running = True
        threading.Thread(target=self._execute, args=(sel,), daemon=True).start()

    def _mock_only(self):
        sel = self._get_selected()
        if not sel:
            messagebox.showwarning('提示', '请至少勾选一个软件')
            return
        self._running = True
        threading.Thread(target=self._execute, args=(sel, True), daemon=True).start()

    def _execute(self, items, mock=False):
        runner = InstallRunner(Path(self._cache_dir_var.get()), log_callback=self._log)
        total = len(items)
        ok = fail = 0

        self._log(f'\n{"="*50}')
        self._log(f'开始 {total} 个任务' + (' (模拟)' if mock else ''))
        self._log(f'{"="*50}')

        for i, item in enumerate(items):
            self._log(f'\n[{i+1}/{total}] {item.name}')
            try:
                if mock:
                    self._log(f' 命令: {item.filepath} {" ".join(item.silent_args)}')
                    self._log(f' 结果: 成功')
                    ok += 1
                else:
                    r = runner.install_single(item)
                    if r['status'] == 'success':
                        ok += 1
                    else:
                        fail += 1
            except Exception as e:
                self._log(f' 异常: {e}')
                fail += 1

        self._log(f'\n完成: 成功 {ok} / 失败 {fail} / 总计 {total}')
        self._running = False


def main():
    root = Tk()
    InstallGUI(root)
    root.mainloop()


if __name__ == '__main__':
    main()
