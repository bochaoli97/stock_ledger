import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { compareMoney, textToSlots, TickerModel } from "./engine";

const fixture = JSON.parse(
  readFileSync(
    new URL("../../tests/fixtures/qt-ticker-reference.json", import.meta.url),
    "utf8",
  ),
);
for (const scene of fixture)
  test(`Qt equivalence: ${scene.name} (${scene.neutral})`, () => {
    const model = new TickerModel(scene.neutral);
    let now = 0;
    for (const event of scene.events) {
      if (event.action === "set")
        model.setText(event.text, {
          now,
          flash: event.flash,
          animate: event.animate,
        });
      else if (event.action === "advance") {
        now += event.ms;
        model.tick(now);
      } else model.settle();
      const tracks = model.ordered;
      assert.deepEqual(
        tracks.map((t) => t.key),
        event.expected.map((t: { key: string }) => t.key),
      );
      tracks.forEach((track, i) => {
        const expected = event.expected[i],
          context = `${scene.name} at ${now}ms: ${track.key}`;
        for (const key of ["digit", "char", "target", "removing"] as const)
          assert.equal(track[key], expected[key], `${context} ${key}`);
        for (const key of [
          "offset",
          "targetOffset",
          "width",
          "opacity",
        ] as const)
          assert.ok(
            Math.abs(track[key] - expected[key]) < 1e-9,
            `${context} ${key}: ${track[key]} != ${expected[key]}`,
          );
        assert.equal(!!track.scroll, expected.scroll, `${context} scroll`);
        assert.equal(!!track.appear, expected.appear, `${context} appear`);
        assert.equal(
          !!track.colorTween,
          expected.colorActive,
          `${context} colorActive`,
        );
        assert.equal(
          track.scroll ? track.scrollDuration : 0,
          expected.scrollDuration,
          `${context} scrollDuration`,
        );
        assert.equal(
          track.appear ? track.appearDuration : 0,
          expected.appearDuration,
          `${context} appearDuration`,
        );
        track.color.forEach((channel, j) =>
          assert.ok(
            Math.abs(Math.round(channel) - expected.color[j]) <= 1,
            `${context} color`,
          ),
        );
      });
    }
  });
test("semantic slots survive carries and collapse reversals", () => {
  const model = new TickerModel();
  model.setText("$999.99", { animate: false });
  const ones = model.tracks.get("int_0");
  model.setText("$1,000.00");
  model.tick(80);
  const thousands = model.tracks.get("int_3"),
    width = thousands!.width;
  model.setText("$999.99", { now: 80 });
  assert.equal(model.tracks.get("int_0"), ones);
  assert.equal(model.tracks.get("int_3"), thousands);
  assert.equal(thousands!.width, width);
  model.tick(120);
  model.setText("$1,000.00", { now: 120 });
  assert.equal(model.tracks.get("int_3"), thousands);
});
test("decimal formatting and direction stay exact beyond JavaScript integer precision", () => {
  assert.equal(
    compareMoney("$9,007,199,254,740,992.01", "$9,007,199,254,740,992.00"),
    1,
  );
  assert.equal(compareMoney("-$0.00", "$0.00"), 0);
  assert.equal(compareMoney("-$12.34", "-$12.35"), 1);
  assert.equal(compareMoney("$1.0", "+$01.00"), 0);
  for (const text of ["NaN", "$Infinity", "$1.00\n", "$1,23", "", "--"])
    assert.equal(textToSlots(text), null);
});
