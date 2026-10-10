#Requires -Version 7.0
[CmdletBinding()]
param(
    [ValidatePattern('^DEMO-ORDER-UNKNOWN-[0-9]{3}$')]
    [string]$UnknownOrderRef = 'DEMO-ORDER-UNKNOWN-746',
    [switch]$Overwrite
)

function ConvertTo-SrtTimestamp {
    param([Parameter(Mandatory)][int]$Milliseconds)
    $value = [Math]::Max(0, $Milliseconds)
    $hours = [int][Math]::Floor($value / 3600000)
    $minutes = [int][Math]::Floor(($value % 3600000) / 60000)
    $seconds = [int][Math]::Floor(($value % 60000) / 1000)
    $remainder = [int]($value % 1000)
    return ('{0:D2}:{1:D2}:{2:D2},{3:D3}' -f $hours, $minutes, $seconds, $remainder)
}

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$outputPath = Join-Path $repositoryRoot 'docs\assets\returnflow-demo.mp4'
$subtitlePath = Join-Path $repositoryRoot 'docs\assets\returnflow-demo.zh-CN.srt'
$localDirectory = Join-Path $repositoryRoot '.local'
$scenePath = Join-Path $repositoryRoot 'frontend\scripts\demo-video-scenes.json'

foreach ($commandName in @('node', 'npm', 'ffmpeg', 'ffprobe')) {
    if (-not (Get-Command $commandName -ErrorAction SilentlyContinue)) {
        throw "Video recording requires $commandName on PATH. Install it and rerun scripts/record-demo-video.ps1."
    }
}
if (-not (Test-Path -LiteralPath $scenePath -PathType Leaf)) {
    throw 'The checked-in video transcript was not found.'
}
if (-not $Overwrite -and ((Test-Path -LiteralPath $outputPath -PathType Leaf) -or (Test-Path -LiteralPath $subtitlePath -PathType Leaf))) {
    throw 'The demo video already exists; pass -Overwrite to replace the published MP4 and subtitle file.'
}

try {
    Add-Type -AssemblyName System.Speech
}
catch {
    throw 'Windows System.Speech is required to synthesize the local Mandarin narration.'
}
$synthesizer = [System.Speech.Synthesis.SpeechSynthesizer]::new()
$voice = $synthesizer.GetInstalledVoices() |
    Where-Object { $_.VoiceInfo.Culture.Name -eq 'zh-CN' -and $_.VoiceInfo.Name -like 'Microsoft Huihui*' } |
    Select-Object -First 1
if (-not $voice) {
    $synthesizer.Dispose()
    throw 'A Microsoft Huihui zh-CN speech voice is required to render the local Mandarin narration.'
}
$synthesizer.SelectVoice($voice.VoiceInfo.Name)
$synthesizer.Rate = -1
$synthesizer.Volume = 100

if ([string]::IsNullOrWhiteSpace($env:COMPOSE_PROJECT_NAME)) {
    $env:COMPOSE_PROJECT_NAME = 'returnflow-demo'
}

Push-Location $repositoryRoot
try {
    Write-Host 'Starting/verifying the local demo before recording.'
    & (Join-Path $PSScriptRoot 'start-demo.ps1')
    if ($LASTEXITCODE -ne 0) {
        throw "Demo start failed with exit code $LASTEXITCODE."
    }

    $settings = @{}
    foreach ($line in Get-Content -LiteralPath (Join-Path $repositoryRoot '.env')) {
        if ($line -match '^(POSTGRES_PORT|API_PORT|PAYMENT_PORT|FRONTEND_PORT|N8N_PORT|MAILPIT_UI_PORT)=([0-9]+)$') {
            $settings[$Matches[1]] = $Matches[2]
        }
    }
    foreach ($name in @('POSTGRES_PORT', 'API_PORT', 'PAYMENT_PORT', 'FRONTEND_PORT', 'N8N_PORT', 'MAILPIT_UI_PORT')) {
        if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name)) -and $settings.ContainsKey($name)) {
            Set-Item -Path "Env:$name" -Value $settings[$name]
        }
    }

    if ([string]::IsNullOrWhiteSpace($env:RETURNFLOW_FRONTEND_URL)) {
        $env:RETURNFLOW_FRONTEND_URL = "http://127.0.0.1:$($env:FRONTEND_PORT)"
    }
    if ([string]::IsNullOrWhiteSpace($env:N8N_BASE_URL)) {
        $env:N8N_BASE_URL = "http://127.0.0.1:$($env:N8N_PORT)"
    }
    if ([string]::IsNullOrWhiteSpace($env:MAILPIT_BASE_URL)) {
        $env:MAILPIT_BASE_URL = "http://127.0.0.1:$($env:MAILPIT_UI_PORT)"
    }
    $env:RETURNFLOW_UNKNOWN_ORDER_REF = $UnknownOrderRef

    & (Join-Path $PSScriptRoot 'verify-demo.ps1')
    if ($LASTEXITCODE -ne 0) {
        throw "Demo health verification failed with exit code $LASTEXITCODE."
    }

    Write-Host 'Creating the synthetic UNKNOWN scenario used in the recording.'
    & (Join-Path $PSScriptRoot 'run-unknown-demo.ps1') -OrderRef $UnknownOrderRef
    if ($LASTEXITCODE -ne 0) {
        throw "The local UNKNOWN scenario failed with exit code $LASTEXITCODE."
    }

    $workName = 'video-work-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff')
    $workDirectory = Join-Path $localDirectory $workName
    New-Item -ItemType Directory -Path $workDirectory | Out-Null
    $env:RETURNFLOW_VIDEO_WORK_DIR = $workDirectory
    $env:RETURNFLOW_VIDEO_POST_ROLL_MS = '1500'

    $scenes = Get-Content -LiteralPath $scenePath -Raw | ConvertFrom-Json
    $manifestScenes = [System.Collections.Generic.List[object]]::new()
    for ($index = 0; $index -lt $scenes.Count; $index++) {
        $scene = $scenes[$index]
        $clipPath = Join-Path $workDirectory ("voice-{0:D2}.wav" -f $index)
        $synthesizer.SetOutputToWaveFile($clipPath)
        $synthesizer.Speak([string]$scene.narration)
        $synthesizer.SetOutputToNull()

        $durationText = (& ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 $clipPath | Select-Object -Last 1).Trim()
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($durationText)) {
            throw "Could not measure Mandarin narration clip $($scene.id)."
        }
        $durationMs = [int][Math]::Round(([double]::Parse($durationText, [Globalization.CultureInfo]::InvariantCulture)) * 1000)
        $manifestScenes.Add([ordered]@{
            id         = [string]$scene.id
            caption    = [string]$scene.caption
            narration  = [string]$scene.narration
            durationMs = $durationMs
            audioPath  = $clipPath
        })
    }
    $manifestPath = Join-Path $workDirectory 'narration-manifest.json'
    $manifestJson = @{ scenes = @($manifestScenes.ToArray()) } | ConvertTo-Json -Depth 6
    [System.IO.File]::WriteAllText($manifestPath, $manifestJson, [System.Text.UTF8Encoding]::new($false))

    Write-Host 'Recording real browser interactions across the ReturnFlow UI, n8n, and Mailpit.'
    Push-Location (Join-Path $repositoryRoot 'frontend')
    try {
        & node (Join-Path $repositoryRoot 'frontend\scripts\record-demo.mjs')
        if ($LASTEXITCODE -ne 0) {
            throw "Playwright recording failed with exit code $LASTEXITCODE. Raw diagnostic files remain under ignored .local."
        }
    }
    finally {
        Pop-Location
    }

    $timelinePath = Join-Path $workDirectory 'timeline.json'
    $timeline = Get-Content -LiteralPath $timelinePath -Raw | ConvertFrom-Json
    $srt = [System.Collections.Generic.List[string]]::new()
    for ($index = 0; $index -lt $timeline.scenes.Count; $index++) {
        $entry = $timeline.scenes[$index]
        $start = [int]$entry.narrationStartMs
        $end = $start + [int]$entry.narrationDurationMs
        $srt.Add([string]($index + 1))
        $srt.Add("$(ConvertTo-SrtTimestamp $start) --> $(ConvertTo-SrtTimestamp $end)")
        $srt.Add(([string]$entry.caption).Replace("`r", '').Replace("`n", ' '))
        $srt.Add('')
    }
    [System.IO.File]::WriteAllText($subtitlePath, ($srt -join "`r`n"), [System.Text.UTF8Encoding]::new($false))

    $audioProbe = & ffprobe -v error -select_streams a:0 -show_entries stream=sample_rate,channels -of json (Join-Path $workDirectory 'voice-00.wav') | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0 -or -not $audioProbe.streams -or -not $audioProbe.streams[0].sample_rate) {
        throw 'Could not inspect the synthesized narration audio.'
    }
    $sampleRate = [int]$audioProbe.streams[0].sample_rate
    $channels = [int]$audioProbe.streams[0].channels
    $channelLayout = if ($channels -eq 1) { 'mono' } else { 'stereo' }
    $audioSegments = [System.Collections.Generic.List[string]]::new()
    $manifestById = @{}
    foreach ($scene in $manifestScenes) { $manifestById[$scene.id] = $scene }

    for ($index = 0; $index -lt $timeline.scenes.Count; $index++) {
        $entry = $timeline.scenes[$index]
        foreach ($segment in @(
            @{ Kind = 'action'; DurationMs = [int]$entry.actionDurationMs },
            @{ Kind = 'narration'; DurationMs = [int]$entry.narrationDurationMs },
            @{ Kind = 'postroll'; DurationMs = [int]$entry.postRollMs }
        )) {
            if ($segment.Kind -eq 'narration') {
                $path = $manifestById[$entry.id].audioPath
            }
            elseif ($segment.DurationMs -gt 0) {
                $path = Join-Path $workDirectory ("silence-{0:D2}-{1}.wav" -f $index, $segment.Kind)
                $seconds = ([double]$segment.DurationMs / 1000).ToString('0.###', [Globalization.CultureInfo]::InvariantCulture)
                & ffmpeg -hide_banner -loglevel error -y -f lavfi -i "anullsrc=channel_layout=${channelLayout}:sample_rate=${sampleRate}" -t $seconds -c:a pcm_s16le $path
                if ($LASTEXITCODE -ne 0) { throw "Could not create the local $($segment.Kind) audio spacer." }
            }
            else {
                continue
            }
            $portablePath = $path.Replace('\', '/')
            $audioSegments.Add("file '$portablePath'")
        }
    }

    $concatPath = Join-Path $workDirectory 'audio-segments.ffconcat'
    [System.IO.File]::WriteAllText($concatPath, ($audioSegments -join "`n") + "`n", [System.Text.UTF8Encoding]::new($false))
    $combinedAudioPath = Join-Path $workDirectory 'returnflow-demo-narration.wav'
    & ffmpeg -hide_banner -loglevel error -y -f concat -safe 0 -i $concatPath -c:a pcm_s16le $combinedAudioPath
    if ($LASTEXITCODE -ne 0) { throw 'Could not align the local narration to the recorded browser timeline.' }

    $rawVideoPath = Join-Path $workDirectory 'returnflow-demo-raw.webm'
    $subtitleFilter = "subtitles=filename='docs/assets/returnflow-demo.zh-CN.srt':force_style='FontName=Microsoft YaHei,FontSize=24,PrimaryColour=&H00FFFFFF,BorderStyle=3,BackColour=&H90000000,Outline=0,Shadow=0,MarginV=30,Alignment=2'"
    & ffmpeg -hide_banner -y -i $rawVideoPath -i $combinedAudioPath -vf $subtitleFilter -map '0:v:0' -map '1:a:0' -c:v libx264 -preset medium -crf 24 -pix_fmt yuv420p -c:a aac -b:a 128k -shortest -movflags +faststart $outputPath
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not encode the final MP4. The raw WebM, narration clips and timeline remain under ignored .local.'
    }

    $finalDuration = (& ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 $outputPath | Select-Object -Last 1).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'The final MP4 was written but ffprobe could not verify it.' }
    $durationSeconds = [Math]::Round([double]::Parse($finalDuration, [Globalization.CultureInfo]::InvariantCulture), 1)
    $sizeMb = [Math]::Round((Get-Item -LiteralPath $outputPath).Length / 1MB, 1)
    Write-Host "Finished real demo video: $outputPath ($durationSeconds seconds, $sizeMb MB)."
    Write-Host "Chinese subtitle file: $subtitlePath. Raw recordings and voice clips remain under ignored $workDirectory."
}
finally {
    $synthesizer.Dispose()
    Pop-Location
}
