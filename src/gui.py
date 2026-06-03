#!/usr/bin/env python3
"""软件安装助手 — 左侧导航（安装 / 搜索）+ 右侧内容切换"""

import sys
import threading
import webbrowser
import urllib.parse
from pathlib import Path
from tkinter import Tk, Canvas, Button, Frame, Text, Scrollbar, filedialog, Label, Entry, PanedWindow
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
        self._target = 1.0 if self._checked else 0.0; self._tick()
    def _tick(self):
        step = 0.15
        self._anim += step if self._checked else -step
        self._anim = max(0.0, min(1.0, self._anim))
        r = int(255-(255-0x00)*self._anim); g = int(255-(255-0x78)*self._anim); b = int(255-(255-0xD4)*self._anim)
        fill = f'#{r:02x}{g:02x}{b:02x}'
        self.canvas.itemconfig(self._box, fill=fill, outline=ACCENT if self._anim > 0 else '#cccccc')
        self.canvas.itemconfig(self._check, text='\u2713' if self._anim > 0.5 else '')
        if abs(self._anim - self._target) > 0.01:
            self._after = self.canvas.after(16, self._tick)
        else: self._anim = self._target
    def set_checked(self, state):
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
        self.root.title('软件安装助手')
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

        # ── 左侧导航 ──
        self._sidebar = Frame(self.root, bg=SIDEBAR_BG, width=180)
        self._sidebar.pack(fill='y', side='left'); self._sidebar.pack_propagate(False)
        self._sidebar_title = Canvas(self._sidebar, highlightthickness=0, bg=SIDEBAR_BG, width=180, height=100)
        self._sidebar_title.pack()
        self._sidebar_title.create_text(90, 35, text='\U0001f4e6', font=(FONT[0], 36), fill=SIDEBAR_ACT)
        self._sidebar_title.create_text(90, 70, text='软件助手', font=(FONT[0], 16, 'bold'), fill=SIDEBAR_ACT)
        self._nav_frame = Frame(self._sidebar, bg=SIDEBAR_BG); self._nav_frame.pack(fill='x', pady=(10,0))
        self._current_page = 'install'; self._nav_buttons = {}; self._nav_indicators = {}
        self._create_nav_button('install', '\U0001f4e6  安装软件', 0)
        self._create_nav_button('search', '\U0001f50d  搜索下载', 1)
        self._set_active_nav('install')
        self._main_frame = Frame(self.root, bg=BG)
        self._main_frame.pack(fill='both', expand=True, side='right')
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
        if pid=='install': self._build_install_page()
        elif pid=='search': self._build_search_page()

    # ═══════════════ 安装页 ═══════════════

    def _build_install_page(self):
        # 顶部工具栏
        tb = Frame(self._main_frame, bg=BG, height=90); tb.pack(fill='x', side='top')
        self._top_canvas = Canvas(tb, highlightthickness=0, bg=BG, height=90)
        self._top_canvas.pack(fill='x', expand=True)

        # 中间：可拖拽分割的上下区域（上=软件列表，下=日志）
        pw = PanedWindow(self._main_frame, bg=BG, sashwidth=4, sashrelief='ridge')
        pw.pack(fill='both', expand=True, side='top')

        # 上：软件列表
        sf = ScrollableCanvas(pw, bg=BG)
        pw.add(sf, stretch='always')
        self._scroll_frame = sf

        # 下：日志区（可拖拽缩放）
        lf = Frame(pw, bg=LOG_BG, height=150)
        pw.add(lf, stretch='never')

        self._log_text = Text(lf, font=LOG_FONT, bg=LOG_BG, fg=LOG_TEXT,
                              relief='flat', bd=0, padx=8, pady=4, wrap='word',
                              state='disabled')
        self._log_text.pack(fill='both', expand=True)

        # 底部按钮栏
        bf = Frame(self._main_frame, bg=BG, height=48); bf.pack(fill='x', side='bottom'); bf.pack_propagate(False)
        Button(bf, text='全选 / 取消', font=(FONT[0],11), bg='#e8e8e8',
               fg=TEXT_MAIN, relief='flat', bd=0, padx=12, pady=4,
               activebackground='#d0d0d0', command=self._toggle_all).pack(side='left', padx=(24,8), pady=8)
        Button(bf, text='退出', font=(FONT[0],11), bg='#e8e8e8', fg=TEXT_MAIN,
               relief='flat', bd=0, padx=12, pady=4, activebackground='#d0d0d0',
               command=self.root.destroy).pack(side='right', padx=8, pady=8)
        Button(bf, text='\u25b6  开始安装', font=(FONT[0],13,'bold'),
               bg=ACCENT, fg='white', relief='flat', bd=0, padx=20, pady=4,
               activebackground='#005a9e', command=self._install).pack(side='right', padx=(8,24), pady=8)
        # 确保 Canvas 渲染完毕再画按钮
        self._top_canvas.update_idletasks()
        self._draw_top_bar()

    def _draw_top_bar(self):
        c=self._top_canvas; c.delete('all')
        # 强制刷新 Canvas 获取正确宽度
        c.update_idletasks()
        w=c.winfo_width() or self._main_frame.winfo_width() - 180 or 800
        cx,cw=16,w-32
        c.create_text(cx,20,text='选择要安装的软件',font=(FONT[0],18,'bold'),fill=TEXT_MAIN,anchor='w')
        py=48; btn_h=30
        c.create_text(cx,py,text='\U0001f4c2 安装包:',font=(FONT[0],10),fill=TEXT_SEC,anchor='w')
        self._path_text=c.create_text(cx+75,py,text=str(self._app_dir),font=(FONT[0],10),fill=ACCENT,anchor='w')
        self._top_canvas_width=cw

        # 刷新按钮（用真实 Button，Canvas 绘制的按钮在 Windows 可能不可点击）
        Button(self._top_canvas,text='\U0001f504 刷新',font=(FONT[0],10,'bold'),
               bg='#e8e8e8',fg=TEXT_MAIN,relief='flat',bd=0,padx=10,pady=2,
               activebackground='#d0d0d0',command=self._scan
               ).place(x=cx+cw-170,y=py-btn_h//2,width=85,height=btn_h)

        # 浏览按钮（选择安装包目录）
        Button(self._top_canvas,text='浏览',font=(FONT[0],10,'bold'),
               bg=ACCENT,fg='white',relief='flat',bd=0,padx=10,pady=2,
               activebackground='#005a9e',command=self._browse
               ).place(x=cx+cw-75,y=py-btn_h//2,width=75,height=btn_h)

        hdr_y=78
        c.create_text(cx+8,hdr_y,text='软件名称',font=(FONT[0],9,'bold'),fill=TEXT_SEC,anchor='w')
        c.create_text(cx+230,hdr_y,text='文件名',font=(FONT[0],9,'bold'),fill=TEXT_SEC,anchor='w')
        c.create_text(cx+420,hdr_y,text='类型',font=(FONT[0],9,'bold'),fill=TEXT_SEC,anchor='w')
        c.create_text(cx+cw-10,hdr_y,text='大小',font=(FONT[0],9,'bold'),fill=TEXT_SEC,anchor='e')

    def _safe_scan(self):
        self._top_canvas.update_idletasks(); self._draw_top_bar(); self._scan()

    def _scan(self):
        self._log('扫描: {}'.format(self._app_dir.resolve()))
        self._items=load_app_items(self._app_dir); self._all_checked=True; self._render_items()
        self._log('找到 {} 个安装包'.format(len(self._items)))

    def _render_items(self):
        for cb in self._checkboxes: cb.destroy()
        self._checkboxes.clear()
        interior=self._scroll_frame.interior()
        for w in interior.winfo_children(): w.destroy()
        if not self._items:
            Label(interior,text='暂无安装包\n请用「浏览」按钮选择目录\n或点击左侧「搜索下载」在线获取',
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
        if not sel: self._log('没有勾选任何软件'); return
        if sys.platform!='win32': self._log('非 Windows 系统，无法安装'); return
        self._running=True; threading.Thread(target=self._exec,args=(sel,),daemon=True).start()

    def _exec(self,items):
        runner=InstallRunner(Path.cwd()/'cache',log_callback=self._log)
        ok=fail=0; self._log('开始 {} 个任务'.format(len(items)))
        for i,item in enumerate(items):
            self._log('[{}/{}] {}'.format(i+1,len(items),item.name))
            try:
                r=runner.install_single(item)
                if r['status']=='success': ok+=1
                else: fail+=1
            except Exception as e: self._log('  异常: {}'.format(e)); fail+=1
        self._log('完成: 成功 {} / 失败 {} / 总计 {}'.format(ok,fail,len(items)))
        self._running=False

    # ═══════════════ 搜索页（百度风格） ═══════════════

    def _build_search_page(self):
        interior=self._main_frame
        for w in interior.winfo_children(): w.destroy()
        center=Frame(interior,bg=BG)
        center.place(relx=0.5,rely=0.4,anchor='center')
        Label(center,text='百度',font=('Segoe UI',48,'bold'),
              bg=BG,fg='#4e6ef2').pack(pady=(0,10))
        Label(center,text='搜索下载安装包',font=('Segoe UI',14),
              bg=BG,fg=TEXT_SEC).pack(pady=(0,20))
        sf=Frame(center,bg='white',highlightbackground='#4e6ef2',
                 highlightthickness=2,bd=0)
        sf.pack(fill='x',padx=40)
        self._search_entry=Entry(sf,font=('Segoe UI',14),relief='flat',bd=0,bg='white',
                                  fg=TEXT_MAIN,highlightthickness=0)
        self._search_entry.pack(side='left',padx=(16,8),fill='x',expand=True,ipady=8)
        self._search_entry.bind('<Return>',lambda e:self._baidu_search())
        Button(sf,text='百度一下',font=('Segoe UI',12,'bold'),
               bg='#4e6ef2',fg='white',relief='flat',bd=0,padx=20,pady=6,
               activebackground='#3a57d0',command=self._baidu_search
               ).pack(side='right',padx=(4,4))
        Label(center,
              text='输入软件名称回车 → 百度结果页 → 自行下载安装包\n下载后放到 app/ 目录，切到左侧「安装软件」扫描安装',
              font=('Segoe UI',10),bg=BG,fg=TEXT_SEC,justify='center'
              ).pack(pady=(20,5))
        qf=Frame(interior,bg=BG)
        qf.place(relx=0.5,rely=0.65,anchor='center')
        Label(qf,text='快捷搜索：',font=('Segoe UI',10),bg=BG,fg=TEXT_SEC).pack(side='left',padx=(0,8))
        for name in ['微信','QQ','钉钉','chrome','vscode','7zip','potplayer','todesk']:
            Button(qf,text=name,font=('Segoe UI',10),bg='#e8e8e8',fg=TEXT_MAIN,
                   relief='flat',bd=0,padx=10,pady=3,activebackground='#d0d0d0',
                   command=lambda n=name:self._quick_baidu(n)).pack(side='left',padx=3)
        status=Frame(interior,bg=LOG_BG,height=28)
        status.place(relx=0,rely=1,relwidth=1)
        Label(status,text='安装时自动检测捆绑包',font=('Consolas',9),
              bg=LOG_BG,fg=LOG_TEXT,anchor='w',padx=10).pack(fill='both',expand=True)

    def _quick_baidu(self,name):
        self._search_entry.delete(0,'end')
        self._search_entry.insert(0,name+' 官方下载')
        self._baidu_search()

    def _baidu_search(self):
        q=self._search_entry.get().strip()
        if not q: q='软件下载'
        url='https://www.baidu.com/s?wd='+urllib.parse.quote(q)
        webbrowser.open(url)

    @staticmethod
    def _fmt_size(b):
        for u in ('B','KB','MB','GB','TB'):
            if b<1024: return '{:.0f} {}'.format(b,u)
            b//=1024
        return '{:.0f} TB'.format(b)


def main():
    root=Tk(); InstallGUI(root); root.mainloop()
if __name__=='__main__': main()
