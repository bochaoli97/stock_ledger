# Numeric animation reference

`qt-ticker-reference.json` is the frozen reference recorded from the former Qt
ticker: 28 scenarios, 202 checkpoints, including dark and light themes.

The original implementation is preserved in Git at
`fbe452bd735b043e8292dd12a5b5fe0e47d35c89`, in `ticker.py` and `qt_widgets.py`.
The migration recorded scroll offsets, targets, widths, opacity, timing and color
before removing the obsolete Qt frontend and its dependency.

The current tests in `src/ticker/engine.test.ts` consume the reference directly;
they do not need Qt or a graphical desktop. Renderer-level interaction tests are
in `tests/desktop.spec.ts` and exercise the actual Electron window.
