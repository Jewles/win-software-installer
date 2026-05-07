#!/usr/bin/env python3
"""安装程序 GUI — 左侧导航 + 右侧可滚动软件列表 + Text 日志"""

import sys
import threading
from pathlib import Path
from tkinter import Tk, Canvas, Button, Frame, Text, Scrollbar, filedialog, Label
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


class ScrollableCanvas(Frame):
    """带垂直滚动条的 Canvas 容器"""

    def __init__(self, parent, **kw):
        super().__init__(parent, **kw)
        self.canvas = Canvas(self, highlightthickness=0, bg=BG)
        self.vbar = Scrollbar(self, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vbar.set)

        self.vbar.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)

        self._interior = interior = Frame(self.canvas, bg=BG)
        self._interior_id = self.canvas.create_window((0, 0), window=interior, anchor='nw', tags='interior')

        def _configure_interior(event):
            size = (interior.winfo_reqwidth(), interior.winfo_reqheight())
            self.canvas.configure(scrollregion=(0, 0, *size))
            if interior.winfo_reqwidth() != self.canvas.winfo_width():
                self.canvas.itemconfig(self._interior_id, width=self.canvas.winfo_width())

        interior.bind('<Configure>', _configure_interior)
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfig(
            self._interior_id, width=e.width))
        # 鼠标滚轮支持
        self.canvas.bind_all('<MouseWheel>', self._on_mousewheel)

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')

    def interior(self):
        return self._interior


class InstallGUI:
    def __init__(self, root: Tk):
        self.root = root
        self.root.title('软件安装助手')
        self.root.configure(bg=BG)
        self.root.minsize(820, 560)
        self.root.geometry('900x620')

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

        # ── 布局 ──
        # 左侧导航
        self._sidebar = Frame(self.root, bg=SIDEBAR_BG, width=180)
        self._sidebar.pack(fill='y', side='left')
        self._sidebar.pack_propagate(False)

        self._sidebar_title = Canvas(self._sidebar, highlightthickness=0,
                                     bg=SIDEBAR_BG, width=180, height=130)
        self._sidebar_title.pack()
        self._sidebar_title.create_text(90, 40, text='\U0001f4e6',
                                        font=(FONT[0], 36), fill=SIDEBAR_ACT)
        self._sidebar_title.create_text(90, 78, text='安装助手',
                                        font=(FONT[0], 16, 'bold'), fill=SIDEBAR_ACT)
        self._sidebar_title.create_text(90, 100, text='一键部署工具',
                                        font=(FONT[0], 10), fill=SIDEBAR_TEXT)

        # 右侧主区域
        main_frame = Frame(self.root, bg=BG)
        main_frame.pack(fill='both', expand=True, side='right')

        # -- 顶部工具栏（标题、路径、刷新、浏览） --
        top_bar = Frame(main_frame, bg=BG, height=90)
        top_bar.pack(fill='x', side='top')

        self._top_canvas = Canvas(top_bar, highlightthickness=0, bg=BG, height=90)
        self._top_canvas.pack(fill='x', expand=True)

        # -- 可滚动的软件列表 --
        self._scroll_frame = ScrollableCanvas(main_frame, bg=BG)
        self._scroll_frame.pack(fill='both', expand=True, side='top')

        # -- 日志区 --
        log_frame = Frame(main_frame, bg=LOG_BG, height=80)
        log_frame.pack(fill='x', side='bottom')
        log_frame.pack_propagate(False)

        self._log_text = Text(
            log_frame, font=LOG_FONT,
            bg=LOG_BG, fg=LOG_TEXT,
            relief='flat', bd=0, padx=8, pady=4,
            wrap='word', state='disabled', height=4,
        )
        self._log_text.pack(fill='both', expand=True)

        # -- 底部按钮栏 --
        self._btn_frame = Frame(main_frame, bg=BG, height=48)
        self._btn_frame.pack(fill='x', side='bottom')
        self._btn_frame.pack_propagate(False)

        Button(self._btn_frame, text='全选 / 取消',
               font=(FONT[0], 11), bg='#e8e8e8', fg=TEXT_MAIN,
               relief='flat', bd=0, padx=12, pady=4,
               activebackground='#d0d0d0', command=self._toggle_all,
               ).pack(side='left', padx=(24, 8), pady=8)

        Button(self._btn_frame, text='退出',
               font=(FONT[0], 11), bg='#e8e8e8', fg=TEXT_MAIN,
               relief='flat', bd=0, padx=12, pady=4,
               activebackground='#d0d0d0', command=self.root.destroy,
               ).pack(side='right', padx=8, pady=8)

        Button(self._btn_frame, text='\u25b6  开始安装',
               font=(FONT[0], 13, 'bold'), bg=ACCENT, fg='white',
               relief='flat', bd=0, padx=20, pady=4,
               activebackground='#005a9e', command=self._install,
               ).pack(side='right', padx=(8, 24), pady=8)

        self._draw_top_bar()
        self.root.after(200, self._safe_scan)

    def _draw_top_bar(self):
        c = self._top_canvas
        c.delete('all')
        w = c.winfo_width()
        if w < 50:
            w = 800
        cx = 16
        cw = w - 32

        c.create_text(cx, 20, text='选择要安装的软件',
                      font=(FONT[0], 18, 'bold'), fill=TEXT_MAIN, anchor='w')

        py = 48
        c.create_text(cx, py, text='\U0001f4c2 安装包:', font=(FONT[0], 10),
                      fill=TEXT_SEC, anchor='w')
        self._path_text = c.create_text(cx+75, py, text=str(self._app_dir),
                                        font=(FONT[0], 10), fill=ACCENT, anchor='w')

        btn_h = 26
        btn_top = py - btn_h//2

        self._top_canvas_width = cw  # 保存供后续刷新

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

        # 表头
        hdr_y = 78
        c.create_text(cx+8, hdr_y, text='软件名称', font=(FONT[0], 9, 'bold'),
                      fill=TEXT_SEC, anchor='w')
        c.create_text(cx+230, hdr_y, text='文件名', font=(FONT[0], 9, 'bold'),
                      fill=TEXT_SEC, anchor='w')
        c.create_text(cx+420, hdr_y, text='类型', font=(FONT[0], 9, 'bold'),
                      fill=TEXT_SEC, anchor='w')
        c.create_text(cx+cw-10, hdr_y, text='大小', font=(FONT[0], 9, 'bold'),
                      fill=TEXT_SEC, anchor='e')

    def _safe_scan(self):
        self._top_canvas.update_idletasks()
        self._draw_top_bar()
        self._scan()

    def _scan(self):
        self._log(f'扫描: {self._app_dir.resolve()}')
        self._items = load_app_items(self._app_dir)
        self._all_checked = True
        self._render_items()
        self._log(f'找到 {len(self._items)} 个安装包')

    def _render_items(self):
        """在可滚动的 interior Frame 里画每一行"""
        # 清空旧的列表
        for cb in self._checkboxes:
            cb.destroy()
        self._checkboxes.clear()
        interior = self._scroll_frame.interior()
        for w in interior.winfo_children():
            w.destroy()

        if not self._items:
            Label(interior, text='暂无安装包\n请将 .exe/.msi 放入 app 目录',
                  font=(FONT[0], 12), fg=TEXT_SEC, bg=BG,
                  justify='center').pack(pady=40)
            return

        # 每个软件一行，用一个 Frame
        rh = 48
        cw = max(600, self._top_canvas.winfo_width() - 32)
        cw = max(cw, getattr(self, '_top_canvas_width', 600))

        for i, item in enumerate(self._items):
            row = Frame(interior, bg='#f5f5f5' if i % 2 == 0 else '#ffffff',
                        height=rh)
            row.pack(fill='x', side='top')
            row.pack_propagate(False)

            # 用 Canvas 画这一行的内容（复选框 + 文字）
            row_canvas = Canvas(row, highlightthickness=0,
                                bg='#f5f5f5' if i % 2 == 0 else '#ffffff',
                                height=rh)
            row_canvas.pack(fill='both', expand=True)

            sz = self._fmt_size(item.filepath.stat().st_size)
            tt = 'MSI' if item.installer_type == 'msi' else 'EXE'

            cb = FlatCheckbutton(row_canvas, 16, (rh - 20)//2,
                                 text=item.name, subtext=item.filename)
            self._checkboxes.append(cb)

            row_canvas.create_text(230, rh//2, text=item.filename,
                                   font=(FONT[0], 9), fill=TEXT_SEC, anchor='w')
            row_canvas.create_text(420, rh//2, text=f'[{tt}]',
                                   font=(FONT[0], 10), fill=ACCENT, anchor='w')
            row_canvas.create_text(cw - 10, rh//2, text=sz,
                                   font=(FONT[0], 10), fill=TEXT_SEC, anchor='e')

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
            self._draw_top_bar()
            self._scan()

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
        for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
            if b < 1024:
                return f'{b:.0f} {unit}'
            b //= 1024
        return f'{b:.0f} TB'


def main():
    root = Tk()
    InstallGUI(root)
    root.mainloop()


if __name__ == '__main__':
    main()
