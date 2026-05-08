# 软件安装助手

新电脑到手后一键安装常用软件。**带图形界面，不用记命令。**

## 使用方法

### 1. 下载安装包

去各软件官网下载 `.exe` 或 `.msi` 安装包，放到 `app/` 目录：

```
sowftware/
├── app/                    ← 你把安装包放这里
│   ├── WeChatWin_4.1.9.exe
│   ├── ChromeSetup.exe
│   └── dingtalk_downloader.exe
```

> 支持任何 .exe / .msi 文件，不做限制，你要装什么就放什么。

### 2. 运行

```bash
python run.py
```

弹出窗口勾选要安装的软件，点「开始安装」。

### 3. 窗口功能

| 功能 | 说明 |
|------|------|
| 🔄 刷新 | 修改了 app/ 目录后刷新列表 |
| 📁 浏览 | 自定义 app/ 目录路径 |
| ✅ 全选/取消 | 一键切换所有勾选状态 |
| 📝 实时日志 | 安装过程实时显示（Text 控件，自动滚动） |
| 🚪 退出 | 关闭程序 |

### 4. 打包成 exe（推荐）

在 Windows 上跑一次（只需一次），以后新电脑直接双击 `.exe`：

```bash
# 安装打包工具
python -m pip install pyinstaller

# 打包（无黑框 + 自定义图标）
pyinstaller --onefile --noconsole --name 安装助手 ^
  --add-data "ico;ico" --icon=ico\app.ico --distpath . run.py
```

如果不需要自定义图标，简化版：

```bash
pyinstaller --onefile --noconsole --name 安装助手 run.py
```

生成 `安装助手.exe`，复制到 U 盘，新电脑上**右键 → 以管理员身份运行**。

> 建议 exe 和 `app/` 文件夹放在 U 盘同一级目录，方便增删安装包。

### 5. Windows 打包注意事项

- **管理员身份运行**：部分软件静默安装需要管理员权限
- app/ 目录保持和 exe 同一层级
- 用 `--noconsole` 避免弹出 CMD 黑框

## 静默参数说明

| 类型 | 默认参数 | 适用 |
|------|----------|------|
| `.exe` | `/S` | Inno Setup / NSIS 打包的安装包（大部分国产软件） |
| `.msi` | `/quiet /norestart` | 微软标准安装包 |
| `.msp` | `/quiet` | 补丁包 |

如果某个软件的静默参数不一样，可以在 `src/core.py` 的 `guess_silent_args()` 里按文件名匹配添加。

## 项目结构

```
sowftware/
├── run.py                  # 启动入口 → 打开 GUI
├── src/
│   ├── core.py             # 核心逻辑（扫描、下载、安装）
│   └── gui.py              # 图形界面
├── app/                    # 你放安装包的地方
├── cache/                  # 自动下载的缓存目录
├── ico/                    # 程序图标
└── REDME.md
```

## 环境要求

- Python 3.8+（使用前安装）
- 或打包后的 `.exe`（零依赖，双击运行）
- Windows 系统（安装需要管理员权限）
