# Windows-only regression for reader-compatible ZIPs with optional cover images.
$ErrorActionPreference = 'Stop'
. (Join-Path (Resolve-Path 'tools').Path 'zip_novel_artifacts.ps1')

$root = Join-Path ([System.IO.Path]::GetTempPath()) ("Novel Library Cover ZIP " + [guid]::NewGuid().ToString('N'))
$book = Join-Path $root 'downloads\martial-world'
New-Item -ItemType Directory -Force -Path $book | Out-Null

try {
    @(
        @{ position = 1; title = 'Chapter 1'; file = 'chapter_0001.txt' }
    ) | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $book 'chapters.json') -Encoding UTF8
    ('Chapter 1' + [Environment]::NewLine + [Environment]::NewLine +
     'This is original synthetic content for validating the cover-enabled ZIP.') |
        Set-Content -LiteralPath (Join-Path $book 'chapter_0001.txt') -Encoding UTF8
    [System.IO.File]::WriteAllBytes((Join-Path $book 'source.epub'), [byte[]]((1..220) | ForEach-Object { $_ % 255 }))
    @{ title = 'Martial World'; source_url = 'https://novelfull.com/martial-world.html'; chapter_count = 1; cover_image = 'cover.png' } |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $book 'metadata.json') -Encoding UTF8

    $picture = Join-Path $book 'cover.png'
    python -c "from PIL import Image; Image.new('RGB',(100,150),'blue').save(r'$picture','PNG')"
    if ($LASTEXITCODE -ne 0) { throw 'Could not create valid cover image fixture' }

    $first = Join-Path $root 'novel-with-cover.zip'
    New-NovelZip (Join-Path $root 'downloads') 'https://novelfull.com/martial-world.html' $first
    if (-not (Test-NovelZip $first 'https://novelfull.com/martial-world.html')) {
        throw 'Cover-enabled archive failed structural validation'
    }
    $zip = [System.IO.Compression.ZipFile]::OpenRead($first)
    try {
        if (-not $zip.GetEntry('martial-world/cover.png')) { throw 'ZIP lost standalone cover' }
        if ($zip.Entries.Count -ne 5) { throw 'Cover ZIP should contain four base members plus cover' }
    } finally { $zip.Dispose() }

    # Legacy ZIPs without a cover remain backwards compatible.
    Remove-Item -LiteralPath $picture
    @{ title = 'Martial World'; source_url = 'https://novelfull.com/martial-world.html'; chapter_count = 1 } |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $book 'metadata.json') -Encoding UTF8
    $second = Join-Path $root 'novel-without-cover.zip'
    New-NovelZip (Join-Path $root 'downloads') 'https://novelfull.com/martial-world.html' $second
    if (-not (Test-NovelZip $second 'https://novelfull.com/martial-world.html')) {
        throw 'Legacy coverless archive failed structural validation'
    }
    $zip = [System.IO.Compression.ZipFile]::OpenRead($second)
    try {
        if ($zip.Entries.Count -ne 4) { throw 'Legacy ZIP count has changed' }
    } finally { $zip.Dispose() }

    # A declared cover must exist; never silently publish a missing image.
    @{ title = 'Martial World'; source_url = 'https://novelfull.com/martial-world.html'; chapter_count = 1; cover_image = 'cover.png' } |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $book 'metadata.json') -Encoding UTF8
    try {
        New-NovelZip (Join-Path $root 'downloads') 'https://novelfull.com/martial-world.html' (Join-Path $root 'should-not-exist.zip')
        throw 'An absent declared cover unexpectedly passed ZIP packaging'
    } catch {
        if ($_.Exception.Message -notmatch 'Expected one complete book') { throw }
    }
    Write-Host 'Verified cover ZIP, coverless ZIP, and missing-cover rejection.' -ForegroundColor Green
} finally {
    Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
}
