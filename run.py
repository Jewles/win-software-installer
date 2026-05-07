#!/usr/bin/env python3
"""软件安装助手 — 启动入口"""

import sys
import os


def main():
    # 如果是打包后的 exe，且不是管理员，提示用户右键管理员运行
    if sys.platform == 'win32':
        import ctypes
        try:
            is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            is_admin = True

        if not is_admin:
            import tkinter.messagebox
            tkinter.messagebox.showwarning(
                '需要管理员权限',
                '请右键「以管理员身份运行」本程序\n'
                '否则部分软件可能安装失败。'
            )
            # 继续运行，不退出，让用户自行决定

    from src.gui import main as gui_main
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    gui_main()


if __name__ == '__main__':
    main()
