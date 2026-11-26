import test from "node:test";
import assert from "node:assert/strict";
import { graphicsSummary } from "./graphics.mjs";

test("hardware detection works with NVIDIA, Intel and AMD adapters", () => {
  for (const name of [
    "NVIDIA GeForce RTX 3060",
    "Intel Iris Xe",
    "AMD Radeon Graphics",
  ]) {
    const summary = graphicsSummary(
      true,
      { gpu_compositing: "enabled" },
      {
        auxAttributes: { glRenderer: `ANGLE (${name}, Direct3D11)` },
        gpuDevice: [{ deviceString: name, active: true }],
      },
    );
    assert.equal(summary.mode, "hardware");
    assert.equal(summary.devices[0].name, name);
  }
});
test("enabled preferences do not hide software compositing or a software adapter", () => {
  assert.equal(
    graphicsSummary(true, { gpu_compositing: "disabled_software" }).mode,
    "software",
  );
  assert.equal(
    graphicsSummary(
      true,
      { gpu_compositing: "enabled" },
      { auxAttributes: { glRenderer: "ANGLE SwiftShader" } },
    ).mode,
    "software",
  );
  assert.equal(
    graphicsSummary(
      true,
      { gpu_compositing: "enabled" },
      {
        gpuDevice: [
          { deviceString: "Microsoft Basic Render Driver", active: true },
        ],
      },
    ).mode,
    "software",
  );
});
test("explicitly disabled acceleration and pending information have distinct states", () => {
  assert.equal(graphicsSummary(false, {}).mode, "software");
  assert.equal(graphicsSummary(true, {}).mode, "unknown");
});
