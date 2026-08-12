param(
    [switch]$Detached
)

$ErrorActionPreference = "Stop"
$env:COMPOSE_PARALLEL_LIMIT = "1"

docker compose build
if ($LASTEXITCODE -ne 0) {
    Write-Warning "Docker build failed once. Retrying after the transient BuildKit snapshot error..."
    docker compose build
    if ($LASTEXITCODE -ne 0) {
        throw "Docker build failed twice. Restart Docker Desktop and run .\start.ps1 again."
    }
}

if ($Detached) {
    docker compose up -d
} else {
    docker compose up
}

exit $LASTEXITCODE
