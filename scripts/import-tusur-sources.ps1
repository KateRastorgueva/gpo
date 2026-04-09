param(
    [string]$BackendUrl = "http://localhost:8000",
    [string]$Email = "admin@example.com",
    [string]$Password = "changethis",
    [string]$SeedPath = "scripts/tusur_sources_seed_v1.json",
    [switch]$SkipFaqImport,
    [switch]$SkipReindex
)

$ErrorActionPreference = "Stop"

function Get-AccessToken {
    param(
        [string]$BaseUrl,
        [string]$UserEmail,
        [string]$UserPassword
    )
    $body = @{
        username = $UserEmail
        password = $UserPassword
    }
    $resp = Invoke-RestMethod `
        -Method Post `
        -Uri "$BaseUrl/api/v1/login/access-token" `
        -Body $body `
        -ContentType "application/x-www-form-urlencoded"
    return $resp.access_token
}

function Upload-Source {
    param(
        [string]$BaseUrl,
        [hashtable]$Headers,
        [pscustomobject]$Entry
    )
    $payload = @{
        title = [string]$Entry.title
        source_url = [string]$Entry.source_url
        manual_content = [string]$Entry.manual_content
    } | ConvertTo-Json -Depth 5
    $payloadBytes = [System.Text.Encoding]::UTF8.GetBytes($payload)

    return Invoke-RestMethod `
        -Method Post `
        -Uri "$BaseUrl/api/v1/admin/sources/upload-json" `
        -Headers $Headers `
        -Body $payloadBytes `
        -ContentType "application/json; charset=utf-8"
}

function Normalize-FaqQuestion {
    param([string]$Question)
    if ([string]::IsNullOrWhiteSpace($Question)) {
        return ""
    }
    $q = $Question.ToLowerInvariant().Trim()
    $q = [regex]::Replace($q, "\s+", " ")
    $q = [regex]::Replace($q, "[^\p{L}\p{Nd}\s\-]", "")
    return $q.Trim()
}

function Get-ExistingFaqMap {
    param(
        [string]$BaseUrl,
        [hashtable]$Headers
    )
    $map = @{}
    $resp = Invoke-RestMethod `
        -Method Get `
        -Uri "$BaseUrl/api/v1/admin/faq" `
        -Headers $Headers

    foreach ($faq in $resp.data) {
        $normalized = Normalize-FaqQuestion -Question ([string]$faq.question)
        if ($normalized) {
            $map[$normalized] = $true
        }
    }
    return $map
}

function Create-Faq {
    param(
        [string]$BaseUrl,
        [hashtable]$Headers,
        [string]$Question,
        [string]$Answer
    )
    $payload = @{
        question = $Question
        answer = $Answer
        is_active = $true
    } | ConvertTo-Json -Depth 3
    $payloadBytes = [System.Text.Encoding]::UTF8.GetBytes($payload)

    return Invoke-RestMethod `
        -Method Post `
        -Uri "$BaseUrl/api/v1/admin/faq" `
        -Headers $Headers `
        -Body $payloadBytes `
        -ContentType "application/json; charset=utf-8"
}

function Build-FaqAnswer {
    param(
        [pscustomobject]$Entry
    )
    if ($Entry.PSObject.Properties.Name -contains "faq_answer") {
        $custom = [string]$Entry.faq_answer
        if (-not [string]::IsNullOrWhiteSpace($custom)) {
            return $custom.Trim()
        }
    }

    $sourceUrl = [string]$Entry.source_url
    if (-not [string]::IsNullOrWhiteSpace($sourceUrl)) {
        return "Official information is available at: $sourceUrl"
    }
    return "Please use the official TUSUR section from the knowledge base."
}

if (!(Test-Path -LiteralPath $SeedPath)) {
    throw "Seed file not found: $SeedPath"
}

$seedFullPath = Resolve-Path -LiteralPath $SeedPath
$seedRaw = Get-Content -LiteralPath $seedFullPath -Raw -Encoding UTF8
$entries = $seedRaw | ConvertFrom-Json

if (!$entries -or $entries.Count -eq 0) {
    throw "Seed file is empty: $seedFullPath"
}

Write-Host "Login to backend: $BackendUrl"
$token = Get-AccessToken -BaseUrl $BackendUrl -UserEmail $Email -UserPassword $Password
$headers = @{
    Authorization = "Bearer $token"
}

$uploaded = @()
foreach ($entry in $entries) {
    Write-Host "Uploading source: $($entry.title)"
    $source = Upload-Source -BaseUrl $BackendUrl -Headers $headers -Entry $entry
    $uploaded += $source
}

$faqCreated = 0
$faqSkipped = 0
if (-not $SkipFaqImport) {
    Write-Host "Importing FAQ from sample_questions..."
    $existingFaqMap = Get-ExistingFaqMap -BaseUrl $BackendUrl -Headers $headers
    foreach ($entry in $entries) {
        if (-not ($entry.PSObject.Properties.Name -contains "sample_questions")) {
            continue
        }
        $answer = Build-FaqAnswer -Entry $entry
        foreach ($questionObj in $entry.sample_questions) {
            $question = [string]$questionObj
            if ([string]::IsNullOrWhiteSpace($question)) {
                continue
            }
            $normalized = Normalize-FaqQuestion -Question $question
            if (-not $normalized) {
                continue
            }
            if ($existingFaqMap.ContainsKey($normalized)) {
                $faqSkipped += 1
                continue
            }
            Write-Host "Creating FAQ: $question"
            Create-Faq -BaseUrl $BackendUrl -Headers $headers -Question $question -Answer $answer | Out-Null
            $existingFaqMap[$normalized] = $true
            $faqCreated += 1
        }
    }
}

if (-not $SkipReindex) {
    Write-Host "Running reindex..."
    $reindexBody = "{}"
    $reindex = Invoke-RestMethod `
        -Method Post `
        -Uri "$BackendUrl/api/v1/admin/sources/reindex" `
        -Headers $headers `
        -Body $reindexBody `
        -ContentType "application/json"
    Write-Host "Reindex done: $($reindex.reindexed_sources)"
}

Write-Host ""
Write-Host "Uploaded sources: $($uploaded.Count)"
foreach ($s in $uploaded) {
    Write-Host "- $($s.title) | status=$($s.status) | id=$($s.id)"
}
if (-not $SkipFaqImport) {
    Write-Host "FAQ created: $faqCreated"
    Write-Host "FAQ skipped (already exists): $faqSkipped"
}
