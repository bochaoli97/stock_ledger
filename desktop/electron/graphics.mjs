/** Classify the actual compositor independently of vendor and platform. */
export function graphicsSummary(hardwareAcceleration, features, info = {}) {
  const renderer = info.auxAttributes?.glRenderer ?? "";
  const devices = (info.gpuDevice ?? []).map((device) => ({
    name:
      device.deviceString ||
      device.vendorString ||
      `GPU ${Number(device.vendorId ?? 0).toString(16)}:${Number(device.deviceId ?? 0).toString(16)}`,
    active: !!device.active,
  }));
  const active = devices.filter((device) => device.active);
  const software =
    /swiftshader|llvmpipe|software|microsoft basic render driver/i;
  const compositor = features.gpu_compositing ?? "";
  let mode = "unknown";
  if (
    !hardwareAcceleration ||
    /software|disabled|unavailable/.test(compositor) ||
    software.test(renderer) ||
    active.some((device) => software.test(device.name))
  )
    mode = "software";
  else if (compositor.startsWith("enabled")) mode = "hardware";
  return {
    mode,
    hardwareAcceleration,
    renderer,
    devices: active.length ? active : devices,
  };
}

export async function runtimeDiagnostics(application, database) {
  let info = {};
  try {
    info = await application.getGPUInfo(
      process.platform === "win32" ? "complete" : "basic",
    );
  } catch {
    /* Feature status can still report a software fallback without adapter details. */
  }
  const gpu = application.getGPUFeatureStatus();
  return {
    electron: process.versions.electron,
    chrome: process.versions.chrome,
    gpu,
    database,
    graphics: graphicsSummary(
      application.isHardwareAccelerationEnabled(),
      gpu,
      info,
    ),
  };
}
