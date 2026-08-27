<#
.SYNOPSIS
    Lokalny PostgreSQL 17 + PostGIS bez Dockera i bez uprawnien administratora.

.DESCRIPTION
    Rownowaznik uslugi "db" z docker-compose.yml: ten sam port 5433, ten sam
    DATABASE_URL, ta sama rola i baza. Gdy na maszynie pojawi sie Docker,
    wystarczy zatrzymac ten serwer i wstac "docker compose up -d db" - kod
    aplikacji nie zmienia sie ani o linie.

    Binaria (PostgreSQL z EDB + bundle PostGIS z OSGeo) sa rozpakowywane do
    tools/, dane do pgdata/. Oba katalogi sa w .gitignore.

.PARAMETER Command
    setup   pobierz binaria, initdb, utworz role i baze (idempotentne)
    start   wystartuj serwer
    stop    zatrzymaj serwer
    status  stan serwera
    psql    otworz konsole psql na bazie grunt
    reset   USUWA katalog pgdata i stawia baze od zera

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\local_pg.ps1 setup
    powershell -ExecutionPolicy Bypass -File scripts\local_pg.ps1 start
#>
param(
    [Parameter(Position = 0)]
    [ValidateSet("setup", "start", "stop", "status", "psql", "reset")]
    [string]$Command = "status"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$ToolsDir = Join-Path $RepoRoot "tools"
$PgRoot = Join-Path $ToolsDir "pgsql"
$PgBin = Join-Path $PgRoot "bin"
$PgData = Join-Path $RepoRoot "pgdata"
$LogFile = Join-Path $RepoRoot "pgdata\server.log"

$PgVersion = "17.6-1"
$PgUrl = "https://get.enterprisedb.com/postgresql/postgresql-$PgVersion-windows-x64-binaries.zip"
$PostgisFile = "postgis-bundle-pg17-3.6.2x64.zip"
$PostgisUrl = "https://download.osgeo.org/postgis/windows/pg17/$PostgisFile"

$Port = 5433
$DbUser = "grunt"
$DbPass = "grunt"
$DbName = "grunt"
$SuperUser = "postgres"

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg) { Write-Host "    $msg" -ForegroundColor Green }

function Get-Archive($url, $dest) {
    if (Test-Path $dest) {
        Write-Ok "jest juz $(Split-Path -Leaf $dest)"
        return
    }
    Write-Step "pobieram $(Split-Path -Leaf $dest)"
    Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
    Write-Ok "$([math]::Round((Get-Item $dest).Length / 1MB, 1)) MB"
}

function Install-Binaries {
    New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null
    $pgZip = Join-Path $ToolsDir "postgresql.zip"
    $gisZip = Join-Path $ToolsDir $PostgisFile

    if (-not (Test-Path (Join-Path $PgBin "postgres.exe"))) {
        Get-Archive $PgUrl $pgZip
        Write-Step "rozpakowuje PostgreSQL"
        Expand-Archive -Path $pgZip -DestinationPath $ToolsDir -Force
        Write-Ok "PostgreSQL w $PgRoot"
    }
    else {
        Write-Ok "binaria PostgreSQL juz sa"
    }

    if (-not (Test-Path (Join-Path $PgRoot "share\extension\postgis.control"))) {
        Get-Archive $PostgisUrl $gisZip
        Write-Step "rozpakowuje PostGIS"
        $tmp = Join-Path $ToolsDir "postgis_tmp"
        if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
        Expand-Archive -Path $gisZip -DestinationPath $tmp -Force
        # bundle ma jeden katalog nadrzedny; kopiujemy jego zawartosc na PgRoot
        $inner = Get-ChildItem $tmp -Directory | Select-Object -First 1
        Copy-Item -Path (Join-Path $inner.FullName "*") -Destination $PgRoot -Recurse -Force
        Remove-Item $tmp -Recurse -Force
        Write-Ok "PostGIS wgrany do instalacji PostgreSQL"
    }
    else {
        Write-Ok "PostGIS juz jest"
    }
}

function Test-ServerRunning {
    & (Join-Path $PgBin "pg_isready.exe") -h localhost -p $Port -q 2>$null
    return ($LASTEXITCODE -eq 0)
}

function Start-Server {
    if (Test-ServerRunning) { Write-Ok "serwer juz dziala na porcie $Port"; return }
    Write-Step "startuje serwer na porcie $Port"
    & (Join-Path $PgBin "pg_ctl.exe") -D $PgData -l $LogFile -o "-p $Port -c listen_addresses=localhost" -w start
    if (-not (Test-ServerRunning)) { throw "serwer nie wstal, zajrzyj do $LogFile" }
    Write-Ok "dziala"
}

function Stop-Server {
    if (-not (Test-ServerRunning)) { Write-Ok "serwer nie dziala"; return }
    Write-Step "zatrzymuje serwer"
    & (Join-Path $PgBin "pg_ctl.exe") -D $PgData -m fast -w stop
    Write-Ok "zatrzymany"
}

function Invoke-Psql($database, $sql, $asUser = $SuperUser) {
    $env:PGPASSWORD = $DbPass
    $out = & (Join-Path $PgBin "psql.exe") -h localhost -p $Port -U $asUser -d $database -v ON_ERROR_STOP=1 -t -A -c $sql
    if ($LASTEXITCODE -ne 0) { throw "psql zwrocil blad dla: $sql" }
    return $out
}

function Initialize-Cluster {
    if (Test-Path (Join-Path $PgData "PG_VERSION")) { Write-Ok "klaster juz zainicjowany"; return }
    Write-Step "initdb"
    New-Item -ItemType Directory -Force -Path $PgData | Out-Null
    # celowo w tools/, a nie w $env:TEMP: sciezka 8.3 (HPOMEN~1) potrafi rozjechac sie
    # miedzy natywnym initdb a cmdletami PowerShella
    $pwFile = Join-Path $ToolsDir "initdb_pw.txt"
    Set-Content -Path $pwFile -Value $DbPass -NoNewline -Encoding ascii
    & (Join-Path $PgBin "initdb.exe") -D $PgData -U $SuperUser --pwfile=$pwFile -A scram-sha-256 -E UTF8 --locale=C
    Remove-Item $pwFile -Force -ErrorAction SilentlyContinue
    Write-Ok "klaster w $PgData"
}

function Initialize-Database {
    $exists = Invoke-Psql "postgres" "SELECT 1 FROM pg_roles WHERE rolname='$DbUser'"
    if (-not $exists) {
        Write-Step "tworze role $DbUser"
        # SUPERUSER jest potrzebny do CREATE EXTENSION postgis w migracji 001
        Invoke-Psql "postgres" "CREATE ROLE $DbUser LOGIN PASSWORD '$DbPass' SUPERUSER" | Out-Null
    }
    $dbExists = Invoke-Psql "postgres" "SELECT 1 FROM pg_database WHERE datname='$DbName'"
    if (-not $dbExists) {
        Write-Step "tworze baze $DbName"
        Invoke-Psql "postgres" "CREATE DATABASE $DbName OWNER $DbUser" | Out-Null
    }
    $ver = Invoke-Psql $DbName "SELECT default_version FROM pg_available_extensions WHERE name='postgis'"
    Write-Ok "PostGIS dostepny w wersji: $ver"
}

switch ($Command) {
    "setup" {
        Install-Binaries
        Initialize-Cluster
        Start-Server
        Initialize-Database
        Write-Host ""
        Write-Ok "gotowe. DATABASE_URL=postgresql+psycopg://$DbUser`:$DbPass@localhost:$Port/$DbName"
        Write-Ok "nastepny krok: uv run alembic upgrade head"
    }
    "start" { Start-Server }
    "stop" { Stop-Server }
    "status" {
        if (Test-ServerRunning) { Write-Ok "dziala na porcie $Port" } else { Write-Host "    nie dziala" -ForegroundColor Yellow }
    }
    "psql" {
        $env:PGPASSWORD = $DbPass
        & (Join-Path $PgBin "psql.exe") -h localhost -p $Port -U $DbUser -d $DbName
    }
    "reset" {
        Stop-Server
        Write-Step "usuwam $PgData"
        if (Test-Path $PgData) { Remove-Item $PgData -Recurse -Force }
        Initialize-Cluster
        Start-Server
        Initialize-Database
        Write-Ok "baza postawiona od zera"
    }
}
