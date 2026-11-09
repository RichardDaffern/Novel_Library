# Download previously created full-novel GitHub Actions artifacts.
# No source-site scraping. Requires GitHub CLI (gh) and permission to archive.
[CmdletBinding()]
param(
    [string]$Repository = 'RichardDaffern/Novel_Library',
    [string]$Destination = '',
    [ValidateRange(1,10)][int]$MaxAttempts = 3,
    [ValidateRange(0,10000)][int]$Limit = 0,
    [switch]$BrowserLogin,
    [switch]$CheckSetup,
    [switch]$RepackOnly,
    [switch]$KeepOriginalFolders,
    [string]$RegistryFile = ''
)

$ErrorActionPreference = 'Stop'
# PowerShell 5.1 evaluates parameter defaults before $PSScriptRoot is populated.
# Calculate filesystem paths only after the param block has bound.
$scriptPath = $MyInvocation.MyCommand.Path
if ([string]::IsNullOrWhiteSpace($scriptPath)) {
    throw 'Unable to determine downloader script path.'
}
$repoRoot = Split-Path -Parent (Split-Path -Parent $scriptPath)
. (Join-Path $PSScriptRoot 'zip_novel_artifacts.ps1')
if ([string]::IsNullOrWhiteSpace($Destination)) {
    $Destination = Join-Path $repoRoot 'Downloaded_Novels'
}
$logFile = Join-Path $repoRoot 'download-last-run.log'
$transcriptStarted = $false
try {
    Start-Transcript -Path $logFile -Force -ErrorAction Stop | Out-Null
    $transcriptStarted = $true
} catch {
    Write-Warning "Could not start diagnostic log: $($_.Exception.Message)"
}
try {
    Write-Host "Log file: $logFile"
    if ($CheckSetup) {
        # This runs with no network, GitHub account, or downloaded book required.
        Write-Host "Startup self-check passed. Destination: $Destination"
        return
    }
if (-not $RepackOnly) {
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw "GitHub CLI (gh) is not installed or not on PATH. Run winget install --id GitHub.cli --exact and open a new terminal."
}
if ($BrowserLogin) {
    Write-Host "Starting GitHub browser sign-in. Follow the one-time code shown here." -ForegroundColor Cyan
    & gh auth login --web --clipboard --skip-ssh-key
    if ($LASTEXITCODE -ne 0) { throw "GitHub browser sign-in was cancelled or unsuccessful." }
}

# Windows PowerShell 5.1 can treat native stderr as a terminating error.
# Check login without that behaviour so the browser prompt remains reachable.
$previousPreference = $ErrorActionPreference
$loginValid = $false
try {
    $ErrorActionPreference = 'Continue'
    & gh auth status *> $null
    $loginValid = ($LASTEXITCODE -eq 0)
} finally {
    $ErrorActionPreference = $previousPreference
}
if (-not $loginValid) {
    Write-Host "No working GitHub CLI authentication was detected." -ForegroundColor Yellow
    $reply = Read-Host "Open browser-based GitHub sign-in now? [Y/n]"
    if ([string]::IsNullOrWhiteSpace($reply) -or $reply -match '^(?i:y|yes)$') {
        Write-Host 'GitHub CLI will display a one-time code and open your browser.'
        & gh auth login --web --clipboard --skip-ssh-key
        if ($LASTEXITCODE -ne 0) { throw "GitHub browser sign-in failed or was cancelled." }
        $previousPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            & gh auth status *> $null
            $loginValid = ($LASTEXITCODE -eq 0)
        } finally {
            $ErrorActionPreference = $previousPreference
        }
        if (-not $loginValid) { throw "GitHub CLI still reports no working login." }
    } else {
        throw "No GitHub CLI login. Run 'gh auth login --web --clipboard' in a terminal to sign in."
    }
}

# An account with read access (such as AdityaSreevatsaK) is sufficient.
try {
    $activeUser = & gh api user --jq .login 2>$null
    if ($LASTEXITCODE -eq 0 -and $activeUser) {
        Write-Host "Using GitHub account: $activeUser" -ForegroundColor Green
    }
} catch {
    Write-Warning 'Could not identify active GitHub account; proceeding with existing credentials.'
}

}

# Fetch the current registry; its entries are links, not the files themselves.
$registryUrl = "https://raw.githubusercontent.com/$Repository/main/downloaded_novels.json"
try {
    if ($RegistryFile) {
        $registry = Get-Content -LiteralPath $RegistryFile -Raw -Encoding UTF8 | ConvertFrom-Json
    } else {
        $registry = Invoke-RestMethod -Uri $registryUrl -TimeoutSec 90
    }
    if ($null -eq $registry.novels) { throw 'The registry has no novels property.' }
} catch {
    throw "Could not read ${registryUrl}: $($_.Exception.Message)"
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
        $raw = & gh api "repos/$Repository/actions/artifacts/$Id"
        if ($LASTEXITCODE -ne 0 -or -not $raw) {
            Write-Warning "GitHub API could not access artifact $Id. Check the GitHub account permissions above."
            return $null
        }
        return (($raw -join "`n") | ConvertFrom-Json)
    } catch {
        Write-Warning "Artifact $Id lookup failed: $($_.Exception.Message)"
        return $null
    }
}

# Already-downloaded folders from older versions can be converted without
# downloading again. Keep the original extraction as a reversible backup.
$backupRoot = $Destination + '_Originals'
$stagingRoot = $Destination + '_Staging'
function Preserve-Legacy([string]$path) {
    if ($KeepOriginalFolders -or -not (Test-Path -LiteralPath $path -PathType Container)) { return }
    New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
    $name = Split-Path -Leaf $path
    $backup = Join-Path $backupRoot $name
    $suffix = 1
    while (Test-Path -LiteralPath $backup) {
        $backup = Join-Path $backupRoot ("$name-$suffix")
        $suffix++
    }
    Move-Item -LiteralPath $path -Destination $backup
    Write-Host "  Existing extracted files preserved at: $backup"
}

$success = 0
$skipped = 0
$failed = [System.Collections.Generic.List[string]]::new()
$position = 0

foreach ($book in $books) {
    $position++
    Write-Host ''
    Write-Host "[$position/$($books.Count)] $($book.Title)" -ForegroundColor Cyan
    $name = [regex]::Replace($book.Title, '[<>:"/\\|?*\x00-\x1F]', '_').Trim().TrimEnd('.')
    if ([string]::IsNullOrWhiteSpace($name)) { $name = "Novel_$position" }
    if ($name.Length -gt 95) { $name = $name.Substring(0,95).Trim().TrimEnd('.') }
    if ($name -match '^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$') { $name = "Novel_$name" }
    $legacy = Join-Path $Destination $name
    $completed = $false
    $candidates = @($book.Candidates | Sort-Object -Property @{
        Expression = { [datetime]$_.completed_at_utc }; Descending = $true
    })

    # A verified ZIP can be reused regardless of which run produced it.
    foreach ($candidate in $candidates) {
        $zipPath = Join-Path $Destination ("novel-$($candidate.artifact_id).zip")
        if (Test-NovelZip $zipPath $book.Url) {
            Write-Host "  Already archived: $([System.IO.Path]::GetFileName($zipPath))"
            Preserve-Legacy $legacy
            $skipped++; $completed = $true; break
        }
        if (Test-Path -LiteralPath $zipPath) {
            Write-Warning "Existing ZIP is invalid or belongs to another novel: $zipPath"
        }
    }
    if ($completed) { continue }

    # Convert an old download from the previous folder-based version.
    if (Test-Path -LiteralPath $legacy -PathType Container) {
        $receiptPath = Join-Path $legacy '.download-complete.json'
        if (Test-Path -LiteralPath $receiptPath -PathType Leaf) {
            try {
                $receipt = Get-Content -LiteralPath $receiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
                $artifactId = [long]$receipt.artifact_id
                $knownIds = @($candidates | ForEach-Object { [long]$_.artifact_id })
                if ($knownIds -notcontains $artifactId) {
                    throw "Old folder receipt artifact $artifactId is not listed for this book."
                }
                $zipPath = Join-Path $Destination ("novel-$artifactId.zip")
                New-NovelZip $legacy $book.Url $zipPath
                Preserve-Legacy $legacy
                $success++; $completed = $true
            } catch {
                Write-Warning "Existing download could not be repacked: $($_.Exception.Message)"
            }
        }
    }
    if ($completed) { continue }
    if ($RepackOnly) {
        Write-Warning 'No complete local folder to repackage; nothing downloaded.'
        $failed.Add($book.Title)
        continue
    }

    foreach ($candidate in $candidates) {
        if ($candidate.expires_at_utc -and [datetime]$candidate.expires_at_utc -le [datetime]::UtcNow) { continue }
        $artifactId = [long]$candidate.artifact_id
        $zipPath = Join-Path $Destination ("novel-$artifactId.zip")
        if (Test-Path -LiteralPath $zipPath) { continue }
        $artifact = Get-ArtifactInfo $artifactId
        if ($null -eq $artifact -or $artifact.expired -or
            [string]::IsNullOrWhiteSpace([string]$artifact.name) -or
            [long]$artifact.id -ne $artifactId) {
            Write-Warning "Artifact $artifactId is unavailable or expired."
            continue
        }
        $stage = Join-Path $stagingRoot ("artifact-$artifactId")
        for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
            try {
                if (Test-Path -LiteralPath $stage) {
                    Remove-Item -LiteralPath $stage -Recurse -Force
                }
                New-Item -ItemType Directory -Path $stage -Force | Out-Null
                Write-Host "  Downloading artifact $artifactId (attempt $attempt/$MaxAttempts)"
                & gh run download ([string]$candidate.run_id) --repo $Repository --name ([string]$artifact.name) --dir $stage
                if ($LASTEXITCODE -ne 0) { throw "GitHub CLI returned exit code $LASTEXITCODE" }
                New-NovelZip $stage $book.Url $zipPath
                Remove-Item -LiteralPath $stage -Recurse -Force
                $success++; $completed = $true; break
            } catch {
                Write-Warning "Attempt $attempt failed: $($_.Exception.Message)"
                if ($attempt -lt $MaxAttempts) { Start-Sleep -Seconds (3 * $attempt) }
            }
        }
        if ($completed) { break }
    }
    if (-not $completed) {
        $failed.Add($book.Title)
        Write-Warning "Failed to produce a verified ZIP for $($book.Title). Existing data was not deleted."
    }
}

$failureLog = Join-Path $Destination 'failed-downloads.txt'
if ($failed.Count) {
    $failed | Set-Content -LiteralPath $failureLog -Encoding UTF8
} elseif (Test-Path -LiteralPath $failureLog) {
    Remove-Item -LiteralPath $failureLog -Force
}
Write-Host "`nFinished: ZIPs created=$success, already archived=$skipped, failed/unavailable=$($failed.Count)." -ForegroundColor Cyan
if ($failed.Count) {
    Write-Warning "See $failureLog ; rerun this launcher to retry."
    exit 2
}
exit 0
} catch {
    Write-Host ''
    Write-Host "FATAL ERROR: $($_.Exception.Message)" -ForegroundColor Red
    if ($_.InvocationInfo -and $_.InvocationInfo.PositionMessage) {
        Write-Host $_.InvocationInfo.PositionMessage -ForegroundColor Red
    }
    Write-Host "Diagnostic log: $logFile" -ForegroundColor Yellow
    exit 1
} finally {
    if ($transcriptStarted) {
        try { Stop-Transcript | Out-Null } catch { }
    }
}
