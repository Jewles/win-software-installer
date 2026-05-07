#!/usr/bin/env python3
"""安装程序 GUI — 向日葵风格（左侧导航 + 右内容 + 自绘复选框）"""

import sys
import threading
from pathlib import Path
from tkinter import Tk, Canvas, Button, Frame, Text, filedialog
from typing import List

from src.core import load_app_items, SoftwareItem, InstallRunner


# ── 配色 ──
SIDEBAR_BG   = '#2b2b2b'
SIDEBAR_TEXT = '#cccccc'
SIDEBAR_ACT  = '#ffffff'
ACCENT       = '#0078d4'
BG           = '#f0f0f0'
TEXT_MAIN    = '#222222'
TEXT_SEC     = '#888888'
FONT         = ('Segoe UI', 'Microsoft YaHei', 'sans-serif')
LOG_BG       = '#1e1e1e'
LOG_TEXT     = '#c0c0c0'
LOG_FONT     = ('Consolas', 9)


def _create_rounded_rect(canvas, x1, y1, x2, y2, r=8, **kw):
    """用 polygon 模拟圆角矩形"""
    kw.pop('radius', None)
    pts = [
        x1+r, y1,  x2-r, y1,  x2, y1,
        x2, y1+r,  x2, y2-r,  x2, y2,
        x2-r, y2,  x1+r, y2,  x1, y2,
        x1, y2-r,  x1, y1+r,  x1, y1,
    ]
    return canvas.create_polygon(pts, smooth=True, **kw)


class FlatCheckbutton:
    """自绘复选框 — 点击动画"""
    SIZE = 20

    def __init__(self, canvas, x, y, text='', subtext='', checked=True):
        self.canvas = canvas
        self._checked = checked
        self._anim = 1.0 if checked else 0.0
        self._target = self._anim
        self._after = None

        self._box = canvas.create_rectangle(
            x, y, x + self.SIZE, y + self.SIZE,
            fill='#0078d4' if checked else '#ffffff',
            outline='#0078d4' if checked else '#cccccc', width=1.5,
        )
        self._check = canvas.create_text(
            x + self.SIZE/2, y + self.SIZE/2,
            text='\u2713' if checked else '',
            font=('Segoe UI', 11, 'bold'), fill='white',
        )
        self._label = canvas.create_text(
            x + self.SIZE + 8, y + self.SIZE/2 - 6,
            text=text, font=(FONT[0], 11), fill=TEXT_MAIN, anchor='w',
        )
        self._sub = None
        if subtext:
            self._sub = canvas.create_text(
                x + self.SIZE + 8, y + self.SIZE/2 + 12,
                text=subtext, font=(FONT[0], 8), fill=TEXT_SEC, anchor='w',
            )

        for item in (self._box, self._check, self._label, self._sub):
            if item:
                canvas.tag_bind(item, '<Button-1>', lambda e: self._click())

    def _click(self):
        self._checked = not self._checked
        self._target = 1.0 if self._checked else 0.0
        self._tick()

    def _tick(self):
        step = 0.15
        self._anim += step if self._checked else -step
        self._anim = max(0.0, min(1.0, self._anim))

        r = int(255 - (255 - 0x00) * self._anim)
        g = int(255 - (255 - 0x78) * self._anim)
        b = int(255 - (255 - 0xD4) * self._anim)
        fill = f'#{r:02x}{g:02x}{b:02x}'

        self.canvas.itemconfig(self._box, fill=fill,
                               outline=ACCENT if self._anim > 0 else '#cccccc')
        self.canvas.itemconfig(self._check,
                               text='\u2713' if self._anim > 0.5 else '')

        if abs(self._anim - self._target) > 0.01:
            self._after = self.canvas.after(16, self._tick)
        else:
            self._anim = self._target

    def set_checked(self, state: bool):
        """强制设状态，不用动画"""
        self._checked = state
        self._anim = 1.0 if state else 0.0
        fill = ACCENT if state else '#ffffff'
        self.canvas.itemconfig(self._box, fill=fill,
                               outline=ACCENT if state else '#cccccc')
        self.canvas.itemconfig(self._check,
                               text='\u2713' if state else '')

    @property
    def checked(self):
        return self._checked

    def destroy(self):
        if self._after:
            self.canvas.after_cancel(self._after)
        for item in (self._box, self._check, self._label, self._sub):
            if item:
                self.canvas.delete(item)


class InstallGUI:
    def __init__(self, root: Tk):
        self.root = root
        self.root.title('软件安装助手')
        self.root.configure(bg=BG)
        self.root.minsize(820, 560)
        self.root.geometry('900x620')
        self._log_ids = []
        self._log_texts = []

        ico = Path(__file__).resolve().parent.parent / 'ico' / 'app.ico'
        if ico.exists():
            try:
                self.root.iconbitmap(str(ico))
            except Exception:
                pass

        self._app_dir = Path.cwd() / 'app'
        self._cache_dir = Path.cwd() / 'cache'
        self._items: List[SoftwareItem] = []
        self._checkboxes: List[FlatCheckbutton] = []
        self._running = False
        self._all_checked = True

        # --- 布局：左侧窄导航 + 右侧主区 ---
        # 左边框
        self._sidebar = Frame(self.root, bg=SIDEBAR_BG, width=180)
        self._sidebar.pack(fill='y', side='left')
        self._sidebar.pack_propagate(False)

        self._sidebar_title = Canvas(self._sidebar, highlightthickness=0,
                                     bg=SIDEBAR_BG, width=180, height=130)
        self._sidebar_title.pack()
        self._sidebar_title.create_text(90, 40, text='\U0001f4e6',
                                        font=(FONT[0], 36), fill=SIDEBAR_ACT)
        self._sidebar_title.create_text(90, 100, text='安装助手',
                                        font=(FONT[0], 16, 'bold'), fill=SIDEBAR_ACT)
        self._sidebar_title.create_text(90, 120, text='一键部署工具',
                                        font=(FONT[0], 10), fill=SIDEBAR_TEXT)

        # 主区域（canvas + 底部按钮）
        main_frame = Frame(self.root, bg=BG)
        main_frame.pack(fill='both', expand=True, side='right')

        # Canvas（软件列表）
        self._canvas = Canvas(main_frame, highlightthickness=0, bg=BG)
        self._canvas.pack(fill='both', expand=True, side='top')
        self._canvas.bind('<Configure>', self._on_resize)

        # 日志区（用 Text widget，自带滚动，不受 canvas 清空影响）
        log_frame = Frame(main_frame, bg=LOG_BG, height=80)
        log_frame.pack(fill='x', side='bottom')
        log_frame.pack_propagate(False)

        self._log_text = Text(
            log_frame,
            font=LOG_FONT,
            bg=LOG_BG, fg=LOG_TEXT,
            relief='flat', bd=0,
            padx=8, pady=4,
            wrap='word',
            state='disabled',
            height=4,
        )
        self._log_text.pack(fill='both', expand=True)

        # 底部按钮栏
        self._btn_frame = Frame(main_frame, bg=BG, height=48)
        self._btn_frame.pack(fill='x', side='bottom')
        self._btn_frame.pack_propagate(False)

        btn_sel = Button(
            self._btn_frame, text='全选 / 取消',
            font=(FONT[0], 11), bg='#e8e8e8', fg=TEXT_MAIN,
            relief='flat', bd=0, padx=12, pady=4,
            activebackground='#d0d0d0', command=self._toggle_all,
        )
        btn_sel.pack(side='left', padx=(24, 8), pady=8)

        self._btn_quit = Button(
            self._btn_frame, text='退出',
            font=(FONT[0], 11), bg='#e8e8e8', fg=TEXT_MAIN,
            relief='flat', bd=0, padx=12, pady=4,
            activebackground='#d0d0d0', command=self.root.destroy,
        )
        self._btn_quit.pack(side='right', padx=8, pady=8)

        self._btn_install = Button(
            self._btn_frame, text='\u25b6  开始安装',
            font=(FONT[0], 13, 'bold'), bg=ACCENT, fg='white',
            relief='flat', bd=0, padx=20, pady=4,
            activebackground='#005a9e', command=self._install,
        )
        self._btn_install.pack(side='right', padx=(8, 24), pady=8)

        # 等窗口显示后再扫描
        self.root.after(200, self._safe_scan)

    def _safe_scan(self):
        self._canvas.update_idletasks()
        self._scan()

    def _on_resize(self, event=None):
        self._canvas.delete('all')
        w = self._canvas.winfo_width()
        h = self._canvas.winfo_height()
        if w < 100 or h < 100:
            return
        self._draw(w, h)

    def _draw(self, w, h):
        c = self._canvas
        cx = 16
        cw = w - 32
        self._cx = cx
        self._cw = cw

        # 标题
        c.create_text(cx, 20, text='选择要安装的软件',
                      font=(FONT[0], 18, 'bold'), fill=TEXT_MAIN, anchor='w')

        # 路径行
        py = 48
        c.create_text(cx, py, text='\U0001f4c2 安装包:', font=(FONT[0], 10),
                      fill=TEXT_SEC, anchor='w')
        self._path_text = c.create_text(cx+75, py, text=str(self._app_dir),
                                        font=(FONT[0], 10), fill=ACCENT, anchor='w')

        btn_h = 26
        btn_top = py - btn_h//2

        # 刷新按钮
        _create_rounded_rect(c, cx+cw-175, btn_top, cx+cw-90, btn_top+btn_h,
                             r=5, fill='#e8e8e8', outline='', tags='refresh')
        c.create_text(cx+cw-132, btn_top+btn_h//2, text='\U0001f504 刷新',
                      fill=TEXT_MAIN, font=(FONT[0], 10, 'bold'), tags='refresh')
        c.tag_bind('refresh', '<Button-1>', lambda e: self._scan())

        # 浏览按钮
        _create_rounded_rect(c, cx+cw-80, btn_top, cx+cw, btn_top+btn_h,
                             r=5, fill=ACCENT, outline='', tags='browse')
        c.create_text(cx+cw-40, btn_top+btn_h//2, text='浏览',
                      fill='white', font=(FONT[0], 10, 'bold'), tags='browse')
        c.tag_bind('browse', '<Button-1>', lambda e: self._browse())

        # ── 表头 ──
        col_name  = 8
        col_file  = 230
        col_type  = 420
        col_size_r = -10

        hdr_y = 78
        c.create_text(cx+col_name, hdr_y, text='软件名称', font=(FONT[0], 9, 'bold'),
                      fill=TEXT_SEC, anchor='w')
        c.create_text(cx+col_file, hdr_y, text='文件名', font=(FONT[0], 9, 'bold'),
                      fill=TEXT_SEC, anchor='w')
        c.create_text(cx+col_type, hdr_y, text='类型', font=(FONT[0], 9, 'bold'),
                      fill=TEXT_SEC, anchor='w')
        c.create_text(cx+cw+col_size_r, hdr_y, text='大小', font=(FONT[0], 9, 'bold'),
                      fill=TEXT_SEC, anchor='e')

        # ── 日志区（用 Text widget，底部不再画日志框） ──
        self._list_top = 92
        self._list_bot = h - 10

        self._cols = (col_name, col_file, col_type, col_size_r)
        # 重新渲染列表
        self._render_items()

    def _clear_list(self):
        for cb in self._checkboxes:
            cb.destroy()
        self._checkboxes.clear()
        self._canvas.delete('item*')

    def _render_items(self):
        c = self._canvas
        self._clear_list()
        cx, cw = self._cx, self._cw
        cols = getattr(self, '_cols', (8, 230, 420, -10))
        y = self._list_top
        rh = 48

        if not self._items:
            c.create_text(cx+cw//2, y+60,
                          text='暂无安装包\n请将 .exe/.msi 放入 app 目录',
                          font=(FONT[0], 12), fill=TEXT_SEC,
                          justify='center', tags='item_empty')
            return

        for i, item in enumerate(self._items):
            if y + rh > self._list_bot:
                break
            bg = '#f5f5f5' if i % 2 == 0 else '#ffffff'
            c.create_rectangle(cx, y, cx+cw, y+rh,
                               fill=bg, outline='', tags='item_bg')

            sz = self._fmt_size(item.filepath.stat().st_size)
            tt = 'MSI' if item.installer_type == 'msi' else 'EXE'

            cb = FlatCheckbutton(c, cx+4, y + (rh - 20)//2,
                                 text=item.name, subtext=item.filename)
            self._checkboxes.append(cb)

            # 文件名列
            c.create_text(cx+cols[1], y+rh//2, text=item.filename,
                          font=(FONT[0], 9), fill=TEXT_SEC, anchor='w', tags='item_bg')
            # 类型 + 大小
            c.create_text(cx+cols[2], y+rh//2, text=f'[{tt}]',
                          font=(FONT[0], 10), fill=ACCENT, anchor='w', tags='item_bg')
            c.create_text(cx+cw+cols[3], y+rh//2, text=sz,
                          font=(FONT[0], 10), fill=TEXT_SEC, anchor='e', tags='item_bg')
            y += rh

    def _log(self, msg):
        self._log_text.configure(state='normal')
        self._log_text.insert('end', msg + '\n')
        self._log_text.see('end')
        self._log_text.configure(state='disabled')
        self.root.update_idletasks()

    def _browse(self):
        d = filedialog.askdirectory(initialdir=str(self._app_dir))
        if d:
            self._app_dir = Path(d)
            # 强制重绘 + 扫描
            w = self._canvas.winfo_width()
            h = self._canvas.winfo_height()
            if w > 100 and h > 100:
                self._canvas.delete('all')
                self._draw(w, h)
            self._scan()

    def _scan(self):
        self._log(f'扫描: {self._app_dir.resolve()}')
        self._items = load_app_items(self._app_dir)
        self._all_checked = True
        self._render_items()
        self._log(f'找到 {len(self._items)} 个安装包')
        if self._items and self._checkboxes:
            self._log(f'包名示例: {self._items[0].filename}')

    def _toggle_all(self):
        if not self._checkboxes:
            return
        self._all_checked = not self._all_checked
        for cb in self._checkboxes:
            cb.set_checked(self._all_checked)

    def _get_selected(self):
        return [self._items[i] for i, cb in enumerate(self._checkboxes) if cb.checked]

    def _install(self):
        if self._running:
            return
        sel = self._get_selected()
        if not sel:
            self._log('没有勾选任何软件')
            return
        if sys.platform != 'win32':
            self._log('非 Windows 系统，无法安装')
            return
        self._running = True
        threading.Thread(target=self._exec, args=(sel,), daemon=True).start()

    def _exec(self, items, mock=False):
        runner = InstallRunner(self._cache_dir, log_callback=self._log)
        ok = fail = 0
        self._log(f'开始 {len(items)} 个任务')
        for i, item in enumerate(items):
            self._log(f'[{i+1}/{len(items)}] {item.name}')
            try:
                r = runner.install_single(item)
                if r['status'] == 'success':
                    ok += 1
                else:
                    fail += 1
            except Exception as e:
                self._log(f'  异常: {e}')
                fail += 1
        self._log(f'完成: 成功 {ok} / 失败 {fail} / 总计 {len(items)}')
        self._running = False

    @staticmethod
    def _fmt_size(b):
        for unit in ('B', 'KB', 'MB', 'GB'):
            if b < 1024:
                return f'{b:.0f} {unit}'
            b //= 1024
        return f'{b:.1f} TB'


def main():
    root = Tk()
    InstallGUI(root)
    root.mainloop()


if __name__ == '__main__':
    main()
