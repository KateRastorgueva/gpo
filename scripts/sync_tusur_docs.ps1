# Replaces the PDFs in "tusur docs" with the reference set and verifies every
# file against scripts/tusur_docs_manifest.json (name, size, SHA-256).
#
# Nothing is deleted: the current PDFs are moved to "tusur docs_old_<time>".
#
#   powershell -ExecutionPolicy Bypass -File scripts\sync_tusur_docs.ps1 -Source C:\path\tusur_docs.zip
#   powershell -ExecutionPolicy Bypass -File scripts\sync_tusur_docs.ps1 -Source C:\path\folder
#   powershell -ExecutionPolicy Bypass -File scripts\sync_tusur_docs.ps1 -CheckOnly
#
# Exit code 0 when "tusur docs" matches the manifest exactly, otherwise 1.

param(
    [string]$Source,
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$target = Join-Path $root "tusur docs"
$manifestPath = Join-Path $PSScriptRoot "tusur_docs_manifest.json"
$manifest = (Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json).files

function Test-Folder([string]$folder) {
    $bad = 0
    foreach ($f in $manifest) {
        $path = Join-Path $folder $f.name
        if (-not (Test-Path -LiteralPath $path)) {
            Write-Host "MISSING  $($f.name)"; $bad++; continue
        }
        $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLower()
        if ($hash -ne $f.sha256) {
            Write-Host "WRONG    $($f.name)"; $bad++
        } else {
            Write-Host "OK       $($f.name)"
        }
    }
    $known = @($manifest | ForEach-Object { $_.name })
    Get-ChildItem -LiteralPath $folder -Filter *.pdf -File | Where-Object { $known -notcontains $_.Name } |
        ForEach-Object { Write-Host "EXTRA    $($_.Name)"; $script:extra++ }
    return $bad
}

if (-not $CheckOnly) {
    if (-not $Source) { throw "Pass -Source <zip or folder> or -CheckOnly" }
    $from = $Source
    $tmp = $null
    if ($Source.ToLower().EndsWith(".zip")) {
        $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("tusur_docs_" + [guid]::NewGuid().ToString("N"))
        Expand-Archive -LiteralPath $Source -DestinationPath $tmp
        $from = $tmp
        $inner = Get-ChildItem -LiteralPath $tmp -Directory
        if ((Get-ChildItem -LiteralPath $tmp -Filter *.pdf -File).Count -eq 0 -and $inner.Count -eq 1) {
            $from = $inner[0].FullName
        }
    }
    Write-Host "Checking source: $from"
    $script:extra = 0
    if ((Test-Folder $from) -ne 0) { throw "Source does not match the manifest, nothing was changed" }

    if (Test-Path -LiteralPath $target) {
        $old = Get-ChildItem -LiteralPath $target -Filter *.pdf -File
        if ($old.Count -gt 0) {
            $backup = "$target" + "_old_" + (Get-Date -Format "yyyyMMdd_HHmmss")
            New-Item -ItemType Directory -Path $backup | Out-Null
            $old | ForEach-Object { Move-Item -LiteralPath $_.FullName -Destination $backup }
            Write-Host "Old PDFs moved to: $backup"
        }
    } else {
        New-Item -ItemType Directory -Path $target | Out-Null
    }
    foreach ($f in $manifest) {
        Copy-Item -LiteralPath (Join-Path $from $f.name) -Destination (Join-Path $target $f.name)
    }
    if ($tmp) { Remove-Item -LiteralPath $tmp -Recurse -Force }
}

Write-Host "Checking: $target"
$script:extra = 0
$bad = Test-Folder $target
if ($bad -eq 0 -and $script:extra -eq 0) {
    Write-Host "RESULT: OK, $($manifest.Count) files match the manifest"
    exit 0
}
Write-Host "RESULT: $bad wrong or missing, $($script:extra) extra"
exit 1
