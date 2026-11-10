# Helper: store exactly one completed novel as a reader-compatible ZIP.
# ZIP layout: <source-slug>/chapter_0001.txt, chapters.json, metadata.json, source.epub.
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Get-NovelKey([string]$url) {
    try {
        $uri = [uri]$url
        return ($uri.Host.ToLowerInvariant() + $uri.AbsolutePath.TrimEnd('/').ToLowerInvariant())
    } catch { return '' }
}
function Get-NovelSlug([string]$url) {
    return [System.IO.Path]::GetFileNameWithoutExtension(([uri]$url).AbsolutePath).ToLowerInvariant()
}
function Get-ValidBook([string]$sourceDirectory, [string]$novelUrl) {
    $foundBooks = @()
    $wanted = Get-NovelKey $novelUrl
    foreach ($file in @(Get-ChildItem -LiteralPath $sourceDirectory -Recurse -Filter 'metadata.json' -File)) {
        $dir = $file.Directory.FullName
        $manifest = Join-Path $dir 'chapters.json'
        $epub = Join-Path $dir 'source.epub'
        if (-not (Test-Path -LiteralPath $manifest -PathType Leaf) -or -not (Test-Path -LiteralPath $epub -PathType Leaf)) { continue }
        try {
            $meta = Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
            if ((Get-NovelKey ([string]$meta.source_url)) -ne $wanted) { Write-Warning "Skipping unrelated book in $($dir): $($meta.source_url)"; continue }
            $parsedChapters = Get-Content -LiteralPath $manifest -Raw -Encoding UTF8 | ConvertFrom-Json
            $chapterList = [System.Collections.Generic.List[object]]::new()
            foreach ($item in $parsedChapters) { $chapterList.Add($item) }
            if ([int]$meta.chapter_count -lt 1 -or $chapterList.Count -ne [int]$meta.chapter_count) { Write-Warning "Invalid manifest size for $($dir): expected $($meta.chapter_count), got $($chapterList.Count)"; continue }
            if ((Get-Item -LiteralPath $epub).Length -lt 100) { Write-Warning "EPUB missing or too small in $($dir)"; continue }
            $seen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
            $chapters = [System.Collections.Generic.List[string]]::new()
            $valid = $true
            foreach ($chapter in $chapterList) {
                $name = [string]$chapter.file
                if ($name -notmatch '^chapter_[0-9]+\.txt$' -or -not $seen.Add($name)) { $valid = $false; break }
                $path = Join-Path $dir $name
                if (-not (Test-Path -LiteralPath $path -PathType Leaf) -or (Get-Item -LiteralPath $path).Length -le 0) { $valid = $false; break }
                $chapters.Add($path)
            }
            if ($valid) { $foundBooks += [pscustomobject]@{ Directory = $dir; Chapters = $chapters.ToArray(); Count = $chapterList.Count } }
            else { Write-Warning "A chapter is missing or invalid in $($dir)" }
        } catch { Write-Warning "Ignoring invalid candidate at $($dir): $($_.Exception.Message)" }
    }
    if ($foundBooks.Count -ne 1) {
        throw "Expected one complete book for '$novelUrl' under '$sourceDirectory'; found $($foundBooks.Count). Unrelated books and partial downloads will not be included."
    }
    return $foundBooks[0]
}
function Test-NovelZip([string]$path, [string]$novelUrl) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $false }
    $archive = $null
    try {
        $archive = [System.IO.Compression.ZipFile]::OpenRead($path)
        $prefix = (Get-NovelSlug $novelUrl) + '/'
        $metaEntry = $archive.GetEntry($prefix + 'metadata.json')
        $manifestEntry = $archive.GetEntry($prefix + 'chapters.json')
        $epubEntry = $archive.GetEntry($prefix + 'source.epub')
        if (-not $metaEntry -or -not $manifestEntry -or -not $epubEntry -or $epubEntry.Length -lt 100) { return $false }
        $reader = [System.IO.StreamReader]::new($metaEntry.Open())
        try { $meta = $reader.ReadToEnd() | ConvertFrom-Json } finally { $reader.Dispose() }
        if ((Get-NovelKey ([string]$meta.source_url)) -ne (Get-NovelKey $novelUrl)) { return $false }
        $reader = [System.IO.StreamReader]::new($manifestEntry.Open())
        try {
            $parsedChapters = $reader.ReadToEnd() | ConvertFrom-Json
            $chapters = [System.Collections.Generic.List[object]]::new()
            foreach ($item in $parsedChapters) { $chapters.Add($item) }
        } finally { $reader.Dispose() }
        if ($chapters.Count -lt 1 -or $chapters.Count -ne [int]$meta.chapter_count) { return $false }
        if ($archive.Entries.Count -ne ($chapters.Count + 3)) { return $false }
        foreach ($chapter in $chapters) {
            $file = [string]$chapter.file
            if ($file -notmatch '^chapter_[0-9]+\.txt$') { return $false }
            $entry = $archive.GetEntry($prefix + $file)
            if (-not $entry -or $entry.Length -le 0) { return $false }
        }
        return $true
    } catch { return $false } finally { if ($archive) { $archive.Dispose() } }
}
function Get-ExistingNovelZipIndex([string[]]$directories) {
    # Check ZIPs only once. Identity comes from metadata.json, not the name.
    $index = @{}
    $visited = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($directory in $directories) {
        if ([string]::IsNullOrWhiteSpace($directory) -or
            -not (Test-Path -LiteralPath $directory -PathType Container)) { continue }
        foreach ($file in @(Get-ChildItem -LiteralPath $directory -File -Filter '*.zip' | Sort-Object Name)) {
            if (-not $visited.Add($file.FullName)) { continue }
            $archive = $null
            try {
                $archive = [System.IO.Compression.ZipFile]::OpenRead($file.FullName)
                $metadata = @($archive.Entries | Where-Object { $_.FullName.EndsWith('/metadata.json') -and ($_.FullName.Split('/').Count -eq 2) })
                if ($metadata.Count -ne 1) { continue }
                $reader = [System.IO.StreamReader]::new($metadata[0].Open())
                try { $details = $reader.ReadToEnd() | ConvertFrom-Json }
                finally { $reader.Dispose() }
                $sourceUrl = [string]$details.source_url
                $key = Get-NovelKey $sourceUrl
                $archive.Dispose()
                $archive = $null
                if ($key -and -not $index.ContainsKey($key) -and (Test-NovelZip $file.FullName $sourceUrl)) {
                    $index[$key] = $file.FullName
                }
            } catch {
                Write-Warning "Cannot inspect local ZIP '$($file.FullName)': $($_.Exception.Message)"
            } finally {
                if ($archive) { $archive.Dispose() }
            }
        }
    }
    return $index
}

function New-NovelZip([string]$sourceDirectory, [string]$novelUrl, [string]$zipPath) {
    $book = Get-ValidBook $sourceDirectory $novelUrl
    if (Test-Path -LiteralPath $zipPath) { throw "Refusing to overwrite an existing ZIP: $zipPath" }
    $temporary = "$zipPath.tmp"
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
    $archive = $null
    try {
        $archive = [System.IO.Compression.ZipFile]::Open($temporary, [System.IO.Compression.ZipArchiveMode]::Create)
        $files = @($book.Chapters) + @((Join-Path $book.Directory 'chapters.json'), (Join-Path $book.Directory 'metadata.json'), (Join-Path $book.Directory 'source.epub'))
        foreach ($file in $files) {
            $entryName = (Get-NovelSlug $novelUrl) + '/' + [System.IO.Path]::GetFileName($file)
            [void][System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $file, $entryName, [System.IO.Compression.CompressionLevel]::Optimal)
        }
    } finally { if ($archive) { $archive.Dispose() } }
    if (-not (Test-NovelZip $temporary $novelUrl)) {
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
        throw "New ZIP failed structural validation: $novelUrl"
    }
    Move-Item -LiteralPath $temporary -Destination $zipPath
    Write-Host "  Created $([System.IO.Path]::GetFileName($zipPath)) ($($book.Count) chapters)" -ForegroundColor Green
}