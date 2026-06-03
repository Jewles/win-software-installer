#!/usr/bin/env python3
"""安装程序 GUI — 左侧导航（安装 / 搜索）+ 右侧内容切换"""

import sys
import threading
import webbrowser
from pathlib import Path
from tkinter import Tk, Canvas, Button, Frame, Text, Scrollbar, filedialog, Label, Entry
from typing import List, Optional

from src.core import load_app_items, SoftwareItem, InstallRunner
from src.searcher import background_search, SearchResult


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
    pts = [x1+r, y1, x2-r, y1, x2, y1,
           x2, y1+r, x2, y2-r, x2, y2,
           x2-r, y2, x1+r, y2, x1, y2,
           x1, y2-r, x1, y1+r, x1, y1]
    return canvas.create_polygon(pts, smooth=True, **kw)


class FlatCheckbutton:
    SIZE = 20
    def __init__(self, canvas, x, y, text='', subtext='', checked=True):
        self.canvas = canvas
        self._checked = checked
        self._anim = 1.0 if checked else 0.0
        self._target = self._anim
        self._after = None
        self._box = canvas.create_rectangle(x, y, x+self.SIZE, y+self.SIZE,
            fill='#0078d4' if checked else '#ffffff',
            outline='#0078d4' if checked else '#cccccc', width=1.5)
        self._check = canvas.create_text(x+self.SIZE/2, y+self.SIZE/2,
            text='\u2713' if checked else '', font=('Segoe UI', 11, 'bold'), fill='white')
        self._label = canvas.create_text(x+self.SIZE+8, y+self.SIZE/2-6,
            text=text, font=(FONT[0], 11), fill=TEXT_MAIN, anchor='w')
        self._sub = None
        if subtext:
            self._sub = canvas.create_text(x+self.SIZE+8, y+self.SIZE/2+12,
                text=subtext, font=(FONT[0], 8), fill=TEXT_SEC, anchor='w')
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
        r = int(255-(255-0x00)*self._anim)
        g = int(255-(255-0x78)*self._anim)
        b = int(255-(255-0xD4)*self._anim)
        fill = f'#{r:02x}{g:02x}{b:02x}'
        self.canvas.itemconfig(self._box, fill=fill, outline=ACCENT if self._anim > 0 else '#cccccc')
        self.canvas.itemconfig(self._check, text='\u2713' if self._anim > 0.5 else '')
        if abs(self._anim - self._target) > 0.01:
            self._after = self.canvas.after(16, self._tick)
        else:
            self._anim = self._target
    def set_checked(self, state: bool):
        self._checked = state; self._anim = 1.0 if state else 0.0
        fill = ACCENT if state else '#ffffff'
        self.canvas.itemconfig(self._box, fill=fill, outline=ACCENT if state else '#cccccc')
        self.canvas.itemconfig(self._check, text='\u2713' if state else '')
    @property
    def checked(self): return self._checked
    def destroy(self):
        if self._after: self.canvas.after_cancel(self._after)
        for item in (self._box, self._check, self._label, self._sub):
            if item: self.canvas.delete(item)


class ScrollableCanvas(Frame):
    def __init__(self, parent, **kw):
        super().__init__(parent, **kw)
        bg = kw.get('bg', BG)
        self.canvas = Canvas(self, highlightthickness=0, bg=bg)
        self.vbar = Scrollbar(self, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vbar.set)
        self.vbar.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        self._interior = interior = Frame(self.canvas, bg=bg)
        self._interior_id = self.canvas.create_window((0, 0), window=interior, anchor='nw', tags='interior')
        def _ci(event):
            s = (interior.winfo_reqwidth(), interior.winfo_reqheight())
            self.canvas.configure(scrollregion=(0, 0, *s))
            if interior.winfo_reqwidth() != self.canvas.winfo_width():
                self.canvas.itemconfig(self._interior_id, width=self.canvas.winfo_width())
        interior.bind('<Configure>', _ci)
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfig(self._interior_id, width=e.width))
        self.canvas.bind_all('<MouseWheel>', lambda e: self.canvas.yview_scroll(int(-1*(e.delta/120)), 'units'))
    def interior(self): return self._interior


class InstallGUI:
    def __init__(self, root: Tk):
        self.root = root
        self.root.title(u'\u8f6f\u4ef6\u5b89\u88c5\u52a9\u624b')
        self.root.configure(bg=BG)
        self.root.minsize(820, 560)
        self.root.geometry('900x620')
        ico = Path(__file__).resolve().parent.parent / 'ico' / 'app.ico'
        if ico.exists():
            try: self.root.iconbitmap(str(ico))
            except Exception: pass
        self._app_dir = Path.cwd() / 'app'
        self._items = []
        self._checkboxes = []
        self._running = False
        self._all_checked = True
        self._searching = False

        # ── 左侧导航 ──
        self._sidebar = Frame(self.root, bg=SIDEBAR_BG, width=180)
        self._sidebar.pack(fill='y', side='left'); self._sidebar.pack_propagate(False)
        self._sidebar_title = Canvas(self._sidebar, highlightthickness=0, bg=SIDEBAR_BG, width=180, height=100)
        self._sidebar_title.pack()
        self._sidebar_title.create_text(90, 35, text='\U0001f4e6', font=(FONT[0], 36), fill=SIDEBAR_ACT)
        self._sidebar_title.create_text(90, 70, text=u'\u8f6f\u4ef6\u52a9\u624b', font=(FONT[0], 16, 'bold'), fill=SIDEBAR_ACT)
        self._nav_frame = Frame(self._sidebar, bg=SIDEBAR_BG); self._nav_frame.pack(fill='x', pady=(10,0))
        self._current_page = 'install'; self._nav_buttons = {}; self._nav_indicators = {}
        self._create_nav_button('install', '\U0001f4e6  \u5b89\u88c5\u8f6f\u4ef6', 0)
        self._create_nav_button('search', '\U0001f50d  \u641c\u7d22\u4e0b\u8f7d', 1)
        self._set_active_nav('install')
        self._main_frame = Frame(self.root, bg=BG)
        self._main_frame.pack(fill='both', expand=True, side='right')
        self._install_widgets = []; self._search_widgets = []
        self._build_install_page()
        self.root.after(200, self._safe_scan)

    def _create_nav_button(self, pid, text, idx):
        f = Frame(self._sidebar, bg=SIDEBAR_BG, height=44); f.pack(fill='x', pady=1); f.pack_propagate(False)
        ind = Canvas(f, highlightthickness=0, bg=SIDEBAR_BG, width=4, height=44)
        ind.pack(side='left', fill='y'); ind.create_rectangle(0,4,4,40, fill=SIDEBAR_BG, outline='')
        btn = Button(f, text=text, font=(FONT[0], 12), bg=SIDEBAR_BG, fg=SIDEBAR_TEXT,
                     activebackground='#3a3a3a', activeforeground=SIDEBAR_ACT,
                     relief='flat', bd=0, anchor='w', padx=20, command=lambda p=pid: self._switch_page(p))
        btn.pack(fill='both', expand=True, side='right')
        self._nav_buttons[pid] = btn; self._nav_indicators[pid] = ind

    def _set_active_nav(self, pid):
        for p, b in self._nav_buttons.items():
            b.configure(bg='#3a3a3a' if p==pid else SIDEBAR_BG, fg=SIDEBAR_ACT if p==pid else SIDEBAR_TEXT)
        for p, ind in self._nav_indicators.items():
            ind.delete('all'); ind.create_rectangle(0,4,4,40, fill=ACCENT if p==pid else SIDEBAR_BG, outline='')

    def _switch_page(self, pid):
        if pid==self._current_page: return
        self._current_page=pid; self._set_active_nav(pid)
        for w in self._main_frame.winfo_children(): w.destroy()
        self._install_widgets.clear(); self._search_widgets.clear()
        if pid=='install': self._build_install_page()
        elif pid=='search': self._build_search_page()

    # ═══════════════ 安装页 ═══════════════

    def _build_install_page(self):
        tb = Frame(self._main_frame, bg=BG, height=90); tb.pack(fill='x', side='top'); self._install_widgets.append(tb)
        self._top_canvas = Canvas(tb, highlightthickness=0, bg=BG, height=90)
        self._top_canvas.pack(fill='x', expand=True)
        sf = ScrollableCanvas(self._main_frame, bg=BG)
        sf.pack(fill='both', expand=True, side='top'); self._install_widgets.append(sf)
        self._scroll_frame = sf
        lf = Frame(self._main_frame, bg=LOG_BG, height=80); lf.pack(fill='x', side='bottom'); lf.pack_propagate(False)
        self._install_widgets.append(lf)
        self._log_text = Text(lf, font=LOG_FONT, bg=LOG_BG, fg=LOG_TEXT,
                              relief='flat', bd=0, padx=8, pady=4, wrap='word', state='disabled', height=4)
        self._log_text.pack(fill='both', expand=True)
        bf = Frame(self._main_frame, bg=BG, height=48); bf.pack(fill='x', side='bottom'); bf.pack_propagate(False)
        self._install_widgets.append(bf)
        Button(bf, text=u'\u5168\u9009 / \u53d6\u6d88', font=(FONT[0],11), bg='#e8e8e8',
               fg=TEXT_MAIN, relief='flat', bd=0, padx=12, pady=4,
               activebackground='#d0d0d0', command=self._toggle_all).pack(side='left', padx=(24,8), pady=8)
        Button(bf, text=u'\u9000\u51fa', font=(FONT[0],11), bg='#e8e8e8', fg=TEXT_MAIN,
               relief='flat', bd=0, padx=12, pady=4, activebackground='#d0d0d0',
               command=self.root.destroy).pack(side='right', padx=8, pady=8)
        Button(bf, text='\u25b6  \u5f00\u59cb\u5b89\u88c5', font=(FONT[0],13,'bold'),
               bg=ACCENT, fg='white', relief='flat', bd=0, padx=20, pady=4,
               activebackground='#005a9e', command=self._install).pack(side='right', padx=(8,24), pady=8)
        self._draw_top_bar()

    def _draw_top_bar(self):
        c=self._top_canvas; c.delete('all'); w=c.winfo_width() or 800; cx,cw=16,w-32
        c.create_text(cx,20,text=u'\u9009\u62e9\u8981\u5b89\u88c5\u7684\u8f6f\u4ef6',font=(FONT[0],18,'bold'),fill=TEXT_MAIN,anchor='w')
        py=48
        c.create_text(cx,py,text='\U0001f4c2 \u5b89\u88c5\u5305:',font=(FONT[0],10),fill=TEXT_SEC,anchor='w')
        self._path_text=c.create_text(cx+75,py,text=str(self._app_dir),font=(FONT[0],10),fill=ACCENT,anchor='w')
        btn_h=26; btn_top=py-13; self._top_canvas_width=cw
        _create_rounded_rect(c,cx+cw-175,btn_top,cx+cw-90,btn_top+btn_h,r=5,fill='#e8e8e8',outline='',tags='refresh')
        c.create_text(cx+cw-132,btn_top+btn_h//2,text='\U0001f504 \u5237\u65b0',fill=TEXT_MAIN,font=(FONT[0],10,'bold'),tags='refresh')
        c.tag_bind('refresh','<Button-1>',lambda e:self._scan())
        _create_rounded_rect(c,cx+cw-80,btn_top,cx+cw,btn_top+btn_h,r=5,fill=ACCENT,outline='',tags='browse')
        c.create_text(cx+cw-40,btn_top+btn_h//2,text=u'\u6d4f\u89c8',fill='white',font=(FONT[0],10,'bold'),tags='browse')
        c.tag_bind('browse','<Button-1>',lambda e:self._browse())
        hdr_y=78
        c.create_text(cx+8,hdr_y,text=u'\u8f6f\u4ef6\u540d\u79f0',font=(FONT[0],9,'bold'),fill=TEXT_SEC,anchor='w')
        c.create_text(cx+230,hdr_y,text=u'\u6587\u4ef6\u540d',font=(FONT[0],9,'bold'),fill=TEXT_SEC,anchor='w')
        c.create_text(cx+420,hdr_y,text=u'\u7c7b\u578b',font=(FONT[0],9,'bold'),fill=TEXT_SEC,anchor='w')
        c.create_text(cx+cw-10,hdr_y,text=u'\u5927\u5c0f',font=(FONT[0],9,'bold'),fill=TEXT_SEC,anchor='e')

    def _safe_scan(self):
        self._top_canvas.update_idletasks(); self._draw_top_bar(); self._scan()

    def _scan(self):
        self._log(u'\u626b\u63cf: {}'.format(self._app_dir.resolve()))
        self._items=load_app_items(self._app_dir); self._all_checked=True; self._render_items()
        self._log(u'\u627e\u5230 {} \u4e2a\u5b89\u88c5\u5305'.format(len(self._items)))

    def _render_items(self):
        for cb in self._checkboxes: cb.destroy()
        self._checkboxes.clear()
        interior=self._scroll_frame.interior()
        for w in interior.winfo_children(): w.destroy()
        if not self._items:
            Label(interior,text=u'\u6682\u65e0\u5b89\u88c5\u5305\n\u8bf7\u5c06 .exe/.msi \u653e\u5165 app \u76ee\u5f55\n\u6216\u70b9\u51fb\u5de6\u4fa7\u300c\u641c\u7d22\u4e0b\u8f7d\u300d\u7ebf\u4e0a\u83b7\u53d6',
                  font=(FONT[0],12),fg=TEXT_SEC,bg=BG,justify='center').pack(pady=40)
            return
        rh=48; cw=max(600,self._top_canvas.winfo_width()-32); cw=max(cw,getattr(self,'_top_canvas_width',600))
        for i,item in enumerate(self._items):
            row=Frame(interior,bg='#f5f5f5' if i%2==0 else '#ffffff',height=rh)
            row.pack(fill='x',side='top'); row.pack_propagate(False)
            rc=Canvas(row,highlightthickness=0,bg='#f5f5f5' if i%2==0 else '#ffffff',height=rh)
            rc.pack(fill='both',expand=True)
            sz=self._fmt_size(item.filepath.stat().st_size); tt='MSI' if item.installer_type=='msi' else 'EXE'
            cb=FlatCheckbutton(rc,16,(rh-20)//2,text=item.name,subtext=item.filename)
            self._checkboxes.append(cb)
            rc.create_text(230,rh//2,text=item.filename,font=(FONT[0],9),fill=TEXT_SEC,anchor='w')
            rc.create_text(420,rh//2,text='[{}]'.format(tt),font=(FONT[0],10),fill=ACCENT,anchor='w')
            rc.create_text(cw-10,rh//2,text=sz,font=(FONT[0],10),fill=TEXT_SEC,anchor='e')

    def _log(self,msg):
        if not hasattr(self,'_log_text') or not self._log_text.winfo_exists(): return
        self._log_text.configure(state='normal')
        self._log_text.insert('end',msg+'\n'); self._log_text.see('end')
        self._log_text.configure(state='disabled'); self.root.update_idletasks()

    def _browse(self):
        d=filedialog.askdirectory(initialdir=str(self._app_dir))
        if d: self._app_dir=Path(d); self._draw_top_bar(); self._scan()

    def _toggle_all(self):
        if not self._checkboxes: return
        self._all_checked = not self._all_checked
        for cb in self._checkboxes: cb.set_checked(self._all_checked)

    def _get_selected(self): return [self._items[i] for i,cb in enumerate(self._checkboxes) if cb.checked]

    def _install(self):
        if self._running: return
        sel=self._get_selected()
        if not sel: self._log(u'\u6ca1\u6709\u52fe\u9009\u4efb\u4f55\u8f6f\u4ef6'); return
        if sys.platform!='win32': self._log(u'\u975e Windows \u7cfb\u7edf\uff0c\u65e0\u6cd5\u5b89\u88c5'); return
        self._running=True; threading.Thread(target=self._exec,args=(sel,),daemon=True).start()

    def _exec(self,items):
        runner=InstallRunner(Path.cwd()/'cache',log_callback=self._log)
        ok=fail=0; self._log(u'\u5f00\u59cb {} \u4e2a\u4efb\u52a1'.format(len(items)))
        for i,item in enumerate(items):
            self._log(u'[{}/{}] {}'.format(i+1,len(items),item.name))
            try:
                r=runner.install_single(item)
                if r['status']=='success': ok+=1
                else: fail+=1
            except Exception as e: self._log(u'  \u5f02\u5e38: {}'.format(e)); fail+=1
        self._log(u'\u5b8c\u6210: \u6210\u529f {} / \u5931\u8d25 {} / \u603b\u8ba1 {}'.format(ok,fail,len(items)))
        self._running=False

    # ═══════════════ 搜索页（纯浏览器） ═══════════════

    def _build_search_page(self):
        """浏览器风格搜索页 — 只出结果，每行可点击在浏览器打开"""
        ab=Frame(self._main_frame,bg='#dee1e6',height=46); ab.pack(fill='x',side='top'); self._search_widgets.append(ab)
        ai=Frame(ab,bg='#dee1e6'); ai.pack(expand=True,padx=12,pady=6,fill='x')
        Label(ai,text='\U0001f50d',font=(FONT[0],12),bg='white',fg=TEXT_SEC).pack(side='left')
        self._search_entry=Entry(ai,font=('Segoe UI',11),relief='flat',bd=0,bg='white',fg=TEXT_MAIN,highlightthickness=0)
        self._search_entry.pack(side='left',padx=(4,0),fill='x',expand=True,ipady=4)
        self._search_entry.insert(0,u'\u8f93\u5165\u8f6f\u4ef6\u540d\u79f0\u641c\u7d22\u2026')
        self._search_entry.bind('<FocusIn>',lambda e:self._search_entry.selection_range(0,'end'))
        self._search_entry.bind('<Return>',lambda e:self._do_search())
        Button(ai,text=u'\u641c\u7d22',font=(FONT[0],10,'bold'),bg=ACCENT,fg='white',
               relief='flat',bd=0,padx=14,pady=2,activebackground='#005a9e',
               command=self._do_search).pack(side='left',padx=(6,0))

        self._search_result_frame=ScrollableCanvas(self._main_frame,bg='white')
        self._search_result_frame.pack(fill='both',expand=True,side='top'); self._search_widgets.append(self._search_result_frame)
        self._show_search_homepage()

        sb=Frame(self._main_frame,bg=LOG_BG,height=28); sb.pack(fill='x',side='bottom'); sb.pack_propagate(False)
        self._search_widgets.append(sb)
        self._search_status=Label(sb,text=u'\u5c31\u7eea',font=('Consolas',9),bg=LOG_BG,fg=LOG_TEXT,anchor='w',padx=10)
        self._search_status.pack(fill='both',expand=True)

    def _show_search_homepage(self):
        interior=self._search_result_frame.interior()
        for w in interior.winfo_children(): w.destroy()
        Label(interior,text='\U0001f50d',font=('Segoe UI',48),bg='white',fg='#cccccc').pack(pady=(60,5))
        Label(interior,text=u'\u641c\u7d22\u8f6f\u4ef6',font=('Segoe UI',16,'bold'),bg='white',fg=TEXT_MAIN).pack(pady=(0,5))
        Label(interior,text=u'\u5728\u9876\u680f\u8f93\u5165\u8f6f\u4ef6\u540d\u79f0\uff0c\u56de\u8f66\u641c\u7d22\n\u4f8b\u5982\uff1a\u5fae\u4fe1\u30017zip\u3001vscode\u3001\u9489\u9489\n\n\u70b9\u51fb\u7ed3\u679c\u94fe\u63a5\u5c06\u5728\u6d4f\u89c8\u5668\u4e2d\u6253\u5f00\u4e0b\u8f7d\u9875\n\u4e0b\u8f7d\u540e\u5c06\u5b89\u88c5\u5305\u653e\u5165 app/ \u76ee\u5f55\uff0c\u5207\u5230\u5b89\u88c5\u9875\u5b89\u88c5',
              font=('Segoe UI',10),bg='white',fg=TEXT_SEC,justify='center').pack(pady=(5,30))
        qf=Frame(interior,bg='white'); qf.pack(pady=10)
        for i,n in enumerate([u'\u5fae\u4fe1','QQ',u'\u9489\u9489','chrome','vscode','7zip','potplayer','todesk',u'\u7f51\u6613\u4e91\u97f3\u4e50',u'\u767e\u5ea6\u7f51\u76d8']):
            Button(qf,text=n,font=('Segoe UI',10),bg='#f0f0f0',fg=TEXT_MAIN,relief='flat',bd=0,padx=12,pady=4,
                   activebackground='#e0e0e0',command=lambda x=n:self._quick_search(x)).grid(row=i//5,column=i%5,padx=4,pady=4)

    def _quick_search(self,name):
        self._search_entry.delete(0,'end'); self._search_entry.insert(0,name); self._do_search()

    def _log_search(self,msg):
        if hasattr(self,'_search_status') and self._search_status.winfo_exists():
            self._search_status.configure(text=msg); self.root.update_idletasks()

    def _do_search(self):
        q=self._search_entry.get().strip()
        if not q or q==u'\u8f93\u5165\u8f6f\u4ef6\u540d\u79f0\u641c\u7d22\u2026': return
        if self._searching: return
        self._searching=True; self._log_search(u'\u641c\u7d22: {}'.format(q))
        interior=self._search_result_frame.interior()
        for w in interior.winfo_children(): w.destroy()
        lf=Frame(interior,bg='white'); lf.pack(pady=60)
        Label(lf,text='\u23f3',font=('Segoe UI',36),bg='white',fg='#cccccc').pack()
        Label(lf,text=u'\u6b63\u5728\u641c\u7d22\u2026',font=('Segoe UI',12),bg='white',fg=TEXT_SEC).pack(pady=10)
        background_search(q,callback=self._on_search_done)

    def _on_search_done(self,results):
        self._searching=False; self.root.after(0,lambda:self._render_search_results(results))

    @staticmethod
    def _open_url(url):
        webbrowser.open(url)

    def _render_search_results(self,results):
        interior=self._search_result_frame.interior()
        for w in interior.winfo_children(): w.destroy()
        if not results:
            Label(interior,text=u'\u6ca1\u6709\u627e\u5230\u5339\u914d\u7684\u7ed3\u679c \U0001f641\n\u8bd5\u8bd5\u5176\u4ed6\u5173\u952e\u8bcd\uff0c\u6216\u76f4\u63a5\u53bb\u5b98\u7f51\u4e0b\u8f7d\u540e\u653e\u5230 app/ \u76ee\u5f55',
                  font=('Segoe UI',12),bg='white',fg=TEXT_SEC,justify='center').pack(pady=60)
            self._log_search(u'\u672a\u627e\u5230\u7ed3\u679c'); return
        self._log_search(u'\u627e\u5230 {} \u4e2a\u7ed3\u679c'.format(len(results)))
        cb=Frame(interior,bg='white',height=30); cb.pack(fill='x',padx=20,pady=(10,0)); cb.pack_propagate(False)
        Label(cb,text=u'\u627e\u5230 {} \u4e2a\u7ed3\u679c  \u2014  \u70b9\u51fb\u94fe\u63a5\u5728\u6d4f\u89c8\u5668\u4e2d\u6253\u5f00'.format(len(results)),
              font=('Segoe UI',9),bg='white',fg=TEXT_SEC).pack(side='left')
        src_colors={'可信源':'#00a854','\u817e\u8baf':'#00a854','\u767e\u5ea6\uff1a':'#00a854','Google':'#4285f4','Microsoft':'#00a4ef',
                    '7-Zip':'#0078d4','GitHub':'#24292e','DuckDuckGo':'#de5833'}
        for r in results:
            card=Frame(interior,bg='white',highlightbackground='#e8e8e8',highlightthickness=1,padx=16,pady=10)
            card.pack(fill='x',padx=20,pady=4)
            hdr=Frame(card,bg='white'); hdr.pack(fill='x')
            sc='#888888'
            for k,v in src_colors.items():
                if k in r.source or r.source in k: sc=v; break
            Label(hdr,text='[{}]'.format(r.source),font=('Segoe UI',9,'bold'),bg='white',fg=sc).pack(side='left')
            nl=Label(hdr,text='  {}'.format(r.name[:60]),font=('Segoe UI',11),bg='white',fg=ACCENT,anchor='w',cursor='hand2')
            nl.pack(side='left',fill='x',expand=True)
            nl.bind('<Button-1>',lambda e,url=r.url:self._open_url(url))
            if r.is_bundle:
                Label(hdr,text='\u26a0\ufe0f \u6346\u7ed1\u8f6f\u4ef6',font=('Segoe UI',9,'bold'),bg='#fff3cd',fg='#856404',padx=6).pack(side='right',padx=(0,8))
            scl='#00a854' if r.score>=8 else ('#e68a00' if r.score>=3 else '#888888')
            Label(hdr,text=u'\u8bc4\u5206:{:+d}'.format(r.score),font=('Segoe UI',9),bg='white',fg=scl).pack(side='right',padx=(0,8))
            if r.size_hint:
                Label(hdr,text=r.size_hint,font=('Segoe UI',9),bg='white',fg=TEXT_SEC).pack(side='right',padx=(0,4))
            ur=Frame(card,bg='white'); ur.pack(fill='x',pady=(4,0))
            ut=r.url[:90]+'\u2026' if len(r.url)>90 else r.url
            ul=Label(ur,text=ut,font=('Consolas',8),bg='white',fg='#1a73e8',anchor='w',cursor='hand2')
            ul.pack(side='left',fill='x',expand=True)
            ul.bind('<Button-1>',lambda e,url=r.url:self._open_url(url))

    @staticmethod
    def _fmt_size(b):
        for u in ('B','KB','MB','GB','TB'):
            if b<1024: return '{:.0f} {}'.format(b,u)
            b//=1024
        return '{:.0f} TB'.format(b)


def main():
    root=Tk(); InstallGUI(root); root.mainloop()
if __name__=='__main__': main()