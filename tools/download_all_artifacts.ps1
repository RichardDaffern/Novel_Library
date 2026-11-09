# Download previously created full-novel GitHub Actions artifacts.
# No source-site scraping. Requires GitHub CLI (gh) and permission to archive.
[CmdletBinding()]
param(
    [string]$Repository = 'RichardDaffern/Novel_Library',
    [string]$Destination = (Join-Path (Split-Path -Parent $PSScriptRoot) 'Downloaded_Novels'),
    [ValidateRange(1,10)][int]$MaxAttempts = 3,
    [ValidateRange(0,10000)][int]$Limit = 0
)

$ErrorActionPreference = 'Stop'

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Host 'GitHub CLI is missing. Install it with:' -ForegroundColor Yellow
    Write-Host '  winget install --id GitHub.cli --exact'
    Write-Host 'Open a NEW terminal afterwards, then run: gh auth login'
    exit 1
}
& gh auth status *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Please authenticate first: gh auth login' -ForegroundColor Yellow
    exit 1
}

# Fetch the current registry; its entries are links, not the files themselves.
$registryUrl = "https://raw.githubusercontent.com/$Repository/main/downloaded_novels.json"
try {
    $registry = Invoke-RestMethod -Uri $registryUrl -TimeoutSec 90
    if ($null -eq $registry.novels) { throw 'The registry has no novels property.' }
} catch {
    Write-Host "Could not read $registryUrl : $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# Group by source URL, and prefer the newest complete full-book artifact.
$grouped = @{}
foreach ($novel in @($registry.novels)) {
    $url = [string]$novel.url
    if ([string]::IsNullOrWhiteSpace($url)) { continue }
    if (-not $grouped.ContainsKey($url)) {
        $grouped[$url] = [pscustomobject]@{
            Url = $url
            Title = [string]$novel.title
            Candidates = [System.Collections.Generic.List[object]]::new()
        }
    }
    foreach ($record in @($novel.downloads)) {
        if ($record.status -eq 'complete' -and $record.range -eq 'all' -and
            $record.artifact_id -and $record.run_id) {
            $grouped[$url].Candidates.Add($record)
        }
    }
}
$books = @($grouped.Values | Where-Object { $_.Candidates.Count -gt 0 } | Sort-Object Title)
if ($Limit -gt 0) { $books = @($books | Select-Object -First $Limit) }

New-Item -ItemType Directory -Path $Destination -Force | Out-Null
Write-Host "Found $($books.Count) unique novels with complete archives."
Write-Host "Destination: $Destination"

function Get-ArtifactInfo([long]$Id) {
    try {
        $raw = & gh api "repos/$Repository/actions/artifacts/$Id" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $raw) { return $null }
        return (($raw -join "`n") | ConvertFrom-Json)
    } catch { return $null }
}

$success = 0
$skipped = 0
$failed = [System.Collections.Generic.List[string]]::new()
$position = 0

foreach ($book in $books) {
    $position++
    Write-Host "`n[$position/$($books.Count)] $($book.Title)" -ForegroundColor Cyan
    $name = [regex]::Replace($book.Title, '[<>:"/\\|?*\x00-\x1F]', '_').Trim().TrimEnd('.')
    if ([string]::IsNullOrWhiteSpace($name)) { $name = "Novel_$position" }
    if ($name.Length -gt 95) { $name = $name.Substring(0,95).Trim().TrimEnd('.') }
    # Prefix Windows reserved device names so the path remains valid.
    if ($name -match '^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$') { $name = "Novel_$name" }
    $target = Join-Path $Destination $name
    $marker = Join-Path $target '.download-complete.json'
    $partial = "$target.partial"

    if (Test-Path -LiteralPath $marker) {
        Write-Host '  Already downloaded; skipping.'
        $skipped++
        continue
    }
    if (Test-Path -LiteralPath $target) {
        Write-Warning "The directory already exists without a completion marker: $target"
        Write-Warning 'Leaving it untouched. Rename it before retrying this novel.'
        $failed.Add($book.Title)
        continue
    }

    $gotIt = $false
    $candidates = @($book.Candidates | Sort-Object -Property @{
        Expression = { [datetime]$_.completed_at_utc }; Descending = $true
    })
    foreach ($candidate in $candidates) {
        if ($candidate.expires_at_utc -and
            [datetime]$candidate.expires_at_utc -le [datetime]::UtcNow) { continue }
        $artifact = Get-ArtifactInfo ([long]$candidate.artifact_id)
        if ($null -eq $artifact -or $artifact.expired -or
            [string]::IsNullOrWhiteSpace([string]$artifact.name) -or
            [long]$artifact.id -ne [long]$candidate.artifact_id) {
            Write-Host "  Artifact $($candidate.artifact_id) is unavailable or expired."
            continue
        }
        for ($attempt=1; $attempt -le $MaxAttempts; $attempt++) {
            if (Test-Path -LiteralPath $partial) {
                Remove-Item -LiteralPath $partial -Recurse -Force
            }
            New-Item -ItemType Directory -Path $partial -Force | Out-Null
            Write-Host "  Downloading artifact $($candidate.artifact_id) (attempt $attempt/$MaxAttempts)"
            & gh run download ([string]$candidate.run_id) --repo $Repository --name ([string]$artifact.name) --dir $partial
            $status = $LASTEXITCODE
            $payload = @(Get-ChildItem -LiteralPath $partial -File -Recurse |
                Where-Object { $_.Extension -in @('.epub', '.zip') })
            if ($status -eq 0 -and $payload.Count -gt 0) {
                Move-Item -LiteralPath $partial -Destination $target
                $receipt = [ordered]@{
                    title = $book.Title
                    source_url = $book.Url
                    artifact_id = [long]$candidate.artifact_id
                    run_id = [long]$candidate.run_id
                    downloaded_utc = [datetime]::UtcNow.ToString('o')
                }
                $receipt | ConvertTo-Json | Set-Content -LiteralPath $marker -Encoding UTF8
                $success++
                $gotIt = $true
                Write-Host '  Saved EPUB/ZIP archive.' -ForegroundColor Green
                break
            }
            Write-Warning "Attempt $attempt failed or did not contain an EPUB/ZIP file."
            if ($attempt -lt $MaxAttempts) { Start-Sleep -Seconds (3 * $attempt) }
        }
        if (Test-Path -LiteralPath $partial) {
            Remove-Item -LiteralPath $partial -Recurse -Force
        }
        if ($gotIt) { break }
    }
    if (-not $gotIt) {
        Write-Warning "No available full-book artifact succeeded for $($book.Title)"
        $failed.Add($book.Title)
    }
}

$failureLog = Join-Path $Destination 'failed-downloads.txt'
if ($failed.Count) {
    $failed | Set-Content -LiteralPath $failureLog -Encoding UTF8
} elseif (Test-Path -LiteralPath $failureLog) {
    Remove-Item -LiteralPath $failureLog -Force
}
Write-Host "`nFinished: downloaded=$success, already present=$skipped, failed/unavailable=$($failed.Count)." -ForegroundColor Cyan
if ($failed.Count) {
    Write-Warning "See $failureLog ; rerun this launcher to retry."
    exit 2
}
exit 0
