param(
    [string]$PresetPath = (Join-Path $PSScriptRoot '..\data\jp_v2_4_presets.json'),
    [string]$OutputPath = (Join-Path $PSScriptRoot '..\data\tags_catalog.json')
)

$ErrorActionPreference = 'Stop'

function New-Tag {
    param(
        [string]$Id,
        [string]$Label,
        [string]$Category,
        [int]$Order,
        [string[]]$StoryKeys = @(),
        [bool]$DefaultVisible = $true,
        [bool]$AutoConfirm = $false
    )

    [ordered]@{
        id = $Id
        label = $Label
        category = $Category
        order = $Order
        default_visible = $DefaultVisible
        auto_confirm = $AutoConfirm
        story_keys_any = @($StoryKeys)
    }
}

function Convert-ToTagIdPart {
    param([string]$Value)

    $bytes = [Text.Encoding]::UTF8.GetBytes($Value)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $hash = $sha.ComputeHash($bytes)
    } finally {
        $sha.Dispose()
    }
    return ([BitConverter]::ToString($hash) -replace '-', '').Substring(0, 12).ToLowerInvariant()
}

$preset = Get-Content -LiteralPath $PresetPath -Raw -Encoding utf8 | ConvertFrom-Json
$tags = [Collections.Generic.List[object]]::new()

foreach ($ending in $preset.titles.endings) {
    $tags.Add((New-Tag `
        -Id ('ending.' + $ending.titleId) `
        -Label ($ending.filePrefix + ' ' + $ending.jpName) `
        -Category 'ending' `
        -Order (1000 + [int]$ending.displayNumber) `
        -AutoConfirm $true))
}

$heroineTags = @(
    @('heroine.none', '無結縁'),
    @('heroine.1', '小師妹'),
    @('heroine.2', '龍湘'),
    @('heroine.3', '葉雲裳'),
    @('heroine.4', '上官螢'),
    @('heroine.5', '夏侯蘭'),
    @('heroine.6', '虞小梅'),
    @('heroine.7', '魏菊'),
    @('heroine.8', '郁竹'),
    @('heroine.tang_jiaojiao', '唐嬌嬌')
)
for ($index = 0; $index -lt $heroineTags.Count; $index++) {
    $tags.Add((New-Tag -Id $heroineTags[$index][0] -Label $heroineTags[$index][1] -Category 'heroine' -Order (2000 + $index) -AutoConfirm $true))
}

$survival = [ordered]@{
    '小師妹生存' = @('LegendInfo/Ch_8_5_1_010')
    '大師兄生存' = @('LegendInfo/Ch_8_1_2_4_008', 'LegendInfo/Ch_8_3_1_3_2_004')
    '二師兄生存' = @()
    '三師兄生存' = @()
    '四師兄生存' = @()
    '掌門生存' = @()
    '龍湘生存' = @()
    '夏侯蘭生存' = @()
    '葉雲裳生存' = @('LegendInfo/Ch_8_1_2_023')
    '葉雲舟生存' = @('LegendInfo/S0028_02_001', 'LegendInfo/S0209_01_07_004')
    '虞小梅生存' = @()
    '上官螢生存' = @()
    '丹霞子生存' = @('LegendInfo/Ch_7_5_5_6_006')
    '金烏上人生存' = @()
}
$order = 3000
foreach ($item in $survival.GetEnumerator()) {
    $id = 'survival.' + (Convert-ToTagIdPart $item.Key)
    $tags.Add((New-Tag -Id $id -Label $item.Key -Category 'survival' -Order $order -StoryKeys $item.Value -AutoConfirm ($item.Value.Count -gt 0)))
    $order++
}

$joins = [ordered]@{
    '唐衫唐門加入' = @('LegendInfo/Ch_6_8_3_020')
    '唐嬌嬌唐門加入' = @('LegendInfo/S0121_01_001')
    '虞小梅唐門加入' = @('LegendInfo/Ch_8_2_5_6_1_013')
}
$order = 4000
foreach ($item in $joins.GetEnumerator()) {
    $id = 'join.' + (Convert-ToTagIdPart $item.Key)
    $tags.Add((New-Tag -Id $id -Label $item.Key -Category 'join' -Order $order -StoryKeys $item.Value -AutoConfirm ($item.Value.Count -gt 0)))
    $order++
}

$statuses = @('丹霞子客将', '錦香宮宮人受入れ', '武館拳師加入', '破廟一行加入')
for ($index = 0; $index -lt $statuses.Count; $index++) {
    $label = $statuses[$index]
    $storyKeys = if ($label -eq '丹霞子客将') { @('LegendInfo/Ch_7_5_5_6_006') } else { @() }
    $tags.Add((New-Tag -Id ('status.' + (Convert-ToTagIdPart $label)) -Label $label -Category 'status' -Order (4500 + $index) -StoryKeys $storyKeys -DefaultVisible $false -AutoConfirm ($storyKeys.Count -gt 0)))
}

$movements = @('崆峒留学', '青城留学', '唐門離脱', '江湖引退', '回疆隠棲', '雪山行き', '行商同行', '破廟ルート', '外遊')
for ($index = 0; $index -lt $movements.Count; $index++) {
    $label = $movements[$index]
    $storyKeys = if ($label -eq '崆峒留学') {
        @(
            'LegendInfo/Ch_2_5_2_1_005',
            'LegendInfo/Ch_2_5_2_2_1_001',
            'LegendInfo/Ch_2_5_2_3_001',
            'LegendInfo/Ch_2_5_2_4_003'
        )
    } else { @() }
    $tags.Add((New-Tag -Id ('movement.' + (Convert-ToTagIdPart $label)) -Label $label -Category 'movement' -Order (5000 + $index) -StoryKeys $storyKeys -DefaultVisible $false -AutoConfirm ($storyKeys.Count -gt 0)))
}

$eventRules = [ordered]@{
    '金烏上人死亡' = @(
        'LegendInfo/Ch_4_8_7_1_004',
        'LegendInfo/Ch_5_4_8_10_001',
        'LegendInfo/Ch_5_4_8_10_003',
        'LegendInfo/Ch_8_2_5_6_1_018'
    )
    '無相祖師討伐' = @('LegendInfo/Ch_8_2_5_9_2_001', 'LegendInfo/Ch_8_2_5_9_2_002')
    '西武林盟成立' = @('LegendInfo/Ch_7_5_5_5_005')
    '眉山決戦' = @('LegendInfo/Ch_8_8_1_002')
    '武林盟決戦' = @()
    '大師兄帰還' = @('LegendInfo/Ch_8_3_1_3_2_004')
    '二師兄帰還' = @()
    '外堡買い戻し' = @('LegendInfo/Meet_Option_F_01_01_001', 'LegendInfo/S0703_01_01_005')
    '錦香宮支援' = @('LegendInfo/Ch_6_7_2_Break_01_009', 'LegendInfo/Ch_6_7_2_Break_01_010')
    '龍湘覚醒' = @('LegendInfo/Ch_8_4_2_1_002')
    '葉雲舟覚醒' = @('LegendInfo/Ch_8_4_10_1_008')
    '葉雲舟・段智秀共闘' = @('LegendInfo/Ch_8_4_10_1_007')
    '瑞杏と温夫人の密談' = @('LegendInfo/Ch_6_4_4_4_2_007')
    '小師妹結縁' = @(
        'LegendInfo/Ch_8_6_3_2_003'
    )
    '龍湘結縁' = @(
        'LegendInfo/S0021_01_001',
        'LegendInfo/S0021_02_04_001',
        'LegendInfo/Ch_8_6_3_2_011'
    )
    '夏侯蘭結縁' = @(
        'LegendInfo/S2504_02_07_Break_01_002',
        'LegendInfo/S2504_04_001',
        'LegendInfo/Ch_8_6_3_2_010'
    )
    '葉雲裳結縁' = @(
        'LegendInfo/S0208_05_05_004',
        'LegendInfo/S0208_06_02_004',
        'LegendInfo/Ch_8_6_3_2_005'
    )
    '虞小梅結縁' = @('LegendInfo/Ch_8_6_3_2_007')
    '上官螢結縁' = @('LegendInfo/Ch_8_6_3_2_006')
    '魏菊結縁' = @(
        'LegendInfo/Ch_6_4_4_2_002',
        'LegendInfo/Ch_8_6_3_2_009'
    )
    '郁竹結縁' = @(
        'LegendInfo/Ch_4_6_16_010',
        'LegendInfo/Ch_8_6_3_2_008'
    )
    '金烏掌派' = @()
    '新唐門十傑' = @()
    '名匠' = @()
}
$order = 6000
foreach ($item in $eventRules.GetEnumerator()) {
    # Keep the previous ID so existing manual assignments receive the renamed label.
    $idSource = if ($item.Key -eq '金烏上人死亡') { '金烏討伐成功' } else { $item.Key }
    $id = 'event.' + (Convert-ToTagIdPart $idSource)
    $defaultVisible = $item.Key -eq '金烏上人死亡'
    $tags.Add((New-Tag -Id $id -Label $item.Key -Category 'event' -Order $order -StoryKeys $item.Value -DefaultVisible $defaultVisible -AutoConfirm ($item.Value.Count -gt 0)))
    $order++
}

$spoilerCandidates = @('金烏未討伐', '大師兄救出失敗', '丹霞子未加入', '龍湘未加入')
for ($index = 0; $index -lt $spoilerCandidates.Count; $index++) {
    $label = $spoilerCandidates[$index]
    $tags.Add((New-Tag -Id ('spoiler.' + (Convert-ToTagIdPart $label)) -Label $label -Category 'spoiler_candidate' -Order (9000 + $index) -DefaultVisible $false))
}

$futureDeathTags = @(
    '転落死', '斬死', '毒死', '殴殺', '袋叩き死', '溺死', '落雷死', '恐怖死',
    '自尽', '食中毒死', '過労死', '誤殺', '見殺し', '逃亡失敗', '圧死', '釜茹で',
    '口封じ', '一刀両断', '強盗殺人', '恋敵の凶刃', '小師妹の制裁', '龍湘の誤殺',
    '上官螢の制裁', '小梅の刺殺', '突然の死'
)

$catalog = [ordered]@{
    schema_version = 1
    preset_version = if ($preset.source.version) { $preset.source.version } else { $preset.source.name }
    generated_at = [DateTimeOffset]::Now.ToString('o')
    policy = [ordered]@{
        initial_scope = 'ending_only'
        positive_observations_only = $true
        bare_faction_tags = $false
        spoiler_candidates_default_visible = $false
        default_picker_categories = @('survival', 'join')
        default_picker_event_tags = @('金烏上人死亡')
        unknown_labels_are_system_state = $true
    }
    categories = @(
        [ordered]@{ id = 'ending'; label = 'ED名'; order = 1 },
        [ordered]@{ id = 'heroine'; label = '結縁相手'; order = 2 },
        [ordered]@{ id = 'survival'; label = '生存'; order = 3 },
        [ordered]@{ id = 'join'; label = '唐門加入'; order = 4 },
        [ordered]@{ id = 'status'; label = '身分・受入れ'; order = 5 },
        [ordered]@{ id = 'movement'; label = '留学・移動'; order = 6 },
        [ordered]@{ id = 'event'; label = '観測済みイベント'; order = 7 },
        [ordered]@{ id = 'manual'; label = '手動タグ'; order = 8 },
        [ordered]@{ id = 'spoiler_candidate'; label = 'ネタバレ候補'; order = 9 }
    )
    tags = $tags
    system_states = @('ED名不明', '結縁相手不明', '手動確認', '低信頼', '重複', '短文', '未分類')
    future_death_tags = $futureDeathTags
}

$directory = Split-Path -Parent $OutputPath
New-Item -ItemType Directory -Path $directory -Force | Out-Null
$json = $catalog | ConvertTo-Json -Depth 12
[IO.File]::WriteAllText($OutputPath, $json + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
Write-Host "Generated $OutputPath ($($tags.Count) active tags)"
