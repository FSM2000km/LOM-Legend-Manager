param(
    [string]$Version = "0.1.4",
    [string]$GameRoot = $env:LOM_GAME_ROOT
)

$ErrorActionPreference = "Stop"

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
if ([string]::IsNullOrWhiteSpace($GameRoot)) {
    $GameRoot = "C:\Program Files (x86)\Steam\steamapps\common\LegendOfMortal"
}
$GameRoot = [IO.Path]::GetFullPath($GameRoot)
if (-not (Test-Path -LiteralPath (Join-Path $GameRoot "Mortal.exe") -PathType Leaf)) {
    throw "Legend of Mortal was not found at GameRoot: $GameRoot"
}

$releaseRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot "release"))
$stagingRoot = [IO.Path]::GetFullPath((Join-Path $releaseRoot "staging"))
$expectedPrefix = $releaseRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
if (-not $stagingRoot.StartsWith($expectedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Staging path is outside the release directory: $stagingRoot"
}

$msbuild = "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\MSBuild\Current\Bin\MSBuild.exe"
$pluginProject = Join-Path $repoRoot "LegendManager\LegendManager.Plugin\LegendManager.Plugin.csproj"
$python = Join-Path $repoRoot "LegendViewer\.venv\Scripts\python.exe"
$pyinstaller = Join-Path $repoRoot "LegendViewer\.venv\Scripts\pyinstaller.exe"
$spec = Join-Path $repoRoot "LegendViewer\LegendViewer.spec"

foreach ($required in @($msbuild, $python, $pyinstaller, $spec)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Required build file was not found: $required"
    }
}

$previousQtPlatform = $env:QT_QPA_PLATFORM
$env:QT_QPA_PLATFORM = "offscreen"
try {
    Push-Location (Join-Path $repoRoot "LegendViewer")
    try {
        & $python -m unittest discover -s tests -v
        if ($LASTEXITCODE -ne 0) {
            throw "Viewer tests failed."
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    $env:QT_QPA_PLATFORM = $previousQtPlatform
}

& $msbuild $pluginProject /t:Rebuild /p:Configuration=Release "/p:GameRoot=$GameRoot" /v:minimal /nologo
if ($LASTEXITCODE -ne 0) {
    throw "MOD build failed."
}

Push-Location $repoRoot
try {
    & $pyinstaller --noconfirm --clean $spec
    if ($LASTEXITCODE -ne 0) {
        throw "Viewer EXE build failed."
    }
}
finally {
    Pop-Location
}

if (Test-Path -LiteralPath $stagingRoot) {
    Remove-Item -LiteralPath $stagingRoot -Recurse -Force
}

$pluginTarget = Join-Path $stagingRoot "BepInEx\plugins\LOM_LegendManager"
$viewerTarget = Join-Path $stagingRoot "LegendViewer"
New-Item -ItemType Directory -Path (Join-Path $pluginTarget "data") -Force | Out-Null
New-Item -ItemType Directory -Path $viewerTarget -Force | Out-Null

Copy-Item -LiteralPath (Join-Path $repoRoot "LegendManager\LegendManager.Plugin\bin\Release\LegendManager.Plugin.dll") -Destination $pluginTarget
Copy-Item -LiteralPath (Join-Path $repoRoot "LegendManager\data\jp_v2_4_presets.json") -Destination (Join-Path $pluginTarget "data")
Copy-Item -LiteralPath (Join-Path $repoRoot "LegendManager\data\tags_catalog.json") -Destination (Join-Path $pluginTarget "data")
Copy-Item -LiteralPath (Join-Path $repoRoot "LegendManager\README.md") -Destination $pluginTarget
Copy-Item -LiteralPath (Join-Path $repoRoot "LegendManager\TAGS.md") -Destination $pluginTarget

Copy-Item -LiteralPath (Join-Path $repoRoot "dist\LegendViewer.exe") -Destination $viewerTarget
Copy-Item -LiteralPath (Join-Path $repoRoot "LegendViewer\Start-LegendViewer.cmd") -Destination $viewerTarget
Copy-Item -LiteralPath (Join-Path $repoRoot "LegendViewer\README.md") -Destination $viewerTarget
Copy-Item -LiteralPath (Join-Path $repoRoot "LegendManager\DISTRIBUTION_README.md") -Destination (Join-Path $stagingRoot "README.md")

$localPathPatterns = @($env:USERPROFILE, $repoRoot) |
    Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
    ForEach-Object { $_, $_.Replace("\", "/") } |
    Sort-Object -Unique
$localPathLeaks = foreach ($file in (Get-ChildItem -LiteralPath $stagingRoot -Recurse -File)) {
    $bytes = [IO.File]::ReadAllBytes($file.FullName)
    $views = @(
        [Text.Encoding]::UTF8.GetString($bytes),
        [Text.Encoding]::Unicode.GetString($bytes),
        [Text.Encoding]::BigEndianUnicode.GetString($bytes)
    )
    foreach ($pattern in $localPathPatterns) {
        if ($views.Where({ $_.IndexOf($pattern, [StringComparison]::OrdinalIgnoreCase) -ge 0 }, "First").Count -gt 0) {
            $relative = $file.FullName.Substring($stagingRoot.Length + 1)
            "$relative contains $pattern"
        }
    }
}
if ($localPathLeaks) {
    throw "Release staging contains local paths:`n$($localPathLeaks -join [Environment]::NewLine)"
}

$checksumPath = Join-Path $stagingRoot "SHA256SUMS.txt"
$checksumLines = Get-ChildItem -LiteralPath $stagingRoot -Recurse -File |
    Where-Object FullName -ne $checksumPath |
    Sort-Object FullName |
    ForEach-Object {
        $relative = $_.FullName.Substring($stagingRoot.Length + 1).Replace("\", "/")
        $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        "$hash  $relative"
    }
Set-Content -LiteralPath $checksumPath -Value $checksumLines -Encoding UTF8

$zipPath = Join-Path $releaseRoot ("LOM_LegendManager_v{0}.zip" -f $Version)
if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}
Compress-Archive -Path (Join-Path $stagingRoot "*") -DestinationPath $zipPath -CompressionLevel Optimal

$zipHash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Host "Release ZIP: $zipPath"
Write-Host "SHA-256: $zipHash"
