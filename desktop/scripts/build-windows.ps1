param(
    [switch]$SkipTests,
    [switch]$RequireGpu,
    [string]$WindowsPython = $env:STOCK_LEDGER_WINDOWS_PYTHON,
    [string]$WorkDirectory
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUNBUFFERED = '1'

try {
    # Probe launchers before Store aliases; resolve the actual Windows interpreter.
    $candidates = @()
    if ($WindowsPython) {
        $candidates += @{ Command = $WindowsPython; Arguments = @() }
    } else {
        $candidates += @{ Command = 'py.exe'; Arguments = @('-3') }
        $candidates += @{ Command = 'python.exe'; Arguments = @() }
        $candidates += @{ Command = 'python3.exe'; Arguments = @() }
    }
    $interpreter = $null
    foreach ($candidate in $candidates) {
        $command = Get-Command $candidate.Command -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $command) { continue }
        $probeArguments = @($candidate.Arguments) + @('-c', 'import sys; assert sys.platform == ''win32'' and sys.version_info >= (3, 12); print(sys.executable)')
        # WinPS 5 treats redirected native stderr as errors; failed probes are expected.
        $previousPreference = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        $result = & $command.Source @probeArguments 2>$null
        $probeExit = $LASTEXITCODE
        $ErrorActionPreference = $previousPreference
        if ($probeExit -eq 0 -and $result) {
            $interpreter = ($result | Select-Object -Last 1).Trim()
            break
        }
    }
    if (-not $interpreter) {
        throw 'Windows Python 3.12+ was not found. Install Windows Python, or use --python /mnt/c/path/to/python.exe. Linux Python cannot build the Windows service.'
    }
    Write-Host "[WSL] Windows Python: $interpreter"
    $validator = Join-Path $PSScriptRoot 'validate-windows.py'
    $buildArguments = @($validator, '--bootstrap-node', '--package', '--archive')
    if ($SkipTests) { $buildArguments += '--skip-tests' }
    if ($RequireGpu) { $buildArguments += '--require-gpu' }
    if ($WorkDirectory) { $buildArguments += @('--work-dir', $WorkDirectory) }
    & $interpreter @buildArguments
    exit $LASTEXITCODE
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
