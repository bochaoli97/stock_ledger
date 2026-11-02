"""Semantic-slot PyQt6 ticker, confined to the three existing headlines.

Each QObject-owned track keeps its numeric/static type throughout its lifetime.
One canvas paints the tracks; width animation never rebuilds surviving digits.
"""
import math
import re
from decimal import Decimal, InvalidOperation

from PyQt6.QtCore import QObject, QEasingCurve, QRectF, QSize, Qt, QVariantAnimation
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PyQt6.QtWidgets import QSizePolicy, QWidget

from qt_widgets import WidgetMixin


def get_slot_rank(key: str) -> float:
    """Sort most-significant digits first, keeping commas between their groups."""
    if key == "placeholder":
        return math.inf
    if key == "sign":
        return 1001.0
    if key == "prefix":
        return 1000.0
    if key == "dot":
        return 0.0
    if key.startswith("dec_"):
        return -float(key.split("_")[1])
    if key.startswith("int_"):
        return int(key.split("_")[1]) + 0.1
    if key.startswith("comma_"):
        return 3 * int(key.split("_")[1]) - 0.5
    raise ValueError(f"Unknown ticker slot: {key}")


class CharacterTrack(QObject):
    """Independent scroll, width/opacity and color channels for one typed slot."""
    def __init__(self, key, char, font, base_color, parent_widget):
        super().__init__(parent_widget)
        self._key = key
        self._is_digit = key.startswith(("int_", "dec_"))
        self._validate_char(char)
        self.char = self.target_char = char
        self.font = QFont(font)
        self.base_white = QColor(base_color)
        self.current_color = QColor(base_color)
        self.parent_widget = parent_widget
        metrics = QFontMetrics(font)
        self.char_height = metrics.height()
        if self.is_digit:
            self.base_width = max(metrics.horizontalAdvance(str(i)) for i in range(10)) + 2
        elif key == "sign":
            self.base_width = max(metrics.horizontalAdvance(c) for c in "+-") + 2
        else:
            self.base_width = metrics.horizontalAdvance(char) + 2
        self.current_offset = float(char) if self.is_digit else 0.0
        self.target_offset = self.current_offset
        self.width_factor = self.opacity = 1.0
        self.is_marked_for_removal = False

        self.scroll_anim = QVariantAnimation(self)
        self.scroll_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.scroll_anim.valueChanged.connect(self._on_scroll)
        self.scroll_anim.finished.connect(self._on_scroll_finished)
        self.appear_anim = QVariantAnimation(self)
        self.appear_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.appear_anim.valueChanged.connect(self._on_appear)
        self.appear_anim.finished.connect(self._on_appear_finished)
        self.color_anim = QVariantAnimation(self)
        self.color_anim.setDuration(600)
        self.color_anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        self.color_anim.valueChanged.connect(self._on_color)

    @property
    def key(self):
        return self._key

    @property
    def is_digit(self):
        return self._is_digit

    def _validate_char(self, char):
        if self.is_digit and not (len(char) == 1 and char in "0123456789"):
            raise ValueError(f"Numeric slot {self.key} cannot contain {char!r}")
        if not self.is_digit and any(c in "0123456789" for c in char) and self.key != "placeholder":
            raise ValueError(f"Static slot {self.key} cannot contain digits")

    def _on_scroll(self, value):
        self.current_offset = float(value)
        self.parent_widget.update()

    def _on_scroll_finished(self):
        self.char = self.target_char
        self.current_offset = self.target_offset = float(self.target_char)
        self.parent_widget.update()

    def _on_appear(self, value):
        self.width_factor = self.opacity = float(value)
        self.parent_widget.on_track_resized()

    def _on_appear_finished(self):
        if self.is_marked_for_removal:
            self.parent_widget.remove_collapsed_track(self)

    def _on_color(self, value):
        self.current_color = QColor(value)
        self.parent_widget.update()

    def clear_color(self):
        if self.color_anim.state() == QVariantAnimation.State.Stopped and self.current_color == self.base_white:
            return
        self.color_anim.stop()
        self.current_color = QColor(self.base_white)
        self.parent_widget.update()

    def flash(self, color):
        self.color_anim.stop()
        self.current_color = QColor(color)
        self.color_anim.setStartValue(QColor(color))
        self.color_anim.setEndValue(self.base_white)
        self.color_anim.start()
        self.parent_widget.update()

    def expand_in(self, duration=350):
        self.is_marked_for_removal = False
        self.appear_anim.stop()
        if self.width_factor == 1.0:
            return
        self._animate_width(1.0, duration)

    def collapse_out(self, duration=260):
        self.is_marked_for_removal = True
        self.appear_anim.stop()
        self.clear_color()
        if self.width_factor <= 0.0:
            self.parent_widget.remove_collapsed_track(self)
            return
        self._animate_width(0.0, duration)

    def _animate_width(self, target, duration):
        # Changing QVariantAnimation's duration can emit a recalculated value at
        # its previous time. Capture the actual width before touching the clock,
        # and suppress those intermediate signals when reversing direction.
        start = float(self.width_factor)
        blocked = self.appear_anim.blockSignals(True)
        self.appear_anim.stop()
        self.appear_anim.setDuration(duration)
        self.appear_anim.setStartValue(start)
        self.appear_anim.setEndValue(float(target))
        self.appear_anim.setCurrentTime(0)
        self.appear_anim.blockSignals(blocked)
        self.appear_anim.start()

    def set_target(self, new_char, duration, flash_color=None, *, retarget=False):
        self._validate_char(new_char)
        if new_char == self.target_char and not retarget:
            # Repeated quotes must not restart a running scroll or its fade.
            return
        self.target_char = new_char
        if not self.is_digit:
            self.char = new_char
            self.parent_widget.update()
            return
        start = self.current_offset % 10
        end = float(new_char)
        if abs(end - start) > 5:
            if start < end:
                start += 10
            else:
                end += 10
        self.target_offset = end
        # Reset the clock before publishing the new endpoints. Otherwise Qt
        # recalculates them at the previous animation time and emits transient
        # offsets (and redundant updates) while the reel is being retargeted.
        blocked = self.scroll_anim.blockSignals(True)
        self.scroll_anim.stop()
        self.scroll_anim.setDuration(duration)
        self.scroll_anim.setStartValue(start)
        self.scroll_anim.setEndValue(end)
        self.scroll_anim.setCurrentTime(0)
        self.current_offset = start
        self.scroll_anim.blockSignals(blocked)
        self.scroll_anim.start()
        if flash_color is not None:
            self.flash(flash_color)
        else:
            self.clear_color()

    def stop(self):
        self.scroll_anim.stop()
        self.appear_anim.stop()
        self.color_anim.stop()

    def settle(self):
        self.stop()
        self.char = self.target_char
        if self.is_digit:
            self.current_offset = self.target_offset = float(self.target_char)
        self.width_factor = self.opacity = 1.0
        self.is_marked_for_removal = False
        self.current_color = QColor(self.base_white)


class RobinhoodAdvancedTicker(QWidget):
    """Canvas with stable semantic tracks and an animated horizontal footprint."""
    HEAVY_ROLL_MS = 650
    EXPAND_MS = 350
    COLLAPSE_MS = 260
    SCRUB_WIDTH_MS = 180
    RIGHT_PADDING = 15
    MIN_WIDTH = 60
    _money_pattern = re.compile(r"(?P<sign>[+-]?)(?P<prefix>\$?)(?P<integer>[0-9]+(?:,[0-9]{3})*)(?:\.(?P<decimal>[0-9]+))?")

    def __init__(self, font, parent=None, neutral="#FFFFFF"):
        super().__init__(parent)
        self.digit_font = QFont(font)
        self.neutral = self.base_white = QColor(neutral)
        self.green_color = QColor("#00C805")
        self.red_color = QColor("#FF5000")
        self.current_price = None
        self.old_str = ""
        self.track_dict = {}
        self._target_slots = {}
        self._batching = False
        self._scrubbing = False
        self.char_height = QFontMetrics(font).height()
        self.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed)
        self.update_geometry_size()

    @staticmethod
    def _price(text):
        try:
            value = Decimal(text.replace("$", "").replace(",", ""))
            return value if value.is_finite() else None
        except InvalidOperation:
            return None

    @classmethod
    def _text_to_slots(cls, text):
        match = cls._money_pattern.fullmatch(text)
        if match is None:
            return None
        parts = match.groupdict()
        slots = {}
        if parts["sign"]:
            slots["sign"] = parts["sign"]
        if parts["prefix"]:
            slots["prefix"] = parts["prefix"]
        if parts["decimal"] is not None:
            slots["dot"] = "."
            slots.update((f"dec_{index}", char) for index, char in enumerate(parts["decimal"], 1))
        digit_index = comma_count = 0
        for char in reversed(parts["integer"]):
            if char == ",":
                comma_count += 1
                slots[f"comma_{comma_count}"] = char
            else:
                slots[f"int_{digit_index}"] = char
                digit_index += 1
        return slots

    def _parse_to_slots(self, price):
        return self._text_to_slots(self._format_price(price))

    @staticmethod
    def _format_price(price):
        price = Decimal(str(price))
        if not price.is_finite():
            raise ValueError("Price must be finite")
        return ("-$" if price < 0 else "$") + f"{abs(price):,.2f}"

    def set_price(self, price, flash=True):
        self.set_text(self._format_price(price), flash=flash)

    @classmethod
    def _calc_gear_duration(cls, new_char, old_char, key, is_scrubbing, *, heavy_slot=None):
        """Use the same vertical gears in live, restore and scrubbing contexts.

        The context argument is retained for callers of the reference API;
        scrubbing suppresses color and speeds horizontal resizing only.
        """
        if not new_char.isdigit() or not old_char.isdigit():
            return 300
        if key == "dec_2":
            return 260
        if key.startswith("dec_"):
            return 320
        if key.startswith("int_"):
            return cls.HEAVY_ROLL_MS if key == heavy_slot and abs(int(new_char) - int(old_char)) % 10 == 1 else 450
        return 450

    @staticmethod
    def _highest_changed_integer_slot(previous_slots, slots):
        changed = (key for key in previous_slots.keys() | slots.keys()
                   if key.startswith("int_") and previous_slots.get(key) != slots.get(key))
        return max(changed, key=get_slot_rank, default=None)

    def ordered_tracks(self):
        return sorted(self.track_dict.values(), key=lambda track: get_slot_rank(track.key), reverse=True)

    def track_rect(self, key):
        x = 0.0
        for track in self.ordered_tracks():
            width = track.base_width * track.width_factor
            if track.key == key:
                return QRectF(x, 0, width, self.char_height)
            x += width
        return QRectF()

    def sizeHint(self):
        width = sum(track.base_width * track.width_factor for track in self.track_dict.values())
        # Retain the previous headline's line height; other page rows do not move.
        return QSize(max(self.MIN_WIDTH, math.ceil(width) + self.RIGHT_PADDING), self.char_height)

    def minimumSizeHint(self):
        return self.sizeHint()

    def update_geometry_size(self):
        size = self.sizeHint()
        if self.size() != size or self.minimumSize() != size or self.maximumSize() != size:
            self.setFixedSize(size)
            self.updateGeometry()

    def on_track_resized(self):
        if not self._batching:
            self.update_geometry_size()
            self.update()

    def remove_collapsed_track(self, track):
        if (self.track_dict.get(track.key) is track and track.is_marked_for_removal
                and track.width_factor <= 0.001):
            del self.track_dict[track.key]
            track.stop()
            track.deleteLater()
            self.on_track_resized()

    def _replace_tracks(self, slots):
        for track in self.track_dict.values():
            track.stop()
            track.deleteLater()
        self.track_dict = {key: CharacterTrack(key, char, self.digit_font, self.neutral, self)
                           for key, char in slots.items()}

    def set_text(self, text, *, flash=True, animate=True):
        text = str(text)
        if animate and self.track_dict and text == self.old_str and (not flash) == self._scrubbing:
            return
        slots = self._text_to_slots(text)
        price = self._price(text) if slots is not None else None
        old_price, old_text = self.current_price, self.old_str
        previous_slots = self._target_slots
        entering_scrub = not flash and not self._scrubbing
        self._scrubbing = not flash
        self.current_price = price
        self.old_str = text
        self._target_slots = slots if price is not None else {"placeholder": text}
        self.setAccessibleName(text)
        if price is None or old_price is None or not animate:
            if self._target_slots != previous_slots or self.track_dict.keys() != self._target_slots.keys():
                self._replace_tracks(self._target_slots)
            else:
                for track in self.track_dict.values():
                    track.settle()
            self.update_geometry_size()
            self.update()
            return

        scrubbing = not flash
        flash_color = None
        if flash and price != old_price:
            flash_color = self.green_color if price > old_price else self.red_color
        # Only the most-significant changed integer can engage the heavy gear.
        # New/removed leading slots count too, so lower digits never take over.
        heavy_slot = self._highest_changed_integer_slot(previous_slots, slots)
        self._batching = True
        try:
            for key, track in list(self.track_dict.items()):
                if scrubbing:
                    track.clear_color()
                if key not in slots and not track.is_marked_for_removal:
                    track.collapse_out(self.SCRUB_WIDTH_MS if scrubbing else self.COLLAPSE_MS)
                elif entering_scrub and track.appear_anim.state() == QVariantAnimation.State.Running:
                    if track.is_marked_for_removal:
                        track.collapse_out(self.SCRUB_WIDTH_MS)
                    else:
                        track.expand_in(self.SCRUB_WIDTH_MS)
            for key, char in slots.items():
                track = self.track_dict.get(key)
                new_slot = key not in previous_slots
                if track is None:
                    track = CharacterTrack(key, char, self.digit_font, self.neutral, self)
                    self.track_dict[key] = track
                    track.width_factor = track.opacity = 0.0
                    track.expand_in(self.SCRUB_WIDTH_MS if scrubbing else self.EXPAND_MS)
                    if track.is_digit and flash_color is not None:
                        track.flash(flash_color)
                    continue
                if track.is_marked_for_removal:
                    track.expand_in(self.SCRUB_WIDTH_MS if scrubbing else self.EXPAND_MS)
                old_char = track.target_char
                duration = self._calc_gear_duration(char, old_char, key, scrubbing, heavy_slot=heavy_slot)
                running = track.scroll_anim.state() == QVariantAnimation.State.Running
                demote = (heavy_slot is not None and key.startswith("int_")
                          and key != heavy_slot and running and track.scroll_anim.duration() == self.HEAVY_ROLL_MS)
                # Retiming an unchanged, already-moving digit must not flash it.
                digit_flash = flash_color if char != old_char else None
                track.set_target(char, duration, digit_flash, retarget=demote)
                if new_slot and track.is_digit and flash_color is not None and old_char == char:
                    track.flash(flash_color)
                elif old_char == char and text != old_text:
                    track.clear_color()
        finally:
            self._batching = False
        # Retargeting preserves the painted position. The animation clock (or
        # an actual color/static-slot change) schedules the next repaint, so
        # high-rate pointer input does not add identical frames between ticks.
        self.update_geometry_size()

    def settle(self):
        for key, track in list(self.track_dict.items()):
            if key not in self._target_slots:
                track.is_marked_for_removal = True
                track.width_factor = 0.0
                self.remove_collapsed_track(track)
            else:
                track.settle()
        self.update_geometry_size()
        self.update()

    def hideEvent(self, event):
        self.settle()
        super().hideEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setFont(self.digit_font)
        x = 0.0
        for track in self.ordered_tracks():
            width = track.base_width * track.width_factor
            if width > 0.1:
                painter.save()
                painter.setOpacity(track.opacity)
                painter.setPen(track.current_color)
                painter.setClipRect(QRectF(x, 0, width, self.char_height))
                if track.is_digit:
                    center = int(round(track.current_offset))
                    for value in range(center - 1, center + 2):
                        # Mirror the reel vertically while keeping its existing
                        # shortest circular path and in-flight offsets intact.
                        rect = QRectF(x, (track.current_offset - value) * self.char_height,
                                      track.base_width, self.char_height)
                        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(value % 10))
                else:
                    painter.drawText(QRectF(x, 0, track.base_width, self.char_height),
                                     Qt.AlignmentFlag.AlignCenter, track.char)
                painter.restore()
            x += width
        painter.end()


# Preserve the existing public entry point; both names use the advanced canvas.
RobinhoodTicker = RobinhoodAdvancedTicker


class TickerLabel(WidgetMixin, RobinhoodAdvancedTicker):
    """Keep the three existing headline integrations and their layout methods."""
    def __init__(self, parent, *, text, font, fg="#FFFFFF", bg="#000000"):
        RobinhoodAdvancedTicker.__init__(self, font, parent, neutral=fg)
        self._init(parent, text=text, font=font, fg=fg, bg=bg)

    def configure(self, cnf=None, **kw):
        super().configure(cnf, **kw)
        if "text" in kw:
            self.set_text(kw["text"])

    def winfo_viewable(self):
        if not super().winfo_viewable():
            return False
        # Wayland can keep WindowNoState while a minimized surface is hidden.
        # Exposure also covers the interval before the native window is mapped.
        handle = self.window().windowHandle()
        return handle is not None and handle.isExposed()

    def set_text(self, text, *, flash=True, animate=True):
        if hasattr(self, "_opts"):
            self._opts["text"] = text
        super().set_text(text, flash=flash, animate=animate and self.winfo_viewable())

    def reset(self):
        self.settle()
        self.current_price = None
