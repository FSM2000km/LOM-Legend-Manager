param(
    [string]$GameRoot = $env:LOM_GAME_ROOT,
    [string]$OutputPath = (Join-Path (Split-Path $PSScriptRoot -Parent) "data\jp_v2_4_presets.json"),
    [string]$JapaneseModZip = (Join-Path $env:USERPROFILE "Downloads\LOM_JP_Mod_v2.4.zip")
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($GameRoot)) {
    $GameRoot = "C:\Program Files (x86)\Steam\steamapps\common\LegendOfMortal"
}
$GameRoot = [IO.Path]::GetFullPath($GameRoot)

function Get-Sha256Hex {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Load-Assemblies {
    param([string]$Root)

    $managedDir = Join-Path $Root "Mortal_Data\Managed"
    $bepInExCore = Join-Path $Root "BepInEx\core"

    foreach ($dir in @($managedDir, $bepInExCore)) {
        if (-not (Test-Path -LiteralPath $dir)) {
            continue
        }

        Get-ChildItem -LiteralPath $dir -Filter "*.dll" | ForEach-Object {
            try {
                [Reflection.Assembly]::LoadFrom($_.FullName) > $null
            } catch {
                # Some Unity modules are not needed for the extractor.
            }
        }
    }
}

function Convert-LibraryTitle {
    param(
        [string]$Key,
        [string]$Value
    )

    if ($Key -notmatch "^Library/Title/(\d+)$") {
        return $null
    }

    $titleId = [int]$Matches[1]
    $kind = "library_title"
    $kindLabel = "Library"
    $displayNumber = $titleId
    $filePrefix = "Title$titleId"

    if ($titleId -ge 10000 -and $titleId -le 10104) {
        $kind = "death"
        $kindLabel = "生死簿"
        $displayNumber = $titleId - 9999
        $filePrefix = ("生死{0:D3}" -f $displayNumber)
    } elseif ($titleId -eq 11000) {
        $kind = "death_special"
        $kindLabel = "生死簿"
        $displayNumber = 0
        $filePrefix = "生死特殊"
    } elseif ($titleId -ge 20000 -and $titleId -le 20053) {
        $kind = "ending"
        $kindLabel = "ED"
        $displayNumber = $titleId - 19999
        $filePrefix = ("ED{0:D2}" -f $displayNumber)
    } elseif ($titleId -ge 30000 -and $titleId -le 30019) {
        $kind = "extra"
        $kindLabel = "追加"
        $displayNumber = $titleId - 29999
        $filePrefix = ("追加{0:D2}" -f $displayNumber)
    }

    [ordered]@{
        key = $Key
        titleId = $titleId
        kind = $kind
        kindLabel = $kindLabel
        displayNumber = $displayNumber
        filePrefix = $filePrefix
        jpName = $Value
        aliases = @()
        heroine = $null
        observedTagSeeds = @()
        hiddenCandidateTagSeeds = @()
        matchingPhrases = @()
    }
}

function Convert-LegendInfo {
    param(
        [string]$Key,
        [string]$Value
    )

    if ($Key -notlike "LegendInfo/*") {
        return $null
    }

    [ordered]@{
        key = $Key
        id = $Key.Substring("LegendInfo/".Length)
        text = $Value
    }
}

$stringVaultDll = Join-Path $GameRoot "BepInEx\plugins\LOM_JP_StringVault\LOM_JP_StringVault.dll"
$stringtableBin = Join-Path $GameRoot "BepInEx\plugins\LOM_JP_StringVault\Stringtable.bin"

if (-not (Test-Path -LiteralPath $stringVaultDll)) {
    throw "LOM_JP_StringVault.dll was not found: $stringVaultDll"
}

if (-not (Test-Path -LiteralPath $stringtableBin)) {
    throw "Stringtable.bin was not found: $stringtableBin"
}

Load-Assemblies -Root $GameRoot

$assembly = [Reflection.Assembly]::LoadFrom($stringVaultDll)
$formatType = $assembly.GetType("StringVaultFormat", $true)
$unpack = $formatType.GetMethod("Unpack", [Reflection.BindingFlags]"NonPublic,Static")

if ($null -eq $unpack) {
    throw "StringVaultFormat.Unpack was not found."
}

$blob = [IO.File]::ReadAllBytes($stringtableBin)
$plainBytes = [byte[]]$unpack.Invoke($null, @(,$blob))
$csvText = [Text.Encoding]::UTF8.GetString($plainBytes).TrimStart([char]0xFEFF)
$rows = $csvText | ConvertFrom-Csv -Header Key,Value

$libraryTitles = New-Object System.Collections.Generic.List[object]
$legendInfo = New-Object System.Collections.Generic.List[object]

foreach ($row in $rows) {
    $title = Convert-LibraryTitle -Key $row.Key -Value $row.Value
    if ($null -ne $title) {
        $libraryTitles.Add([pscustomobject]$title)
        continue
    }

    $legend = Convert-LegendInfo -Key $row.Key -Value $row.Value
    if ($null -ne $legend) {
        $legendInfo.Add([pscustomobject]$legend)
    }
}

$endings = @($libraryTitles | Where-Object { $_.kind -eq "ending" } | Sort-Object titleId)
$deathTitles = @($libraryTitles | Where-Object { $_.kind -eq "death" -or $_.kind -eq "death_special" } | Sort-Object titleId)
$extraTitles = @($libraryTitles | Where-Object { $_.kind -eq "extra" } | Sort-Object titleId)
$otherTitles = @($libraryTitles | Where-Object { $_.kind -eq "library_title" } | Sort-Object titleId)

$preset = [ordered]@{
    schemaVersion = 1
    generatedAt = (Get-Date).ToString("o")
    source = [ordered]@{
        name = "LOM_JP_Mod_v2.4"
        gameRoot = $GameRoot
        stringtablePath = $stringtableBin
        stringtableSha256 = Get-Sha256Hex -Path $stringtableBin
        stringVaultDllPath = $stringVaultDll
        stringVaultDllSha256 = Get-Sha256Hex -Path $stringVaultDll
        japaneseModZipPath = $(if (Test-Path -LiteralPath $JapaneseModZip) { $JapaneseModZip } else { $null })
        japaneseModZipSha256 = Get-Sha256Hex -Path $JapaneseModZip
        rowCount = $rows.Count
    }
    naming = [ordered]@{
        endingKindLabel = "ED"
        deathKindLabel = "生死簿"
        extraKindLabel = "追加"
        unknownEndingName = "ED名不明"
        unknownHeroineName = "結縁相手不明"
        noHeroineName = "無結縁"
        fileNamePattern = "{filePrefix}_{jpName}_{heroine}_{exportedAt}_{hash8}.txt"
    }
    titles = [ordered]@{
        endings = $endings
        deaths = $deathTitles
        extras = $extraTitles
        others = $otherTitles
    }
    legendInfo = @($legendInfo | Sort-Object key)
}

$outputDir = Split-Path -Parent $OutputPath
New-Item -ItemType Directory -Path $outputDir -Force > $null
$preset | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $OutputPath -Encoding UTF8

[pscustomobject]@{
    OutputPath = $OutputPath
    RowCount = $rows.Count
    EndingCount = $endings.Count
    DeathCount = $deathTitles.Count
    ExtraCount = $extraTitles.Count
    OtherTitleCount = $otherTitles.Count
    LegendInfoCount = $legendInfo.Count
}
