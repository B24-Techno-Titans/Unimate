#!/usr/bin/env python3
"""
UniMate — Tkinter kiosk UI (mock data only). Eyes-only center panel.

Run on Pi desktop:
  python3 unimate_tk.py

Fullscreen by default on HDMI/touch screen.
Development window mode:
  UNIMATE_WINDOWED=1 python3 unimate_tk.py
"""

from __future__ import annotations

import math
import os
import random
import sys
import tkinter as tk
from tkinter import ttk

# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------
class Theme:
    """Liquid glass on OLED-style black."""

    BLACK = "#000000"
    BG0 = "#000000"
    BG1 = "#000000"
    GLASS_BG = "#0c0e14"
    GLASS_BG_HI = "#141824"
    PANEL = "#0c0e14"
    BORDER = "#3d9fdf"
    BORDER_DIM = "#1e3a52"
    TEXT = "#eef6ff"
    MUTED = "#7a8fa8"
    ACCENT = "#5ecbff"
    ACCENT_SOFT = "#8bd9ff"
    OK = "#5eea9b"
    WARN = "#ffd089"
    DANGER = "#ff8b8b"
    BTN = "#141c28"
    BTN_HI = "#1e2d42"
    BTN_ACTIVE = "#1a4a66"


EMOTIONS = (
    "neutral",
    "happy",
    "angry",
    "sad",
    "surprised",
    "sleepy",
    "thinking",
    "listening",
    "speaking",
    "look_left",
    "look_right",
)

MCQ_BANK = [
    {
        "q": "What gas do plants take in for photosynthesis?",
        "options": ["Oxygen", "Carbon dioxide", "Nitrogen", "Hydrogen"],
        "correct": 1,
        "explain": "Plants use CO₂ with light to make sugars and release O₂.",
    },
    {
        "q": "Newton's first law is about…",
        "options": ["Gravity", "Inertia", "Friction", "Mass × acceleration"],
        "correct": 1,
        "explain": "An object stays at rest or in uniform motion unless a net force acts.",
    },
    {
        "q": "In Python, what starts a function definition?",
        "options": ["func", "def", "function", "fn"],
        "correct": 1,
        "explain": "Use def name(args): to define a function.",
    },
]


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Eyes-only expressions (LED / vector robot clips)
# ---------------------------------------------------------------------------
class RobotEyes(tk.Canvas):
  """Large capsule LED eyes with emotion presets — no mouth / face chrome."""

  SOCKET_FILL = "#050810"
  SOCKET_EDGE = "#152638"
  CORE = "#070c14"
  IRIS = "#5ecbff"
  IRIS_HI = "#f5fcff"

  def __init__(self, master, **kw):
    super().__init__(master, bg=Theme.BLACK, highlightthickness=0, bd=0, **kw)
    self.emotion = "neutral"
    self._tick = 0
    self._blink_t = 0.0
    self._blink_phase = "idle"
    self._next_blink = random.uniform(2.0, 4.8)
    self._double_blink = False
    self._pulse = 0.0
    self._listen_ring = 0.0
    self._pupil = [0.0, 0.0]
    self._pupil_tgt = [0.0, 0.0]
    self.bind("<Configure>", lambda _e: self._draw())
    self.after(33, self._animate)

  def set_emotion(self, name: str) -> None:
    if name in EMOTIONS:
      self.emotion = name

  def _blink_amt(self) -> float:
    if self.emotion == "sleepy":
      return 0.0
    if self._blink_phase == "idle":
      return 0.0
    if self._blink_phase == "closed":
      return 1.0
    if self._blink_phase == "closing":
      return min(1.0, self._blink_t / 0.07)
    if self._blink_phase == "opening":
      return max(0.0, 1.0 - self._blink_t / 0.09)
    return 0.0

  def _animate(self) -> None:
    self._tick += 1
    dt = 0.033
    t = self._tick
    e = self.emotion

    if e != "sleepy":
      self._blink_t += dt
      if self._blink_phase == "idle" and self._blink_t >= self._next_blink:
        self._blink_phase = "closing"
        self._blink_t = 0.0
      elif self._blink_phase == "closing" and self._blink_t >= 0.07:
        self._blink_phase = "closed"
        self._blink_t = 0.0
      elif self._blink_phase == "closed" and self._blink_t >= 0.05:
        self._blink_phase = "opening"
        self._blink_t = 0.0
      elif self._blink_phase == "opening" and self._blink_t >= 0.09:
        if self._double_blink:
          self._double_blink = False
          self._blink_phase = "closing"
          self._blink_t = 0.0
        else:
          self._blink_phase = "idle"
          self._blink_t = 0.0
          self._next_blink = random.uniform(2.4, 5.5)
          if random.random() < 0.2:
            self._double_blink = True
            self._next_blink = 0.15

    if e == "speaking":
      self._pulse += 0.5
    elif e == "listening":
      self._listen_ring = 0.55 + 0.45 * math.sin(t * 0.13)
    else:
      self._listen_ring *= 0.94

    tx = ty = 0.0
    if e == "thinking":
      tx, ty = 0.0, -18.0
    elif e == "look_left":
      tx, ty = -28.0, 4.0
    elif e == "look_right":
      tx, ty = 28.0, 4.0
    elif e == "neutral":
      tx = 7 * math.sin(t * 0.035)
      ty = 5 * math.cos(t * 0.028)
    elif e == "happy":
      tx = 6 * math.sin(t * 0.055)
      ty = -8 + 4 * math.sin(t * 0.07)
    elif e == "angry":
      tx, ty = 0.0, 14.0
    elif e == "sad":
      tx = -5.0
      ty = 12.0
    elif e == "surprised":
      tx = 4 * math.sin(t * 0.12)
      ty = -6 * math.sin(t * 0.1)

    self._pupil_tgt = [tx, ty]
    self._pupil[0] += (self._pupil_tgt[0] - self._pupil[0]) * 0.22
    self._pupil[1] += (self._pupil_tgt[1] - self._pupil[1]) * 0.22

    self._draw()
    self.after(33, self._animate)

  def _breath_outline(self, s: float) -> int:
    return max(2, int(2 + 4 * (0.5 + 0.5 * math.sin(self._tick * 0.052))))

  def _blink_line(self, ex: float, ey: float, half_w: float, s: float) -> None:
    self.create_line(
      ex - half_w,
      ey,
      ex + half_w,
      ey,
      fill=Theme.ACCENT,
      width=max(5, int(7 * s)),
      capstyle=tk.ROUND,
    )

  def _iris(self, ex: float, ey: float, s: float, rx: float, ry: float) -> None:
    px = self._pupil[0] * s
    py = self._pupil[1] * s
    sp = 1.0 + (0.16 * abs(math.sin(self._pulse)) if self.emotion == "speaking" else 0.0)
    irx = rx * sp
    iry = ry * sp
    self.create_oval(
      ex + px - irx,
      ey + py - iry,
      ex + px + irx,
      ey + py + iry,
      fill=self.IRIS,
      outline="",
    )
    sh = min(irx, iry) * 0.38
    self.create_oval(
      ex + px - irx * 0.35 - sh,
      ey + py - iry * 0.65 - sh,
      ex + px - irx * 0.35 + sh,
      ey + py - iry * 0.65 + sh,
      fill=self.IRIS_HI,
      outline="",
    )

  def _listening_rings(self, cx: float, cy: float, gap: float, s: float) -> None:
    if self.emotion != "listening" or self._listen_ring < 0.06:
      return
    ew = 82 * s
    eh = 34 * s
    extra = 14 * self._listen_ring * s
    for sg in (-1, 1):
      ex = cx + sg * gap
      self.create_oval(
        ex - ew - extra,
        cy - eh - extra,
        ex + ew + extra,
        cy + eh + extra,
        outline=Theme.ACCENT_SOFT,
        width=2,
      )

  def _thinking_dots(self, cx: float, cy: float, gap: float, s: float) -> None:
    if self.emotion != "thinking":
      return
    bx = cx + gap + 92 * s
    by = cy - 52 * s
    phase = (self._tick // 7) % 4
    for i in range(3):
      if (phase + i) % 4 == 0:
        continue
      r = (5 - i * 0.8) * s
      ox = i * 15 * s
      oy = -i * 9 * s
      self.create_oval(bx + ox - r, by + oy - r, bx + ox + r, by + oy + r, fill=Theme.ACCENT, outline="")

  def _draw_one(self, ex: float, ey: float, s: float, blink: float, side: str) -> None:
    e = self.emotion

    if e == "happy":
      ew, eh = 74 * s, 54 * s
      if blink > 0.52:
        self._blink_line(ex, ey, 58 * s, s)
        return
      self.create_arc(
        ex - ew,
        ey - eh * 0.12,
        ex + ew,
        ey + eh * 0.82,
        start=215 if side == "l" else 325,
        extent=88,
        style=tk.ARC,
        outline=Theme.ACCENT,
        width=max(6, int(7 * s)),
      )
      return

    if e == "sleepy":
      ew, eh = 78 * s, 22 * s
      self.create_arc(
        ex - ew,
        ey - eh,
        ex + ew,
        ey + eh * 2.2,
        start=0,
        extent=180,
        style=tk.CHORD,
        fill=self.SOCKET_FILL,
        outline=Theme.ACCENT,
        width=3,
      )
      return

    if e == "surprised":
      r = (44 + 9 * math.sin(self._tick * 0.085)) * s
      if blink > 0.52:
        self._blink_line(ex, ey, r * 1.15, s)
        return
      ow = self._breath_outline(s)
      self.create_oval(ex - r, ey - r, ex + r, ey + r, fill=self.SOCKET_FILL, outline=Theme.ACCENT, width=ow)
      self._iris(ex, ey, s, r * 0.38, r * 0.42)
      return

    if e == "sad":
      ew, eh = 70 * s, 36 * s
      skew = 15 * s
      if blink > 0.52:
        self._blink_line(ex, ey, 58 * s, s)
        return
      self.create_polygon(
        ex - ew + skew,
        ey - eh,
        ex + ew + skew,
        ey - eh,
        ex + ew - skew,
        ey + eh,
        ex - ew - skew,
        ey + eh,
        fill=self.SOCKET_FILL,
        outline=Theme.ACCENT,
        width=3,
      )
      self._iris(ex, ey + 8 * s, s, 24 * s, 14 * s)
      return

    if e == "angry":
      ew, eh = 68 * s, 30 * s
      skew = -17 * s if side == "l" else 17 * s
      if blink > 0.52:
        self._blink_line(ex, ey, 56 * s, s)
        return
      self.create_polygon(
        ex - ew + skew,
        ey - eh,
        ex + ew + skew,
        ey - eh,
        ex + ew - skew,
        ey + eh,
        ex - ew - skew,
        ey + eh,
        fill=self.SOCKET_FILL,
        outline=Theme.DANGER,
        width=3,
      )
      self._iris(ex, ey + 6 * s, s, 22 * s, 11 * s)
      return

    # LED capsules: neutral, thinking, listening, speaking, look_*
    ew0 = 78 * s
    eh0 = 31 * s
    scale = 1.06 if e == "listening" else 1.0
    ew = ew0 * scale
    eh = eh0 * scale * (1.0 - 0.9 * blink)

    if blink > 0.52:
      self._blink_line(ex, ey, 72 * s, s)
      return

    ow = self._breath_outline(s)
    self.create_oval(
      ex - ew,
      ey - eh,
      ex + ew,
      ey + eh,
      fill=self.SOCKET_FILL,
      outline=Theme.ACCENT,
      width=ow,
    )
    ix = ew * 0.68
    iy = eh * 0.52
    self.create_oval(
      ex - ix,
      ey - iy,
      ex + ix,
      ey + iy,
      fill=self.CORE,
      outline=self.SOCKET_EDGE,
      width=1,
    )
    self._iris(ex, ey, s, 23 * s, 13 * s)

  def _draw(self) -> None:
    self.delete("all")
    w = max(self.winfo_width(), 220)
    h = max(self.winfo_height(), 200)
    cx = w / 2
    cy = h / 2
    s = min(w, h) / 380
    gap = 118 * s
    blink = self._blink_amt()

    self._listening_rings(cx, cy, gap, s)

    ey = cy
    self._draw_one(cx - gap, ey, s, blink, "l")
    self._draw_one(cx + gap, ey, s, blink, "r")

    self._thinking_dots(cx, cy, gap, s)


# ---------------------------------------------------------------------------
# Styled widgets helpers
# ---------------------------------------------------------------------------
def glass_card(parent: tk.Widget, **pack_kw) -> tk.Frame:
  """Liquid-glass panel. Pack keys optional — omit packing when embedding manually."""
  f = tk.Frame(
    parent,
    bg=Theme.GLASS_BG,
    highlightbackground=Theme.BORDER_DIM,
    highlightthickness=1,
  )
  if pack_kw:
    f.pack(**pack_kw)
  return f


def style_ttk(root: tk.Tk) -> ttk.Style:
  s = ttk.Style(root)
  try:
    s.theme_use("clam")
  except tk.TclError:
    pass
  blk = Theme.BLACK
  gl = Theme.GLASS_BG
  s.configure("TFrame", background=blk)
  s.configure("Card.TFrame", background=Theme.GLASS_BG, relief="flat")
  s.configure("TLabel", background=blk, foreground=Theme.TEXT, font=("Segoe UI", 11))
  s.configure("Title.TLabel", font=("Segoe UI", 16, "bold"), foreground=Theme.ACCENT, background=blk)
  s.configure("Muted.TLabel", foreground=Theme.MUTED, font=("Segoe UI", 9), background=blk)
  s.configure("Big.TLabel", font=("Segoe UI", 22, "bold"), foreground=Theme.TEXT, background=blk)
  s.configure(
    "Accent.TButton",
    font=("Segoe UI", 11, "bold"),
    padding=(12, 10),
  )
  s.map(
    "Accent.TButton",
    background=[("active", Theme.BTN_ACTIVE), ("!disabled", Theme.BTN_HI)],
    foreground=[("!disabled", Theme.TEXT)],
  )
  s.configure(
    "Vertical.TScrollbar",
    background=Theme.GLASS_BG,
    troughcolor=blk,
    bordercolor=Theme.BORDER_DIM,
    arrowcolor=Theme.MUTED,
    gripcount=0,
    relief="flat",
  )
  return s


def make_button(parent, text, command, accent=False) -> tk.Button:
  bg = Theme.BTN_ACTIVE if accent else Theme.BTN_HI
  btn = tk.Button(
    parent,
    text=text,
    command=command,
    bg=bg,
    fg=Theme.TEXT,
    activebackground=Theme.ACCENT,
    activeforeground=Theme.BLACK,
    relief=tk.FLAT,
    bd=0,
    highlightbackground=Theme.BORDER,
    highlightthickness=1,
    padx=14,
    pady=12,
    font=("Segoe UI", 10, "bold"),
    cursor="hand2",
  )
  btn.bind("<Enter>", lambda _e: btn.configure(bg=Theme.BTN_ACTIVE))
  btn.bind("<Leave>", lambda _e: btn.configure(bg=bg))
  return btn


# ---------------------------------------------------------------------------
# Display (SSH / headless guard)
# ---------------------------------------------------------------------------
def ensure_display() -> None:
  """
  Tkinter needs a GUI session. Over SSH, DISPLAY is often unset even when
  the 7\" HDMI desktop is running locally — point at :0 in that case.
  """
  if os.environ.get("DISPLAY"):
    return

  # Explicit override: UNIMATE_DISPLAY=:0
  forced = os.environ.get("UNIMATE_DISPLAY", "").strip()
  if forced:
    os.environ["DISPLAY"] = forced
    return

  # Pi / Linux: first local X11 socket usually means HDMI desktop is up
  if sys.platform.startswith("linux"):
    if os.path.isdir("/tmp/.X11-unix"):
      for name in sorted(os.listdir("/tmp/.X11-unix")):
        if name.startswith("X") and name[1:].isdigit():
          os.environ["DISPLAY"] = f":{name[1:]}"
          print(f"UniMate: using DISPLAY={os.environ['DISPLAY']} (local X11)")
          return
    # Common default when logged in on the Pi desktop
    os.environ["DISPLAY"] = ":0"
    print("UniMate: trying DISPLAY=:0 (Pi HDMI desktop)")
    return

  print(
    "ERROR: No graphical display for Tkinter.\n\n"
    "Run the UI where the Waveshare screen is active:\n"
    "  • Open Terminal on the Pi desktop (not SSH), then:\n"
    "      cd ~/Unimate/UIUX && python3 unimate_tk.py\n\n"
    "  • Or from SSH, show on the HDMI screen:\n"
    "      export DISPLAY=:0\n"
    "      xhost +local:   # once, on the Pi desktop terminal\n"
    "      python3 unimate_tk.py\n\n"
    "  • Windowed dev mode:\n"
    "      UNIMATE_WINDOWED=1 python3 unimate_tk.py\n",
    file=sys.stderr,
  )
  sys.exit(1)


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------
class UniMateApp:
  def __init__(self) -> None:
    self.root = tk.Tk()
    self.root.title("UniMate")
    self.root.configure(bg=Theme.BG0)
    self.root.minsize(800, 480)

    windowed = os.environ.get("UNIMATE_WINDOWED", "").strip().lower() in ("1", "true", "yes")
    if windowed:
      self.root.geometry("1024x600")
    else:
      self.root.attributes("-fullscreen", True)

    style_ttk(self.root)

    self.mock = {
      "room_temp": 24.2,
      "humidity": 48.0,
      "lux": 320.0,
      "body_temp": 36.6,
      "heart_rate": 72,
      "fan": 2,
      "humidifier": "off",
      "led_on": True,
      "led_brightness": 180,
      "led_rgb": (255, 244, 220),
    }
    self.panel_index = 1
    self.mcq_index = 0
    self._swipe_x: int | None = None

    self._build_chrome()
    self._build_panels()
    self._show_panel(1)
    self._bind_swipe()
    self._tick_sensors()
    self._idle_reset()

  def _build_chrome(self) -> None:
    top = tk.Frame(self.root, bg=Theme.BG0, pady=6, padx=12)
    top.pack(fill=tk.X)
    tk.Label(
      top,
      text="UniMate",
      bg=Theme.BG0,
      fg=Theme.ACCENT,
      font=("Segoe UI", 14, "bold"),
    ).pack(side=tk.LEFT)
    tk.Label(
      top,
      text="Swipe · Study · Eyes · Controls",
      bg=Theme.BG0,
      fg=Theme.MUTED,
      font=("Segoe UI", 8),
    ).pack(side=tk.RIGHT)

    self.container = tk.Frame(self.root, bg=Theme.BLACK)
    self.container.pack(fill=tk.BOTH, expand=True, padx=10, pady=6)

    nav = tk.Frame(self.root, bg=Theme.BG0, pady=8)
    nav.pack(fill=tk.X)
    self.dots: list[tk.Canvas] = []
    for i in range(3):
      c = tk.Canvas(nav, width=18, height=18, bg=Theme.BLACK, highlightthickness=0)
      c.pack(side=tk.LEFT, padx=10)
      c.bind("<Button-1>", lambda e, n=i: self._show_panel(n))
      self.dots.append(c)

  def _dot_draw(self) -> None:
    for i, c in enumerate(self.dots):
      c.delete("all")
      fill = Theme.ACCENT_SOFT if i == self.panel_index else Theme.BORDER_DIM
      c.create_oval(4, 4, 14, 14, fill=fill, outline="")

  def _build_panels(self) -> None:
    self.panels: list[tk.Frame] = []
    for _ in range(3):
      f = tk.Frame(self.container, bg=Theme.BLACK)
      self.panels.append(f)

    self._build_study(self.panels[0])
    self._build_face(self.panels[1])
    self._build_dashboard(self.panels[2])

  def _build_study(self, parent: tk.Frame) -> None:
    shell = tk.Frame(parent, bg=Theme.BLACK)
    shell.pack(fill=tk.BOTH, expand=True)
    card = glass_card(shell, fill=tk.BOTH, expand=True, padx=14, pady=14)
    bg = Theme.GLASS_BG

    tk.Label(
      card,
      text="Study Buddy",
      bg=bg,
      fg=Theme.ACCENT_SOFT,
      font=("Segoe UI", 18, "bold"),
    ).pack(anchor=tk.W, pady=(0, 4))
    tk.Label(
      card,
      text="Demo mode · mock answers",
      bg=bg,
      fg=Theme.WARN,
      font=("Segoe UI", 9),
    ).pack(anchor=tk.W)

    chips = tk.Frame(card, bg=bg)
    chips.pack(fill=tk.X, pady=10)
    for topic in ("Photosynthesis", "Newton's laws", "Python basics", "World War II"):
      make_button(chips, topic, lambda t=topic: self._study_topic(t)).pack(
        side=tk.LEFT, padx=4, pady=4
      )

    actions = tk.Frame(card, bg=bg)
    actions.pack(fill=tk.X, pady=6)
    make_button(actions, "Ask", self._study_ask).pack(side=tk.LEFT, padx=4)
    make_button(actions, "MCQ", self._study_mcq, accent=True).pack(side=tk.LEFT, padx=4)
    make_button(actions, "Explain", self._study_explain).pack(side=tk.LEFT, padx=4)
    make_button(actions, "Quiz me", self._study_quiz).pack(side=tk.LEFT, padx=4)

    row = tk.Frame(card, bg=bg)
    row.pack(fill=tk.X, pady=8)
    self.ask_var = tk.StringVar()
    ent = tk.Entry(
      row,
      textvariable=self.ask_var,
      bg=Theme.GLASS_BG_HI,
      fg=Theme.TEXT,
      insertbackground=Theme.ACCENT,
      relief=tk.FLAT,
      highlightbackground=Theme.BORDER_DIM,
      highlightthickness=1,
      font=("Segoe UI", 12),
    )
    ent.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=10, padx=(0, 8))
    make_button(row, "Send", self._study_send, accent=True).pack(side=tk.RIGHT)

    self.study_text = tk.Text(
      card,
      height=6,
      bg=Theme.GLASS_BG_HI,
      fg=Theme.TEXT,
      relief=tk.FLAT,
      highlightbackground=Theme.BORDER_DIM,
      highlightthickness=1,
      font=("Segoe UI", 11),
      wrap=tk.WORD,
    )
    self.study_text.pack(fill=tk.BOTH, expand=True, pady=8)
    self.study_text.insert("1.0", "Pick a topic chip or tap MCQ to practice.")
    self.study_text.configure(state=tk.DISABLED)

    self.mcq_frame = tk.Frame(card, bg=Theme.GLASS_BG_HI, padx=12, pady=12,
                             highlightbackground=Theme.BORDER_DIM, highlightthickness=1)
    self.mcq_q = tk.Label(
      self.mcq_frame,
      text="",
      bg=Theme.GLASS_BG_HI,
      fg=Theme.TEXT,
      font=("Segoe UI", 12, "bold"),
      wraplength=900,
      justify=tk.LEFT,
    )
    self.mcq_q.pack(anchor=tk.W)
    self.mcq_btns: list[tk.Button] = []
    self.mcq_fb = tk.Label(
      self.mcq_frame,
      text="",
      bg=Theme.GLASS_BG_HI,
      fg=Theme.MUTED,
      font=("Segoe UI", 10),
      wraplength=900,
      justify=tk.LEFT,
    )

  def _build_face(self, parent: tk.Frame) -> None:
    shell = tk.Frame(parent, bg=Theme.BLACK)
    shell.pack(fill=tk.BOTH, expand=True)

    bar = glass_card(shell, fill=tk.X, padx=14, pady=(14, 8))
    bar_bg = Theme.GLASS_BG
    self.chip_mode = tk.Label(
      bar,
      text="Eyes",
      bg=bar_bg,
      fg=Theme.MUTED,
      padx=10,
      pady=4,
      font=("Segoe UI", 9),
    )
    self.chip_mode.pack(side=tk.LEFT, padx=4)
    tk.Label(
      bar,
      text="● Ready",
      bg=bar_bg,
      fg=Theme.OK,
      padx=10,
      pady=4,
      font=("Segoe UI", 9),
    ).pack(side=tk.LEFT, padx=4)
    self.chip_study = tk.Label(
      bar,
      text="Study off",
      bg=bar_bg,
      fg=Theme.MUTED,
      padx=10,
      pady=4,
      font=("Segoe UI", 9),
    )
    self.chip_study.pack(side=tk.LEFT, padx=4)

    self.face = RobotEyes(shell)
    self.face.pack(fill=tk.BOTH, expand=True, pady=(4, 8))

    demo = glass_card(shell, fill=tk.X, padx=14, pady=(0, 14))
    demo_bg = Theme.GLASS_BG
    tk.Label(
      demo,
      text="Expressions (demo)",
      bg=demo_bg,
      fg=Theme.MUTED,
      font=("Segoe UI", 8),
    ).pack(anchor=tk.W)

    labels = {
      "neutral": "Calm",
      "happy": "Happy",
      "angry": "Angry",
      "sad": "Sad",
      "surprised": "Wow",
      "sleepy": "Sleep",
      "thinking": "Think",
      "listening": "Listen",
      "speaking": "Talk",
      "look_left": "←",
      "look_right": "→",
    }
    row1 = tk.Frame(demo, bg=demo_bg)
    row1.pack(fill=tk.X, pady=4)
    row2 = tk.Frame(demo, bg=demo_bg)
    row2.pack(fill=tk.X)
    half = len(EMOTIONS) // 2 + len(EMOTIONS) % 2
    for i, em in enumerate(EMOTIONS):
      target = row1 if i < half else row2
      make_button(target, labels[em], lambda e=em: self.face.set_emotion(e)).pack(
        side=tk.LEFT, padx=2, pady=2
      )


  def _build_dashboard(self, parent: tk.Frame) -> None:
    shell = tk.Frame(parent, bg=Theme.BLACK)
    shell.pack(fill=tk.BOTH, expand=True)
    canvas = tk.Canvas(shell, bg=Theme.BLACK, highlightthickness=0)
    scroll = ttk.Scrollbar(shell, orient=tk.VERTICAL, command=canvas.yview)
    inner = tk.Frame(canvas, bg=Theme.BLACK)
    inner.bind(
      "<Configure>",
      lambda _e: canvas.configure(scrollregion=canvas.bbox("all")),
    )
    inner_win = canvas.create_window((0, 0), window=inner, anchor=tk.NW)
    canvas.configure(yscrollcommand=scroll.set)

    def _fill_canvas(event: tk.Event) -> None:
      canvas.itemconfigure(inner_win, width=event.width)

    canvas.bind("<Configure>", _fill_canvas)

    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scroll.pack(side=tk.RIGHT, fill=tk.Y)

    card = glass_card(inner, fill=tk.BOTH, expand=True, padx=14, pady=14)
    bg = Theme.GLASS_BG

    tk.Label(
      card,
      text="Sensors & controls",
      bg=bg,
      fg=Theme.ACCENT_SOFT,
      font=("Segoe UI", 18, "bold"),
    ).pack(anchor=tk.W)
    tk.Label(
      card,
      text="Mock data · connect Pi API later",
      bg=bg,
      fg=Theme.WARN,
      font=("Segoe UI", 9),
    ).pack(anchor=tk.W, pady=(0, 10))

    grid = tk.Frame(card, bg=bg)
    grid.pack(fill=tk.X)
    self.val_labels = {}
    hi = Theme.GLASS_BG_HI
    for key, title in (
      ("room_temp", "Room temp"),
      ("humidity", "Humidity"),
      ("lux", "Light"),
      ("body_temp", "Body temp"),
      ("heart_rate", "Heart rate"),
    ):
      mini = tk.Frame(
        grid,
        bg=hi,
        highlightbackground=Theme.BORDER_DIM,
        highlightthickness=1,
        padx=10,
        pady=10,
      )
      mini.pack(side=tk.LEFT, padx=5, pady=6, fill=tk.BOTH, expand=True)
      tk.Label(mini, text=title, bg=hi, fg=Theme.MUTED, font=("Segoe UI", 9)).pack(anchor=tk.W)
      lb = tk.Label(
        mini,
        text="--",
        bg=hi,
        fg=Theme.TEXT,
        font=("Segoe UI", 19, "bold"),
      )
      lb.pack(anchor=tk.W)
      self.val_labels[key] = lb

    ctrl = tk.Frame(
      card,
      bg=hi,
      highlightbackground=Theme.BORDER_DIM,
      highlightthickness=1,
      padx=14,
      pady=14,
    )
    ctrl.pack(fill=tk.X, pady=12)

    tk.Label(ctrl, text="Fan", bg=hi, fg=Theme.ACCENT_SOFT, font=("Segoe UI", 11, "bold")).pack(
      anchor=tk.W
    )
    self.fan_var = tk.IntVar(value=self.mock["fan"])
    fan_row = tk.Frame(ctrl, bg=hi)
    fan_row.pack(fill=tk.X, pady=6)
    for i, name in enumerate(("Off", "Low", "Med", "High")):
      tk.Radiobutton(
        fan_row,
        text=name,
        variable=self.fan_var,
        value=i,
        bg=hi,
        fg=Theme.TEXT,
        selectcolor=Theme.BTN_ACTIVE,
        activebackground=hi,
        highlightthickness=0,
        command=lambda: self._set_mock("fan", self.fan_var.get()),
      ).pack(side=tk.LEFT, padx=8)

    tk.Label(
      ctrl, text="Humidifier", bg=hi, fg=Theme.ACCENT_SOFT, font=("Segoe UI", 11, "bold")
    ).pack(anchor=tk.W, pady=(12, 0))
    self.humid_var = tk.StringVar(value="off")
    humid_row = tk.Frame(ctrl, bg=hi)
    humid_row.pack(fill=tk.X, pady=6)
    for v in ("off", "on", "auto"):
      tk.Radiobutton(
        humid_row,
        text=v.capitalize(),
        variable=self.humid_var,
        value=v,
        bg=hi,
        fg=Theme.TEXT,
        selectcolor=Theme.BTN_ACTIVE,
        activebackground=hi,
        highlightthickness=0,
        command=lambda: self._set_mock("humidifier", self.humid_var.get()),
      ).pack(side=tk.LEFT, padx=8)

    tk.Label(ctrl, text="LED lamp", bg=hi, fg=Theme.ACCENT_SOFT, font=("Segoe UI", 11, "bold")).pack(
      anchor=tk.W, pady=(12, 0)
    )
    self.led_on_var = tk.BooleanVar(value=True)
    tk.Checkbutton(
      ctrl,
      text="Lamp on",
      variable=self.led_on_var,
      bg=hi,
      fg=Theme.TEXT,
      selectcolor=Theme.BTN_ACTIVE,
      activebackground=hi,
      highlightthickness=0,
      command=lambda: self._set_mock("led_on", self.led_on_var.get()),
    ).pack(anchor=tk.W)
    self.bright_var = tk.IntVar(value=180)
    tk.Scale(
      ctrl,
      from_=0,
      to=255,
      orient=tk.HORIZONTAL,
      variable=self.bright_var,
      bg=hi,
      fg=Theme.TEXT,
      troughcolor=Theme.BTN,
      highlightthickness=0,
      command=lambda _: self._set_mock("led_brightness", self.bright_var.get()),
    ).pack(fill=tk.X, pady=6)
    colors = tk.Frame(ctrl, bg=hi)
    colors.pack(fill=tk.X)
    presets = (
      ((255, 244, 220), "#fff4dc"),
      ((200, 220, 255), "#c8dcff"),
      ((255, 100, 120), "#ff6478"),
      ((100, 200, 255), "#64c8ff"),
    )
    for rgb, hex_c in presets:
      b = tk.Button(
        colors,
        bg=hex_c,
        width=3,
        height=1,
        relief=tk.FLAT,
        highlightbackground=Theme.BORDER_DIM,
        highlightthickness=1,
        command=lambda r=rgb: self._set_mock("led_rgb", r),
      )
      b.pack(side=tk.LEFT, padx=6)
    self.led_preview = tk.Label(ctrl, text="", bg=hi, fg=Theme.MUTED, font=("Segoe UI", 9))
    self.led_preview.pack(anchor=tk.W, pady=6)

    self._refresh_sensor_labels()

  def _set_mock(self, key: str, val) -> None:
    self.mock[key] = val
    if key.startswith("led"):
      r, g, b = self.mock["led_rgb"]
      on = self.mock["led_on"]
      self.led_preview.configure(
        text=f"{'ON' if on else 'OFF'} rgb({r},{g},{b}) @ {self.mock['led_brightness']}"
      )

  def _refresh_sensor_labels(self) -> None:
    m = self.mock
    self.val_labels["room_temp"].configure(text=f"{m['room_temp']:.1f}°C")
    self.val_labels["humidity"].configure(text=f"{m['humidity']:.0f}%")
    self.val_labels["lux"].configure(text=f"{m['lux']:.0f} lx")
    self.val_labels["body_temp"].configure(text=f"{m['body_temp']:.1f}°C")
    self.val_labels["heart_rate"].configure(text=f"{m['heart_rate']} bpm")
    r, g, b = m["led_rgb"]
    self.led_preview.configure(
      text=f"{'ON' if m['led_on'] else 'OFF'} rgb({r},{g},{b}) @ {m['led_brightness']}"
    )


  def _tick_sensors(self) -> None:
    m = self.mock
    m["room_temp"] += (random.random() - 0.5) * 0.08
    m["humidity"] = max(35, min(65, m["humidity"] + (random.random() - 0.5) * 0.5))
    m["lux"] = max(50, min(800, m["lux"] + (random.random() - 0.5) * 12))
    m["body_temp"] += (random.random() - 0.5) * 0.03
    m["heart_rate"] = int(max(58, min(100, m["heart_rate"] + (random.random() - 0.5) * 2)))
    self._refresh_sensor_labels()
    self.root.after(2500, self._tick_sensors)

  def _show_panel(self, index: int) -> None:
    index = max(0, min(2, index))
    self.panel_index = index
    for i, p in enumerate(self.panels):
      if i == index:
        p.pack(fill=tk.BOTH, expand=True)
      else:
        p.pack_forget()
    self.chip_mode.configure(
      text=["Study mode", "Eyes", "Controls"][index]
    )
    self.chip_study.configure(text="Study on" if index == 0 else "Study off")
    self._dot_draw()
    self._idle_reset()

  def _panel_next(self) -> None:
    self._show_panel(self.panel_index + 1)

  def _panel_prev(self) -> None:
    self._show_panel(self.panel_index - 1)

  def _bind_swipe(self) -> None:
    w = self.container
    w.bind("<ButtonPress-1>", self._swipe_start, add="+")
    w.bind("<ButtonRelease-1>", self._swipe_end, add="+")
    self.root.bind("<Left>", lambda e: self._panel_prev())
    self.root.bind("<Right>", lambda e: self._panel_next())
    self.root.bind("<Escape>", lambda e: self.root.attributes("-fullscreen", False))

  def _swipe_start(self, event) -> None:
    self._swipe_x = event.x_root

  def _swipe_end(self, event) -> None:
    if self._swipe_x is None:
      return
    dx = event.x_root - self._swipe_x
    self._swipe_x = None
    if abs(dx) < 80:
      return
    if dx > 0:
      self._panel_next()
    else:
      self._panel_prev()

  def _idle_reset(self) -> None:
    if hasattr(self, "_idle_job") and self._idle_job:
      self.root.after_cancel(self._idle_job)
    self._idle_job = self.root.after(90_000, lambda: self._show_panel(1))

  def _study_write(self, text: str) -> None:
    self.study_text.configure(state=tk.NORMAL)
    self.study_text.delete("1.0", tk.END)
    self.study_text.insert("1.0", text)
    self.study_text.configure(state=tk.DISABLED)
    self.mcq_frame.pack_forget()

  def _study_topic(self, topic: str) -> None:
    self._study_write(f"Topic: {topic}\n\n(Mock answer) UniMate would explain this briefly here.")
    self.face.set_emotion("happy")
    self.root.after(1600, lambda: self.face.set_emotion("neutral"))

  def _study_ask(self) -> None:
    self._study_write("Type your question above and tap Send.")

  def _study_explain(self) -> None:
    self._study_write("Explain (mock):\n• Main idea\n• Why it matters\n• One example")
    self.face.set_emotion("thinking")

  def _study_quiz(self) -> None:
    self._study_write(
      "Quiz me (mock):\n• Tap MCQ for multiple choice.\n"
      "• Or pick a topic chip for a quick drill.\n• Backend hooks later."
    )
    self.face.set_emotion("listening")

  def _study_send(self) -> None:
    q = self.ask_var.get().strip()
    if not q:
      self._study_write("(Mock) Ask me anything — I am listening.")
      return
    self._study_write(f"You asked: {q}\n\n(Mock) Short helpful answer would appear here.")
    self.face.set_emotion("thinking")
    self.root.after(400, lambda: self.face.set_emotion("speaking"))
    self.root.after(2200, lambda: self.face.set_emotion("neutral"))

  def _study_mcq(self) -> None:
    item = MCQ_BANK[self.mcq_index % len(MCQ_BANK)]
    self.mcq_index += 1
    self._study_write("Tap the correct answer below.")
    self.mcq_frame.pack(fill=tk.X, pady=8)
    self.mcq_q.configure(text=item["q"])
    for b in self.mcq_btns:
      b.destroy()
    self.mcq_btns.clear()
    self.mcq_fb.pack_forget()

    def pick(idx: int) -> None:
      ok = idx == item["correct"]
      for j, btn in enumerate(self.mcq_btns):
        btn.configure(state=tk.DISABLED)
        if j == item["correct"]:
          btn.configure(bg=Theme.OK)
        elif j == idx and not ok:
          btn.configure(bg=Theme.DANGER)
      self.mcq_fb.configure(text=item["explain"])
      self.mcq_fb.pack(anchor=tk.W, pady=8)
      self.face.set_emotion("happy" if ok else "sad")
      self.root.after(2000, lambda: self.face.set_emotion("neutral"))

    for i, opt in enumerate(item["options"]):
      btn = make_button(self.mcq_frame, opt, lambda i=i: pick(i))
      btn.pack(fill=tk.X, pady=4)
      self.mcq_btns.append(btn)

  def run(self) -> None:
    self.root.mainloop()


def main() -> None:
  ensure_display()
  try:
    UniMateApp().run()
  except tk.TclError as e:
    if "no display" in str(e).lower() or "display" in str(e).lower():
      print(
        f"\nTkinter could not open a window: {e}\n\n"
        "If you are on SSH, set DISPLAY=:0 and allow local X access "
        "(run `xhost +local:` once from a desktop terminal on the Pi).\n"
        "Or run this script from a terminal on the Pi desktop itself.\n",
        file=sys.stderr,
      )
      sys.exit(1)
    raise


if __name__ == "__main__":
  main()
