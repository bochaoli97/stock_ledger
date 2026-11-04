"""Compare optimized full/partial paints with the original ticker renderer."""
import os
import unittest
from unittest import mock

from PyQt6.QtCore import QAbstractAnimation, QEvent, QRectF, Qt
from PyQt6.QtGui import QFont, QImage, QPainter, QPaintEvent, QPixmap, QRegion

import qt_widgets as qt
from ticker import RobinhoodTicker, get_slot_rank

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def paint_reference(widget, event):
    """Freeze the former full renderer as the pixel-equivalence oracle."""
    painter = QPainter(widget)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.setFont(widget.digit_font)
    x = 0.0
    for track in sorted(widget.track_dict.values(), key=lambda item: get_slot_rank(item.key), reverse=True):
        width = track.base_width * track.width_factor
        if width > 0.1:
            painter.save()
            painter.setOpacity(track.opacity)
            painter.setPen(track.current_color)
            painter.setClipRect(QRectF(x, 0, width, widget.char_height))
            if track.is_digit:
                center = round(track.current_offset)
                for value in range(center - 1, center + 2):
                    painter.drawText(QRectF(x, (track.current_offset - value) * widget.char_height,
                                            track.base_width, widget.char_height),
                                     Qt.AlignmentFlag.AlignCenter, str(value % 10))
            else:
                painter.drawText(QRectF(x, 0, track.base_width, widget.char_height),
                                 Qt.AlignmentFlag.AlignCenter, track.char)
            painter.restore()
        x += width
    painter.end()


class TickerRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = qt.application()

    def setUp(self):
        self.widgets = []
        self.ticker = self.make_ticker()

    def make_ticker(self, family="Sans Serif", size=30, background="#000000", foreground="#FFFFFF"):
        widget = RobinhoodTicker(QFont(family, size), neutral=foreground)
        widget.setStyleSheet(f"background: {background};")
        widget.show()
        self.widgets.append(widget)
        return widget

    def tearDown(self):
        for widget in self.widgets:
            widget.close()
            widget.deleteLater()
        self.qt_app.processEvents()
        self.qt_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    @staticmethod
    def advance(widget, elapsed):
        for track in list(widget.track_dict.values()):
            for animation in (track.scroll_anim, track.color_anim, track.appear_anim):
                if animation.state() == QAbstractAnimation.State.Running:
                    animation.setCurrentTime(min(elapsed, animation.duration()))

    @staticmethod
    def reference_image(widget):
        with mock.patch.object(RobinhoodTicker, "paintEvent", paint_reference):
            return widget.grab().toImage()

    def test_frames_match_original_renderer(self):
        transitions = (
            ("$12,345.67", "$12,345.68"), ("$123.99", "$124.00"),
            ("$999.99", "$1,000.00"), ("$1,000.00", "$999.99"),
            ("$0.35", "$1,000,000.01"), ("$19.90", "$19.99"),
            ("-$999.99", "$1,000.00"), ("+$1.00", "-$2.00"),
            ("$1.00", "-"), ("-", "$2.00"),
        )
        for family, size in (("Sans Serif", 30), ("DejaVu Sans Mono", 39)):
            for background, foreground in (("#000000", "#FFFFFF"), ("#FFFFFF", "#111315")):
                widget = self.make_ticker(family, size, background, foreground)
                for start, target in transitions:
                    for flash in (True, False):
                        widget.set_text(start, animate=False)
                        widget.set_text(target, flash=flash)
                        for elapsed in (0, 1, 16, 89, 175, 259, 320, 450, 600, 650):
                            with self.subTest(font=family, background=background, start=start,
                                              target=target, flash=flash, elapsed=elapsed):
                                self.advance(widget, elapsed)
                                self.assertEqual(widget.grab().toImage(), self.reference_image(widget))

    def test_partial_paints_preserve_the_entire_frame(self):
        widget = self.ticker
        widget.set_text("$12,345.67", animate=False)
        frame = QPixmap.fromImage(self.reference_image(widget))
        dirty = QRegion()

        def mark_dirty(*args):
            nonlocal dirty
            dirty |= QRegion(args[0] if args else widget.rect())

        with mock.patch.object(widget, "update", side_effect=mark_dirty):
            for target, flash in (("$12,345.68", True), ("$12,346.12", True),
                                  ("$12,346.01", False), ("$12,345.99", False),
                                  ("$12,345.99", True)):
                widget.set_text(target, flash=flash)
                for elapsed in (0, 16, 52, 89, 175, 259, 320, 450, 600, 650):
                    self.advance(widget, elapsed)
                    if not dirty.isEmpty():
                        # Use QWidget's real system clip and font rasterization;
                        # leave pixels outside the invalidated region untouched.
                        widget.render(frame, dirty.boundingRect().topLeft(), dirty)
                    with self.subTest(target=target, elapsed=elapsed):
                        self.assertEqual(frame.toImage(), self.reference_image(widget))
                    dirty = QRegion()

    def test_scroll_and_color_ticks_only_invalidate_the_changed_column(self):
        widget = self.ticker
        widget.set_text("$12,345.67", animate=False)
        widget.set_text("$12,345.68")
        track = widget.track_dict["dec_2"]
        bounds = widget.track_rect("dec_2").toAlignedRect()
        with mock.patch.object(widget, "update", wraps=widget.update) as update:
            track.scroll_anim.setCurrentTime(80)
            track.color_anim.setCurrentTime(80)
            self.assertTrue(update.called)
            self.assertTrue(all(call.args == (bounds,) for call in update.call_args_list))

        # Even a full paint now submits one glyph per resting digit. A partial
        # animation paint should visit only the three glyphs of the moving reel.
        frame = QImage(widget.size(), QImage.Format.Format_ARGB32_Premultiplied)

        class RecordingPainter(QPainter):
            calls = 0

            def __init__(self, _widget):
                super().__init__(frame)

            def drawText(self, *args):
                type(self).calls += 1
                return super().drawText(*args)

        with mock.patch("ticker.QPainter", RecordingPainter):
            widget.paintEvent(QPaintEvent(QRegion(bounds)))
        self.assertEqual(RecordingPainter.calls, 3)

    def test_resting_frame_submits_one_glyph_per_slot(self):
        self.ticker.set_text("$12,345.68", animate=False)

        class RecordingPainter(QPainter):
            calls = 0

            def drawText(self, *args):
                type(self).calls += 1
                return super().drawText(*args)

        with mock.patch("ticker.QPainter", RecordingPainter):
            self.ticker.grab()
        self.assertEqual(RecordingPainter.calls, len(self.ticker.track_dict))
