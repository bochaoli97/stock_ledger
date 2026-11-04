"""Native Qt interactions and deterministic per-digit animation regressions."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shutil
import subprocess
import sys
import time
import unittest
from datetime import datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace
from unittest import mock

from PyQt6.QtCore import QAbstractAnimation, QEvent, QEasingCurve, QPoint, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QLabel

import app
import i18n
import qt_widgets as qt
from ledger import Txn
from quotes import Quote
from test_ledger import _close_gui, _gui_window, _turn_on_finance
from ticker import CharacterTrack, RobinhoodTicker, TickerLabel, get_slot_rank

RUNNING = QAbstractAnimation.State.Running


def move_mouse(widget, position):
    # QWidget's QTest overload warps the OS cursor, which Wayland may forbid.
    # Inject into the native window so Qt still routes the event to the widget.
    window = widget.window()
    QTest.mouseMove(window.windowHandle(), widget.mapTo(window, position))


def wait_for(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(10)
    return bool(predicate())


class DigitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = qt.application()

    def setUp(self):
        self.ticker = RobinhoodTicker(QFont("Sans Serif", 30))
        self.ticker.show()

    def tearDown(self):
        self.ticker.settle()
        self.ticker.close()
        self.ticker.deleteLater()
        self.qt_app.processEvents()
        self.qt_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def digits(self):
        return [track for track in self.ticker.ordered_tracks() if track.is_digit]

    def finish(self):
        for track in list(self.ticker.track_dict.values()):
            for animation in (track.scroll_anim, track.color_anim, track.appear_anim):
                if animation.state() == RUNNING:
                    animation.setCurrentTime(animation.duration())

    def painted_glyph_rects(self, key):
        """Record the actual drawText calls while Qt renders the canvas."""
        x = self.ticker.track_rect(key).x()
        rects = {}
        class RecordingPainter(QPainter):
            def drawText(self, rect, flags, text):
                if abs(rect.x() - x) < 0.001:
                    rects[text] = QRectF(rect)
                return super().drawText(rect, flags, text)
        with mock.patch("ticker.QPainter", RecordingPainter):
            self.ticker.grab()
        return rects

    def test_initial_value_and_repeated_tick_leave_columns_asleep(self):
        self.ticker.set_price(D("54.67"))
        digits = self.digits()
        self.assertTrue(all(d.scroll_anim.state() != RUNNING for d in digits))
        self.ticker.set_price(D("54.68"))
        changed = self.ticker.track_dict["dec_2"]
        self.assertEqual(changed.current_color, QColor("#00C805"))
        changed.scroll_anim.setCurrentTime(125)
        changed.color_anim.setCurrentTime(125)
        self.ticker.set_price(D("54.68"))
        self.assertEqual(changed.scroll_anim.currentTime(), 125)
        self.assertEqual(changed.color_anim.currentTime(), 125)
        self.assertTrue(all(d.scroll_anim.state() != RUNNING and d.current_color == QColor("white") for d in digits[:-1]))
        for track in self.ticker.track_dict.values():
            if not track.is_digit:
                self.assertEqual(track.current_color, QColor("white"))
                self.assertNotEqual(track.scroll_anim.state(), RUNNING)
                self.assertNotEqual(track.color_anim.state(), RUNNING)

    def test_scrub_restore_and_live_tick_have_independent_channels(self):
        self.ticker.set_price(D("54.67"))
        self.ticker.set_price(D("54.60"), flash=False)
        digits = self.digits()
        self.assertEqual(self.ticker.track_dict["dec_2"].scroll_anim.duration(), 260)
        self.assertTrue(all(d.current_color == QColor("white") and d.color_anim.state() != RUNNING for d in digits))
        self.ticker.settle()
        self.ticker.set_price(D("55.76"))
        durations = {"int_0": 650, "dec_1": 320, "dec_2": 260}
        self.assertNotEqual(self.ticker.track_dict["int_1"].scroll_anim.state(), RUNNING)
        for key, duration in durations.items():
            digit = self.ticker.track_dict[key]
            self.assertEqual(digit.scroll_anim.duration(), duration)
            self.assertEqual(digit.scroll_anim.easingCurve().type(), QEasingCurve.Type.OutCubic)
            self.assertEqual(digit.color_anim.duration(), 600)
            self.assertEqual(digit.color_anim.easingCurve().type(), QEasingCurve.Type.OutQuad)
            self.assertEqual(digit.current_color, QColor("#00C805"))
        self.finish()
        self.assertTrue(all(d.current_offset % 10 == int(d.target_char) and d.current_color == QColor("white") for d in digits))
        self.ticker.set_price(D("55.74"))
        self.assertEqual(digits[-1].current_color, QColor("#FF5000"))
        self.assertTrue(all(d.current_color == QColor("white") for d in digits[:-1]))
        self.ticker.set_price(D("55.74"), flash=False)
        self.assertTrue(all(d.current_color == QColor("white") and d.color_anim.state() != RUNNING for d in digits))

    def test_circular_shortest_path_and_midflight_retarget(self):
        self.ticker.set_price(D("19.99"))
        digit = self.ticker.track_dict["dec_2"]
        self.ticker.set_price(D("19.90"))
        self.assertEqual(abs(digit.scroll_anim.endValue() - digit.scroll_anim.startValue()), 1)
        digit.scroll_anim.setCurrentTime(140)
        position = digit.current_offset % 10
        self.ticker.set_price(D("19.98"))
        self.assertAlmostEqual(digit.scroll_anim.startValue() % 10, position)
        self.assertLessEqual(abs(digit.scroll_anim.endValue() - digit.scroll_anim.startValue()), 5)
        self.ticker.settle()
        self.ticker.set_price(D("19.99"))
        self.assertEqual(abs(digit.scroll_anim.endValue() - digit.scroll_anim.startValue()), 1)
        self.finish()
        self.ticker.set_price(D("19.90"))
        self.finish()
        self.ticker.set_price(D("19.90"))
        self.assertNotEqual(digit.scroll_anim.state(), RUNNING, "a wrapped zero must remain asleep on a repeated quote")

    def test_increasing_digit_enters_from_above_and_decreasing_digit_from_below(self):
        for previous, target, outgoing, incoming, downward in (
                ("3.00", "4.00", "3", "4", True),
                ("4.00", "3.00", "4", "3", False)):
            with self.subTest(previous=previous, target=target):
                self.ticker.set_text(self.ticker._format_price(D(previous)), animate=False)
                self.ticker.set_price(D(target))
                track = self.ticker.track_dict["int_0"]
                track.scroll_anim.setCurrentTime(170)
                rects = self.painted_glyph_rects("int_0")
                if downward:
                    self.assertGreater(rects[outgoing].y(), 0)
                    self.assertLess(rects[incoming].y(), 0)
                else:
                    self.assertLess(rects[outgoing].y(), 0)
                    self.assertGreater(rects[incoming].y(), 0)
                self.assertEqual(self.painted_glyph_rects("prefix")["$"].y(), 0)

    def test_wraparound_direction_is_reversed_but_still_uses_one_step(self):
        for previous, target, outgoing, incoming, downward in (
                ("19.99", "20.00", "9", "0", True),
                ("20.00", "19.99", "0", "9", False)):
            with self.subTest(previous=previous, target=target):
                self.ticker.set_text(self.ticker._format_price(D(previous)), animate=False)
                self.ticker.set_price(D(target))
                track = self.ticker.track_dict["int_0"]
                self.assertEqual(abs(track.scroll_anim.endValue() - track.scroll_anim.startValue()), 1)
                track.scroll_anim.setCurrentTime(90)
                rects = self.painted_glyph_rects("int_0")
                if downward:
                    self.assertGreater(rects[outgoing].y(), 0)
                    self.assertLess(rects[incoming].y(), 0)
                else:
                    self.assertLess(rects[outgoing].y(), 0)
                    self.assertGreater(rects[incoming].y(), 0)

    def test_shortest_path_keeps_priority_over_total_price_direction(self):
        self.ticker.set_price(D("19.90"))
        self.ticker.set_price(D("19.99"))
        track = self.ticker.track_dict["dec_2"]
        self.assertEqual(track.scroll_anim.startValue(), 10)
        self.assertEqual(track.scroll_anim.endValue(), 9)
        track.scroll_anim.setCurrentTime(52)
        rects = self.painted_glyph_rects("dec_2")
        self.assertLess(rects["0"].y(), 0)
        self.assertGreater(rects["9"].y(), 0)

    def test_tabular_width_static_anchors_and_format_boundaries(self):
        self.ticker.set_price(D("1111.11"))
        tracks = dict(self.ticker.track_dict)
        geometry = {key: self.ticker.track_rect(key) for key in tracks}
        self.ticker.set_price(D("8888.88"))
        self.assertEqual(self.ticker.track_dict, tracks)
        self.assertEqual({key: self.ticker.track_rect(key) for key in tracks}, geometry)
        self.assertEqual(len({d.base_width for d in self.digits()}), 1)
        for value in ("999.99", "1000", "-1000", "-0.01", "0", "9999999999999999.99"):
            self.ticker.set_price(D(value))
            self.assertEqual(self.ticker.current_price, D(value))
            self.finish()
            self.assertTrue(all(d.current_offset == float(d.target_char) for d in self.digits()))
            for key, track in self.ticker.track_dict.items():
                self.assertEqual(track.is_digit, key.startswith(("int_", "dec_")))
        self.ticker.set_text("-")
        self.assertIsNone(self.ticker.current_price)

    def test_real_animation_clock_finishes_without_manual_time_steps(self):
        self.ticker.set_price(D("54.67"))
        self.ticker.set_price(D("55.76"))
        self.assertTrue(any(d.scroll_anim.state() == RUNNING for d in self.digits()))
        QTest.qWait(1000)
        for digit in self.digits():
            self.assertNotEqual(digit.scroll_anim.state(), RUNNING)
            self.assertNotEqual(digit.color_anim.state(), RUNNING)
            self.assertEqual(digit.current_offset % 10, int(digit.target_char))
            self.assertEqual(digit.current_color, QColor("white"))

    def test_only_the_selected_integer_single_step_uses_650ms(self):
        for key in ("int_0", "int_1", "int_2", "int_7"):
            self.assertEqual(self.ticker._calc_gear_duration("4", "3", key, False, heavy_slot=key), 650)
            self.assertEqual(self.ticker._calc_gear_duration("2", "1", key, False, heavy_slot=key), 650)
            self.assertEqual(self.ticker._calc_gear_duration("3", "4", key, False, heavy_slot=key), 650)
            self.assertEqual(self.ticker._calc_gear_duration("4", "2", key, False, heavy_slot=key), 450)
            self.assertEqual(self.ticker._calc_gear_duration("0", "9", key, False, heavy_slot=key), 450)
            self.assertEqual(self.ticker._calc_gear_duration("4", "3", key, False, heavy_slot="int_9"), 450)
        self.assertEqual(self.ticker._calc_gear_duration(",", ",", "comma_1", False), 300)

    def test_scrubbing_and_live_contexts_choose_identical_vertical_gears(self):
        for scrubbing in (False, True):
            for new, old, key, heavy, duration in (
                    ("4", "3", "int_0", "int_0", 650),
                    ("2", "1", "int_2", "int_2", 650),
                    ("4", "3", "int_0", "int_2", 450),
                    ("4", "2", "int_1", "int_1", 450),
                    ("0", "9", "dec_1", "int_0", 320),
                    ("0", "9", "dec_2", "int_0", 260)):
                with self.subTest(scrubbing=scrubbing, slot=key, old=old, new=new):
                    self.assertEqual(self.ticker._calc_gear_duration(
                        new, old, key, scrubbing, heavy_slot=heavy), duration)

    def test_123_99_carry_is_still_rolling_after_decimals_stop(self):
        self.ticker.set_price(D("123.99"))
        self.ticker.set_price(D("124.00"))
        ones = self.ticker.track_dict["int_0"]
        self.assertEqual(ones.scroll_anim.duration(), 650)
        for key, duration in (("dec_1", 320), ("dec_2", 260)):
            track = self.ticker.track_dict[key]
            self.assertEqual(track.scroll_anim.duration(), duration)
            track.scroll_anim.setCurrentTime(duration)
            self.assertEqual(track.current_offset, 0)
        ones.scroll_anim.setCurrentTime(500)
        self.assertEqual(ones.scroll_anim.state(), RUNNING)
        self.assertGreater(ones.current_offset, 3)
        self.assertLess(ones.current_offset, 4)
        ones.scroll_anim.setCurrentTime(600)
        self.assertEqual(ones.scroll_anim.state(), RUNNING)
        ones.scroll_anim.setCurrentTime(650)
        self.assertEqual(ones.current_offset, 4)
        self.assertNotEqual(ones.scroll_anim.state(), RUNNING)

    def test_heavy_roll_decelerates_over_equal_time_intervals(self):
        self.ticker.set_price(D("123.99"))
        self.ticker.set_price(D("124.00"))
        ones = self.ticker.track_dict["int_0"]
        self.assertEqual(ones.scroll_anim.duration(), 650)
        self.assertEqual(ones.scroll_anim.easingCurve().type(), QEasingCurve.Type.OutCubic)
        offsets = []
        for elapsed in (0, 130, 260, 390, 520, 650):
            ones.scroll_anim.setCurrentTime(elapsed)
            offsets.append(ones.current_offset)
        distances = [end - start for start, end in zip(offsets, offsets[1:])]
        self.assertTrue(all(left > right > 0 for left, right in zip(distances, distances[1:])))
        self.assertLess(distances[-1], distances[0] / 30)
        self.assertEqual(ones.current_offset, 4)
        self.assertNotEqual(ones.scroll_anim.state(), RUNNING)

    def test_199_99_carry_and_multi_step_jump_use_different_gears(self):
        self.ticker.set_price(D("199.99"))
        self.ticker.set_price(D("200.00"))
        self.assertEqual(self.ticker.track_dict["int_2"].scroll_anim.duration(), 650)
        self.assertEqual(self.ticker.track_dict["int_1"].scroll_anim.duration(), 450)
        self.finish()
        self.ticker.set_text("$23.00", animate=False)
        self.ticker.set_price(D("45.00"))
        self.assertEqual(self.ticker.track_dict["int_1"].scroll_anim.duration(), 450)
        self.assertEqual(self.ticker.track_dict["int_0"].scroll_anim.duration(), 450)

    def test_123_99_to_224_00_only_hundreds_has_heavy_inertia(self):
        self.ticker.set_price(D("123.99"))
        self.ticker.set_price(D("224.00"))
        tracks = self.ticker.track_dict
        self.assertEqual(tracks["int_2"].scroll_anim.duration(), 650)
        self.assertEqual(tracks["int_0"].scroll_anim.duration(), 450)
        self.assertNotEqual(tracks["int_1"].scroll_anim.state(), RUNNING)
        for key, duration in (("int_0", 450), ("dec_1", 320), ("dec_2", 260)):
            self.assertEqual(tracks[key].scroll_anim.duration(), duration)
            tracks[key].scroll_anim.setCurrentTime(duration)
            self.assertNotEqual(tracks[key].scroll_anim.state(), RUNNING)
        tracks["int_2"].scroll_anim.setCurrentTime(500)
        self.assertEqual(tracks["int_2"].scroll_anim.state(), RUNNING)
        self.assertGreater(tracks["int_2"].current_offset, 1)
        self.assertLess(tracks["int_2"].current_offset, 2)

    def test_multiple_integer_single_steps_only_engage_the_leading_heavy_gear(self):
        self.ticker.set_price(D("123.99"))
        self.ticker.set_price(D("234.00"))
        for key, duration in (("int_2", 650), ("int_1", 450), ("int_0", 450)):
            self.assertEqual(self.ticker.track_dict[key].scroll_anim.duration(), duration)

    def test_larger_leading_jump_does_not_select_a_lower_single_step(self):
        self.ticker.set_price(D("123.99"))
        self.ticker.set_price(D("324.00"))
        self.assertEqual(self.ticker.track_dict["int_2"].scroll_anim.duration(), 450)
        self.assertEqual(self.ticker.track_dict["int_0"].scroll_anim.duration(), 450)

    def test_a_new_leading_slot_prevents_lower_digits_from_using_650ms(self):
        self.ticker.set_price(D("23.99"))
        self.ticker.set_price(D("124.00"))
        self.assertEqual(self.ticker.track_dict["int_0"].scroll_anim.duration(), 450)
        self.assertEqual(self.ticker.track_dict["int_2"].appear_anim.state(), RUNNING)

    def test_a_new_leading_change_demotes_an_ongoing_lower_heavy_roll(self):
        self.ticker.set_price(D("123.99"))
        self.ticker.set_price(D("124.00"))
        ones = self.ticker.track_dict["int_0"]
        ones.scroll_anim.setCurrentTime(100)
        position = ones.current_offset
        self.ticker.set_price(D("224.00"))
        self.assertEqual(self.ticker.track_dict["int_2"].scroll_anim.duration(), 650)
        self.assertEqual(ones.scroll_anim.duration(), 450)
        self.assertAlmostEqual(ones.current_offset, position)
        self.assertEqual(ones.current_color, QColor("white"))
        self.assertEqual([key for key, track in self.ticker.track_dict.items()
                          if track.scroll_anim.state() == RUNNING and track.scroll_anim.duration() == 650],
                         ["int_2"])

    def test_scrubbing_reassigns_the_heavy_gear_without_a_position_jump(self):
        self.ticker.set_price(D("123.99"))
        self.ticker.set_price(D("124.00"), flash=False)
        ones = self.ticker.track_dict["int_0"]
        self.assertEqual(ones.scroll_anim.duration(), 650)
        ones.scroll_anim.setCurrentTime(100)
        position = ones.current_offset
        self.ticker.set_price(D("224.00"), flash=False)
        self.assertEqual(self.ticker.track_dict["int_2"].scroll_anim.duration(), 650)
        self.assertEqual(ones.scroll_anim.duration(), 450)
        self.assertAlmostEqual(ones.current_offset, position)
        self.assertTrue(all(track.current_color == QColor("white")
                            and track.color_anim.state() != RUNNING for track in self.digits()))

    def test_retargeting_emits_no_intermediate_offsets_from_the_previous_clock(self):
        for target in ("224.00", "126.00"):
            with self.subTest(target=target):
                self.ticker.set_text("$123.99", animate=False)
                self.ticker.set_price(D("124.00"), flash=False)
                ones = self.ticker.track_dict["int_0"]
                ones.scroll_anim.setCurrentTime(500)
                position = ones.current_offset % 10
                offsets = []
                ones.scroll_anim.valueChanged.connect(offsets.append)
                self.ticker.set_price(D(target), flash=False)
                ones.scroll_anim.valueChanged.disconnect(offsets.append)
                self.assertEqual(ones.scroll_anim.duration(), 450)
                self.assertAlmostEqual(ones.current_offset % 10, position)
                self.assertLessEqual(len(offsets), 1)
                for offset in offsets:
                    self.assertAlmostEqual(offset % 10, position)
                ones.scroll_anim.setCurrentTime(100)
                self.assertNotAlmostEqual(ones.current_offset % 10, position)

    def test_scrubbing_repaints_on_animation_ticks_instead_of_each_target(self):
        self.ticker.setStyleSheet("background: #000000;")
        self.ticker.set_price(D("54.67"))
        digit = self.ticker.track_dict["dec_2"]
        before = self.ticker.grab().toImage()
        with mock.patch.object(self.ticker, "update", wraps=self.ticker.update) as update:
            self.ticker.set_price(D("54.60"), flash=False)
            update.assert_not_called()
            self.assertEqual(self.ticker.grab().toImage(), before)
            digit.scroll_anim.setCurrentTime(16)
            update.assert_called()
            self.assertNotEqual(self.ticker.grab().toImage(), before)

    def test_decimal_only_ticks_do_not_restart_an_existing_heavy_integer_roll(self):
        self.ticker.set_price(D("123.99"))
        self.ticker.set_price(D("124.00"))
        ones = self.ticker.track_dict["int_0"]
        ones.scroll_anim.setCurrentTime(100)
        self.ticker.set_price(D("124.01"))
        self.assertEqual(ones.scroll_anim.duration(), 650)
        self.assertEqual(ones.scroll_anim.currentTime(), 100)

    def test_gear_diff_uses_the_latest_target_after_several_ticks(self):
        self.ticker.set_price(D("121.00"))
        self.ticker.set_price(D("131.00"))
        self.finish()
        tens = self.ticker.track_dict["int_1"]
        self.assertEqual(tens.char, "3")
        self.ticker.set_price(D("141.00"))
        self.assertEqual(tens.scroll_anim.duration(), 650)
        tens.scroll_anim.setCurrentTime(100)
        self.ticker.set_price(D("151.00"))
        self.assertEqual(tens.scroll_anim.duration(), 650)

    def test_semantic_slots_keep_identity_and_push_neighbors_smoothly(self):
        self.ticker.set_price(D("999.99"))
        existing = dict(self.ticker.track_dict)
        width_before = self.ticker.width()
        x_before = self.ticker.track_rect("int_2").x()
        self.ticker.set_price(D("1000.00"))
        for key, track in existing.items():
            self.assertIs(self.ticker.track_dict[key], track)
        self.assertEqual(self.ticker.width(), width_before)
        for key in ("int_3", "comma_1"):
            track = self.ticker.track_dict[key]
            self.assertEqual(track.width_factor, 0)
            self.assertEqual(track.opacity, 0)
            self.assertEqual(track.appear_anim.duration(), 350)
            self.assertIs(track.parent(), self.ticker)
            self.assertIs(track.appear_anim.parent(), track)
            track.appear_anim.setCurrentTime(175)
        self.assertGreater(self.ticker.track_rect("int_2").x(), x_before)
        self.assertGreater(self.ticker.width(), width_before)
        middle_width = self.ticker.width()
        self.finish()
        self.assertGreater(self.ticker.width(), middle_width)
        self.assertEqual([t.key for t in self.ticker.ordered_tracks()],
                         ["prefix", "int_3", "comma_1", "int_2", "int_1", "int_0", "dot", "dec_1", "dec_2"])

    def test_collapsed_slots_are_collected_without_another_quote(self):
        self.ticker.set_price(D("1000.00"))
        self.ticker.set_price(D("999.99"))
        track = self.ticker.track_dict["int_3"]
        self.assertTrue(track.is_marked_for_removal)
        self.assertIn("comma_1", self.ticker.track_dict)
        track.appear_anim.setCurrentTime(track.appear_anim.duration())
        self.assertNotIn("int_3", self.ticker.track_dict)
        comma = self.ticker.track_dict["comma_1"]
        comma.appear_anim.setCurrentTime(comma.appear_anim.duration())
        self.assertNotIn("comma_1", self.ticker.track_dict)
        self.qt_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        from PyQt6 import sip
        self.assertTrue(sip.isdeleted(track))
        self.assertTrue(sip.isdeleted(comma))

    def test_mid_collapse_reversal_revives_the_same_tracks(self):
        self.ticker.set_price(D("1000.00"))
        tracks = {key: self.ticker.track_dict[key] for key in ("int_3", "comma_1")}
        self.ticker.set_price(D("999.99"))
        for track in tracks.values():
            track.appear_anim.setCurrentTime(100)
        before = self.ticker.width()
        factors = {key: track.width_factor for key, track in tracks.items()}
        self.ticker.set_price(D("1000.00"))
        self.assertEqual(self.ticker.width(), before)
        for key, track in tracks.items():
            self.assertIs(self.ticker.track_dict[key], track)
            self.assertFalse(track.is_marked_for_removal)
            self.assertEqual(track.width_factor, factors[key])
        self.finish()
        self.assertTrue(all(track.width_factor == 1 for track in tracks.values()))

    def test_mid_expansion_reversal_does_not_snap_width_or_painted_frame(self):
        self.ticker.set_price(D("999.99"))
        self.ticker.set_price(D("1000.00"), flash=False)
        for key in ("int_3", "comma_1"):
            self.ticker.track_dict[key].appear_anim.setCurrentTime(80)
        before = self.ticker.width()
        image = self.ticker.grab().toImage()
        self.ticker.set_price(D("999.99"), flash=False)
        self.assertEqual(self.ticker.width(), before)
        self.assertEqual(self.ticker.grab().toImage(), image)
        self.finish()
        self.assertNotIn("int_3", self.ticker.track_dict)
        self.assertNotIn("comma_1", self.ticker.track_dict)

    def test_scrubbing_keeps_every_track_neutral_and_uses_the_same_gears(self):
        self.ticker.set_price(D("999.99"))
        self.ticker.set_price(D("1000.00"))
        self.assertTrue(any(d.color_anim.state() == RUNNING for d in self.digits()))
        self.ticker.set_price(D("23.45"), flash=False)
        for track in self.ticker.track_dict.values():
            self.assertEqual(track.current_color, QColor("white"))
            self.assertNotEqual(track.color_anim.state(), RUNNING)
            if track.scroll_anim.state() == RUNNING and not track.is_marked_for_removal:
                self.assertEqual(track.scroll_anim.duration(), 260 if track.key == "dec_2" else 320 if track.key.startswith("dec_") else 450)
            if track.appear_anim.state() == RUNNING:
                self.assertEqual(track.appear_anim.duration(), 180)

    def test_entering_scrub_preserves_vertical_motion_and_keeps_horizontal_motion_responsive(self):
        self.ticker.set_price(D("1000.00"))
        self.ticker.set_price(D("999.99"))
        ghost = self.ticker.track_dict["int_3"]
        ghost.appear_anim.setCurrentTime(80)
        decimal = self.ticker.track_dict["dec_1"]
        decimal.scroll_anim.setCurrentTime(70)
        before = self.ticker.width()
        self.ticker.set_price(D("998.98"), flash=False)
        self.assertEqual(self.ticker.width(), before)
        self.assertEqual(ghost.appear_anim.duration(), 180)
        decimal = self.ticker.track_dict["dec_1"]
        self.assertEqual(decimal.scroll_anim.duration(), 320)
        self.assertEqual(decimal.scroll_anim.currentTime(), 70)
        decimal.scroll_anim.setCurrentTime(20)
        ghost.appear_anim.setCurrentTime(20)
        self.ticker.set_price(D("998.98"), flash=False)
        self.assertEqual(decimal.scroll_anim.currentTime(), 20)
        self.assertEqual(ghost.appear_anim.currentTime(), 20)

    def test_zero_is_a_real_previous_price_and_sign_is_never_a_digit(self):
        self.ticker.set_price(D("0"))
        self.ticker.set_price(D("1"))
        self.assertEqual(self.ticker.track_dict["int_0"].current_color, QColor("#00C805"))
        self.ticker.set_price(D("-999.99"))
        self.assertFalse(self.ticker.track_dict["sign"].is_digit)
        self.assertEqual(self.ticker.track_dict["sign"].current_color, QColor("white"))
        self.finish()
        self.assertEqual("".join(t.target_char for t in self.ticker.ordered_tracks()), "-$999.99")
        self.ticker.set_price(D("1000.00"))
        self.finish()
        self.assertNotIn("sign", self.ticker.track_dict)
        self.assertEqual("".join(t.target_char for t in self.ticker.ordered_tracks()), "$1,000.00")
        for track in self.ticker.track_dict.values():
            self.assertEqual(track.is_digit, track.key.startswith(("int_", "dec_")))
        with self.assertRaises(ValueError):
            self.ticker.track_dict["int_0"].set_target(",", 180)
        with self.assertRaises(AttributeError):
            self.ticker.track_dict["prefix"].is_digit = True
        self.assertGreater(get_slot_rank("comma_2"), get_slot_rank("int_5"))

    def test_rapid_boundary_crossings_release_retired_qobjects(self):
        for index in range(150):
            self.ticker.set_price(D("1000000.01") if index % 2 else D("0.35"), flash=False)
            for track in list(self.ticker.track_dict.values()):
                if track.appear_anim.state() == RUNNING:
                    track.appear_anim.setCurrentTime(30)
        self.finish()
        self.qt_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertEqual(len(self.ticker.findChildren(CharacterTrack)), len(self.ticker.track_dict))
        self.assertTrue(all(not track.is_marked_for_removal for track in self.ticker.track_dict.values()))
        from PyQt6.QtCore import QVariantAnimation
        self.assertEqual(len(self.ticker.findChildren(QVariantAnimation)), 3 * len(self.ticker.track_dict))

    def test_canvas_has_a_nonzero_size_even_when_left_aligned(self):
        from PyQt6.QtWidgets import QHBoxLayout, QWidget
        container = QWidget()
        container.setStyleSheet("background: #000000;")
        layout = QHBoxLayout(container)
        self.ticker.setParent(container)
        layout.addWidget(self.ticker, alignment=Qt.AlignmentFlag.AlignLeft)
        container.resize(800, 90)
        container.show()
        self.ticker.show()
        self.ticker.set_price(D("999.99"))
        self.qt_app.processEvents()
        height = self.ticker.height()
        for value in ("1000.00", "999.99", "0.35", "1000000.01"):
            self.ticker.set_price(D(value))
            self.finish()
            self.qt_app.processEvents()
            self.assertEqual(self.ticker.size(), self.ticker.sizeHint())
            self.assertEqual(self.ticker.minimumSizeHint(), self.ticker.sizeHint())
            self.assertGreaterEqual(self.ticker.width(), 60)
            self.assertEqual(self.ticker.height(), height)
            self.assertEqual(len(self.ticker.findChildren(QWidget)), 0)
            self.assertTrue(self.ticker.isVisible())
            frame = self.ticker.grab().toImage()
            self.assertTrue(any(frame.pixelColor(x, y).value() > 0
                                for x in range(frame.width()) for y in range(frame.height())))
        self.ticker.setParent(None)
        container.close()
        container.deleteLater()


class ChartRenderingTests(unittest.TestCase):
    def setUp(self):
        self.root = qt.Window()
        app.set_theme("light")
        app.UI.setup(self.root)
        self.hover = mock.Mock()
        self.chart = app.LineChart(self.root, height=220, on_hover=self.hover)
        self.chart.pack(fill="x")
        self.root.resize(900, 300)
        self.root.show()
        self.chart.set_data([10, 12, 11, 14], baseline=11, labels=["A", "B", "C", "D"])
        for _ in range(3):
            qt.application().processEvents()

    def tearDown(self):
        self.root.destroy()
        qt.application().processEvents()

    def motion(self, index):
        chart = self.chart
        step = (chart.width() - 2 * chart.pad) / (max(len(chart.values), chart.slots, 2) - 1)
        chart._motion(SimpleNamespace(x=chart.pad + index * step, y=100))

    def assert_original_pixels(self):
        cached = self.chart.grab().toImage()
        with mock.patch.object(app.LineChart, "paintEvent", qt.Canvas.paintEvent):
            original = self.chart.grab().toImage()
        self.assertEqual(cached, original, "caching must preserve the original chart's pixels")

    def test_repeated_pointer_samples_skip_work_and_new_points_reuse_the_overlay(self):
        self.motion(1)
        overlay = self.chart.find_withtag("hover")
        backing = self.chart._plot_cache.cacheKey()
        with mock.patch.object(self.chart, "_xy", side_effect=AssertionError("rescanned history")), \
                mock.patch.object(self.chart, "update", wraps=self.chart.update) as update:
            for _ in range(100):
                self.motion(1)
            update.assert_not_called()
            self.hover.assert_called_once_with(1)
            self.motion(2)
        self.assertEqual(self.chart.find_withtag("hover"), overlay)
        self.assertEqual(self.hover.call_args_list, [mock.call(1), mock.call(2)])
        painted = []
        draw_shapes = self.chart._paint_shapes

        def record_shapes(painter, shapes):
            shapes = list(shapes)
            painted.extend(shapes)
            draw_shapes(painter, shapes)

        with mock.patch.object(self.chart, "_paint_shapes", side_effect=record_shapes):
            self.chart.grab()
        self.assertTrue(painted)
        self.assertTrue(all("hover" in self.chart._shape_tags(shape[2]) for shape in painted))
        self.assertEqual(self.chart._plot_cache.cacheKey(), backing)
        self.chart._leave(None)
        self.hover.assert_called_with(None)
        self.motion(2)
        self.assertEqual(self.hover.call_args_list[-2:], [mock.call(None), mock.call(2)])

    def test_backing_matches_original_pixels_in_both_themes_and_hover_states(self):
        for theme in ("light", "dark"):
            app.set_theme(theme)
            self.chart.configure(bg=app.C["bg"])
            for pulse in (False, True):
                with self.subTest(theme=theme, pulse=pulse):
                    self.chart.set_data([10, 12, 11, 14], baseline=11, labels=["A", "B", "C", "D"],
                                        color=app.C["gain"], pulse=pulse)
                    self.chart._stop_pulse()
                    self.chart._leave(None)
                    self.assert_original_pixels()
                    for index in (0, 1, 3):
                        self.motion(index)
                        self.assert_original_pixels()
                    self.chart._leave(None)
                    self.assert_original_pixels()

    def test_data_resize_background_and_missing_labels_refresh_the_backing(self):
        self.motion(1)
        self.chart.grab()
        backing = self.chart._plot_cache.cacheKey()
        self.chart.set_data([30, 15, 45, 20], baseline=25, labels=["New"])
        self.motion(1)
        self.hover.assert_called_with(1)
        self.assert_original_pixels()
        self.assertNotEqual(self.chart._plot_cache.cacheKey(), backing)
        self.assertEqual(self.chart.itemcget(self.chart._hover_items[2], "state"), "hidden")
        self.root.resize(700, 300)
        qt.application().processEvents()
        self.motion(0)
        self.assert_original_pixels()
        self.chart.configure(bg="#E0E0E0")
        self.assert_original_pixels()
        self.chart.set_data([], message="Loading…")
        self.assert_original_pixels()

    def test_cached_pixels_match_for_flat_negative_and_partially_filled_charts(self):
        for theme in ("light", "dark"):
            app.set_theme(theme)
            self.chart.configure(bg=app.C["bg"])
            for values, baseline, slots in (([3, 3, 3], 3, 0), ([-2, -1, -4], 0, 0),
                                            ([0, .01, -.01], None, 0), ([6, 8, 7], 7, 79)):
                with self.subTest(theme=theme, values=values, baseline=baseline, slots=slots):
                    self.chart.set_data(values, baseline=baseline, slots=slots, color=app.C["loss"],
                                        labels=["A", "B", "C"])
                    self.chart._leave(None)
                    self.assert_original_pixels()
                    for index in (0, 2):
                        self.motion(index)
                        self.assert_original_pixels()


class AppTests(unittest.TestCase):
    def setUp(self):
        self.root, self.app = _gui_window()
        self.folder = self.app.db.path.parent
        self.errors = []
        self.old_hook = sys.excepthook
        sys.excepthook = lambda *error: self.errors.append(error)
        self.network = mock.patch.object(app.App, "run_bg", side_effect=AssertionError("unexpected network"))
        self.network.start()
        self.live = mock.patch("app.is_live", return_value=False)
        self.live.start()
        self.root.resize(1440, 1000)
        self.root.process_events()
        self.assertTrue(QTest.qWaitForWindowExposed(self.root, 3000))
        self.assertTrue(QTest.qWaitForWindowActive(self.root, 3000))
        self.root.process_events()

    def tearDown(self):
        self.network.stop()
        self.live.stop()
        _close_gui(self.root)
        self.app.db.close()
        shutil.rmtree(self.folder)
        i18n.set_language("en")
        sys.excepthook = self.old_hook
        self.assertEqual(self.errors, [])

    @staticmethod
    def quote(price, stamp=None):
        return Quote(price=D(price), prev_close=D("10"), time=stamp,
                     points=[(1800000000, 10.0), (1800000300, 10.5)])

    def apply(self, price):
        self.app.v_live.set(True)
        quotes = {"SKYD": self.quote(price), "AAPL": self.quote("155")}
        self.app._apply_quotes(list(quotes), quotes)

    def test_older_quotes_cannot_replace_prices_or_history_in_a_mixed_batch(self):
        a = self.app
        a.v_live.set(True)
        stamp = datetime(2026, 11, 4, 10, 5)
        current = {"SKYD": self.quote("11", stamp), "AAPL": self.quote("155", stamp)}
        a._apply_quotes(list(current), current)
        a.open_symbol("SKYD")
        points = list(a.detail.hero.chart.values)
        incoming = {"SKYD": self.quote("10.50", stamp - timedelta(minutes=5)),
                    "AAPL": self.quote("154", stamp + timedelta(seconds=10))}
        incoming["SKYD"].points = [(1800000000, 9.0), (1800000300, 9.5)]

        with mock.patch.object(a.db, "set_prices", wraps=a.db.set_prices) as save:
            a._apply_quotes(list(incoming), incoming)
            save.assert_called_once_with({"AAPL": D(154)})

        self.assertIs(a.quotes["SKYD"], current["SKYD"])
        self.assertEqual(a.prices["SKYD"], D(11))
        self.assertEqual(a.db.get_prices()["SKYD"][0], D(11))
        self.assertEqual(a.detail.hero.now[0], "$11.00")
        self.assertEqual(a.detail.hero.chart.values, points)
        self.assertIs(a.quotes["AAPL"], incoming["AAPL"])
        self.assertEqual(a.prices["AAPL"], D(154))

    def test_newer_and_same_time_quotes_still_update_prices(self):
        a = self.app
        a.v_live.set(True)
        stamp = datetime(2026, 11, 4, 10, 5)
        for price, offset in (("11", 0), ("10.50", 10), ("10.51", 10)):
            with self.subTest(price=price, seconds=offset):
                quote = self.quote(price, stamp + timedelta(seconds=offset))
                a._apply_quotes(["SKYD"], {"SKYD": quote})
                self.assertIs(a.quotes["SKYD"], quote)
                self.assertEqual(a.prices["SKYD"], D(price))
                self.assertEqual(a.db.get_prices()["SKYD"][0], D(price))

    def test_unchanged_price_advances_the_accepted_quote_time(self):
        a = self.app
        a.v_live.set(True)
        stamp = datetime(2026, 11, 4, 10, 5)
        a._apply_quotes(["SKYD"], {"SKYD": self.quote("11", stamp)})
        newer = self.quote("11", stamp + timedelta(minutes=5))
        with mock.patch.object(a.db, "set_prices", wraps=a.db.set_prices) as save:
            a._apply_quotes(["SKYD"], {"SKYD": newer})
            save.assert_not_called()
        a._apply_quotes(["SKYD"], {"SKYD": self.quote("10.50", stamp + timedelta(minutes=3))})
        self.assertIs(a.quotes["SKYD"], newer)
        self.assertEqual(a.prices["SKYD"], D(11))
        self.assertEqual(a.db.get_prices()["SKYD"][0], D(11))

    def test_quotes_without_time_remain_compatible_but_cannot_replace_a_timed_quote(self):
        a = self.app
        a.v_live.set(True)
        for price in ("10.50", "11"):
            a._apply_quotes(["SKYD"], {"SKYD": self.quote(price)})
            self.assertEqual(a.prices["SKYD"], D(price))
        current = self.quote("12", datetime(2026, 11, 4, 10, 5))
        a._apply_quotes(["SKYD"], {"SKYD": current})
        with mock.patch.object(a.db, "set_prices", wraps=a.db.set_prices) as save:
            a._apply_quotes(["SKYD"], {"SKYD": self.quote("10.50")})
            save.assert_not_called()
        self.assertIs(a.quotes["SKYD"], current)
        self.assertEqual(a.prices["SKYD"], D(12))

    def test_live_toggle_preserves_quote_time_validation_for_each_symbol(self):
        a = self.app
        a.v_live.set(True)
        stamp = datetime(2026, 11, 4, 10, 5)
        current = {"SKYD": self.quote("11", stamp), "AAPL": self.quote("155", stamp)}
        a._apply_quotes(list(current), current)
        a.open_symbol("SKYD")
        a.v_live.set(False)
        a.toggle_live()
        self.assertEqual(a.quotes, {})

        incoming = {"SKYD": self.quote("10.50", stamp - timedelta(minutes=5)),
                    "AAPL": self.quote("154", stamp + timedelta(seconds=10))}
        with mock.patch.object(a, "run_bg") as background:
            a.v_live.set(True)
            a.toggle_live()
            done = background.call_args.args[2]
            with mock.patch.object(a.db, "set_prices", wraps=a.db.set_prices) as save:
                done(incoming)
                save.assert_called_once_with({"AAPL": D(154)})

        self.assertEqual(a.prices["SKYD"], D(11))
        self.assertEqual(a.db.get_prices()["SKYD"][0], D(11))
        self.assertEqual(a.detail.hero.now[0], "$11.00")
        self.assertEqual(a.prices["AAPL"], D(154))
        newer = self.quote("10.25", stamp + timedelta(minutes=1))
        a._apply_quotes(["SKYD"], {"SKYD": newer})
        self.assertIs(a.quotes["SKYD"], newer)
        self.assertEqual(a.prices["SKYD"], D("10.25"))
        self.assertEqual(a.detail.hero.now[0], "$10.25")

    def test_live_toggle_rejects_untimed_quotes_but_allows_same_time_corrections(self):
        a = self.app
        a.v_live.set(True)
        stamp = datetime(2026, 11, 4, 10, 5)
        a._apply_quotes(["SKYD"], {"SKYD": self.quote("11", stamp)})
        a.v_live.set(False)
        a.toggle_live()
        with mock.patch.object(a, "run_bg") as background:
            a.v_live.set(True)
            a.toggle_live()
            with mock.patch.object(a.db, "set_prices", wraps=a.db.set_prices) as save:
                background.call_args.args[2]({"SKYD": self.quote("10.50")})
                save.assert_not_called()
        self.assertEqual(a.prices["SKYD"], D(11))
        self.assertEqual(a.db.get_prices()["SKYD"][0], D(11))
        corrected = self.quote("11.01", stamp)
        a._apply_quotes(["SKYD"], {"SKYD": corrected})
        self.assertIs(a.quotes["SKYD"], corrected)
        self.assertEqual(a.prices["SKYD"], D("11.01"))
        self.assertEqual(a.db.get_prices()["SKYD"][0], D("11.01"))

    def test_quotes_ignored_while_live_is_off_do_not_advance_the_time_guard(self):
        a = self.app
        a.v_live.set(True)
        stamp = datetime(2026, 11, 4, 10, 5)
        a._apply_quotes(["SKYD"], {"SKYD": self.quote("11", stamp)})
        a.v_live.set(False)
        a.toggle_live()
        a._apply_quotes(["SKYD"], {"SKYD": self.quote("12", stamp + timedelta(minutes=5))})
        self.assertEqual(a.quotes, {})
        self.assertEqual(a.prices["SKYD"], D(11))
        self.assertEqual(a.db.get_prices()["SKYD"][0], D(11))
        current = self.quote("11.50", stamp + timedelta(minutes=2))
        with mock.patch.object(a, "run_bg") as background:
            a.v_live.set(True)
            a.toggle_live()
            background.call_args.args[2]({"SKYD": current})
        self.assertIs(a.quotes["SKYD"], current)
        self.assertEqual(a.prices["SKYD"], D("11.50"))
        self.assertEqual(a.db.get_prices()["SKYD"][0], D("11.50"))

    def test_only_the_three_requested_headlines_animate(self):
        a = self.app
        second = a.db.create_account("Second")
        a.db.add_txn(Txn(account_id=second, date="2026-02-01", type="DEPOSIT", amount=D(5000)))
        a.load_accounts(select_id=app.ALL_ACCOUNTS)
        _turn_on_finance(a)
        self.root.process_events()
        self.apply("11")
        self.assertIsInstance(a.hero.value, TickerLabel)
        self.assertEqual(a.hero.value.cget("text"), "$26,050.00")
        self.assertIsInstance(a.stock_rows["SKYD"].pill, qt.Canvas)
        self.assertNotIsInstance(a.stock_rows["SKYD"].pill, TickerLabel)
        self.assertTrue(all(isinstance(value, QLabel) for value, _ in a.stats.cells.values()))
        self.assertTrue(all(isinstance(value, QLabel) for value, _ in a.net_summary[1].cells.values()))
        for account in (app.ALL_ACCOUNTS, a.accounts[0]["id"]):
            a._select_account(account)
            a.open_symbol("SKYD")
            self.root.process_events()
            self.assertIsInstance(a.detail.hero.value, TickerLabel)
            self.assertEqual(a.detail.hero.value.old_str, "$11.00")
            self.apply("11.01")
            digit = a.detail.hero.value.track_dict["dec_2"]
            self.assertEqual(digit.scroll_anim.state(), RUNNING)
            self.assertEqual(digit.current_color, QColor("#00C805"))
            self.assertTrue(all(d.scroll_anim.state() != RUNNING for d in a.hero.value.track_dict.values() if d.is_digit))
            self.apply("11")
            a.close_detail()
        self.assertNotIn("tkinter", sys.modules)

    def test_unplaced_summary_and_scrollbars_stay_hidden(self):
        _turn_on_finance(self.app)
        self.root.process_events()
        self.assertFalse(self.app.net_summary[0].isVisible())
        self.app.open_finance()
        self.root.process_events()
        bars = [w for w in self.app.finance.detail.master.winfo_children() if isinstance(w, qt.Scrollbar)]
        self.assertTrue(bars)
        self.assertTrue(all(not bar.isVisible() for bar in bars))

    def test_width_changes_preserve_the_existing_headline_and_page_row_heights(self):
        hero = self.app.hero
        # Let the existing nested table/stat layouts finish their initial font
        # measurements before recording the page geometry for this comparison.
        for _ in range(6):
            self.root.process_events()
        geometry = (hero.height(), hero.chart.geometry(), hero.change.parentWidget().geometry(),
                    self.app.stats.geometry())
        hero.value.set_text("$999.99", animate=False)
        hero.value.set_text("$1,000.00")
        for track in list(hero.value.track_dict.values()):
            if track.appear_anim.state() == RUNNING:
                track.appear_anim.setCurrentTime(175)
        self.root.process_events()
        self.assertEqual((hero.height(), hero.chart.geometry(), hero.change.parentWidget().geometry(),
                          self.app.stats.geometry()), geometry)

    def test_quotes_during_probe_restore_the_latest_price(self):
        self.apply("11")
        self.app.open_symbol("SKYD")
        self.root.process_events()
        hero = self.app.detail.hero
        hero._hover(0)
        self.assertEqual(hero.value.old_str, "$10.00")
        self.assertTrue(all(d.color_anim.state() != RUNNING for d in hero.value.track_dict.values() if d.is_digit))
        self.apply("12")
        self.assertEqual(hero.value.old_str, "$10.00")
        hero._hover(None)
        self.assertEqual(hero.value.old_str, "$12.00")
        self.assertTrue(any(d.scroll_anim.duration() in (260, 320, 450, 650) and d.current_color == QColor("#00C805") for d in hero.value.track_dict.values() if d.is_digit))

    def test_quote_replaces_the_hovered_point_even_when_its_index_is_unchanged(self):
        self.apply("11")
        self.app.open_symbol("SKYD")
        self.root.process_events()
        hero = self.app.detail.hero
        move_mouse(hero.chart, QPoint(hero.chart.pad, hero.chart.height() // 2))
        self.assertEqual(hero._scrub_index, 0)
        self.assertEqual(hero.value.old_str, "$10.00")
        hero.chart.grab()
        backing = hero.chart._plot_cache.cacheKey()
        quotes = {"SKYD": Quote(price=D(12), prev_close=D(10), time=None,
                                points=[(1800000000, 10.25), (1800000300, 10.75)]),
                  "AAPL": self.quote("155")}
        self.app._apply_quotes(list(quotes), quotes)
        self.assertEqual(hero._scrub_index, 0)
        self.assertEqual(hero.value.old_str, "$10.25")
        self.assertIn("0.25", hero.change.cget("text"))
        self.assertTrue(hero.value._scrubbing)
        hero.chart.grab()
        self.assertNotEqual(hero.chart._plot_cache.cacheKey(), backing)
        with mock.patch.object(hero.chart, "on_hover", wraps=hero._hover) as hover:
            move_mouse(hero.chart, QPoint(hero.chart.pad, hero.chart.height() // 2 + 1))
            hover.assert_called_once_with(0)
        qt.application().sendEvent(hero.chart, QEvent(QEvent.Type.Leave))
        self.assertIsNone(hero._scrub_index)
        self.assertEqual(hero.value.old_str, "$12.00")
        self.assertFalse(hero.value._scrubbing)

    def test_restoring_the_same_displayed_price_leaves_scrub_mode(self):
        self.apply("10")
        self.app.open_symbol("SKYD")
        self.root.process_events()
        hero = self.app.detail.hero
        hero._hover(0)
        self.assertEqual(hero.value.old_str, "$10.00")
        self.assertTrue(hero.value._scrubbing)
        hero._hover(None)
        self.assertEqual(hero.value.old_str, "$10.00")
        self.assertFalse(hero.value._scrubbing)
        self.assertEqual(hero.period.cget("text"), hero.now[3])
        self.apply("10.01")
        self.assertEqual(hero.value.old_str, "$10.01")
        self.assertEqual(hero.value.track_dict["dec_2"].current_color, QColor("#00C805"))

    def test_native_chart_pointer_and_keyboard_shortcuts(self):
        self.apply("11")
        self.app.open_symbol("SKYD")
        self.root.process_events()
        hero = self.app.detail.hero
        move_mouse(hero.chart, QPoint(hero.chart.pad, hero.chart.height() // 2))
        self.assertIsNotNone(hero._scrub_index)
        self.assertEqual(hero.value.old_str, "$10.00")
        qt.application().sendEvent(hero.chart, QEvent(QEvent.Type.Leave))
        self.assertIsNone(hero._scrub_index)
        self.assertEqual(hero.value.old_str, "$11.00")
        self.app.close_detail()
        with mock.patch.object(self.app, "add_txn") as add, mock.patch.object(self.app, "refresh") as refresh:
            QTest.keyClick(self.app.hold_tree, Qt.Key.Key_N, Qt.KeyboardModifier.ControlModifier)
            add.assert_called_once()
            QTest.keyClick(self.app.hold_tree, Qt.Key.Key_F5)
            refresh.assert_called_once()

    def test_scrubbing_only_updates_changed_headline_label_properties(self):
        hero = self.app.hero
        hero.show("1W", "$12.00", [(1800000000, 10, 0), (1800000300, 11, 0), (1800000600, 12, 0)],
                  baseline=9)
        hero._hover(0)
        with mock.patch.object(hero.change, "setStyleSheet", wraps=hero.change.setStyleSheet) as style, \
                mock.patch.object(hero.period, "configure", wraps=hero.period.configure) as period:
            hero._hover(1)
            self.assertEqual(hero.value.old_str, "$11.00")
            self.assertIn("2.00", hero.change.cget("text"))
            style.assert_not_called()
            period.assert_not_called()
            with mock.patch.object(hero.change, "configure", wraps=hero.change.configure) as change:
                hero._hover(1)
                change.assert_not_called()

    def test_native_chart_scrubbing_uses_heavy_gears_in_all_three_headlines(self):
        a = self.app
        single = a.accounts[0]["id"]
        second = a.db.create_account("Second")
        a.db.add_txn(Txn(account_id=second, date="2026-02-01", type="DEPOSIT", amount=D(5000)))
        times = (1800000000, 1800000300, 1800000600)
        quotes = {
            "SKYD": Quote(price=D("225"), prev_close=D("123.99"), time=None,
                          points=list(zip(times, (123.99, 124.0, 224.0)))),
            "AAPL": Quote(price=D("155"), prev_close=D("155"), time=None,
                          points=[(ts, 155.0) for ts in times]),
        }
        a.v_live.set(True)
        a._apply_quotes(list(quotes), quotes)
        a.load_accounts(select_id=app.ALL_ACCOUNTS)

        def move(hero, index, dy=0):
            chart = hero.chart
            slots = max(len(chart.values), chart.slots, 2)
            step = (chart.width() - 2 * chart.pad) / (slots - 1)
            move_mouse(chart, QPoint(round(chart.pad + index * step), chart.height() // 2 + dy))
            self.assertEqual(hero._scrub_index, index)

        def assert_gears(ticker, gears):
            for key, duration in gears.items():
                track = ticker.track_dict[key]
                self.assertEqual(track.scroll_anim.state(), RUNNING, key)
                self.assertEqual(track.scroll_anim.duration(), duration, key)
                self.assertEqual(track.scroll_anim.easingCurve().type(), QEasingCurve.Type.OutCubic)
            for track in ticker.track_dict.values():
                self.assertEqual(track.current_color, ticker.neutral)
                self.assertNotEqual(track.color_anim.state(), RUNNING)

        for account in (app.ALL_ACCOUNTS, single):
            with self.subTest(account=account):
                a._select_account(account)
                self.root.process_events()
                hero = a.hero
                move(hero, 2)
                move(hero, 0)
                hero.value.settle()
                move(hero, 1)
                assert_gears(hero.value, {"int_1": 650})

                a.open_symbol("SKYD")
                self.root.process_events()
                hero = a.detail.hero
                move(hero, 2)
                move(hero, 0)
                hero.value.settle()
                self.assertEqual(hero.value.old_str, "$123.99")
                move(hero, 1)
                self.assertEqual(hero.value.old_str, "$124.00")
                assert_gears(hero.value, {"int_0": 650, "dec_1": 320, "dec_2": 260})
                ones = hero.value.track_dict["int_0"]
                ones.scroll_anim.setCurrentTime(100)
                with mock.patch.object(ones.scroll_anim, "start", wraps=ones.scroll_anim.start) as start:
                    move(hero, 1, dy=1)
                    start.assert_not_called()
                ones.scroll_anim.setCurrentTime(500)
                self.assertEqual(ones.scroll_anim.state(), RUNNING)
                self.assertGreater(ones.current_offset, 3)
                self.assertLess(ones.current_offset, 4)

                move(hero, 0)
                hero.value.settle()
                move(hero, 2)
                self.assertEqual(hero.value.old_str, "$224.00")
                assert_gears(hero.value, {"int_2": 650, "int_0": 450, "dec_1": 320, "dec_2": 260})
                a.close_detail()

    def test_symbol_suggestions_pick_without_saving_the_dialog(self):
        def suggest(query, show):
            show(query, [("AAPL", "Apple", "10 shares"), ("AMZN", "Amazon", "")])
        dialog = app.AccountDialog(self.root, "Account", suggest=suggest)
        dialog.v_name.set("Test")
        dialog.deiconify()
        self.assertTrue(QTest.qWaitForWindowExposed(dialog, 3000))
        self.assertTrue(QTest.qWaitForWindowActive(dialog, 3000))
        entry = dialog.pos_sym_entry
        QTest.mouseClick(entry, Qt.MouseButton.LeftButton)
        self.assertTrue(wait_for(lambda: entry.focus_get() is entry))
        QTest.keyClicks(entry, "A")
        self.assertIsNotNone(entry.popup)
        self.assertEqual(entry.active, 0)
        QTest.keyClick(entry, Qt.Key.Key_Down)
        self.assertEqual(entry.active, 1)
        QTest.keyClick(entry, Qt.Key.Key_Return)
        self.assertEqual(entry.var.get(), "AMZN")
        self.assertIsNone(entry.popup)
        self.assertTrue(dialog.winfo_exists())
        dialog.destroy()

    def test_stock_row_mouse_click_is_dispatched_once(self):
        clicked = mock.Mock()
        row = app.StockRow(self.root, "AAPL", clicked)
        row.pack()
        self.root.process_events()
        QTest.mouseClick(row.sym_label, Qt.MouseButton.LeftButton)
        clicked.assert_called_once_with("AAPL")

    def test_suggestion_mouse_click_picks_once_without_callback_errors(self):
        def suggest(query, show):
            show(query, [("AAPL", "Apple", "10 shares")])
        dialog = app.AccountDialog(self.root, "Account", suggest=suggest)
        dialog.deiconify()
        self.assertTrue(QTest.qWaitForWindowExposed(dialog, 3000))
        self.assertTrue(QTest.qWaitForWindowActive(dialog, 3000))
        entry = dialog.pos_sym_entry
        QTest.mouseClick(entry, Qt.MouseButton.LeftButton)
        self.assertTrue(wait_for(lambda: entry.focus_get() is entry))
        QTest.keyClicks(entry, "A")
        self.assertIsNotNone(entry.popup)
        label = entry.row_widgets[0][1]
        QTest.mouseClick(label, Qt.MouseButton.LeftButton)
        self.assertEqual(entry.var.get(), "AAPL")
        self.assertIsNone(entry.popup)
        self.assertTrue(dialog.winfo_exists())
        self.assertEqual(self.errors, [])
        dialog.destroy()

    def test_table_double_click_opens_one_editor_and_ignores_right_button(self):
        self.app._show_page("Transactions")
        self.root.process_events()
        tree = self.app.txn_tree
        iid = tree.get_children()[0]
        x, y, width, height = tree.bbox(iid, 0)
        point = QPoint(x + width // 2, y - tree.horizontalHeader().height() + height // 2)
        with mock.patch.object(self.app, "edit_txn") as edit:
            QTest.mouseDClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=point)
            edit.assert_called_once()
            edit.reset_mock()
            QTest.mouseDClick(tree.viewport(), Qt.MouseButton.RightButton, pos=point)
            edit.assert_not_called()

    def test_keypad_enter_saves_a_modal_dialog(self):
        dialog = app.TxnDialog(self.root, "Add", positions=self.app.result.positions,
                               check=lambda txn, owner: True, suggest=self.app.symbol_search)
        dialog.v_type.set("Deposit")
        dialog._on_type()
        dialog.v_amount.set("42.25")
        modality = []
        def press_enter():
            modality.append(self.root.grab_current() is dialog)
            QTest.keyClick(dialog.amount_entry, Qt.Key.Key_Enter)
            # Prevent a regression from hanging the entire test run.
            if not dialog._dead:
                dialog.cancel()
        QTimer.singleShot(0, press_enter)
        result = dialog.show()
        self.assertEqual(modality, [True])
        self.assertIsNotNone(result, "keypad Enter must perform the same save as Return")
        self.assertEqual(result.amount, D("42.25"))

    def test_minimized_window_adopts_quotes_without_running_animations(self):
        self.apply("11")
        self.root.showMinimized()
        self.root.process_events()
        self.assertTrue(wait_for(lambda: self.root.isMinimized() or not self.root.windowHandle().isExposed()))
        self.assertFalse(self.app.hero.value.winfo_viewable())
        self.apply("12")
        self.assertEqual(self.app.hero.value.cget("text"), "$22,050.00")
        self.assertTrue(all(d.scroll_anim.state() != RUNNING and d.color_anim.state() != RUNNING
                            for d in self.app.hero.value.track_dict.values() if d.is_digit))
        # Remap explicitly: Wayland may report WindowNoState even while hidden,
        # so showNormal() alone need not ask the compositor to restore it.
        self.root.hide()
        self.root.showNormal()
        self.assertTrue(QTest.qWaitForWindowExposed(self.root, 3000))
        self.root.process_events()
        self.assertEqual(self.app.hero.value.cget("text"), "$22,050.00")

    def test_unexposed_native_window_adopts_quotes_without_running_animations(self):
        self.apply("11")
        self.assertFalse(self.root.isMinimized())
        with mock.patch.object(self.root.windowHandle(), "isExposed", return_value=False):
            self.assertFalse(self.app.hero.value.winfo_viewable())
            self.apply("12")
            self.assertEqual(self.app.hero.value.cget("text"), "$22,050.00")
            self.assertTrue(all(track.scroll_anim.state() != RUNNING and track.color_anim.state() != RUNNING
                                for track in self.app.hero.value.track_dict.values()))
        self.assertTrue(self.app.hero.value.winfo_viewable())
        self.apply("13")
        self.assertTrue(any(track.scroll_anim.state() == RUNNING for track in self.app.hero.value.track_dict.values()))

    def test_native_transaction_dialog_keyboard_and_opening_positions(self):
        d = app.TxnDialog(self.root, "Add", positions=self.app.result.positions,
                          check=lambda t, dialog: True, suggest=self.app.symbol_search)
        d.v_type.set("Deposit")
        d._on_type()
        d.v_amount.set("42.25")
        QTimer.singleShot(0, lambda: QTest.keyClick(d.amount_entry, Qt.Key.Key_Return))
        result = d.show()
        self.assertEqual(result.type, "DEPOSIT")
        self.assertEqual(result.amount, D("42.25"))
        d = app.AccountDialog(self.root, "Account", suggest=self.app.symbol_search)
        d.v_name.set("New")
        d.v_cash.set("1000")
        d.v_pos_sym.set("AAPL")
        d.v_pos_qty.set("2")
        d.v_pos_cost.set("100")
        d._add_position()
        result = d.build_result()
        self.assertEqual([t.type for t in result["opening"]], ["DEPOSIT", "SHARES_IN"])
        d.destroy()

    def test_theme_language_and_account_switch_cancel_old_animations(self):
        self.apply("11")
        self.apply("11.01")
        previous = self.app.hero.value
        self.app.v_dark.set(True)
        i18n.set_language("zh")
        self.app.rebuild()
        self.root.process_events()
        self.assertFalse(previous.winfo_exists())
        self.assertEqual(self.app.hero.value.old_str, "$21,060.00")
        self.assertTrue(all(d.current_color == QColor("white") for d in self.app.hero.value.track_dict.values() if d.is_digit))
        second = self.app.db.create_account("Second")
        self.app.db.add_txn(Txn(account_id=second, date="2026-02-01", type="DEPOSIT", amount=D(5000)))
        self.app.load_accounts(select_id=second)
        self.assertEqual(self.app.hero.value.old_str, "$5,000.00")
        self.assertTrue(all(d.scroll_anim.state() != RUNNING for d in self.app.hero.value.track_dict.values() if d.is_digit))

    def test_application_exits_cleanly_from_the_native_event_loop(self):
        code = """
from PyQt6.QtCore import QTimer
from test_ledger import _gui_window
root, ledger = _gui_window()
QTimer.singleShot(20, ledger.quit)
root.mainloop()
print('closed')
"""
        result = subprocess.run([sys.executable, "-X", "faulthandler", "-c", code],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("closed", result.stdout)

    def test_native_event_loop_survives_rebuild_and_navigation_stress(self):
        code = """
import sys
from decimal import Decimal
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QWidget
from unittest import mock
from test_ledger import _gui_window
import app
import i18n
import qt_widgets as qt
from quotes import Quote

errors = []
sys.excepthook = lambda *error: errors.append(error)
root, ledger = _gui_window()
network = mock.patch.object(app.App, 'run_bg', side_effect=AssertionError('unexpected network'))
network.start()
market = mock.patch('app.is_live', return_value=False)
market.start()
iteration = 0
counts = {}
def cycle():
    global iteration
    try:
        ledger.v_dark.set(bool(iteration % 2))
        ledger.v_finance.set(bool(iteration % 2))
        ledger.db.set_finance_enabled(ledger.v_finance.get())
        ledger.v_text_size.set(list(app.TEXT_SIZES)[iteration % 4])
        i18n.set_language('zh' if iteration % 2 else 'en')
        ledger.rebuild()
        ledger.v_live.set(True)
        price = Decimal('11') + Decimal(iteration) / 100
        quote = Quote(price=price, prev_close=Decimal('10'), time=None,
                      points=[(1800000000, 10.0), (1800000300, 10.5)])
        other = Quote(price=Decimal('155'), prev_close=Decimal('150'), time=None,
                      points=[(1800000000, 150.0), (1800000300, 154.0)])
        with mock.patch('app.is_live', return_value=False):
            ledger._apply_quotes(['SKYD', 'AAPL'], {'SKYD': quote, 'AAPL': other})
        ledger.open_symbol('SKYD')
        ledger.detail.hero._hover(0)
        ledger.detail.hero._hover(None)
        ledger.close_detail()
        if ledger.v_finance.get():
            ledger.open_finance()
            ledger.close_finance()
        root.process_events()
        key = iteration % 4
        widgets = len(root.findChildren(QWidget))
        if key in counts:
            assert widgets == counts[key], (iteration, widgets, counts[key])
        counts[key] = widgets
        assert len(qt._jobs) <= 2, len(qt._jobs)
        assert not errors, errors
        iteration += 1
        if iteration < 60:
            QTimer.singleShot(0, cycle)
        else:
            ledger.quit()
            assert not qt._jobs, list(qt._jobs)
    except BaseException:
        import traceback
        traceback.print_exc()
        sys.exit(1)
QTimer.singleShot(0, cycle)
root.mainloop()
assert iteration == 60, iteration
print('60 rebuild/navigation cycles passed')
"""
        result = subprocess.run([sys.executable, "-X", "faulthandler", "-c", code],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("60 rebuild/navigation cycles passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
