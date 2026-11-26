import path from "node:path";

/** Keep portable-app data outside the launcher's temporary extraction directory. */
export function preferredDataDirectory({
  packaged,
  repoRoot,
  executable,
  environment = process.env,
  platform = process.platform,
}) {
  const paths = platform === "win32" ? path.win32 : path.posix;
  if (!packaged) return paths.join(repoRoot, "data");
  const directory =
    environment.PORTABLE_EXECUTABLE_DIR ||
    (environment.APPIMAGE
      ? paths.dirname(environment.APPIMAGE)
      : paths.dirname(executable));
  return paths.join(directory, "data");
}
