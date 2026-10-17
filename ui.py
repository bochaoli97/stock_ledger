"""
ui.py -- look and feel: color themes, fonts, ttk styling and custom-drawn widgets
(pill buttons, toggle switch, line chart, tab bar, scrollable list).

Everything is drawn with plain tkinter; no extra packages. The colors live in C, which
set_theme() fills from PALETTES; widgets read it when they are built, so switching themes
means rebuilding the window (App.rebuild does that).
"""

from __future__ import annotations

import re
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

# Gain/loss colors follow the US convention (green = up, red = down).
# Set to True for the Chinese-market convention (red = up, green = down).
RED_UP = False

PALETTES = {
    "dark": {
        "bg": "#000000",
        "text": "#FFFFFF",
        "muted": "#9BA1A9",
        "border": "#24272B",
        "chip": "#1A1C1F",  # secondary button / input background
        "chip_hover": "#2A2D31",
        "select": "#1C1F22",  # selected table row
        "hover": "#0E1012",  # table row under the mouse
        "accent": "#00C805",  # brand green: primary buttons, active tabs
        "accent_hover": "#2BDB2B",
        "on_accent": "#000000",
        "gain": "#00C805",
        "loss": "#FF5000",
        "toggle_off": "#3A3D42",
    },
    "light": {
        "bg": "#FFFFFF",
        "text": "#111315",
        "muted": "#5E646B",
        "border": "#E3E6EA",
        "chip": "#F1F3F5",
        "chip_hover": "#E3E6E9",
        "select": "#EEF9EE",
        "hover": "#F7F8F9",
        "accent": "#00C805",
        "accent_hover": "#00B004",
        "on_accent": "#000000",
        "gain": "#00A30A",
        "loss": "#F04E00",
        "toggle_off": "#C9CDD2",
    },
}
C: dict[str, str] = {}

# Text size choices (menu label -> zoom); everything -- fonts, spacing, charts -- grows with it
TEXT_SIZES = {"Small": 0.9, "Standard": 1.0, "Large": 1.15, "Extra large": 1.3}
DEFAULT_TEXT_SIZE = "Large"

FONT_FAMILIES = [
    "Segoe UI Variable Text",
    "Segoe UI",
    "SF Pro Text",
    "Helvetica Neue",
    "Inter",
    "Ubuntu Sans",
    "Ubuntu",
    "Noto Sans",
    "DejaVu Sans",
]
# Chinese mode puts a font with good Chinese glyphs first (its Latin letters and digits look fine too)
CJK_FONT_FAMILIES = [
    "Microsoft YaHei UI",  # Windows
    "Microsoft YaHei",
    "PingFang SC",  # macOS
    "Noto Sans CJK SC",  # Linux / WSL (fonts-noto-cjk)
    "Source Han Sans SC",
    "WenQuanYi Micro Hei",
]


def set_theme(name: str) -> None:
    C.clear()
    C.update(PALETTES.get(name, PALETTES["dark"]))
    C["name"] = name if name in PALETTES else "dark"
    if RED_UP:
        C["gain"], C["loss"] = C["loss"], C["gain"]


def color_for(value) -> str:
    """Gain/loss color for a number; plain text color for zero or None."""
    if value is None or value == 0:
        return C["text"]
    return C["gain"] if value > 0 else C["loss"]


# ======================================================================
# Fonts, scaling and ttk styles
# ======================================================================
class UI:
    scale = 1.0  # screen DPI factor x text size zoom
    zoom = 1.0
    family: str | None = None

    @classmethod
    def setup(cls, root: tk.Tk, zoom: float = 1.0, cjk: bool = False) -> None:
        """Called at startup and again after a theme, text size or language switch."""
        cls.zoom = zoom
        cls.scale = max(root.winfo_fpixels("1i") / 96, 1.0) * zoom
        families = set(tkfont.families(root))
        cls.family = next((f for f in (CJK_FONT_FAMILIES if cjk else []) + FONT_FAMILIES if f in families), None)
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont", "TkTooltipFont"):
            try:
                f = tkfont.nametofont(name)
            except tk.TclError:
                continue
            if cls.family:
                f.configure(family=cls.family)
            f.configure(size=round(10 * zoom))

        cls.hero = cls.font(30, "bold")  # the big portfolio number
        cls.h1 = cls.font(20, "bold")
        cls.h2 = cls.font(13, "bold")
        cls.body = cls.font(10)
        cls.bold = cls.font(10, "bold")
        cls.small = cls.font(9)
        cls.small_bold = cls.font(9, "bold")
        cls.stat = cls.font(12, "bold")
        cls.button = cls.font(10, "bold")

        root.configure(background=C["bg"])
        root.option_add("*TCombobox*Listbox.background", C["chip"])
        root.option_add("*TCombobox*Listbox.foreground", C["text"])
        root.option_add("*TCombobox*Listbox.selectBackground", C["chip_hover"])
        root.option_add("*TCombobox*Listbox.selectForeground", C["text"])
        root.option_add("*TCombobox*Listbox.borderWidth", 0)

        s = ttk.Style(root)
        s.theme_use("clam")  # the only built-in theme whose colors can all be changed
        s.configure(".", background=C["bg"], foreground=C["text"], fieldbackground=C["chip"],
                    bordercolor=C["border"], lightcolor=C["chip"], darkcolor=C["chip"], troughcolor=C["bg"],
                    selectbackground=C["chip_hover"], selectforeground=C["text"], insertcolor=C["text"],
                    focuscolor=C["bg"], font=tkfont.nametofont("TkDefaultFont"))
        s.configure("TFrame", background=C["bg"])
        s.configure("TLabel", background=C["bg"], foreground=C["text"])
        s.configure("Muted.TLabel", foreground=C["muted"])
        s.configure("TSeparator", background=C["border"])
        s.configure("TEntry", fieldbackground=C["chip"], foreground=C["text"], bordercolor=C["chip"],
                    lightcolor=C["chip"], darkcolor=C["chip"], padding=cls.px(6))
        s.map("TEntry", bordercolor=[("focus", C["accent"])], lightcolor=[("focus", C["accent"])])
        s.configure("TCombobox", fieldbackground=C["chip"], foreground=C["text"], background=C["chip"],
                    bordercolor=C["chip"], lightcolor=C["chip"], darkcolor=C["chip"], arrowcolor=C["muted"],
                    padding=cls.px(5))
        s.map("TCombobox", fieldbackground=[("readonly", C["chip"])], background=[("active", C["chip_hover"])],
              selectbackground=[("readonly", C["chip"])], selectforeground=[("readonly", C["text"])],
              bordercolor=[("focus", C["accent"])])
        s.configure("TButton", background=C["chip"], foreground=C["text"], bordercolor=C["chip"],
                    lightcolor=C["chip"], darkcolor=C["chip"], padding=(cls.px(8), cls.px(4)), font=cls.small_bold)
        s.map("TButton", background=[("active", C["chip_hover"])], lightcolor=[("active", C["chip_hover"])],
              darkcolor=[("active", C["chip_hover"])])

        line = tkfont.nametofont("TkDefaultFont").metrics("linespace")
        s.configure("Treeview", background=C["bg"], fieldbackground=C["bg"], foreground=C["text"],
                    borderwidth=0, rowheight=line + cls.px(16))
        s.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])  # no border
        s.map("Treeview", background=[("selected", C["select"])], foreground=[("selected", C["text"])])
        s.configure("Treeview.Heading", background=C["bg"], foreground=C["muted"], borderwidth=0, relief="flat",
                    font=cls.small_bold, padding=(cls.px(6), cls.px(6)), lightcolor=C["bg"], darkcolor=C["bg"],
                    bordercolor=C["bg"])
        s.map("Treeview.Heading", background=[("active", C["bg"])], foreground=[("active", C["text"])])

        # slim scrollbar: just a thumb, no arrows
        s.layout("Slim.Vertical.TScrollbar", [("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
            ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
        s.configure("Slim.Vertical.TScrollbar", troughcolor=C["bg"], background=C["chip_hover"],
                    bordercolor=C["bg"], lightcolor=C["chip_hover"], darkcolor=C["chip_hover"],
                    gripcount=0, width=cls.px(8), arrowsize=cls.px(8))
        s.map("Slim.Vertical.TScrollbar", background=[("active", C["muted"])])
        s.layout("Slim.Horizontal.TScrollbar", [("Horizontal.Scrollbar.trough", {"sticky": "we", "children": [
            ("Horizontal.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
        s.configure("Slim.Horizontal.TScrollbar", troughcolor=C["bg"], background=C["chip_hover"],
                    bordercolor=C["bg"], lightcolor=C["chip_hover"], darkcolor=C["chip_hover"],
                    gripcount=0, width=cls.px(8), arrowsize=cls.px(8))
        s.map("Slim.Horizontal.TScrollbar", background=[("active", C["muted"])])

    @classmethod
    def font(cls, size: int, weight: str = "normal") -> tkfont.Font:
        f = tkfont.nametofont("TkDefaultFont").copy()
        f.configure(size=round(size * cls.zoom), weight=weight)
        return f

    @classmethod
    def px(cls, n: float) -> int:
        return int(n * cls.scale)

    @classmethod
    def fit(cls, win, w: int, h: int) -> str:
        """Window size: scaled for DPI but never larger than the screen."""
        w = min(cls.px(w), int(win.winfo_screenwidth() * 0.92))
        h = min(cls.px(h), int(win.winfo_screenheight() * 0.85))
        return f"{w}x{h}"


def style_menu(menu: tk.Menu) -> tk.Menu:
    # Windows draws popup menus natively and ignores most of these; Linux/macOS use them
    menu.configure(background=C["chip"], foreground=C["text"], activebackground=C["chip_hover"],
                   activeforeground=C["text"], selectcolor=C["accent"], borderwidth=0, relief="flat",
                   font=UI.body)
    return menu


def label(parent, text="", *, font=None, color=None, **kw) -> tk.Label:
    """A plain tk.Label on the page background (tk.Label allows per-label colors, unlike ttk)."""
    return tk.Label(parent, text=text, font=font or UI.body, fg=color or C["text"], bg=kw.pop("bg", C["bg"]),
                    bd=0, **kw)


def separator(parent) -> tk.Frame:
    return tk.Frame(parent, height=1, bg=C["border"])


# ======================================================================
# Custom widgets
# ======================================================================
def logo(parent, name: str = "Stock Ledger") -> tk.Frame:
    """Green diamond mark + app name."""
    f = tk.Frame(parent, bg=C["bg"])
    s = UI.px(16)
    c = tk.Canvas(f, width=s, height=s, bg=C["bg"], highlightthickness=0, bd=0)
    c.create_polygon(s / 2, 1, s - 1, s / 2, s / 2, s - 1, 1, s / 2, fill=C["accent"], outline=C["accent"])
    c.pack(side="left", padx=(0, UI.px(8)))
    label(f, name, font=UI.h2).pack(side="left")
    return f


def round_rect(canvas: tk.Canvas, x1, y1, x2, y2, r, **kw):
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2,
           x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(pts, smooth=True, **kw)


class PillButton(tk.Canvas):
    """Fully rounded button. kind: primary (green), secondary (grey), outline (green border), ghost (text only).
    caret=True adds a small down arrow; icon="more" draws three dots instead of text; icon="back" puts a
    left-pointing chevron before the text.
    (Shapes are drawn rather than typed as symbols, because not every font has those glyphs.)"""

    def __init__(self, parent, text: str, command, kind: str = "primary", *, font=None, padx=16, pady=7, bg=None,
                 caret=False, icon=None):
        self.font = font or UI.button
        self.kind = kind
        self.command = command
        self.text = text
        self.caret = caret
        self.icon = icon
        self.padx = UI.px(padx)
        w = self._content_width() + 2 * self.padx
        h = self.font.metrics("linespace") + 2 * UI.px(pady)
        super().__init__(parent, width=w, height=h, bg=bg or C["bg"], highlightthickness=0, bd=0, cursor="hand2")
        self._draw(False)
        self.bind("<Enter>", lambda e: self._draw(True))
        self.bind("<Leave>", lambda e: self._draw(False))
        self.bind("<ButtonRelease-1>", self._click)

    def _content_width(self):
        if self.icon == "more":
            return UI.px(18)
        extra = UI.px(16) if self.caret else UI.px(18) if self.icon == "back" else 0
        return self.font.measure(self.text) + extra

    def set_text(self, text: str):
        self.text = text
        self.configure(width=self._content_width() + 2 * self.padx)
        self._draw(False)

    def _colors(self, hover):
        k = self.kind
        if k == "primary":
            return (C["accent_hover"] if hover else C["accent"]), "", C["on_accent"]
        if k == "secondary":
            return (C["chip_hover"] if hover else C["chip"]), "", C["text"]
        if k == "outline":
            return (C["chip"] if hover else self["bg"]), C["accent"], C["accent"]
        return (C["chip"] if hover else self["bg"]), "", C["text"]  # ghost

    def _draw(self, hover):
        self.delete("all")
        w, h = int(self["width"]), int(self["height"])
        fill, outline, fg = self._colors(hover)
        round_rect(self, 1, 1, w - 1, h - 1, h / 2, fill=fill, outline=outline or fill, width=1.5 if outline else 1)
        if self.icon == "more":
            r = max(UI.px(1.6), 1.5)
            for dx in (-UI.px(6), 0, UI.px(6)):
                self.create_oval(w / 2 + dx - r, h / 2 - r, w / 2 + dx + r, h / 2 + r, fill=fg, outline=fg)
            return
        if self.icon == "back":
            a = UI.px(4)
            left = w / 2 - self._content_width() / 2
            cx, cy = left + a, h / 2
            self.create_line(cx + a / 2, cy - a, cx - a / 2, cy, cx + a / 2, cy + a, fill=fg,
                             width=max(UI.px(1.5), 1.5), capstyle="round", joinstyle="round")
            self.create_text(left + UI.px(18), cy, text=self.text, anchor="w", fill=fg, font=self.font)
            return
        tx = w / 2 - (UI.px(8) if self.caret else 0)
        self.create_text(tx, h / 2, text=self.text, fill=fg, font=self.font)
        if self.caret:
            cx, cy, a = tx + self.font.measure(self.text) / 2 + UI.px(10), h / 2, UI.px(3.5)
            self.create_line(cx - a, cy - a / 2, cx, cy + a / 2, cx + a, cy - a / 2, fill=fg, width=max(UI.px(1.5), 1.5),
                             capstyle="round", joinstyle="round")

    def _click(self, event):
        if 0 <= event.x <= int(self["width"]) and 0 <= event.y <= int(self["height"]):
            self.command()


class Toggle(tk.Canvas):
    """On/off switch bound to a BooleanVar."""

    def __init__(self, parent, variable: tk.BooleanVar, command=None, bg=None):
        self.w, self.h = UI.px(38), UI.px(22)
        super().__init__(parent, width=self.w, height=self.h, bg=bg or C["bg"], highlightthickness=0, bd=0,
                         cursor="hand2")
        self.var = variable
        self.command = command
        self.bind("<ButtonRelease-1>", self._click)
        self._trace = variable.trace_add("write", lambda *a: self._draw())
        self.bind("<Destroy>", lambda e: self._untrace())
        self._draw()

    def _untrace(self):
        try:
            self.var.trace_remove("write", self._trace)
        except tk.TclError:
            pass

    def _draw(self):
        self.delete("all")
        on = self.var.get()
        round_rect(self, 0, 0, self.w, self.h, self.h / 2, fill=C["accent"] if on else C["toggle_off"], outline="")
        m = UI.px(3)
        d = self.h - 2 * m
        x = self.w - m - d if on else m
        self.create_oval(x, m, x + d, m + d, fill="#FFFFFF", outline="")

    def _click(self, event):
        self.var.set(not self.var.get())
        if self.command:
            self.command()


class LineChart(tk.Canvas):
    """Robinhood-style line chart: no axes, optional dotted baseline, crosshair on hover.

    on_hover(index or None) is called as the mouse moves, so the caller can show that point's value.
    `slots` reserves room for more points than there are (e.g. a full trading day while the market is open).
    pulse=True marks the latest point with a dot and a halo that keeps swelling and fading (a live price).
    """

    PULSE_PERIOD = 1.8  # seconds per pulse: the halo grows and fades over most of it, then rests
    PULSE_FPS = 30

    def __init__(self, parent, height: int, *, on_hover=None, interactive=True, pad=10, line_width=2.0, bg=None,
                 width=None):
        kw = {"width": width} if width else {}
        super().__init__(parent, height=height, bg=bg or C["bg"], highlightthickness=0, bd=0, **kw)
        self.on_hover = on_hover
        self.pad = UI.px(pad)
        self.line_width = UI.px(line_width) or 1
        self.values: list[float] = []
        self.labels: list[str] = []
        self.baseline: float | None = None
        self.color = C["gain"]
        self.slots = 0
        self.message = ""
        self.pulse = False
        self._pulse_at: tuple[float, float] | None = None  # where the latest point is drawn
        self._pulse_job = None
        self._hovering = False
        self.bind("<Configure>", lambda e: self.redraw())
        self.bind("<Destroy>", lambda e: self._stop_pulse() if e.widget is self else None, add="+")
        if interactive:
            self.bind("<Motion>", self._motion)
            self.bind("<Leave>", self._leave)

    def set_data(self, values, *, color=None, baseline=None, labels=None, slots=0, message="", pulse=False):
        self.values = list(values)
        self.labels = list(labels or [])
        self.baseline = baseline
        self.color = color or C["gain"]
        self.slots = slots
        self.message = message
        self.pulse = pulse and len(self.values) >= 2
        self.redraw()
        if self.pulse and self._pulse_job is None:
            self._pulse_tick()
        elif not self.pulse:
            self._stop_pulse()

    def _xy(self):
        w, h = self.winfo_width(), self.winfo_height()
        n = max(len(self.values), self.slots, 2)
        lo = min(self.values + ([self.baseline] if self.baseline is not None else []))
        hi = max(self.values + ([self.baseline] if self.baseline is not None else []))
        if hi == lo:
            hi, lo = hi + 1, lo - 1
        p = self.pad
        top = p + UI.px(14)  # room for the hover label
        x = lambda i: p + i * (w - 2 * p) / (n - 1)  # noqa: E731
        y = lambda v: top + (hi - v) * (h - top - p) / (hi - lo)  # noqa: E731
        return x, y

    def redraw(self):
        self.delete("all")
        if len(self.values) < 2:
            if self.message:
                self.create_text(self.winfo_width() / 2, self.winfo_height() / 2, text=self.message,
                                 fill=C["muted"], font=UI.body)
            return
        x, y = self._xy()
        self._pulse_at = None
        if self.pulse:  # the halo goes under everything else, so the line stays crisp on top of it
            self._pulse_at = (x(len(self.values) - 1), y(self.values[-1]))
            self.create_oval(0, 0, 0, 0, fill=C["bg"], outline="", state="hidden", tags="halo")
        if self.baseline is not None:
            yb = y(self.baseline)
            self.create_line(self.pad, yb, self.winfo_width() - self.pad, yb, fill=C["muted"],
                             dash=(1, 4), width=1)
        coords = [c for i, v in enumerate(self.values) for c in (x(i), y(v))]
        self.create_line(*coords, fill=self.color, width=self.line_width, capstyle="round", joinstyle="round")
        if self._pulse_at:
            cx, cy = self._pulse_at
            r = UI.px(4.5)
            self.create_oval(cx - r, cy - r, cx + r, cy + r, fill=self.color, outline="", tags="dot")
            if self._hovering:
                self.itemconfigure("dot", state="hidden")

    # ---- the live dot's pulse
    def _mix(self, a: str, b: str, t: float) -> str:
        """Color a blended toward b by t (0..1); the canvas has no transparency, so fading means blending."""
        (r1, g1, b1), (r2, g2, b2) = self.winfo_rgb(a), self.winfo_rgb(b)
        return "#%02x%02x%02x" % tuple(int((u + (v - u) * t) / 257) for u, v in ((r1, r2), (g1, g2), (b1, b2)))

    def _pulse_tick(self):
        self._pulse_job = None
        if not self.pulse:
            return
        try:
            visible = self.winfo_viewable()
        except tk.TclError:  # destroyed
            return
        if visible and self._pulse_at and not self._hovering:
            phase = (time.monotonic() % self.PULSE_PERIOD) / self.PULSE_PERIOD
            grow = min(phase / 0.75, 1.0)  # swell over the first 3/4, then rest unseen
            ease = 1 - (1 - grow) ** 3  # fast at first, slowing as it widens
            r = UI.px(4.5) + ease * UI.px(13)
            cx, cy = self._pulse_at
            self.coords("halo", cx - r, cy - r, cx + r, cy + r)
            # starts as a soft tint of the line color and fades into the background
            self.itemconfigure("halo", fill=self._mix(self.color, C["bg"], 0.5 + 0.5 * grow),
                               state="hidden" if grow >= 1 else "normal")
        # when the window is minimized or covered by another page, check back slowly instead of animating
        self._pulse_job = self.after(1000 // self.PULSE_FPS if visible else 500, self._pulse_tick)

    def _stop_pulse(self):
        if self._pulse_job is not None:
            try:
                self.after_cancel(self._pulse_job)
            except tk.TclError:
                pass
            self._pulse_job = None

    def _motion(self, event):
        self.delete("hover")
        if len(self.values) < 2:
            return
        self._hovering = True  # the crosshair's own dot takes over from the live dot
        self.itemconfigure("halo", state="hidden")
        self.itemconfigure("dot", state="hidden")
        x, y = self._xy()
        n = max(len(self.values), self.slots, 2)
        step = (self.winfo_width() - 2 * self.pad) / (n - 1)
        i = min(max(round((event.x - self.pad) / step), 0), len(self.values) - 1)
        xi, yi = x(i), y(self.values[i])
        self.create_line(xi, self.pad + UI.px(14), xi, self.winfo_height() - self.pad, fill=C["muted"], width=1,
                         tags="hover")
        r = UI.px(5)
        self.create_oval(xi - r, yi - r, xi + r, yi + r, fill=self.color, outline=C["bg"], width=2, tags="hover")
        if i < len(self.labels):
            tx = min(max(xi, UI.px(60)), self.winfo_width() - UI.px(60))
            self.create_text(tx, self.pad, text=self.labels[i], fill=C["muted"], font=UI.small, anchor="n",
                             tags="hover")
        if self.on_hover:
            self.on_hover(i)

    def _leave(self, event):
        self.delete("hover")
        self._hovering = False
        self.itemconfigure("dot", state="normal")
        if self.on_hover:
            self.on_hover(None)


class TabBar(tk.Frame):
    """Row of text tabs; the active one is bold with a colored underline.
    `labels` ({key: text}) shows different text than the keys handed to `command` (e.g. translated)."""

    def __init__(self, parent, items: list[str], command, *, font=None, gap=20, active=None, accent=None,
                 labels: dict[str, str] | None = None):
        super().__init__(parent, bg=C["bg"])
        self.command = command
        self.accent = accent or C["accent"]
        self.font = font or UI.bold
        self.items: dict[str, tuple[tk.Label, tk.Frame]] = {}
        for i, key in enumerate(items):
            lbl = label(self, (labels or {}).get(key, key), font=self.font, color=C["muted"], cursor="hand2")
            lbl.grid(row=0, column=i, padx=(0, UI.px(gap)), pady=(0, UI.px(4)))
            bar = tk.Frame(self, height=UI.px(2), bg=C["bg"])
            bar.grid(row=1, column=i, sticky="we", padx=(0, UI.px(gap)))
            lbl.bind("<Button-1>", lambda e, k=key: self.select(k, notify=True))
            self.items[key] = (lbl, bar)
        self.active = active or items[0]
        self.select(self.active)

    def set_accent(self, color: str):
        self.accent = color
        self.select(self.active)

    def select(self, key: str, notify: bool = False):
        self.active = key
        for k, (lbl, bar) in self.items.items():
            on = k == key
            lbl.configure(fg=self.accent if on else C["muted"])
            bar.configure(bg=self.accent if on else C["bg"])
        if notify:
            self.command(key)


class ScrollFrame(tk.Frame):
    """A vertically scrollable frame; put children in .inner. The scrollbar only shows when needed."""

    def __init__(self, parent, **kw):
        super().__init__(parent, bg=kw.pop("bg", C["bg"]), **kw)
        self.canvas = tk.Canvas(self, bg=self["bg"], highlightthickness=0, bd=0)
        self.inner = tk.Frame(self.canvas, bg=self["bg"])
        self.sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview, style="Slim.Vertical.TScrollbar")
        self.canvas.configure(yscrollcommand=self.sb.set)
        self.win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner.bind("<Configure>", lambda e: self._update())
        self.canvas.bind("<Configure>", lambda e: (self.canvas.itemconfigure(self.win, width=e.width), self._update()))
        self.bind("<Enter>", lambda e: self._wheel(True))
        self.bind("<Leave>", lambda e: self._wheel(False))

    def _update(self):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        need = self.inner.winfo_reqheight() > self.canvas.winfo_height() > 1
        if need and not self.sb.winfo_ismapped():
            self.sb.pack(side="right", fill="y")
        elif not need and self.sb.winfo_ismapped():
            self.sb.pack_forget()
            self.canvas.yview_moveto(0)

    def _wheel(self, on: bool):
        seqs = ("<MouseWheel>", "<Button-4>", "<Button-5>")
        if on:
            def scroll(e):
                if self.sb.winfo_ismapped():
                    self.canvas.yview_scroll(-1 if (e.num == 4 or e.delta > 0) else 1, "units")
            for s in seqs:
                self.bind_all(s, scroll)
        else:
            for s in seqs:
                self.unbind_all(s)


class PageScroll(tk.Frame):
    """A whole page that scrolls up and down when the window is too short for it; put children in .inner.

    With room to spare the page is as tall as the window, so a table can stretch to fill the rest; otherwise it
    is as tall as its content needs and a slim scroll bar shows. Call bind_wheel() once the page is built so the
    mouse wheel scrolls it (a table that has rows to scroll keeps the wheel for itself)."""

    def __init__(self, parent, **kw):
        super().__init__(parent, bg=C["bg"], **kw)
        self.canvas = tk.Canvas(self, bg=C["bg"], highlightthickness=0, bd=0, yscrollincrement=UI.px(30))
        self.inner = tk.Frame(self.canvas, bg=C["bg"])
        self.sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview, style="Slim.Vertical.TScrollbar")
        self.canvas.configure(yscrollcommand=self.sb.set)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner.bind("<Configure>", lambda e: self._fit())
        self.canvas.bind("<Configure>", lambda e: self._fit())

    def _fit(self):
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        need = self.inner.winfo_reqheight()
        height = max(h, need)
        self.canvas.itemconfigure(self._win, width=w, height=height)
        self.canvas.configure(scrollregion=(0, 0, w, height))
        scrolls = need > h > 1
        if scrolls and not self.sb.winfo_ismapped():
            self.sb.pack(side="right", fill="y")
        elif not scrolls and self.sb.winfo_ismapped():
            self.sb.pack_forget()
            self.canvas.yview_moveto(0)

    def refit(self):
        """Re-measure after the content changed size (e.g. another tab was shown)."""
        self.update_idletasks()
        self._fit()

    def bind_wheel(self):
        def scroll(e):
            if not self.sb.winfo_ismapped() or e.state & 0x1:  # nothing to scroll; Shift = sideways, for tables
                return
            kind = e.widget.winfo_class()
            if kind == "TCombobox" or (kind == "Treeview" and e.widget.yview() != (0.0, 1.0)):
                return
            self.canvas.yview_scroll(-2 if (e.num == 4 or e.delta > 0) else 2, "units")

        def walk(widget):
            for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                widget.bind(seq, scroll, add="+")
            for child in widget.winfo_children():
                walk(child)

        walk(self)


class SymbolEntry(ttk.Entry):
    """A text box with a type-ahead dropdown of matching stocks, like Robinhood's search.

    suggest(query, show) is called as the user types (and on Down, or a click into an empty box).
    It calls show(query, items) as often as it likes -- e.g. once with offline matches, again when
    an online search comes back -- with items as (symbol, name, detail) tuples. Results for text
    that is no longer in the box are ignored. Picking a row puts its symbol in the box and fires
    <<SymbolPicked>>.
    Keys: Up/Down move through the list, Enter or Tab picks, Escape closes it.
    """

    MAX_ROWS = 8
    NAME_CHARS = 30  # longer company names are cut off with an ellipsis

    def __init__(self, parent, textvariable: tk.StringVar, suggest, **kw):
        super().__init__(parent, textvariable=textvariable, **kw)
        self.var = textvariable
        self.suggest = suggest
        self.items: list[tuple[str, str, str]] = []
        self.active = -1  # highlighted row, -1 = none
        self.popup: tk.Toplevel | None = None
        self.row_widgets: list[list[tk.Widget]] = []
        self._quiet = textvariable.get()  # text put in the box by the program, not typed: no dropdown for it

        # Our own bind tag in front of the widget's, so these keys are seen first and can stop
        # Enter/Escape from also reaching the dialog (save/cancel) or the widget's own bindings
        self._tag = f"SymbolEntry{id(self)}"
        self.bindtags((self._tag, *self.bindtags()))
        self._keys = {
            "<Down>": lambda e: self._move(1),
            "<Up>": lambda e: self._move(-1),
            "<Return>": self._on_return,
            "<KP_Enter>": self._on_return,
            "<Tab>": self._on_tab,
            "<Escape>": self._on_escape,
        }
        for seq, fn in self._keys.items():
            self.bind_class(self._tag, seq, fn)
        self.bind("<FocusOut>", lambda e: self.after(150, self._close_if_unfocused), add="+")
        self.bind("<Button-1>", lambda e: self.after_idle(self._open_if_empty), add="+")
        self.bind("<Destroy>", self._on_destroy, add="+")
        self._trace = textvariable.trace_add("write", self._on_change)
        self._top = self.winfo_toplevel()
        self._top.bind("<Configure>", self._on_move, add="+")

    # ---- input
    def _has_focus(self) -> bool:
        try:
            return self.focus_get() is self
        except (KeyError, tk.TclError):  # focus is in a widget tkinter does not know (e.g. a combobox list)
            return False

    def _on_change(self, *args):
        text = self.var.get()
        if text == self._quiet or not self._has_focus():
            return
        self._quiet = None
        self.suggest(text, self._show)

    def _open_if_empty(self):
        if self.winfo_exists() and not self.var.get().strip() and self.popup is None:
            self.suggest("", self._show)

    def _move(self, step: int):
        if self.popup is None:
            self.suggest(self.var.get(), self._show)
        elif self.items:
            self.active = (self.active + step) % len(self.items) if self.active >= 0 else (0 if step > 0 else len(self.items) - 1)
            self._highlight()
        return "break"

    def _on_return(self, event):
        if self.popup is None:
            return None
        if self.active < 0:
            self.close()
            return None
        # When the box already holds exactly the highlighted symbol, let Enter go on to its normal job (e.g. Save)
        same = self.items[self.active][0] == self.var.get()
        self.pick(self.active)
        return None if same else "break"

    def _on_tab(self, event):
        if self.popup is not None and self.active >= 0:
            self.pick(self.active, notify=False)  # Tab moves the focus on by itself
        self.close()
        return None

    def _on_escape(self, event):
        if self.popup is None:
            return None  # let Escape close the dialog
        self.close()
        return "break"

    def pick(self, index: int, notify: bool = True):
        symbol = self.items[index][0]
        self._quiet = symbol
        self.var.set(symbol)
        self.icursor("end")
        self.close()
        self.focus_set()
        if notify:
            self.event_generate("<<SymbolPicked>>")

    # ---- dropdown
    def _show(self, query: str, items):
        if not self.winfo_exists() or query != self.var.get() or not self._has_focus():
            return
        items = list(items)[: self.MAX_ROWS]
        if not items:
            self.close()
            return
        keep = self.items[self.active][0] if self.popup is not None and 0 <= self.active < len(self.items) else None
        self.items = items
        symbols = [i[0] for i in items]
        if keep in symbols:  # an update arrived while a row was highlighted: keep it highlighted
            self.active = symbols.index(keep)
        else:  # Robinhood-style: the top match is ready to pick with Enter (but not for the unfiltered list)
            self.active = 0 if query.strip() else -1
        self._render()

    def _render(self):
        if self.popup is None:
            self.popup = tk.Toplevel(self, bg=C["border"])
            self.popup.withdraw()
            self.popup.overrideredirect(True)
            try:
                self.popup.attributes("-topmost", True)
            except tk.TclError:
                pass
            self.list_frame = tk.Frame(self.popup, bg=C["chip"])
            self.list_frame.pack(fill="both", expand=True, padx=1, pady=1)
        for w in self.list_frame.winfo_children():
            w.destroy()
        self.row_widgets = []
        pad = UI.px(10)
        for i, (sym, name, detail) in enumerate(self.items):
            if len(name) > self.NAME_CHARS:
                name = name[: self.NAME_CHARS - 1].rstrip() + "…"
            row = tk.Frame(self.list_frame, bg=C["chip"])
            row.pack(fill="x")
            parts = [
                label(row, sym, font=UI.bold, bg=C["chip"], anchor="w", width=7),
                label(row, name, color=C["muted"], bg=C["chip"], anchor="w"),
                label(row, detail, font=UI.small, color=C["muted"], bg=C["chip"], anchor="e"),
            ]
            parts[0].pack(side="left", padx=(pad, UI.px(6)), pady=UI.px(6))
            parts[2].pack(side="right", padx=(UI.px(12), pad))
            parts[1].pack(side="left", fill="x", expand=True)
            for w in (row, *parts):
                w.bind("<Button-1>", lambda e, i=i: self.pick(i))
                # Motion rather than Enter: a list that opens under a resting mouse must not move the highlight
                w.bind("<Motion>", lambda e, i=i: self._hover(i))
                w.configure(cursor="hand2")
            self.row_widgets.append([row, *parts])
        self._highlight()
        self._place()

    def _hover(self, index: int):
        if index != self.active:
            self.active = index
            self._highlight()

    def _highlight(self):
        for i, widgets in enumerate(self.row_widgets):
            bg = C["chip_hover"] if i == self.active else C["chip"]
            for w in widgets:
                w.configure(bg=bg)

    def _place(self):
        if self.popup is None:
            return
        self.popup.update_idletasks()
        width = max(self.winfo_width(), self.list_frame.winfo_reqwidth() + 2, UI.px(340))
        height = self.list_frame.winfo_reqheight() + 2
        x, y = self.winfo_rootx(), self.winfo_rooty() + self.winfo_height() + UI.px(2)
        self.popup.geometry(f"{width}x{height}+{x}+{y}")
        self.popup.deiconify()
        self.popup.lift()

    def _on_move(self, event):
        if event.widget is self._top and self.popup is not None:
            self._place()  # the dialog moved or grew: keep the list under the box

    def _close_if_unfocused(self):
        if self.winfo_exists() and not self._has_focus():
            self.close()

    def close(self):
        if self.popup is not None:
            self.popup.destroy()
            self.popup = None
        self.items, self.row_widgets, self.active = [], [], -1

    def _on_destroy(self, event):
        if event.widget is not self:
            return
        self.close()
        try:
            self.var.trace_remove("write", self._trace)
        except tk.TclError:
            pass
        for seq in self._keys:
            self.unbind_class(self._tag, seq)


# ======================================================================
# Tables
# ======================================================================
WHEEL_STEP = 80  # pixels a table scrolls sideways per notch of the mouse wheel


def make_tree(parent, columns: list[tuple[str, str, int, str]]):
    """Create a table with slim scrollbars, click-to-sort headers and row hover.
    columns: (key, title, width, anchor w/e/center)

    A column never gets narrower than its width: when the window is too small for all of them the table
    scrolls sideways (the scrollbar only shows then, and Shift + wheel moves it); when there is room the
    columns stretch to fill it.
    It asks for 5 rows; with more room it grows, with less the page it sits on scrolls (see PageScroll)."""
    frame = ttk.Frame(parent)
    tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings", selectmode="browse", height=5)
    for key, text, width, anchor in columns:
        tree.heading(key, text=text.upper(), anchor=anchor, command=lambda k=key: sort_tree(tree, k))
        tree.column(key, width=UI.px(width), minwidth=UI.px(width), anchor=anchor, stretch=True)
    vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview, style="Slim.Vertical.TScrollbar")
    hsb = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview, style="Slim.Horizontal.TScrollbar")

    def on_xscroll(first, last):
        hsb.set(first, last)
        if float(first) <= 0 and float(last) >= 1:
            hsb.grid_remove()
        else:
            hsb.grid()

    def sideways(event):
        # Tk's own binding moves 1 pixel (Windows) or 5 (Linux) per wheel notch, far too slow for a wide table
        notches = {4: 1, 5: -1}.get(event.num, event.delta / 120)
        tree.xview_scroll(round(-notches * UI.px(WHEEL_STEP)), "units")  # a ttk "unit" is one pixel
        return "break"

    for widget, sequences in ((tree, ("<Shift-MouseWheel>", "<Shift-Button-4>", "<Shift-Button-5>")),
                              (hsb, ("<MouseWheel>", "<Button-4>", "<Button-5>"))):
        for sequence in sequences:
            widget.bind(sequence, sideways)

    tree.configure(yscrollcommand=vsb.set, xscrollcommand=on_xscroll)
    tree.grid(row=0, column=0, sticky="nsew")
    vsb.grid(row=0, column=1, sticky="ns")
    hsb.grid(row=1, column=0, sticky="we")
    hsb.grid_remove()
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    tree.tag_configure("hover", background=C["hover"])
    tree.tag_configure("gain", foreground=C["gain"])
    tree.tag_configure("loss", foreground=C["loss"])
    tree.tag_configure("muted", foreground=C["muted"])
    tree.sort_state = {}
    tree.hover_row = ""

    def hover(event):
        row = tree.identify_row(event.y)
        if row == tree.hover_row:
            return
        for iid, add in ((tree.hover_row, False), (row, True)):
            if iid and tree.exists(iid):
                tags = [t for t in tree.item(iid, "tags") if t != "hover"]
                tree.item(iid, tags=tags + ["hover"] if add else tags)
        tree.hover_row = row

    tree.bind("<Motion>", hover)
    tree.bind("<Leave>", lambda e: (setattr(e, "y", -100), hover(e)))
    return frame, tree


def sort_tree(tree: ttk.Treeview, col: str, desc: bool | None = None) -> None:
    """Sort by a column; desc=None toggles the direction (a header click)."""
    if desc is None:
        desc = not tree.sort_state.get(col, False)
    tree.sort_state = {col: desc}

    def key(iid):
        text = tree.set(iid, col)
        m = re.fullmatch(r"([+-]?[\d,]*\.?\d+)%?(\s*\(.*\))?", text)
        return (0, float(m.group(1).replace(",", ""))) if m else (1, text)

    items = sorted(tree.get_children(""), key=key, reverse=desc)
    blanks = [iid for iid in items if tree.set(iid, col) in ("", "-")]
    items = [iid for iid in items if iid not in blanks] + blanks  # empty cells last either way
    for index, iid in enumerate(items):
        tree.move(iid, "", index)

