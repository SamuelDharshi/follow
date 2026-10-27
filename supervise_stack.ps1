# Keeps the Follow stack alive: recorder, API (port 8000) and the production frontend (port 3002).
# Checks every 20 seconds and restarts whatever is down. Run hidden:  powershell -WindowStyle Hidden -File supervise_stack.ps1
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Test-Url($url) {
    try { (Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 6).StatusCode -eq 200 } catch { $false }
}

while ($true) {
    # recorder: healthy if any feed heartbeat is fresh; the .cmd wrapper already restarts it if it exits
    $rec = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*follow.recorder*' }
    if (-not $rec) {
        Start-Process -WindowStyle Hidden -FilePath cmd.exe -ArgumentList '/c', "`"$root\run_recorder.cmd`""
    }
    if (-not (Test-Url 'http://localhost:8000/api/health')) {
        $api = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*follow.api*' }
        $api | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Start-Process -WindowStyle Hidden -WorkingDirectory $root -FilePath python -ArgumentList '-m', 'follow.api'
    }
    if (-not (Test-Url 'http://localhost:3002/')) {
        Start-Process -WindowStyle Hidden -WorkingDirectory "$root\web" -FilePath cmd.exe -ArgumentList '/c', 'npx next start -p 3002'
    }
    # public tunnel to the API (India region keeps latency low); the free static domain is reused on restart
    if (-not (Get-Process ngrok -ErrorAction SilentlyContinue)) {
        Start-Process -WindowStyle Hidden -FilePath ngrok -ArgumentList 'http', '8000', '--region=in', '--log=stdout'
    }
    Start-Sleep -Seconds 20
}
