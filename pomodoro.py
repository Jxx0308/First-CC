"""
Pomodoro Timer - 桌面番茄钟
Focus: 25min | Short Break: 5min | Long Break: 15min

程序整体架构：
  1. ConfigManager  —— 读写 pomodoro_config.json 配置文件
  2. PomodoroApp    —— 主应用：Tkinter GUI + 倒计时逻辑 + 番茄循环
"""

import tkinter as tk
from tkinter import ttk, messagebox
import time
import threading
import json
import os
from datetime import datetime

# ── 配置常量 ──────────────────────────────────────────────────────────────
# 配置文件路径：与当前脚本同目录下的 pomodoro_config.json
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pomodoro_config.json")

# 默认配置项（首次运行或配置文件损坏时使用）
DEFAULT_CONFIG = {
    "focus": 25,                  # 专注时长（分钟）
    "short_break": 5,             # 短休息时长（分钟）
    "long_break": 15,             # 长休息时长（分钟）
    "long_break_interval": 4,     # 每完成 N 个专注番茄后触发长休息
    "sound": True,                # 是否播放提示音（预留项）
    "always_on_top": False,       # 窗口是否始终置顶
}

# 界面配色方案（日式侘寂风暖色调）
COLORS = {
    "bg": "#f6f0ec",        # 暖白奶油色背景
    "card": "#eee1d9",      # 暖米色卡片/未选中标签
    "accent": "#c75c4b",    # 陶土红强调色（专注、跳过按钮）
    "accent2": "#d8cfca",   # 暖灰色次要强调色（设置按钮）
    "text": "#5c4e46",      # 暖棕深色主文字
    "text_dim": "#a09890",  # 暖灰色次要文字
    "success": "#8faa8a",   # 鼠尾草绿（休息模式）
    "warning": "#d4a76a",   # 暖琥珀色（重置按钮）
    "border": "#d8cfca",    # 暖灰边框色
}

# 字体定义
FONT_DIGITAL = ("Consolas", 72, "bold")   # 大号数字时钟
FONT_LARGE = ("Segoe UI", 20, "bold")
FONT_MEDIUM = ("Segoe UI", 12)
FONT_SMALL = ("Segoe UI", 10)


# ── 配置管理器 ──────────────────────────────────────────────────────────────
class ConfigManager:
    """负责从 JSON 文件加载、保存用户设置。"""

    def __init__(self):
        # 先复制默认配置，再尝试从文件覆盖
        self.data = dict(DEFAULT_CONFIG)
        self.load()

    def load(self):
        """从磁盘读取配置文件；文件不存在或解析失败则静默使用默认值。"""
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    self.data.update(json.load(f))
            except:
                pass  # 读取失败时不中断程序

    def save(self):
        """将当前配置写回 JSON 文件。"""
        with open(CONFIG_FILE, "w") as f:
            json.dump(self.data, f, indent=2)

    def get(self, key):
        """获取配置项，若缺失则回退到默认值。"""
        return self.data.get(key, DEFAULT_CONFIG[key])

    def set(self, key, value):
        """设置配置项并立即持久化到文件。"""
        self.data[key] = value
        self.save()


# ── 主应用 ────────────────────────────────────────────────────────────────
class PomodoroApp:
    """
    番茄钟主窗口。

    核心状态机：
        focus → (完成) → short_break 或 long_break
        short_break / long_break → (完成) → focus

    计时方式：使用 Tkinter 的 root.after(1000, ...) 每秒回调一次 tick()，
    而非独立线程，避免与 GUI 主线程竞争。
    """

    def __init__(self):
        # 加载用户配置
        self.config = ConfigManager()

        # 创建主窗口
        self.root = tk.Tk()
        self.root.title("🍅 番茄钟")
        self.root.geometry("420x560")
        self.root.configure(bg=COLORS["bg"])
        self.root.resizable(False, False)  # 固定窗口大小

        # 根据配置决定是否置顶
        self.root.attributes("-topmost", self.config.get("always_on_top"))

        # ── 运行时状态 ──────────────────────────────────────────────
        self.mode = "focus"          # 当前模式：focus | short_break | long_break
        self.time_left = self.config.get("focus") * 60  # 剩余秒数
        self.is_running = False      # 计时器是否正在运行
        self.focus_count = 0         # 今日累计完成的专注番茄数
        self.current_session = 0     # 当前周期内已完成的专注次数（用于判断长休息）
        self.thread = None           # 预留字段（当前未使用线程计时）
        self.after_id = None         # after 定时器 ID，用于暂停/取消倒计时

        # 构建界面
        self.setup_ui()

        # 将窗口居中显示到屏幕中央
        self.root.update_idletasks()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")

        # 键盘快捷键绑定
        self.root.bind("<space>", lambda e: self.toggle())           # 空格：开始/暂停
        self.root.bind("<r>", lambda e: self.reset())                # R：重置
        self.root.bind("<Escape>", lambda e: self.minimize_to_tray())  # Esc：最小化
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)     # 关闭按钮

    # ── 界面搭建 ────────────────────────────────────────────────────────
    def setup_ui(self):
        """创建所有 UI 组件：标题、模式标签、圆形计时器、按钮、统计、进度点、设置入口。"""
        # 主画布容器
        self.canvas = tk.Canvas(self.root, bg=COLORS["bg"], highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        # ── 顶部标题 ────────────────────────────────────────────────
        header_frame = tk.Frame(self.canvas, bg=COLORS["bg"])
        header_frame.pack(pady=(20, 0))

        tk.Label(header_frame, text="🍅 番茄钟", font=("Segoe UI", 16, "bold"),
                 fg=COLORS["accent"], bg=COLORS["bg"]).pack()

        # ── 模式切换标签（专注 / 短休 / 长休）──────────────────────
        tab_frame = tk.Frame(self.canvas, bg=COLORS["bg"])
        tab_frame.pack(pady=(15, 0))

        # 当前选中标签高亮为 accent 色，其余为 card 背景
        self.tab_focus = tk.Label(tab_frame, text="  专注  ", font=FONT_MEDIUM,
                                  fg="#ffffff", bg=COLORS["accent"], padx=12, pady=4, cursor="hand2")
        self.tab_focus.pack(side="left", padx=3)
        self.tab_focus.bind("<Button-1>", lambda e: self.switch_mode("focus"))

        self.tab_short = tk.Label(tab_frame, text="  短休  ", font=FONT_MEDIUM,
                                  fg=COLORS["text_dim"], bg=COLORS["card"], padx=12, pady=4, cursor="hand2")
        self.tab_short.pack(side="left", padx=3)
        self.tab_short.bind("<Button-1>", lambda e: self.switch_mode("short_break"))

        self.tab_long = tk.Label(tab_frame, text="  长休  ", font=FONT_MEDIUM,
                                 fg=COLORS["text_dim"], bg=COLORS["card"], padx=12, pady=4, cursor="hand2")
        self.tab_long.pack(side="left", padx=3)
        self.tab_long.bind("<Button-1>", lambda e: self.switch_mode("long_break"))

        # ── 圆形计时器区域 ──────────────────────────────────────────
        self.timer_canvas = tk.Canvas(self.canvas, width=280, height=280,
                                      bg=COLORS["bg"], highlightthickness=0)
        self.timer_canvas.pack(pady=(10, 0))

        self._draw_timer_bg()  # 绘制外圈边框 + 进度弧
        # 中央大号倒计时文字
        self.timer_text = self.timer_canvas.create_text(
            140, 140, text=self._format_time(self.time_left),
            font=FONT_DIGITAL, fill=COLORS["text"], anchor="center"
        )
        # 下方状态文字（如"专注时间 ● 进行中"）
        self.status_text = self.timer_canvas.create_text(
            140, 190, text="准备开始",
            font=FONT_MEDIUM, fill=COLORS["text_dim"], anchor="center"
        )

        # ── 控制按钮：开始/暂停、重置、跳过 ─────────────────────────
        btn_frame = tk.Frame(self.canvas, bg=COLORS["bg"])
        btn_frame.pack(pady=(5, 0))

        self.btn_toggle = self._make_button(btn_frame, "▶  开始", self.toggle,
                                            COLORS["success"], width=10, fg="#ffffff")
        self.btn_toggle.pack(side="left", padx=6)

        self.btn_reset = self._make_button(btn_frame, "↺  重置", self.reset,
                                           COLORS["warning"], width=10)
        self.btn_reset.pack(side="left", padx=6)

        self.btn_skip = self._make_button(btn_frame, "⏭  跳过", self.skip,
                                          COLORS["accent"], width=10, fg="#ffffff")
        self.btn_skip.pack(side="left", padx=6)

        # ── 今日完成番茄数统计 ──────────────────────────────────────
        stats_frame = tk.Frame(self.canvas, bg=COLORS["bg"])
        stats_frame.pack(pady=(20, 0))

        self.stats_label = tk.Label(stats_frame, text="今日完成: 0 个番茄",
                                    font=FONT_MEDIUM, fg=COLORS["text_dim"], bg=COLORS["bg"])
        self.stats_label.pack()

        # ── 周期进度圆点（每完成一个专注点亮一个点）──────────────────
        self.dots_frame = tk.Frame(self.canvas, bg=COLORS["bg"])
        self.dots_frame.pack(pady=(8, 0))
        self.dots = []
        self._draw_progress_dots()

        # ── 底部：快捷键提示 + 设置按钮 ─────────────────────────────
        bottom_frame = tk.Frame(self.canvas, bg=COLORS["bg"])
        bottom_frame.pack(side="bottom", pady=(0, 15))

        tk.Label(bottom_frame, text="空格=开始/暂停  R=重置",
                 font=FONT_SMALL, fg=COLORS["text_dim"], bg=COLORS["bg"]).pack(side="left", padx=10)
        self._make_button(bottom_frame, "⚙", self.open_settings,
                          COLORS["accent2"], width=3, height=1).pack(side="left")

    def _draw_timer_bg(self):
        """绘制计时器背景：静态圆环边框 + 可动态更新的进度弧（arc）。"""
        # 外圈灰色边框
        self.timer_canvas.create_oval(20, 20, 260, 260,
                                      outline=COLORS["border"], width=4)
        # 进度弧：从 12 点方向（start=90）顺时针绘制，extent 表示已走过的角度
        self.progress_arc = self.timer_canvas.create_arc(
            20, 20, 260, 260, start=90, extent=360,
            outline=COLORS["accent"], width=5, style="arc"
        )

    def _draw_progress_dots(self):
        """根据 long_break_interval 配置绘制周期进度圆点。"""
        # 清空旧圆点
        for w in self.dots_frame.winfo_children():
            w.destroy()
        self.dots = []
        interval = self.config.get("long_break_interval")
        for i in range(interval):
            dot = tk.Canvas(self.dots_frame, width=16, height=16,
                            bg=COLORS["bg"], highlightthickness=0)
            dot.create_oval(2, 2, 14, 14, fill=COLORS["card"],
                            outline=COLORS["border"], width=1)
            dot.pack(side="left", padx=4)
            self.dots.append(dot)

    def _make_button(self, parent, text, command, color, width=8, height=1, fg=None):
        """统一风格的扁平化按钮工厂方法。"""
        if fg is None:
            fg = COLORS["text"]
        return tk.Button(parent, text=text, command=command,
                         font=FONT_MEDIUM, bg=color, fg=fg,
                         activebackground=color, activeforeground=fg,
                         bd=0, padx=12, pady=6 if height > 1 else 4,
                         width=width, cursor="hand2",
                         relief="flat", highlightthickness=0,
                         borderwidth=0)

    # ── 计时核心逻辑 ─────────────────────────────────────────────────────
    def _format_time(self, seconds):
        """将秒数格式化为 MM:SS 字符串。"""
        m = seconds // 60
        s = seconds % 60
        return f"{m:02d}:{s:02d}"

    def get_duration(self):
        """根据当前模式返回该阶段的完整时长（秒）。"""
        if self.mode == "focus":
            return self.config.get("focus") * 60
        elif self.mode == "short_break":
            return self.config.get("short_break") * 60
        else:
            return self.config.get("long_break") * 60

    def get_mode_label(self):
        """返回当前模式的中文显示名称。"""
        labels = {
            "focus": "专注时间",
            "short_break": "短休息",
            "long_break": "长休息",
        }
        return labels.get(self.mode, "")

    def update_display(self):
        """刷新所有与计时相关的 UI：数字、进度弧、状态文字、标签高亮。"""
        # 更新中央倒计时数字
        self.timer_canvas.itemconfig(self.timer_text,
                                     text=self._format_time(self.time_left))

        # 更新圆形进度弧：已消耗时间占比 × 360°
        total = self.get_duration()
        if total > 0:
            progress = (total - self.time_left) / total * 360
            # 专注模式用红色，休息模式用绿色
            color = COLORS["accent"] if self.mode == "focus" else COLORS["success"]
            self.timer_canvas.itemconfig(self.progress_arc,
                                         extent=progress, outline=color)

        # 更新状态文字
        status = self.get_mode_label()
        if self.is_running:
            status += " ● 进行中"
        else:
            # 若剩余时间小于总时长，说明曾开始过 → 显示"已暂停"；否则"等待开始"
            status += " ● 已暂停" if self.time_left < self.get_duration() else " ● 等待开始"
        self.timer_canvas.itemconfig(self.status_text, text=status)

        # 高亮当前模式对应的标签页
        for tab, mode in [(self.tab_focus, "focus"),
                          (self.tab_short, "short_break"),
                          (self.tab_long, "long_break")]:
            if mode == self.mode:
                tab.config(fg="#ffffff", bg=COLORS["accent"])
            else:
                tab.config(fg=COLORS["text_dim"], bg=COLORS["card"])

    def tick(self):
        """
        每秒执行一次的倒计时回调（由 root.after 调度）。

        流程：is_running 为真且 time_left > 0 → 减 1 秒并继续调度；
              time_left 归零 → 调用 time_complete() 处理阶段切换。
        """
        if not self.is_running:
            return
        if self.time_left > 0:
            self.time_left -= 1
            self.update_display()
            # 1000ms 后再次调用自身，形成链式定时器
            self.after_id = self.root.after(1000, self.tick)
        else:
            self.time_complete()

    def time_complete(self):
        """
        当前阶段计时结束时的处理逻辑。

        1. 停止计时器
        2. 若是专注模式：累计番茄数、更新统计
        3. 闪烁窗口 + 系统提示音
        4. 自动切换到下一阶段（专注→短休/长休，休息→专注）
        """
        self.is_running = False
        self.update_display()

        if self.mode == "focus":
            self.focus_count += 1           # 今日总番茄数 +1
            self.current_session += 1       # 当前周期内专注次数 +1
            self.stats_label.config(text=f"今日完成: {self.focus_count} 个番茄")
            self._draw_progress_dots()    # 刷新进度圆点

        self.flash_window()  # 视觉闪烁提醒
        self.notify()        # 系统铃声 + 短暂置顶

        # 自动切换到下一阶段
        self.root.bell()
        if self.mode == "focus":
            # 达到长休息间隔 → 长休息；否则 → 短休息
            if self.current_session >= self.config.get("long_break_interval"):
                self.switch_mode("long_break")
            else:
                self.switch_mode("short_break")
        else:
            # 休息结束 → 回到专注
            self.switch_mode("focus")
        self.update_display()

    def toggle(self):
        """开始/暂停切换。空格键和"开始"按钮均调用此方法。"""
        self.is_running = not self.is_running
        if self.is_running:
            self.btn_toggle.config(text="⏸  暂停", fg="#ffffff")
            self.tick()  # 启动倒计时链
        else:
            self.btn_toggle.config(text="▶  开始", fg="#ffffff")
            # 取消已排队的 after 回调，真正暂停计时
            if self.after_id:
                self.root.after_cancel(self.after_id)
                self.after_id = None

    def reset(self):
        """重置当前阶段：停止计时，剩余时间恢复为完整时长。"""
        self.is_running = False
        if self.after_id:
            self.root.after_cancel(self.after_id)
            self.after_id = None
        self.time_left = self.get_duration()
        self.btn_toggle.config(text="▶  开始", fg="#ffffff")
        self.update_display()

    def skip(self):
        """跳过当前阶段：确认后将 time_left 置 0，触发 time_complete 自动切换。"""
        if messagebox.askyesno("跳过", f"确定跳过当前{self.get_mode_label()}吗？",
                               parent=self.root):
            self.is_running = False
            if self.after_id:
                self.root.after_cancel(self.after_id)
                self.after_id = None
            self.time_left = 0
            self.time_complete()

    def switch_mode(self, mode):
        """
        手动或自动切换模式（专注/短休/长休）。

        切换时会：停止计时、重置剩余时间、刷新 UI。
        切回专注模式时，current_session 归零，开始新的番茄周期。
        """
        self.mode = mode
        if self.after_id:
            self.root.after_cancel(self.after_id)
            self.after_id = None
        self.is_running = False
        self.time_left = self.get_duration()
        self.btn_toggle.config(text="▶  开始", fg="#ffffff")
        self._draw_progress_dots()
        self.update_display()

        # 回到专注模式 = 新周期开始，重置周期内计数
        if mode == "focus":
            self.current_session = 0

    def notify(self):
        """计时结束通知：短暂置顶窗口以吸引注意，并播放系统铃声。"""
        self.root.attributes("-topmost", True)
        self.root.attributes("-topmost", self.config.get("always_on_top"))
        self.root.bell()

    def flash_window(self):
        """计时器画布背景红闪 3 次，提供视觉反馈（会阻塞约 0.6 秒）。"""
        for _ in range(3):
            self.timer_canvas.configure(bg=COLORS["accent"])
            self.root.update()
            time.sleep(0.1)
            self.timer_canvas.configure(bg=COLORS["bg"])
            self.root.update()
            time.sleep(0.1)

    def minimize_to_tray(self):
        """Esc 键：最小化窗口到任务栏（未实现系统托盘图标）。"""
        self.root.iconify()

    def on_closing(self):
        """关闭窗口前：若正在计时则二次确认；保存配置后销毁窗口。"""
        if self.is_running:
            if not messagebox.askyesno("退出", "番茄钟正在运行，确定退出吗？", parent=self.root):
                return
        self.config.save()
        self.root.destroy()

    # ── 设置对话框 ─────────────────────────────────────────────────────────
    def open_settings(self):
        """弹出模态设置窗口，可修改各阶段时长、长休间隔、置顶选项。"""
        win = tk.Toplevel(self.root)
        win.title("设置")
        win.geometry("360x320")
        win.configure(bg=COLORS["bg"])
        win.transient(self.root)  # 设为子窗口
        win.grab_set()            # 模态：锁定焦点

        # 相对主窗口居中
        win.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - 360) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 320) // 2
        win.geometry(f"+{x}+{y}")

        # 可编辑的配置字段：(键名, 显示标签, 默认值)
        fields = [
            ("focus", "专注时间 (分钟)", 25),
            ("short_break", "短休时间 (分钟)", 5),
            ("long_break", "长休时间 (分钟)", 15),
            ("long_break_interval", "长休间隔 (番茄数)", 4),
        ]

        entries = {}
        for i, (key, label, default) in enumerate(fields):
            tk.Label(win, text=label, font=FONT_MEDIUM,
                     fg=COLORS["text"], bg=COLORS["bg"]).grid(
                         row=i, column=0, sticky="w", padx=20, pady=(12, 2))
            var = tk.StringVar(value=str(self.config.get(key)))
            entries[key] = var
            tk.Spinbox(win, from_=1, to=99, textvariable=var,
                       font=FONT_MEDIUM, width=8,
                       bg=COLORS["card"], fg=COLORS["text"],
                       buttonbg=COLORS["accent2"],
                       bd=0, relief="flat",
                       highlightthickness=0).grid(
                           row=i, column=1, padx=20, pady=(12, 2))

        # "置顶显示"复选框
        top_var = tk.BooleanVar(value=self.config.get("always_on_top"))
        tk.Checkbutton(win, text="置顶显示", variable=top_var,
                       font=FONT_MEDIUM, fg=COLORS["text"],
                       bg=COLORS["bg"], selectcolor=COLORS["card"],
                       activebackground=COLORS["bg"],
                       activeforeground=COLORS["text"]).grid(
                           row=len(fields), column=0, columnspan=2,
                           sticky="w", padx=20, pady=(12, 2))

        def save_settings():
            """校验并保存设置，应用置顶属性，重置计时器。"""
            for key, var in entries.items():
                try:
                    val = int(var.get())
                    if val < 1:
                        val = DEFAULT_CONFIG[key]  # 非法值回退默认
                    self.config.set(key, val)
                except:
                    pass  # 非数字输入则跳过
            self.config.set("always_on_top", top_var.get())
            self.root.attributes("-topmost", top_var.get())
            self.reset()              # 用新时长重置当前阶段
            self._draw_progress_dots()  # 长休间隔可能已变，重绘圆点
            win.destroy()

        btn_frame = tk.Frame(win, bg=COLORS["bg"])
        btn_frame.grid(row=len(fields) + 1, column=0, columnspan=2, pady=20)
        self._make_button(btn_frame, "  保存  ", save_settings,
                          COLORS["success"], width=8, fg="#ffffff").pack(side="left", padx=6)
        self._make_button(btn_frame, "  取消  ", win.destroy,
                          COLORS["accent"], width=8, fg="#ffffff").pack(side="left", padx=6)

    # ── 启动入口 ─────────────────────────────────────────────────────────────
    def run(self):
        """初始化显示并进入 Tkinter 事件主循环。"""
        self.update_display()
        self.root.mainloop()


# ── 程序入口 ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = PomodoroApp()
    app.run()
