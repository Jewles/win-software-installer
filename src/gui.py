#!/usr/bin/env python3
"""安装程序 GUI — 左侧导航（安装 / 搜索）+ 右侧内容切换"""

import sys
import threading
import tkinter.messagebox as mb
from pathlib import Path
from tkinter import Tk, Canvas, Button, Frame, Text, Scrollbar, filedialog, Label, Entry
from typing import List, Optional

from src.core import load_app_items, SoftwareItem, InstallRunner
from src.searcher import background_search, SearchResult, download_to_app, check_is_bundle


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
        self.canvas.itemconfig(self._check, text='\u2713' if self._anim > 0.5 else '')
        if abs(self._anim - self._target) > 0.01:
            self._after = self.canvas.after(16, self._tick)
        else:
            self._anim = self._target

    def set_checked(self, state: bool):
        self._checked = state
        self._anim = 1.0 if state else 0.0
        fill = ACCENT if state else '#ffffff'
        self.canvas.itemconfig(self._box, fill=fill, outline=ACCENT if state else '#cccccc')
        self.canvas.itemconfig(self._check, text='\u2713' if state else '')

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
    def __init__(self, parent, **kw):
        super().__init__(parent, **kw)
        self.canvas = Canvas(self, highlightthickness=0, bg=kw.get('bg', BG))
        self.vbar = Scrollbar(self, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vbar.set)
        self.vbar.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        self._interior = interior = Frame(self.canvas, bg=kw.get('bg', BG))
        self._interior_id = self.canvas.create_window((0, 0), window=interior, anchor='nw', tags='interior')

        def _configure_interior(event):
            size = (interior.winfo_reqwidth(), interior.winfo_reqheight())
            self.canvas.configure(scrollregion=(0, 0, *size))
            if interior.winfo_reqwidth() != self.canvas.winfo_width():
                self.canvas.itemconfig(self._interior_id, width=self.canvas.winfo_width())

        interior.bind('<Configure>', _configure_interior)
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfig(self._interior_id, width=e.width))
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
        self._searching = False

        # ── 左侧导航 ──
        self._sidebar = Frame(self.root, bg=SIDEBAR_BG, width=180)
        self._sidebar.pack(fill='y', side='left')
        self._sidebar.pack_propagate(False)

        self._sidebar_title = Canvas(self._sidebar, highlightthickness=0,
                                     bg=SIDEBAR_BG, width=180, height=100)
        self._sidebar_title.pack()
        self._sidebar_title.create_text(90, 35, text='\U0001f4e6', font=(FONT[0], 36), fill=SIDEBAR_ACT)
        self._sidebar_title.create_text(90, 70, text='软件助手', font=(FONT[0], 16, 'bold'), fill=SIDEBAR_ACT)

        self._nav_frame = Frame(self._sidebar, bg=SIDEBAR_BG)
        self._nav_frame.pack(fill='x', pady=(10, 0))

        self._current_page = 'install'
        self._nav_buttons = {}
        self._nav_indicators = {}

        self._create_nav_button('install', '\U0001f4e6  安装软件', 0)
        self._create_nav_button('search', '\U0001f50d  搜索下载', 1)
        self._set_active_nav('install')

        self._main_frame = Frame(self.root, bg=BG)
        self._main_frame.pack(fill='both', expand=True, side='right')

        self._install_widgets = []
        self._search_widgets = []

        self._build_install_page()
        self.root.after(200, self._safe_scan)

    def _create_nav_button(self, page_id: str, text: str, index: int):
        frame = Frame(self._sidebar, bg=SIDEBAR_BG, height=44)
        frame.pack(fill='x', pady=1)
        frame.pack_propagate(False)
        indicator = Canvas(frame, highlightthickness=0, bg=SIDEBAR_BG, width=4, height=44)
        indicator.pack(side='left', fill='y')
        indicator.create_rectangle(0, 4, 4, 40, fill=SIDEBAR_BG, outline='')
        btn = Button(frame, text=text, font=(FONT[0], 12),
                     bg=SIDEBAR_BG, fg=SIDEBAR_TEXT,
                     activebackground='#3a3a3a', activeforeground=SIDEBAR_ACT,
                     relief='flat', bd=0, anchor='w', padx=20,
                     command=lambda pid=page_id: self._switch_page(pid))
        btn.pack(fill='both', expand=True, side='right')
        self._nav_buttons[page_id] = btn
        self._nav_indicators[page_id] = indicator

    def _set_active_nav(self, page_id: str):
        for pid, btn in self._nav_buttons.items():
            btn.configure(bg='#3a3a3a' if pid == page_id else SIDEBAR_BG,
                          fg=SIDEBAR_ACT if pid == page_id else SIDEBAR_TEXT)
        for pid, ind in self._nav_indicators.items():
            ind.delete('all')
            ind.create_rectangle(0, 4, 4, 40, fill=ACCENT if pid == page_id else SIDEBAR_BG, outline='')

    def _switch_page(self, page_id: str):
        if page_id == self._current_page:
            return
        self._current_page = page_id
        self._set_active_nav(page_id)
        for w in self._main_frame.winfo_children():
            w.destroy()
        self._install_widgets.clear()
        self._search_widgets.clear()
        if page_id == 'install':
            self._build_install_page()
        elif page_id == 'search':
            self._build_search_page()

    # ═══════════════════════════ 安装页 ═══════════════════════════

    def _build_install_page(self):
        top_bar = Frame(self._main_frame, bg=BG, height=90)
        top_bar.pack(fill='x', side='top')
        self._install_widgets.append(top_bar)

        self._top_canvas = Canvas(top_bar, highlightthickness=0, bg=BG, height=90)
        self._top_canvas.pack(fill='x', expand=True)

        self._scroll_frame = ScrollableCanvas(self._main_frame, bg=BG)
        self._scroll_frame.pack(fill='both', expand=True, side='top')
        self._install_widgets.append(self._scroll_frame)

        log_frame = Frame(self._main_frame, bg=LOG_BG, height=80)
        log_frame.pack(fill='x', side='bottom')
        log_frame.pack_propagate(False)
        self._install_widgets.append(log_frame)

        self._log_text = Text(log_frame, font=LOG_FONT, bg=LOG_BG, fg=LOG_TEXT,
                              relief='flat', bd=0, padx=8, pady=4, wrap='word',
                              state='disabled', height=4)
        self._log_text.pack(fill='both', expand=True)

        btn_frame = Frame(self._main_frame, bg=BG, height=48)
        btn_frame.pack(fill='x', side='bottom')
        btn_frame.pack_propagate(False)
        self._install_widgets.append(btn_frame)

        Button(btn_frame, text='全选 / 取消', font=(FONT[0], 11), bg='#e8e8e8',
               fg=TEXT_MAIN, relief='flat', bd=0, padx=12, pady=4,
               activebackground='#d0d0d0', command=self._toggle_all,
               ).pack(side='left', padx=(24, 8), pady=8)

        Button(btn_frame, text='退出', font=(FONT[0], 11), bg='#e8e8e8',
               fg=TEXT_MAIN, relief='flat', bd=0, padx=12, pady=4,
               activebackground='#d0d0d0', command=self.root.destroy,
               ).pack(side='right', padx=8, pady=8)

        Button(btn_frame, text='\u25b6  开始安装', font=(FONT[0], 13, 'bold'),
               bg=ACCENT, fg='white', relief='flat', bd=0, padx=20, pady=4,
               activebackground='#005a9e', command=self._install,
               ).pack(side='right', padx=(8, 24), pady=8)

        self._draw_top_bar()

    def _draw_top_bar(self):
        c = self._top_canvas
        c.delete('all')
        w = c.winfo_width() or 800
        cx, cw = 16, w - 32
        c.create_text(cx, 20, text='选择要安装的软件', font=(FONT[0], 18, 'bold'), fill=TEXT_MAIN, anchor='w')
        py = 48
        c.create_text(cx, py, text='\U0001f4c2 安装包:', font=(FONT[0], 10), fill=TEXT_SEC, anchor='w')
        self._path_text = c.create_text(cx+75, py, text=str(self._app_dir), font=(FONT[0], 10), fill=ACCENT, anchor='w')
        btn_h = 26
        btn_top = py - btn_h // 2
        self._top_canvas_width = cw
        _create_rounded_rect(c, cx+cw-175, btn_top, cx+cw-90, btn_top+btn_h, r=5, fill='#e8e8e8', outline='', tags='refresh')
        c.create_text(cx+cw-132, btn_top+btn_h//2, text='\U0001f504 刷新', fill=TEXT_MAIN, font=(FONT[0], 10, 'bold'), tags='refresh')
        c.tag_bind('refresh', '<Button-1>', lambda e: self._scan())
        _create_rounded_rect(c, cx+cw-80, btn_top, cx+cw, btn_top+btn_h, r=5, fill=ACCENT, outline='', tags='browse')
        c.create_text(cx+cw-40, btn_top+btn_h//2, text='浏览', fill='white', font=(FONT[0], 10, 'bold'), tags='browse')
        c.tag_bind('browse', '<Button-1>', lambda e: self._browse())
        hdr_y = 78
        c.create_text(cx+8, hdr_y, text='软件名称', font=(FONT[0], 9, 'bold'), fill=TEXT_SEC, anchor='w')
        c.create_text(cx+230, hdr_y, text='文件名', font=(FONT[0], 9, 'bold'), fill=TEXT_SEC, anchor='w')
        c.create_text(cx+420, hdr_y, text='类型', font=(FONT[0], 9, 'bold'), fill=TEXT_SEC, anchor='w')
        c.create_text(cx+cw-10, hdr_y, text='大小', font=(FONT[0], 9, 'bold'), fill=TEXT_SEC, anchor='e')

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
        for cb in self._checkboxes:
            cb.destroy()
        self._checkboxes.clear()
        interior = self._scroll_frame.interior()
        for w in interior.winfo_children():
            w.destroy()
        if not self._items:
            Label(interior, text='暂无安装包\n请将 .exe/.msi 放入 app 目录\n或点击左侧「搜索下载」在线获取',
                  font=(FONT[0], 12), fg=TEXT_SEC, bg=BG, justify='center').pack(pady=40)
            return
        rh = 48
        cw = max(600, self._top_canvas.winfo_width() - 32)
        cw = max(cw, getattr(self, '_top_canvas_width', 600))
        for i, item in enumerate(self._items):
            row = Frame(interior, bg='#f5f5f5' if i % 2 == 0 else '#ffffff', height=rh)
            row.pack(fill='x', side='top')
            row.pack_propagate(False)
            row_canvas = Canvas(row, highlightthickness=0,
                                bg='#f5f5f5' if i % 2 == 0 else '#ffffff', height=rh)
            row_canvas.pack(fill='both', expand=True)
            sz = self._fmt_size(item.filepath.stat().st_size)
            tt = 'MSI' if item.installer_type == 'msi' else 'EXE'
            cb = FlatCheckbutton(row_canvas, 16, (rh - 20)//2, text=item.name, subtext=item.filename)
            self._checkboxes.append(cb)
            row_canvas.create_text(230, rh//2, text=item.filename, font=(FONT[0], 9), fill=TEXT_SEC, anchor='w')
            row_canvas.create_text(420, rh//2, text=f'[{tt}]', font=(FONT[0], 10), fill=ACCENT, anchor='w')
            row_canvas.create_text(cw - 10, rh//2, text=sz, font=(FONT[0], 10), fill=TEXT_SEC, anchor='e')

    def _log(self, msg):
        if not hasattr(self, '_log_text') or not self._log_text.winfo_exists():
            return
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

    # ═══════════════════════════ 搜索页（浏览器风格） ═══════════════════════════

    def _build_search_page(self):
        """浏览器风格搜索页"""
        # 地址栏
        addr_bar = Frame(self._main_frame, bg='#dee1e6', height=46)
        addr_bar.pack(fill='x', side='top')
        self._search_widgets.append(addr_bar)

        addr_inner = Frame(addr_bar, bg='#dee1e6')
        addr_inner.pack(expand=True, padx=12, pady=6, fill='x')

        Label(addr_inner, text='🔍', font=(FONT[0], 12), bg='white', fg=TEXT_SEC).pack(side='left')

        self._search_entry = Entry(addr_inner, font=('Segoe UI', 11), relief='flat', bd=0,
                                    bg='white', fg=TEXT_MAIN, highlightthickness=0)
        self._search_entry.pack(side='left', padx=(4, 0), fill='x', expand=True, ipady=4)
        self._search_entry.insert(0, '输入软件名称搜索…')
        self._search_entry.bind('<FocusIn>', lambda e: self._search_entry.selection_range(0, 'end'))
        self._search_entry.bind('<Return>', lambda e: self._do_search())

        Button(addr_inner, text='搜索', font=(FONT[0], 10, 'bold'),
               bg=ACCENT, fg='white', relief='flat', bd=0, padx=14, pady=2,
               activebackground='#005a9e', command=self._do_search,
               ).pack(side='left', padx=(6, 0))

        # 结果区域
        self._search_result_frame = ScrollableCanvas(self._main_frame, bg='white')
        self._search_result_frame.pack(fill='both', expand=True, side='top')
        self._search_widgets.append(self._search_result_frame)

        # 首页
        self._show_search_homepage()

        # 状态栏
        status_bar = Frame(self._main_frame, bg=LOG_BG, height=28)
        status_bar.pack(fill='x', side='bottom')
        status_bar.pack_propagate(False)
        self._search_widgets.append(status_bar)
        self._search_status = Label(status_bar, text='就绪', font=('Consolas', 9),
                                     bg=LOG_BG, fg=LOG_TEXT, anchor='w', padx=10)
        self._search_status.pack(fill='both', expand=True)

    def _show_search_homepage(self):
        interior = self._search_result_frame.interior()
        for w in interior.winfo_children():
            w.destroy()

        Label(interior, text='🔍', font=('Segoe UI', 48), bg='white', fg='#cccccc').pack(pady=(60, 5))
        Label(interior, text='搜索并下载软件', font=('Segoe UI', 16, 'bold'), bg='white', fg=TEXT_MAIN).pack(pady=(0, 5))
        Label(interior,
              text='在顶栏输入软件名称，回车搜索\n'
                   '例如：微信、7zip、vscode、钉钉、chrome\n\n'
                   '下载的包会自动放到 app/ 目录，下完切到安装页安装',
              font=('Segoe UI', 10), bg='white', fg=TEXT_SEC, justify='center').pack(pady=(5, 30))

        quick_frame = Frame(interior, bg='white')
        quick_frame.pack(pady=10)
        quick_softs = ['微信', 'QQ', '钉钉', 'chrome', 'vscode', '7zip', 'potplayer', 'todesk', '网易云音乐', '百度网盘']
        for i, name in enumerate(quick_softs):
            btn = Button(quick_frame, text=name, font=('Segoe UI', 10), bg='#f0f0f0',
                         fg=TEXT_MAIN, relief='flat', bd=0, padx=12, pady=4,
                         activebackground='#e0e0e0', command=lambda n=name: self._quick_search(n))
            btn.grid(row=i//5, column=i%5, padx=4, pady=4)

    def _quick_search(self, name: str):
        self._search_entry.delete(0, 'end')
        self._search_entry.insert(0, name)
        self._do_search()

    def _log_search(self, msg: str):
        if hasattr(self, '_search_status') and self._search_status.winfo_exists():
            self._search_status.configure(text=msg)
            self.root.update_idletasks()

    def _do_search(self):
        query = self._search_entry.get().strip()
        if not query or query == '输入软件名称搜索…':
            return
        if self._searching:
            return
        self._searching = True
        self._log_search(f'搜索: {query}')

        interior = self._search_result_frame.interior()
        for w in interior.winfo_children():
            w.destroy()

        load_frame = Frame(interior, bg='white')
        load_frame.pack(pady=60)
        Label(load_frame, text='⏳', font=('Segoe UI', 36), bg='white', fg='#cccccc').pack()
        Label(load_frame, text='正在搜索…', font=('Segoe UI', 12), bg='white', fg=TEXT_SEC).pack(pady=10)

        background_search(query, callback=self._on_search_done)

    def _on_search_done(self, results: List[SearchResult]):
        self._searching = False
        self.root.after(0, lambda: self._render_search_results(results))

    def _render_search_results(self, results: List[SearchResult]):
        interior = self._search_result_frame.interior()
        for w in interior.winfo_children():
            w.destroy()

        if not results:
            Label(interior,
                  text='没有找到匹配的结果 🙁\n试试其他关键词，或者直接去官网下载后放到 app/ 目录',
                  font=('Segoe UI', 12), bg='white', fg=TEXT_SEC, justify='center').pack(pady=60)
            self._log_search('未找到结果')
            return

        self._log_search(f'找到 {len(results)} 个结果')

        # 结果计数
        count_bar = Frame(interior, bg='white', height=30)
        count_bar.pack(fill='x', padx=20, pady=(10, 0))
        count_bar.pack_propagate(False)
        Label(count_bar, text=f'找到 {len(results)} 个相关下载',
              font=('Segoe UI', 9), bg='white', fg=TEXT_SEC).pack(side='left')

        # 搜索结果卡片
        source_colors = {
            '可信源': '#00a854', '腾讯官方': '#00a854', 'Google官方': '#4285f4',
            'Microsoft官方': '#00a4ef', '7-Zip官方': '#0078d4',
            'GitHub': '#24292e', 'DuckDuckGo': '#de5833',
            '钉钉官方下载页': '#00a854',
        }

        for i, r in enumerate(results):
            card = Frame(interior, bg='white', highlightbackground='#e8e8e8',
                         highlightthickness=1, padx=16, pady=10)
            card.pack(fill='x', padx=20, pady=4)

            hdr = Frame(card, bg='white')
            hdr.pack(fill='x')

            # 来源标签颜色
            src_clr = '#888888'
            for k, v in source_colors.items():
                if k in r.source or r.source in k:
                    src_clr = v
                    break
            Label(hdr, text=f'[{r.source}]', font=('Segoe UI', 9, 'bold'),
                  bg='white', fg=src_clr).pack(side='left')

            Label(hdr, text=f'  {r.name[:60]}', font=('Segoe UI', 11),
                  bg='white', fg=TEXT_MAIN, anchor='w').pack(side='left', fill='x', expand=True)

            if r.is_bundle:
                Label(hdr, text='⚠️ 捆绑软件', font=('Segoe UI', 9, 'bold'),
                      bg='#fff3cd', fg='#856404', padx=6).pack(side='right', padx=(0, 8))

            score_clr = '#00a854' if r.score >= 8 else ('#e68a00' if r.score >= 3 else '#888888')
            Label(hdr, text=f'评分:{r.score:+d}', font=('Segoe UI', 9),
                  bg='white', fg=score_clr).pack(side='right', padx=(0, 8))

            if r.size_hint:
                Label(hdr, text=r.size_hint, font=('Segoe UI', 9),
                      bg='white', fg=TEXT_SEC).pack(side='right', padx=(0, 4))

            # 第二行：URL + 下载按钮
            url_row = Frame(card, bg='white')
            url_row.pack(fill='x', pady=(4, 0))

            url_text = r.url[:80] + '…' if len(r.url) > 80 else r.url
            Label(url_row, text=url_text, font=('Consolas', 8), bg='white', fg=TEXT_SEC,
                  anchor='w').pack(side='left', fill='x', expand=True)

            Button(url_row, text='⬇ 下载', font=('Segoe UI', 9, 'bold'),
                   bg=ACCENT, fg='white', relief='flat', bd=0, padx=12, pady=2,
                   activebackground='#005a9e',
                   command=lambda res=r: self._download_search_result(res),
                   ).pack(side='right')

    def _download_search_result(self, result: SearchResult):
        """弹窗选目录 → 下载 → 检测捆绑"""
        # 弹窗让用户选下载目录（默认 app/）
        default_dir = str(self._app_dir.resolve())
        download_dir = filedialog.askdirectory(
            initialdir=default_dir,
            title='选择下载保存目录（默认 app/）',
        )
        if not download_dir:
            self._log_search('已取消下载')
            return

        dl_path = Path(download_dir)
        self._log_search(f'下载到: {dl_path}')
        self._log_search(f'下载: {result.name}')

        # 检测捆绑
        if result.is_bundle:
            mb.showwarning('⚠️ 疑似捆绑软件',
                           f'{result.name}\n\n此软件被检测为疑似捆绑/垃圾软件，不建议下载。\n\n来源: {result.source}\nURL: {result.url}')
            self._log_search('已阻止捆绑包下载')
            return

        # 检测评分
        if result.score < 0:
            self._log_search('❌ 评分过低，已阻止下载')
            mb.showwarning('下载被阻止', f'{result.name}\n来源评分过低，可能是垃圾/捆绑软件')
            return

        target = download_to_app(result.url, dl_path, log_callback=self._log_search)
        if target:
            self._log_search(f'✅ {target.name} 已下载到 {dl_path.name}/')
            self._log_search('切换到「安装软件」页勾选安装')
            # 如果下载到了 app/ 目录，自动刷新
            if dl_path.resolve() == self._app_dir.resolve():
                if self._current_page == 'install':
                    self._scan()
        else:
            self._log_search('❌ 下载失败')

    # ═══════════════════════════ 工具方法 ═══════════════════════════

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