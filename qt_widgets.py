"""Native Qt widgets with the ledger's existing declarative layout vocabulary.

The small pack/grid helpers preserve the original page geometry while every
control, event, timer, font, dialog and drawing operation is owned by PyQt6.
There is no Tcl/Tk interpreter or second event loop.
"""
from __future__ import annotations

import itertools
import re
from pathlib import Path
from types import SimpleNamespace

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QEventLoop, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import (
    QAction, QActionGroup, QColor, QFont, QFontDatabase, QFontMetrics, QIcon,
    QPainter, QPainterPath, QPen, QPolygonF, QTextBlockFormat, QTextCharFormat, QTextCursor,
)
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QGridLayout,
    QLabel, QLayout, QLineEdit, QListWidget, QMenu, QMessageBox, QPushButton,
    QScrollArea, QScrollBar, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget, QWidgetItem,
)

WidgetError = RuntimeError
_application = None
_names = itertools.count()
_jobs = {}
_styles = {}


def application():
    global _application
    _application = QApplication.instance() or QApplication([])
    return _application


class Font(QFont):
    def copy(self):
        return Font(self)

    def configure(self, **kw):
        if "family" in kw:
            self.setFamily(kw["family"])
        if "size" in kw:
            self.setPointSize(kw["size"])
        if "weight" in kw:
            self.setBold(kw["weight"] == "bold")

    def measure(self, text):
        return QFontMetrics(self).horizontalAdvance(str(text))

    def metrics(self, name):
        metrics = QFontMetrics(self)
        return {"linespace": metrics.height(), "ascent": metrics.ascent(), "descent": metrics.descent()}[name]


def families(root=None):
    application()
    return QFontDatabase.families()


class Variable:
    def __init__(self, master=None, value=None):
        self.value = self.convert(value)
        self._traces = {}

    def convert(self, value):
        return value

    def get(self):
        return self.value

    def set(self, value):
        self.value = self.convert(value)
        for callback in list(self._traces.values()):
            callback("", "", "write")

    def trace_add(self, mode, callback):
        key = str(next(_names))
        self._traces[key] = callback
        return key

    def trace_remove(self, mode, key):
        self._traces.pop(key, None)


class StringVar(Variable):
    def convert(self, value):
        return "" if value is None else str(value)


class BooleanVar(Variable):
    def convert(self, value):
        return bool(value)


class IntVar(Variable):
    def convert(self, value):
        return int(value or 0)


def _pair(value):
    return (value, value) if isinstance(value, (int, float)) else value


def _alignment(anchor):
    anchor = "" if anchor == "center" else anchor
    result = Qt.AlignmentFlag(0)
    result |= Qt.AlignmentFlag.AlignLeft if "w" in anchor else Qt.AlignmentFlag.AlignRight if "e" in anchor else Qt.AlignmentFlag.AlignHCenter
    result |= Qt.AlignmentFlag.AlignTop if "n" in anchor else Qt.AlignmentFlag.AlignBottom if "s" in anchor else Qt.AlignmentFlag.AlignVCenter
    return result


class DockLayout(QLayout):
    """Cavity layout: the same ordered top/bottom/left/right packing as the old UI."""
    def __init__(self, parent):
        super().__init__(parent)
        self.entries = []
        self.setContentsMargins(*parent._padding)
        self.setSpacing(0)

    def addItem(self, item):
        self.entries.append((item, {}))

    def count(self):
        return len(self.entries)

    def itemAt(self, index):
        return self.entries[index][0] if 0 <= index < self.count() else None

    def takeAt(self, index):
        return self.entries.pop(index)[0] if 0 <= index < self.count() else None

    def sizeHint(self):
        return self._required(self.entries)

    def minimumSize(self):
        return self.sizeHint()

    def _required(self, entries):
        width = height = 0
        for item, opts in reversed(entries):
            hint = item.sizeHint()
            px, py = _pair(opts.get("padx", 0)), _pair(opts.get("pady", 0))
            w, h = hint.width() + sum(px), hint.height() + sum(py)
            if opts.get("side", "top") in ("left", "right"):
                width, height = width + w, max(height, h)
            else:
                width, height = max(width, w), height + h
        l, t, r, b = self.getContentsMargins()
        return QSize(width + l + r, height + t + b)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        l, t, r, b = self.getContentsMargins()
        cavity = rect.adjusted(l, t, -r, -b)
        for index, (item, opts) in enumerate(self.entries):
            side = opts.get("side", "top")
            horizontal = side in ("left", "right")
            hint = item.sizeHint()
            px, py = _pair(opts.get("padx", 0)), _pair(opts.get("pady", 0))
            extent = (hint.width() + sum(px)) if horizontal else (hint.height() + sum(py))
            if opts.get("expand"):
                remaining = self.entries[index:]
                required = self._required(remaining)
                count = sum(bool(o.get("expand")) for _, o in remaining if (o.get("side", "top") in ("left", "right")) == horizontal)
                extra = (cavity.width() - required.width()) if horizontal else (cavity.height() - required.height())
                extent += max(0, extra) // max(count, 1)
            extent = max(0, min(extent, cavity.width() if horizontal else cavity.height()))
            if side == "left":
                parcel = QRect(cavity.x(), cavity.y(), extent, cavity.height())
                cavity.setLeft(cavity.left() + extent)
            elif side == "right":
                parcel = QRect(cavity.right() - extent + 1, cavity.y(), extent, cavity.height())
                cavity.setRight(cavity.right() - extent)
            elif side == "bottom":
                parcel = QRect(cavity.x(), cavity.bottom() - extent + 1, cavity.width(), extent)
                cavity.setBottom(cavity.bottom() - extent)
            else:
                parcel = QRect(cavity.x(), cavity.y(), cavity.width(), extent)
                cavity.setTop(cavity.top() + extent)
            parcel.adjust(px[0], py[0], -px[1], -py[1])
            fill = opts.get("fill", "none")
            w = max(0, parcel.width() if fill in ("x", "both") else min(hint.width(), parcel.width()))
            h = max(0, parcel.height() if fill in ("y", "both") else min(hint.height(), parcel.height()))
            aligned = parcel
            anchor = opts.get("anchor", "")
            x = aligned.x() if "w" in anchor else aligned.right() - w + 1 if "e" in anchor else aligned.x() + (aligned.width() - w) // 2
            y = aligned.y() if "n" in anchor else aligned.bottom() - h + 1 if "s" in anchor else aligned.y() + (aligned.height() - h) // 2
            item.setGeometry(QRect(x, y, w, h))

    def put(self, widget, opts):
        self.removeWidget(widget)
        self.addChildWidget(widget)
        entry = (QWidgetItem(widget), opts)
        before = opts.get("before")
        index = next((i for i, (item, _) in enumerate(self.entries) if item.widget() is before), len(self.entries))
        self.entries.insert(index, entry)
        self.invalidate()


class GridLayout(QGridLayout):
    """Keep unused grid space at the bottom/right unless a row/column expands."""
    def __init__(self, parent):
        super().__init__(parent)
        self._rows = self._cols = 0
        self._row_weights = {}
        self._col_weights = {}
        self.setContentsMargins(*parent._padding)
        self.setSpacing(0)

    def addWidget(self, widget, row, col, rowspan=1, colspan=1):
        QGridLayout.setRowStretch(self, self._rows, self._row_weights.get(self._rows, 0))
        QGridLayout.setColumnStretch(self, self._cols, self._col_weights.get(self._cols, 0))
        self._rows = max(self._rows, row + rowspan)
        self._cols = max(self._cols, col + colspan)
        super().addWidget(widget, row, col, rowspan, colspan)
        self._balance()

    def _balance(self):
        QGridLayout.setRowStretch(self, self._rows, 0 if any(self._row_weights.values()) else 1)
        QGridLayout.setColumnStretch(self, self._cols, 0 if any(self._col_weights.values()) else 1)

    def setRowStretch(self, row, weight):
        self._row_weights[row] = weight
        QGridLayout.setRowStretch(self, row, weight)
        self._balance()

    def setColumnStretch(self, col, weight):
        self._col_weights[col] = weight
        QGridLayout.setColumnStretch(self, col, weight)
        self._balance()


class WidgetMixin:
    def _init(self, parent=None, **kw):
        self.master = parent
        self._logical_children = []
        if parent is not None and hasattr(parent, "_logical_children"):
            parent._logical_children.append(self)
        self._opts = {}
        self._bindings = {}
        self._priority_bindings = {}
        self._timers = set()
        self._dead = False
        self._manager = ""
        self._layout_box = None
        self._padding = (0, 0, 0, 0)
        self.setObjectName(f"ledger{next(_names)}")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMouseTracking(True)
        self.installEventFilter(self)
        self.configure(**kw)
        # A constructed control stays hidden until the page explicitly places it.
        # Qt otherwise reveals unmanaged children when their parent is shown.
        QWidget.hide(self)

    def configure(self, cnf=None, **kw):
        if cnf:
            kw.update(cnf)
        aliases = {"background": "bg", "foreground": "fg", "borderwidth": "bd"}
        kw = {aliases.get(k, k): v for k, v in kw.items()}
        self._opts.update(kw)
        if "font" in kw:
            self.setFont(kw["font"])
        if "padding" in kw:
            pad = kw["padding"]
            self._padding = (pad, pad, pad, pad) if isinstance(pad, int) else tuple(pad)
            if self.layout():
                self.layout().setContentsMargins(*self._padding)
        if "cursor" in kw:
            self.setCursor(Qt.CursorShape.PointingHandCursor if kw["cursor"] == "hand2" else Qt.CursorShape.ArrowCursor)
        if "bg" in kw or "fg" in kw:
            rules = []
            if self._opts.get("bg"):
                rules.append(f"background-color: {self._opts['bg']}")
            if self._opts.get("fg"):
                rules.append(f"color: {self._opts['fg']}")
            self.setStyleSheet(f"#{self.objectName()} {{ {'; '.join(rules)}; }}")
        if "state" in kw:
            self.setEnabled(kw["state"] != "disabled" or isinstance(self, QTextEdit))
            if isinstance(self, QTextEdit):
                self.setReadOnly(kw["state"] == "disabled")
        self.updateGeometry()
        self.update()

    config = configure

    def cget(self, key):
        return self._opts.get({"background": "bg", "foreground": "fg"}.get(key, key), "")

    def __getitem__(self, key):
        return self.cget(key)

    def __setitem__(self, key, value):
        self.configure(**{key: value})

    def _detach(self):
        if self._layout_box:
            self.master.layout().removeWidget(self._layout_box)
            self.setParent(self.master)
            self._layout_box.deleteLater()
            self._layout_box = None
        elif self.master and self.master.layout():
            self.master.layout().removeWidget(self)

    def pack(self, **kw):
        if self._manager == "pack" and (not kw or kw == self._pack_opts):
            QWidget.show(self)
            return
        self._detach()
        if self.master.layout() is None:
            DockLayout(self.master)
        self._pack_opts = kw or getattr(self, "_pack_opts", {})
        self.master.layout().put(self, self._pack_opts)
        self._manager = "pack"
        QWidget.show(self)

    def pack_forget(self):
        if not self._manager:
            QWidget.hide(self)
            return
        self._detach()
        self._manager = ""
        QWidget.hide(self)

    def pack_info(self):
        return dict(self._pack_opts)

    def pack_slaves(self):
        layout = self.layout()
        return [item.widget() for item, _ in layout.entries] if isinstance(layout, DockLayout) else []

    def pack_propagate(self, value):
        if not value and self._opts.get("width"):
            self.setFixedWidth(self._opts["width"])

    def grid(self, **kw):
        if self._manager == "grid" and (not kw or kw == self._grid_opts):
            QWidget.show(self)
            return
        self._detach()
        if self.master.layout() is None:
            GridLayout(self.master)
        layout = self.master.layout()
        self._grid_opts = kw or getattr(self, "_grid_opts", {})
        opts = self._grid_opts
        box = self._layout_box = QWidget(self.master)
        box.setObjectName(f"spacing{next(_names)}")
        box.setStyleSheet(f"#{box.objectName()} {{ background: transparent; }}")
        inside = QVBoxLayout(box)
        px, py = _pair(opts.get("padx", 0)), _pair(opts.get("pady", 0))
        inside.setContentsMargins(px[0], py[0], px[1], py[1])
        inside.setSpacing(0)
        sticky = opts.get("sticky", "")
        align = Qt.AlignmentFlag(0)
        if not ("w" in sticky and "e" in sticky):
            align |= Qt.AlignmentFlag.AlignLeft if "w" in sticky else Qt.AlignmentFlag.AlignRight if "e" in sticky else Qt.AlignmentFlag.AlignHCenter
        if not ("n" in sticky and "s" in sticky):
            align |= Qt.AlignmentFlag.AlignTop if "n" in sticky else Qt.AlignmentFlag.AlignBottom if "s" in sticky else Qt.AlignmentFlag.AlignVCenter
        inside.addWidget(self, 1, align)
        layout.addWidget(box, opts.get("row", 0), opts.get("column", 0), opts.get("rowspan", 1), opts.get("columnspan", 1))
        self._manager = "grid"
        QWidget.show(self)
        box.show()

    grid_remove = pack_forget
    grid_forget = pack_forget

    def columnconfigure(self, column, weight=0, uniform=None, minsize=0):
        if self.layout() is None:
            GridLayout(self)
        self.layout().setColumnStretch(column, weight)
        self.layout().setColumnMinimumWidth(column, minsize)
        if uniform:
            self.layout().setColumnStretch(column, max(1, weight))

    def rowconfigure(self, row, weight=0, **kw):
        if self.layout() is None:
            self.columnconfigure(0)
        self.layout().setRowStretch(row, weight)

    def bind(self, sequence, callback, add=None):
        if sequence.startswith(("<Button", "<Double", "<Motion")):
            # Qt bubbles ignored mouse events to parent widgets; the original
            # widget bindings do not. Keep native editing/focus handling while
            # preventing a stock-row or dropdown click from firing twice.
            self.setAttribute(Qt.WidgetAttribute.WA_NoMousePropagation, True)
        if add != "+":
            self._bindings[sequence] = []
        self._bindings.setdefault(sequence, []).append(callback)
        return str(id(callback))

    def unbind(self, sequence, key=None):
        self._bindings.pop(sequence, None)

    def bind_all(self, sequence, callback):
        return self.bind(sequence, callback, "+")

    def _dispatch(self, sequence, event=None):
        event = event or SimpleNamespace(widget=self, x=0, y=0, state=0, delta=0, num=0)
        for callback in list(self._priority_bindings.get(sequence, [])) + list(self._bindings.get(sequence, [])):
            result = callback(event)
            if isinstance(result, str) and result == "break":
                return True
        return False

    def event_generate(self, sequence, **kw):
        values = dict(widget=self, x=0, y=0, state=0, delta=0, num=0)
        if "Shift-" in sequence:
            values["state"] = 1
        if "Button-4" in sequence or "Button-5" in sequence:
            values["num"] = 4 if "Button-4" in sequence else 5
            values["delta"] = 120 if values["num"] == 4 else -120
        values.update(kw)
        event = SimpleNamespace(**values)
        if self._dispatch(sequence, event):
            return
        if "MouseWheel" in sequence or values["num"] in (4, 5):
            parent = self.master
            while parent:
                if hasattr(parent, "_page_wheel") and parent._page_wheel(event):
                    break
                parent = getattr(parent, "master", None)

    def eventFilter(self, watched, event):
        kind = event.type()
        data = SimpleNamespace(widget=self, x=0, y=0, state=0, delta=0, num=0, width=self.width(), height=self.height())
        sequence = None
        if kind in (QEvent.Type.Resize, QEvent.Type.Move):
            sequence = "<Configure>"
        elif kind in (QEvent.Type.Enter, QEvent.Type.Leave, QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            sequence = {QEvent.Type.Enter: "<Enter>", QEvent.Type.Leave: "<Leave>", QEvent.Type.FocusIn: "<FocusIn>", QEvent.Type.FocusOut: "<FocusOut>"}[kind]
        elif kind in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick):
            if kind != QEvent.Type.MouseMove and event.button() != Qt.MouseButton.LeftButton:
                return False
            data.x, data.y = event.position().x(), event.position().y()
            sequence = {QEvent.Type.MouseMove: "<Motion>", QEvent.Type.MouseButtonPress: "<Button-1>", QEvent.Type.MouseButtonRelease: "<ButtonRelease-1>", QEvent.Type.MouseButtonDblClick: "<Double-1>"}[kind]
        elif kind == QEvent.Type.Wheel:
            data.delta = event.angleDelta().y()
            data.state = 1 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 0
            sequence = "<Shift-MouseWheel>" if data.state else "<MouseWheel>"
        elif kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            key = {Qt.Key.Key_Return: "Return", Qt.Key.Key_Enter: "KP_Enter", Qt.Key.Key_Escape: "Escape", Qt.Key.Key_Tab: "Tab", Qt.Key.Key_Up: "Up", Qt.Key.Key_Down: "Down", Qt.Key.Key_Delete: "Delete", Qt.Key.Key_F5: "F5"}.get(event.key(), event.text().lower())
            prefix = "Control-" if event.modifiers() & Qt.KeyboardModifier.ControlModifier else ""
            if prefix and Qt.Key.Key_A <= event.key() <= Qt.Key.Key_Z:
                key = chr(event.key()).lower()
            sequence = f"<{prefix}{key}>" if kind == QEvent.Type.KeyPress else "<KeyRelease>"
        if sequence and self._dispatch(sequence, data):
            return True
        if kind == QEvent.Type.KeyPress:
            if sequence == "<KP_Enter>":
                sequence = "<Return>"
                if self._dispatch(sequence, data):
                    return True
            top = self.winfo_toplevel()
            if top is not self and sequence in top._bindings and not (isinstance(self, QTextEdit) and sequence in ("<Return>", "<KP_Enter>")):
                top._dispatch(sequence, data)
                return True
            if isinstance(self, (Window, Toplevel)) and sequence in self._bindings:
                return True
        if kind == QEvent.Type.Wheel:
            parent = self.master
            while parent:
                if hasattr(parent, "_page_wheel") and parent._page_wheel(data):
                    return True
                parent = getattr(parent, "master", None)
        return False

    def after(self, ms, callback):
        key = f"qt_timer_{next(_names)}"
        timer = QTimer(self)
        timer.setSingleShot(True)
        self._timers.add(key)
        _jobs[key] = timer
        def invoke():
            _jobs.pop(key, None)
            self._timers.discard(key)
            timer.deleteLater()
            if not self._dead:
                callback()
        timer.timeout.connect(invoke)
        timer.start(ms)
        return key

    def after_idle(self, callback):
        return self.after(0, callback)

    def after_cancel(self, key):
        timer = _jobs.pop(key, None)
        self._timers.discard(key)
        if timer:
            timer.stop()
            timer.deleteLater()

    def destroy(self):
        if self._dead:
            return
        self._cleanup()
        if self.master and hasattr(self.master, "_logical_children") and self in self.master._logical_children:
            self.master._logical_children.remove(self)
        # Let QObject ownership destroy the subtree. Deleting the scroll area's
        # attached scrollbar before the area itself leaves Qt with a stale bar.
        target = self._layout_box if self._layout_box is not None else self
        if self.master and self.master.layout() is not None:
            self.master.layout().removeWidget(target)
        self._layout_box = None
        self._manager = ""
        QWidget.hide(target)
        target.deleteLater()

    def _cleanup(self):
        if self._dead:
            return
        self._dispatch("<Destroy>")
        for child in list(self._logical_children):
            child._cleanup()
        self._logical_children.clear()
        for key in list(self._timers):
            self.after_cancel(key)
        self._dead = True
        if hasattr(self, "_dialog_loop"):
            self._dialog_loop.quit()

    def update_idletasks(self):
        if self.layout():
            self.layout().activate()
        application().sendPostedEvents(None, QEvent.Type.LayoutRequest)

    def process_events(self):
        application().processEvents()
        application().sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def winfo_children(self):
        return list(self._logical_children)

    def winfo_toplevel(self):
        widget = self
        while widget.master is not None and not isinstance(widget, (Window, Toplevel)):
            widget = widget.master
        return widget

    def winfo_exists(self):
        return not self._dead and not sip.isdeleted(self)

    def winfo_ismapped(self):
        return self.isVisible()

    def winfo_viewable(self):
        return self.isVisible() and not self.window().isMinimized()

    def winfo_manager(self):
        return self._manager

    def winfo_width(self):
        return self.width()

    def winfo_height(self):
        return self.height()

    def winfo_reqwidth(self):
        return self.sizeHint().width()

    def winfo_reqheight(self):
        return self.sizeHint().height()

    def winfo_rootx(self):
        return self.mapToGlobal(QPoint()).x()

    def winfo_rooty(self):
        return self.mapToGlobal(QPoint()).y()

    def winfo_y(self):
        return self.y()

    def winfo_screenwidth(self):
        return application().primaryScreen().availableGeometry().width()

    def winfo_screenheight(self):
        return application().primaryScreen().availableGeometry().height()

    def winfo_fpixels(self, value):
        return self.logicalDpiX()

    def winfo_rgb(self, color):
        c = QColor(color)
        return c.red() * 257, c.green() * 257, c.blue() * 257

    def winfo_class(self):
        return {Combobox: "Combobox", Treeview: "Treeview", Text: "Text"}.get(type(self), type(self).__name__)

    def focus_set(self):
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def focus_force(self):
        self.window().activateWindow()
        self.focus_set()

    def focus_get(self):
        return application().focusWidget()

class Frame(WidgetMixin, QWidget):
    def __init__(self, parent=None, **kw):
        super().__init__(parent)
        self._init(parent, **kw)

    def sizeHint(self):
        size = super().sizeHint()
        return QSize(int(self._opts.get("width", max(0, size.width()))), int(self._opts.get("height", max(0, size.height()))))


class Window(Frame):
    def __init__(self):
        application()
        super().__init__()
        self._close_callback = self.destroy

    def title(self, text=None):
        if text is None:
            return self.windowTitle()
        self.setWindowTitle(text)

    def geometry(self, value):
        match = re.fullmatch(r"(?:(\d+)x(\d+))?(?:\+(-?\d+)\+(-?\d+))?", value)
        if match:
            w, h, x, y = match.groups()
            if w:
                self._explicit_size = True
                self.resize(int(w), int(h))
            if x:
                self.move(int(x), int(y))

    def minsize(self, w, h):
        self.setMinimumSize(w, h)

    def withdraw(self):
        QWidget.hide(self)

    def deiconify(self):
        QWidget.show(self)

    def state(self, value):
        if value == "zoomed":
            self.showMaximized()

    def iconbitmap(self, default):
        self.setWindowIcon(QIcon(default))

    def protocol(self, name, callback):
        self._close_callback = callback

    def closeEvent(self, event):
        event.ignore()
        self._close_callback()

    def grab_current(self):
        return application().activeModalWidget()

    def destroy(self):
        super().destroy()
        application().quit()

    def mainloop(self):
        self.deiconify()
        return application().exec()


class Toplevel(WidgetMixin, QDialog):
    def __init__(self, parent=None, **kw):
        super().__init__(parent)
        self._init(parent, **kw)
        self._close_callback = self.destroy
        self._dialog_loop = QEventLoop(self)

    title = Window.title
    geometry = Window.geometry
    withdraw = Window.withdraw
    protocol = Window.protocol
    closeEvent = Window.closeEvent

    def transient(self, parent):
        self.setWindowModality(Qt.WindowModality.WindowModal)

    def resizable(self, width, height):
        self._resizable = width or height

    def deiconify(self):
        if not getattr(self, "_resizable", True) and self.layout() is not None:
            self.layout().setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
        if not getattr(self, "_explicit_size", False):
            self.adjustSize()
        QWidget.show(self)

    def overrideredirect(self, value):
        self.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

    def attributes(self, name, value):
        if name == "-topmost":
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, value)

    def lift(self):
        self.raise_()

    def grab_set(self):
        self.setWindowModality(Qt.WindowModality.ApplicationModal)

    def wait_window(self):
        self._dialog_loop.exec()


class Label(WidgetMixin, QLabel):
    def __init__(self, parent=None, **kw):
        super().__init__(parent)
        self._init(parent, **kw)

    def configure(self, cnf=None, **kw):
        if kw.get("style") == "Muted.TLabel":
            kw.setdefault("fg", _styles.get("muted", "#9BA1A9"))
        super().configure(cnf, **kw)
        if "text" in kw:
            self.setText(str(kw["text"]))
        self.setAlignment(_alignment(self._opts.get("anchor", "w")))
        if self._opts.get("wraplength"):
            self.setWordWrap(True)
            self.setMaximumWidth(self._opts["wraplength"])
        self.setMargin(0)

    def sizeHint(self):
        size = super().sizeHint()
        if self._opts.get("width"):
            size.setWidth(QFontMetrics(self.font()).horizontalAdvance("0") * self._opts["width"])
        return size


class Entry(WidgetMixin, QLineEdit):
    def __init__(self, parent=None, **kw):
        super().__init__(parent)
        self._init(parent, **kw)
        self.var = kw.get("textvariable", StringVar())
        self.setText(self.var.get())
        self._var_trace = self.var.trace_add("write", self._sync)
        self.bind("<Destroy>", lambda e: self.var.trace_remove("write", self._var_trace), "+")
        self.textChanged.connect(lambda text: self.var.set(text) if text != self.var.get() else None)

    def _sync(self, *args):
        if self.text() != self.var.get():
            self.setText(self.var.get())

    def configure(self, cnf=None, **kw):
        super().configure(cnf, **kw)
        if kw.get("justify") == "right":
            self.setAlignment(Qt.AlignmentFlag.AlignRight)

    def sizeHint(self):
        size = super().sizeHint()
        size.setWidth(QFontMetrics(self.font()).horizontalAdvance("0") * self._opts.get("width", 20) + 16)
        return size

    def get(self):
        return self.text()

    def icursor(self, index):
        self.setCursorPosition(len(self.text()) if index == "end" else index)

    def state(self, states=None):
        current = self._opts.setdefault("states", set())
        if states is None:
            return tuple(current)
        for state in states:
            current.discard(state[1:]) if state.startswith("!") else current.add(state)
        self.setReadOnly("readonly" in current)
        self.setProperty("invalid", "invalid" in current)
        self.style().unpolish(self)
        self.style().polish(self)

    def instate(self, states):
        current = self._opts.get("states", set())
        return all((state[1:] not in current) if state.startswith("!") else state in current for state in states)


class Button(WidgetMixin, QPushButton):
    def __init__(self, parent=None, **kw):
        super().__init__(parent)
        self._init(parent, **kw)
        self.setText(kw.get("text", ""))
        if kw.get("command"):
            self.clicked.connect(lambda: kw["command"]())


class Combobox(WidgetMixin, QComboBox):
    def __init__(self, parent=None, **kw):
        super().__init__(parent)
        self.var = kw.get("textvariable", StringVar())
        self._init(parent, **kw)
        self._var_trace = self.var.trace_add("write", self._sync)
        self.bind("<Destroy>", lambda e: self.var.trace_remove("write", self._var_trace), "+")
        self._sync()
        self.activated.connect(self._picked)

    def configure(self, cnf=None, **kw):
        super().configure(cnf, **kw)
        if "values" in kw:
            self.blockSignals(True)
            self.clear()
            self.addItems([str(x) for x in kw["values"]])
            self.blockSignals(False)
            self._sync()

    def _sync(self, *args):
        self.setCurrentIndex(self.findText(self.var.get()))

    def _picked(self, index):
        self.var.set(self.itemText(index))
        self._dispatch("<<ComboboxSelected>>")

    def sizeHint(self):
        size = super().sizeHint()
        size.setWidth(QFontMetrics(self.font()).horizontalAdvance("0") * self._opts.get("width", 20) + 28)
        return size


class Scrollbar(WidgetMixin, QScrollBar):
    def __init__(self, parent=None, orient="vertical", command=None, **kw):
        super().__init__(Qt.Orientation.Vertical if orient == "vertical" else Qt.Orientation.Horizontal, parent)
        self._init(parent, orient=orient, **kw)
        self.command = command
        self.valueChanged.connect(lambda value: command("moveto", value / 10000) if command else None)

    def set(self, first, last):
        first, last = float(first), float(last)
        self.blockSignals(True)
        self.setRange(0, max(0, round((1 - (last - first)) * 10000)))
        self.setPageStep(max(1, round((last - first) * 10000)))
        self.setValue(round(first * 10000))
        self.blockSignals(False)


def _view(widget, horizontal, args):
    bar = widget.horizontalScrollBar() if horizontal else widget.verticalScrollBar()
    total = bar.maximum() + bar.pageStep()
    if not args:
        return (bar.value() / total, min(1.0, (bar.value() + bar.pageStep()) / total)) if total else (0.0, 1.0)
    if args[0] == "moveto":
        bar.setValue(round(float(args[1]) * total))
    elif args[0] == "scroll":
        bar.setValue(bar.value() + int(args[1]) * (bar.pageStep() if args[2] == "pages" else bar.singleStep()))


class ScrollView(WidgetMixin, QScrollArea):
    def __init__(self, parent, **kw):
        super().__init__(parent)
        self._init(parent, **kw)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBar(Scrollbar(self))
        self.verticalScrollBar().setSingleStep(30)

    def sizeHint(self):
        return QSize(self._opts.get("width", 200), self._opts.get("height", 200))

    def yview(self, *args):
        return _view(self, False, args)

    def yview_moveto(self, fraction):
        self.yview("moveto", fraction)

    def yview_scroll(self, amount, units):
        self.yview("scroll", amount, units)


class Treeview(WidgetMixin, QTableWidget):
    def __init__(self, parent=None, **kw):
        super().__init__(parent)
        self._rows = {}
        self._columns = []
        self._column_opts = {}
        self._headings = {}
        self._tags = {}
        self._init(parent, **kw)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self.setShowGrid(False)
        self.verticalHeader().hide()
        self.horizontalHeader().setMinimumSectionSize(1)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.viewport().setMouseTracking(True)
        self.viewport().installEventFilter(self)
        self.horizontalHeader().sectionClicked.connect(self._heading_clicked)
        self.horizontalHeader().sectionResized.connect(self._column_resized)
        self.itemSelectionChanged.connect(lambda: self._dispatch("<<TreeviewSelect>>"))
        for bar, key in ((self.horizontalScrollBar(), "xscrollcommand"), (self.verticalScrollBar(), "yscrollcommand")):
            bar.valueChanged.connect(lambda *_, k=key: self._notify_scroll(k))
            bar.rangeChanged.connect(lambda *_, k=key: self._notify_scroll(k))

    def configure(self, cnf=None, **kw):
        super().configure(cnf, **kw)
        if "columns" in kw:
            self._columns = list(kw["columns"])
            self.setColumnCount(len(self._columns))

    def sizeHint(self):
        row_height = QFontMetrics(self.font()).height() + _styles.get("row_padding", 16)
        self.verticalHeader().setDefaultSectionSize(row_height)
        return QSize(400, self.horizontalHeader().sizeHint().height() + row_height * self._opts.get("height", 5))

    def minimumSizeHint(self):
        return QSize(0, self.sizeHint().height())

    def _notify_scroll(self, key):
        callback = self._opts.get(key)
        if callback:
            callback(*self.xview() if key == "xscrollcommand" else self.yview())

    def _heading_clicked(self, column):
        callback = self._headings.get(self._columns[column], {}).get("command")
        if callback:
            callback()

    def _column_resized(self, index, old, new):
        if index < len(self._columns):
            minimum = self._column_opts.get(self._columns[index], {}).get("minwidth", 1)
            if new < minimum:
                self.setColumnWidth(index, minimum)

    def heading(self, key, option=None, **kw):
        if not kw:
            return self._headings.get(key, {}).get(option, "") if option else self._headings.get(key, {})
        self._headings.setdefault(key, {}).update(kw)
        item = QTableWidgetItem(kw.get("text", key))
        item.setTextAlignment(_alignment(kw.get("anchor", "w")))
        self.setHorizontalHeaderItem(self._columns.index(key), item)

    def column(self, key, option=None, **kw):
        opts = self._column_opts.setdefault(key, {})
        if kw:
            opts.update(kw)
            self.setColumnWidth(self._columns.index(key), kw.get("width", 100))
        return self.columnWidth(self._columns.index(key)) if option == "width" else opts.get(option, "") if option else dict(opts)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        minimum = sum(self._column_opts.get(k, {}).get("minwidth", 100) for k in self._columns)
        extra = max(0, self.viewport().width() - minimum) // max(len(self._columns), 1)
        for i, key in enumerate(self._columns):
            self.setColumnWidth(i, self._column_opts.get(key, {}).get("minwidth", 100) + extra)
        self._notify_scroll("xscrollcommand")

    def insert(self, parent, index, iid=None, values=(), tags=()):
        iid = str(iid if iid is not None else next(_names))
        row = self.rowCount() if index == "end" else index
        self.insertRow(row)
        self._rows[iid] = {"values": tuple(values), "tags": list(tags)}
        for col, value in enumerate(values):
            cell = QTableWidgetItem(str(value))
            cell.setData(Qt.ItemDataRole.UserRole, iid)
            cell.setTextAlignment(_alignment(self._column_opts.get(self._columns[col], {}).get("anchor", "w")))
            QTableWidget.setItem(self, row, col, cell)
        self._apply_tags(iid)
        return iid

    def _row_index(self, iid):
        return next((r for r in range(self.rowCount()) if self._row_id(r) == str(iid)), -1)

    def _row_id(self, row):
        item = QTableWidget.item(self, row, 0) if row >= 0 else None
        return item.data(Qt.ItemDataRole.UserRole) if item else ""

    def get_children(self, parent=""):
        return tuple(self._row_id(r) for r in range(self.rowCount()))

    def delete(self, *items):
        self.blockSignals(True)
        for iid in items:
            row = self._row_index(iid)
            if row >= 0:
                self.removeRow(row)
                self._rows.pop(str(iid), None)
        self.blockSignals(False)

    def exists(self, iid):
        return str(iid) in self._rows

    def item(self, iid, option=None, **kw):
        data = self._rows[str(iid)]
        if kw:
            data.update(kw)
            self._apply_tags(str(iid))
        return data.get(option, ()) if option else dict(data)

    def set(self, iid, column, value=None):
        index = self._columns.index(column)
        if value is None:
            return str(self._rows[str(iid)]["values"][index])
        data = list(self._rows[str(iid)]["values"])
        data[index] = value
        self._rows[str(iid)]["values"] = tuple(data)
        QTableWidget.item(self, self._row_index(iid), index).setText(str(value))

    def move(self, iid, parent, index):
        current = self._row_index(iid)
        if current == index:
            return
        focused = self.focus()
        selected = self.selection()
        blocked = self.blockSignals(True)
        cells = [self.takeItem(current, c) for c in range(self.columnCount())]
        self.removeRow(current)
        self.insertRow(index)
        for column, cell in enumerate(cells):
            QTableWidget.setItem(self, index, column, cell)
        if focused:
            self.focus(focused)
        for key in selected:
            self.selection_set(key)
        self.blockSignals(blocked)

    def focus(self, iid=None):
        if iid is None:
            return self._row_id(self.currentRow())
        self.setCurrentCell(self._row_index(iid), 0)

    def selection(self):
        return tuple(self._row_id(index.row()) for index in self.selectionModel().selectedRows())

    def selection_set(self, iid):
        self.selectRow(self._row_index(iid))

    def see(self, iid):
        self.scrollToItem(QTableWidget.item(self, self._row_index(iid), 0))

    def identify_row(self, y):
        return self._row_id(self.rowAt(int(y) - self.horizontalHeader().height()))

    def identify_column(self, x):
        return f"#{self.columnAt(int(x)) + 1}"

    def identify_region(self, x, y):
        return "heading" if y < self.horizontalHeader().height() else "cell" if self.identify_row(y) else "nothing"

    def bbox(self, iid, column=0):
        col = self._columns.index(column) if isinstance(column, str) and column in self._columns else int(column)
        rect = self.visualItemRect(QTableWidget.item(self, self._row_index(iid), col))
        return rect.x(), rect.y() + self.horizontalHeader().height(), rect.width(), rect.height()

    def eventFilter(self, watched, event):
        if watched is self.viewport() and event.type() in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonDblClick):
            if event.type() == QEvent.Type.MouseButtonDblClick and event.button() != Qt.MouseButton.LeftButton:
                return False
            data = SimpleNamespace(widget=self, x=event.position().x(), y=event.position().y() + self.horizontalHeader().height(), num=0, delta=0, state=0)
            # Select before the double-click callback, as Qt's default handler does.
            if event.type() == QEvent.Type.MouseButtonDblClick:
                self.setCurrentCell(self.rowAt(int(event.position().y())), self.columnAt(int(event.position().x())))
            sequence = "<Motion>" if event.type() == QEvent.Type.MouseMove else "<Double-1>"
            consumed = self._dispatch(sequence, data)
            return consumed or (sequence == "<Double-1>" and bool(self._bindings.get(sequence)))
        return super().eventFilter(watched, event)

    def tag_configure(self, tag, **kw):
        self._tags[tag] = kw

    def _apply_tags(self, iid):
        row = self._row_index(iid)
        opts = {}
        for tag in self._rows[iid]["tags"]:
            opts.update(self._tags.get(tag, {}))
        for col in range(self.columnCount()):
            cell = QTableWidget.item(self, row, col)
            if cell:
                cell.setForeground(QColor(opts.get("foreground", _styles.get("text", "#FFFFFF"))))
                cell.setBackground(QColor(opts.get("background", _styles.get("bg", "#000000"))))
                cell.setFont(opts.get("font", self.font()))

    def xview(self, *args):
        return _view(self, True, args)

    def yview(self, *args):
        return _view(self, False, args)

    def xview_scroll(self, amount, units):
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + amount)

    def yview_moveto(self, fraction):
        self.yview("moveto", fraction)

    def xview_moveto(self, fraction):
        self.xview("moveto", fraction)


class Text(WidgetMixin, QTextEdit):
    def __init__(self, parent=None, **kw):
        super().__init__(parent)
        self._tags = {}
        self._init(parent, **kw)
        self.setFrameShape(QTextEdit.Shape.NoFrame)
        self.setAcceptRichText(False)
        self.document().setDocumentMargin(0)
        self.setViewportMargins(kw.get("padx", 0), kw.get("pady", 0), kw.get("padx", 0), kw.get("pady", 0))
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.verticalScrollBar().valueChanged.connect(self._scrolled)
        self.verticalScrollBar().rangeChanged.connect(self._scrolled)

    def sizeHint(self):
        fm = QFontMetrics(self.font())
        return QSize(fm.horizontalAdvance("0") * self._opts.get("width", 30) + 12, fm.height() * self._opts.get("height", 8) + 12)

    def get(self, start, end):
        return self.toPlainText()

    def delete(self, start, end):
        self.clear()

    def insert(self, index, text, tags=()):
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        style = QTextCharFormat()
        block = QTextBlockFormat()
        if isinstance(tags, str):
            tags = (tags,)
        for tag in tags:
            opts = self._tags.get(tag, {})
            if "font" in opts:
                style.setFont(opts["font"])
            if "foreground" in opts:
                style.setForeground(QColor(opts["foreground"]))
            if "lmargin1" in opts:
                block.setLeftMargin(opts["lmargin1"])
        cursor.setBlockFormat(block)
        cursor.insertText(text, style)

    def tag_configure(self, tag, **kw):
        self._tags[tag] = kw

    def _scrolled(self, *args):
        callback = self._opts.get("yscrollcommand")
        if callback:
            callback(*self.yview())

    def yview(self, *args):
        return _view(self, False, args)


class Listbox(WidgetMixin, QListWidget):
    def __init__(self, parent=None, **kw):
        super().__init__(parent)
        self._init(parent, **kw)
        self.itemSelectionChanged.connect(lambda: self._dispatch("<<ListboxSelect>>"))

    def sizeHint(self):
        fm = QFontMetrics(self.font())
        return QSize(fm.horizontalAdvance("0") * self._opts.get("width", 20), fm.height() * self._opts.get("height", 9) + 8)

    def insert(self, index, text):
        self.insertItem(self.count() if index == "end" else index, text)

    def delete(self, start, end):
        self.clear()

    def selection_set(self, index):
        blocked = self.blockSignals(True)
        self.setCurrentRow(index)
        self.blockSignals(blocked)

    def selection_clear(self, start, end):
        self.clearSelection()

    def curselection(self):
        return tuple(self.row(item) for item in self.selectedItems())

    def see(self, index):
        self.scrollToItem(self.item(index))

    def get(self, start, end=None):
        if end is None:
            return self.item(start).text()
        last = self.count() - 1 if end == "end" else end
        return tuple(self.item(index).text() for index in range(start, last + 1))


class Canvas(Frame):
    """Retained vector drawing surface, painted and clipped entirely by QPainter."""
    def __init__(self, parent=None, **kw):
        self._shapes = {}
        self._shape_ids = itertools.count(1)
        super().__init__(parent, **kw)

    def sizeHint(self):
        return QSize(self._opts.get("width", 200), self._opts.get("height", 200))

    def _create(self, kind, points, kw):
        if len(points) == 1 and isinstance(points[0], (tuple, list)):
            points = points[0]
        key = next(self._shape_ids)
        self._shapes[key] = [kind, list(points), dict(kw)]
        self.update()
        return key

    def create_polygon(self, *points, **kw):
        return self._create("polygon", points, kw)

    def create_line(self, *points, **kw):
        return self._create("line", points, kw)

    def create_oval(self, *points, **kw):
        return self._create("oval", points, kw)

    def create_text(self, *points, **kw):
        return self._create("text", points, kw)

    def _matching(self, key):
        return [i for i, (_, _, opts) in self._shapes.items() if key == "all" or i == key or key in self._shape_tags(opts)]

    @staticmethod
    def _shape_tags(opts):
        tags = opts.get("tags", ())
        return (tags,) if isinstance(tags, str) else tags

    def delete(self, key):
        for item in self._matching(key):
            del self._shapes[item]
        self.update()

    def coords(self, key, *points):
        items = self._matching(key)
        if points:
            for item in items:
                self._shapes[item][1] = list(points)
            self.update()
        return list(self._shapes[items[0]][1]) if items else []

    def itemconfigure(self, key, **kw):
        for item in self._matching(key):
            self._shapes[item][2].update(kw)
        self.update()

    itemconfig = itemconfigure

    def find_all(self):
        return tuple(self._shapes)

    def find_withtag(self, tag):
        return tuple(self._matching(tag))

    def type(self, item):
        return self._shapes[item][0]

    def itemcget(self, item, key):
        return self._shapes[item][2].get(key, "")

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        self._paint_shapes(painter, self._shapes.values())
        painter.end()

    def _paint_shapes(self, painter, shapes):
        """Draw retained shapes into either the widget or a chart's backing pixmap."""
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        for kind, points, opts in shapes:
            if opts.get("state") == "hidden":
                continue
            fill = opts.get("fill", "")
            outline = opts.get("outline", "") if kind != "line" else fill
            pen = QPen(QColor(outline)) if outline else QPen(Qt.PenStyle.NoPen)
            pen.setWidthF(float(opts.get("width", 1)))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            if opts.get("dash"):
                pen.setStyle(Qt.PenStyle.DotLine)
            painter.setPen(pen)
            painter.setBrush(QColor(fill) if fill and kind != "line" else Qt.BrushStyle.NoBrush)
            if kind == "oval":
                x0, y0, x1, y1 = points
                painter.drawEllipse(QRectF(x0, y0, x1 - x0, y1 - y0))
            elif kind in ("polygon", "line"):
                polygon = QPolygonF([QPointF(x, y) for x, y in zip(points[::2], points[1::2])])
                if opts.get("smooth") and kind == "polygon" and len(polygon) > 2:
                    path = QPainterPath((polygon[-1] + polygon[0]) / 2)
                    for index, point in enumerate(polygon):
                        path.quadTo(point, (point + polygon[(index + 1) % len(polygon)]) / 2)
                    path.closeSubpath()
                    painter.drawPath(path)
                elif kind == "polygon":
                    painter.drawPolygon(polygon)
                else:
                    painter.drawPolyline(polygon)
            elif kind == "text":
                font = opts.get("font", application().font())
                painter.setFont(font)
                painter.setPen(QColor(fill or "#FFFFFF"))
                text = str(opts.get("text", ""))
                fm = QFontMetrics(font)
                rect = QRectF(0, 0, fm.horizontalAdvance(text), fm.height())
                x, y = points
                anchor = opts.get("anchor", "")
                rect.moveLeft(x if "w" in anchor else x - rect.width() if "e" in anchor else x - rect.width() / 2)
                rect.moveTop(y if "n" in anchor else y - rect.height() if "s" in anchor else y - rect.height() / 2)
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)


class Menu(WidgetMixin, QMenu):
    def __init__(self, parent=None, **kw):
        super().__init__(parent)
        self._init(parent, **kw)
        self._radio_groups = {}

    def add_command(self, label, command, state="normal", accelerator=None):
        action = QAction(label + (f"\t{accelerator}" if accelerator else ""), self)
        action.setEnabled(state != "disabled")
        action.triggered.connect(lambda: command())
        self.addAction(action)
        return action

    def add_separator(self):
        self.addSeparator()

    def add_checkbutton(self, label, variable, command):
        action = self.add_command(label, lambda: (variable.set(not variable.get()), command()))
        action.setCheckable(True)
        action.setChecked(variable.get())

    def add_radiobutton(self, label, variable, value, command):
        group = self._radio_groups.setdefault(id(variable), QActionGroup(self))
        action = self.add_command(label, lambda: (variable.set(value), command()))
        action.setCheckable(True)
        action.setChecked(variable.get() == value)
        group.addAction(action)

    def add_cascade(self, label, menu):
        menu.setTitle(label)
        self.addMenu(menu)

    def popup_at(self, x, y):
        self.popup(QPoint(x, y))

    def index(self, index):
        return len(self.actions()) - 1 if index == "end" else index

    def type(self, index):
        action = self.actions()[index]
        return "separator" if action.isSeparator() else "cascade" if action.menu() else "radiobutton" if action.actionGroup() else "checkbutton" if action.isCheckable() else "command"

    def entrycget(self, index, key):
        action = self.actions()[index]
        return action.text().split("\t")[0] if key == "label" else "normal" if action.isEnabled() else "disabled"


def _message(kind, title, text, parent=None, **kw):
    parent = parent or application().activeWindow()
    if kind == "question":
        return QMessageBox.question(parent, title, text, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes) == QMessageBox.StandardButton.Yes
    return getattr(QMessageBox, kind)(parent, title, text)


messagebox = SimpleNamespace(
    showerror=lambda title, text, **kw: _message("critical", title, text, **kw),
    showinfo=lambda title, text, **kw: _message("information", title, text, **kw),
    askyesno=lambda title, text, **kw: _message("question", title, text, **kw),
)


def _save_file(title="", initialfile="", filetypes=(), defaultextension="", **kw):
    filters = ";;".join(f"{name} ({pattern})" for name, pattern in filetypes)
    path, _ = QFileDialog.getSaveFileName(application().activeWindow(), title, initialfile, filters)
    if path and defaultextension and not Path(path).suffix:
        path += defaultextension
    return path


filedialog = SimpleNamespace(
    askdirectory=lambda title="", **kw: QFileDialog.getExistingDirectory(application().activeWindow(), title),
    asksaveasfilename=_save_file,
)

Widget = QWidget

