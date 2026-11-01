"""Ticker regressions ported from Tk to Qt.

Run ``python -m unittest -v test_ticker`` or ``python -m pytest -q``.
The eight original scenarios remain, with the current three-place animation
scope, shortest circular paths, and animated scrubbing/restoration contract.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shutil
import sys
import unittest
from decimal import Decimal as D
from unittest import mock

from PyQt6 import sip
from PyQt6.QtCore import QAbstractAnimation, QVariantAnimation
from PyQt6.QtWidgets import QLabel

import app
import i18n
import ui
from finance import FinMonth
from ledger import Txn
from quotes import Quote
from test_ledger import _close_gui, _gui_window, _turn_on_finance
from ticker import TickerLabel

RUNNING = QAbstractAnimation.State.Running


class TickerTests(unittest.TestCase):
    def setUp(self):
        self.root, self.app = _gui_window()
        self.folder = self.app.db.path.parent
        self.errors = []
        hook = mock.patch.object(sys, "excepthook", lambda *error: self.errors.append(error))
        hook.start()
        self.addCleanup(hook.stop)
        for patch in (mock.patch.object(app.App, "run_bg", side_effect=AssertionError("unexpected network")),
                      mock.patch("app.is_live", return_value=False)):
            patch.start()
            self.addCleanup(patch.stop)
        self.root.process_events()

    def tearDown(self):
        _close_gui(self.root)
        self.root.process_events()
        self.app.db.close()
        shutil.rmtree(self.folder)
        i18n.set_language("en")
        self.assertEqual(self.errors, [], "Qt callbacks raised during animation or cleanup")

    def number(self, text="-"):
        widget = TickerLabel(self.root, text=text, font=ui.UI.hero, fg=ui.C["text"], bg=ui.C["bg"])
        widget.resize(widget.sizeHint())
        widget.move(30, 30)
        widget.show()
        self.root.process_events()
        return widget

    @staticmethod
    def finish(widget):
        for track in list(widget.track_dict.values()):
            for animation in (track.scroll_anim, track.color_anim, track.appear_anim):
                if animation.state() == RUNNING:
                    animation.setCurrentTime(animation.duration())

    def visible_text(self, widget):
        chars = []
        for child in widget.ordered_tracks():
            if child.is_digit:
                self.assertAlmostEqual(child.current_offset % 10, int(child.target_char))
                chars.append(child.target_char)
            else:
                chars.append(child.char)
        return "".join(chars)

    @staticmethod
    def quote(price):
        return Quote(price=D(price), prev_close=D("10"), time=None,
                     points=[(1800000000, 10.0), (1800000300, 10.5)])

    def apply(self, skyd, aapl="155"):
        quotes = {"SKYD": self.quote(skyd), "AAPL": self.quote(aapl)}
        self.app.v_live.set(True)
        self.app._apply_quotes(list(quotes), quotes)

    def test_first_value_placeholders_and_unchanged_quotes_do_not_roll(self):
        widget = self.number()
        widget.set_text("$19.99")
        self.assertFalse(any(a.state() == RUNNING for a in widget.findChildren(QVariantAnimation)))
        self.assertEqual(self.visible_text(widget), "$19.99")
        widget.set_text("$19.98")
        digit = widget.track_dict["dec_2"]
        digit.scroll_anim.setCurrentTime(125)
        widget.configure(text="$19.98", fg=ui.C["text"])
        self.assertEqual(digit.scroll_anim.currentTime(), 125)
        self.assertEqual(widget.cget("text"), "$19.98")
        self.finish(widget)
        self.assertEqual(self.visible_text(widget), "$19.98")
        widget.set_text("-")
        self.assertEqual(self.visible_text(widget), "-")
        widget.set_text("$20.00")
        self.assertEqual(self.visible_text(widget), "$20.00")

    def test_carry_decline_and_negative_amounts_finish_at_exact_value(self):
        widget = self.number("$9.99")
        for target in ("$10.00", "$9.99", "-$0.01", "-$0.02", "$0.01", "$999.99", "$1,000.00", "$999.99"):
            with self.subTest(target=target):
                widget.set_text(target)
                self.finish(widget)
                self.assertEqual(widget.cget("text"), target)
                self.assertEqual(self.visible_text(widget), target)

    def test_changed_digits_move_vertically_and_other_digits_stay_still(self):
        widget = self.number("$12.34")
        children = widget.ordered_tracks()
        geometry = [widget.track_rect(child.key) for child in children]
        widget.set_text("$12.35")
        children[-1].scroll_anim.setCurrentTime(150)
        self.assertGreater(children[-1].current_offset, 4)
        self.assertLess(children[-1].current_offset, 5)
        self.assertTrue(all(d.scroll_anim.state() != RUNNING for d in children[:-1] if d.is_digit))
        self.assertEqual([widget.track_rect(child.key) for child in children], geometry)
        self.finish(widget)
        widget.set_text("$12.34")
        children[-1].scroll_anim.setCurrentTime(150)
        self.assertGreater(children[-1].current_offset, 4)
        self.assertLess(children[-1].current_offset, 5)
        self.finish(widget)
        self.assertEqual(self.visible_text(widget), "$12.34")

    def test_new_quote_retargets_in_flight_without_snapping(self):
        widget = self.number("$12.34")
        widget.set_text("$12.39", flash=False)
        digit = widget.track_dict["dec_2"]
        digit.scroll_anim.setCurrentTime(90)
        position = digit.current_offset % 10
        before = widget.grab().toImage()
        widget.set_text("$12.31", flash=False)
        self.assertAlmostEqual(digit.current_offset % 10, position)
        self.assertEqual(widget.grab().toImage(), before, "retargeting must preserve the currently painted frame")
        self.finish(widget)
        self.assertEqual(self.visible_text(widget), "$12.31")

    def test_hidden_and_destroyed_widgets_cancel_their_animation(self):
        widget = self.number("$1.00")
        widget.set_text("$2.00")
        animations = widget.findChildren(QVariantAnimation)
        self.assertTrue(any(a.state() == RUNNING for a in animations))
        widget.hide()
        self.assertTrue(all(a.state() != RUNNING for a in animations))
        widget.set_text("$3.00")
        self.assertEqual(self.visible_text(widget), "$3.00")
        widget.show()
        widget.set_text("$4.00")
        widget.destroy()
        self.root.process_events()
        self.assertTrue(sip.isdeleted(widget))
        self.assertTrue(all(sip.isdeleted(animation) for animation in animations))

    def test_quotes_update_overview_net_worth_sidebar_and_stock_detail(self):
        a = self.app
        second = a.db.create_account("Second")
        a.db.add_txn(Txn(account_id=second, date="2026-02-01", type="DEPOSIT", amount=D(5000)))
        a.db.add_txn(Txn(account_id=second, date="2026-02-02", type="BUY", symbol="SKYD", quantity=D(500), price=D(12)))
        a.db.set_prices({"SKYD": D(11), "AAPL": D(155)})
        a.load_accounts(select_id=app.ALL_ACCOUNTS)
        _turn_on_finance(a)
        a.db.save_finance_month(FinMonth("2026-01", D(1400)))
        a.refresh()
        self.root.process_events()
        self.apply("12")
        self.assertEqual(a.hero.value.cget("text"), "$27,050.00")
        self.assertTrue(any(d.scroll_anim.state() == RUNNING for d in a.hero.value.track_dict.values() if d.is_digit))
        _, grid = a.net_summary
        for key, value in (("stock", "$27,050.00"), ("total", "$28,450.00"), ("finance", "$1,400.00")):
            self.assertIsInstance(grid.cells[key][0], QLabel)
            self.assertEqual(grid.cells[key][0].cget("text"), value)
            self.assertFalse(grid.cells[key][0].findChildren(QVariantAnimation))
        self.assertFalse(a.stock_rows["SKYD"].pill.findChildren(QVariantAnimation))
        self.assertEqual(a.db.get_prices()["SKYD"][0], D("12"))
        a.open_symbol("SKYD")
        self.root.process_events()
        detail = a.detail.hero.value
        self.assertEqual(detail.cget("text"), "$12.00")
        self.apply("11.50")
        self.assertEqual(detail.cget("text"), "$11.50")
        self.assertTrue(any(d.scroll_anim.state() == RUNNING for d in detail.track_dict.values() if d.is_digit))
        self.assertTrue(all(d.scroll_anim.state() != RUNNING for d in a.hero.value.track_dict.values() if d.is_digit))
        self.finish(detail)
        self.assertEqual(self.visible_text(detail), "$11.50")

    def test_chart_hover_and_restore_are_animated_and_survive_new_quotes(self):
        self.apply("11")
        self.app.open_symbol("SKYD")
        self.root.process_events()
        hero = self.app.detail.hero
        hero._hover(0)
        self.assertEqual(hero.value.cget("text"), "$10.00")
        active = [d for d in hero.value.track_dict.values() if d.is_digit and d.scroll_anim.state() == RUNNING]
        self.assertTrue(active)
        self.assertTrue(all(d.scroll_anim.duration() == 650 and d.color_anim.state() != RUNNING for d in active))
        self.apply("12")
        self.assertEqual(hero.value.cget("text"), "$10.00")
        hero._hover(None)
        self.assertEqual(hero.value.cget("text"), "$12.00")
        active = [d for d in hero.value.track_dict.values() if d.is_digit and d.scroll_anim.state() == RUNNING]
        self.assertTrue(active)
        self.assertTrue(all(d.scroll_anim.duration() in (260, 320, 450, 650) for d in active))

    def test_account_switch_and_rebuild_do_not_replay_stale_numbers(self):
        a = self.app
        self.apply("11")
        self.apply("12")
        old = a.hero.value
        a.v_dark.set(not a.v_dark.get())
        i18n.set_language("zh")
        a.rebuild()
        self.root.process_events()
        self.assertTrue(sip.isdeleted(old))
        self.assertEqual(a.hero.value.cget("text"), "$22,050.00")
        self.assertTrue(all(d.scroll_anim.state() != RUNNING for d in a.hero.value.track_dict.values() if d.is_digit))
        second = a.db.create_account("Second")
        a.db.add_txn(Txn(account_id=second, date="2026-02-01", type="DEPOSIT", amount=D(5000)))
        a.load_accounts(select_id=second)
        self.assertEqual(a.hero.value.cget("text"), "$5,000.00")
        self.assertTrue(all(d.scroll_anim.state() != RUNNING for d in a.hero.value.track_dict.values() if d.is_digit))


if __name__ == "__main__":
    unittest.main(verbosity=2)
