param([ValidateRange(1024, 65535)][int]$Port = 8765)

# Use fixed replies for a local UI preview; no external model requests are made.
$previousProvider = $env:MODEL_PROVIDER
Push-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
try {
    $env:MODEL_PROVIDER = 'stub'
    python -m uvicorn app:app --host 127.0.0.1 --port $Port
}
finally {
    $env:MODEL_PROVIDER = $previousProvider
    Pop-Location
}
