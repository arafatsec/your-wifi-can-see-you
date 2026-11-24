<#
.SYNOPSIS
  Configure, build and flash the two ESP32 CSI boards (sender + receiver) in one go.

.EXAMPLE
  .\scripts\flash_esp32_boards.ps1 -SenderPort COM6 -ReceiverPort COM5 -Channel 1

.NOTES
  Needs ESP-IDF v5.5.x (default C:\esp\esp-idf, tools in C:\Espressif) and esp-csi
  (default C:\esp\esp-csi). See docs/hardware/esp32.md.
#>
param(
  [Parameter(Mandatory = $true)][string]$SenderPort,
  [Parameter(Mandatory = $true)][string]$ReceiverPort,
  [int]$Channel = 1,
  [ValidateSet(20, 40)][int]$Bandwidth = 20,
  [string]$IdfPath = "C:\esp\esp-idf",
  [string]$IdfTools = "C:\Espressif",
  [string]$EspCsi = "C:\esp\esp-csi"
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot

Write-Host "1/4 Applying radio settings (channel $Channel, $Bandwidth MHz)" -ForegroundColor Cyan
python "$repo\firmware\esp32\configure_esp_csi.py" --esp-csi $EspCsi --channel $Channel --bandwidth $Bandwidth
if ($LASTEXITCODE -ne 0) { throw "configure_esp_csi.py failed" }

Write-Host "2/4 Loading ESP-IDF" -ForegroundColor Cyan
$env:IDF_TOOLS_PATH = $IdfTools
. "$IdfPath\export.ps1" | Out-Null

foreach ($job in @(@{Name = "csi_send"; Port = $SenderPort}, @{Name = "csi_recv"; Port = $ReceiverPort})) {
  $dir = Join-Path $EspCsi "examples\get-started\$($job.Name)"
  Write-Host "3/4 Building $($job.Name) (clean build so sdkconfig.defaults apply)" -ForegroundColor Cyan
  Push-Location $dir
  try {
    if (Test-Path sdkconfig) { Remove-Item sdkconfig }
    if (Test-Path build) { Remove-Item build -Recurse -Force }
    # Check the native exit code before any pipeline. Piping into Select-Object
    # can hide a failed idf.py on some PowerShell hosts.
    & idf.py set-target esp32
    if ($LASTEXITCODE -ne 0) { throw "set-target failed for $($job.Name)" }
    & idf.py build
    if ($LASTEXITCODE -ne 0) { throw "build failed for $($job.Name)" }
    Write-Host "4/4 Flashing $($job.Name) to $($job.Port)" -ForegroundColor Cyan
    & idf.py -p $job.Port -b 460800 flash
    if ($LASTEXITCODE -ne 0) { throw "flash failed for $($job.Name) on $($job.Port)" }
  } finally { Pop-Location }
}
Write-Host "Done. Start the live dashboard with: python tools\live_dashboard\server.py --port $ReceiverPort" -ForegroundColor Green
