$ErrorActionPreference = 'Stop'

$poolManifest = Join-Path $PSScriptRoot '..\k8s\dsh-environment-pools.yaml'
$gatewayManifest = Join-Path $PSScriptRoot '..\k8s\dsh-environment-gateway.yaml'
$promotionManifest = Join-Path $PSScriptRoot '..\k8s\dsh-package-promotion.yaml'
$migrationManifest = Join-Path $PSScriptRoot '..\k8s\dsh-auth-migration.yaml'
$pools = Get-Content -LiteralPath $poolManifest -Raw
$gateway = Get-Content -LiteralPath $gatewayManifest -Raw
$promotion = Get-Content -LiteralPath $promotionManifest -Raw
$migration = Get-Content -LiteralPath $migrationManifest -Raw
$dockerfile = Get-Content -LiteralPath (Join-Path $PSScriptRoot '..\Dockerfile') -Raw
$entrypoint = Get-Content -LiteralPath (Join-Path $PSScriptRoot '..\container\start-dsh.sh') -Raw

foreach ($required in @(
    'name: dsh-secure',
    'name: dsh-internet',
    'dsh.bot.or.th/egress-mode: offline',
    'dsh.bot.or.th/egress-mode: online',
    'runAsNonRoot: true',
    'claimName: dsh-secure-state',
    'claimName: dsh-internet-state',
    'claimName: dsh-internet-staging',
    'claimName: dsh-secure-workspace',
    'claimName: dsh-package-incoming',
    'claimName: dsh-package-approved',
    'claimName: dsh-secure-token',
    'claimName: dsh-internet-token'
)) {
    if (-not $pools.Contains($required)) { throw "Missing pool control: $required" }
}
if (($pools | Select-String -Pattern 'clusterIP: None' -AllMatches).Matches.Count -ne 2) {
    throw 'Both execution-pool Services must be headless for dynamic application routing.'
}

$internetDocument = @($pools -split '(?m)^---\s*$' | Where-Object { $_ -match 'kind: Deployment' -and $_ -match 'name: dsh-internet' })[0]
if ($internetDocument -match 'protected-workspace|claimName: dsh-secure-workspace') {
    throw 'Internet pool must not mount the protected workspace.'
}
if ($internetDocument -notmatch 'claimName: dsh-internet-token' -or $internetDocument -match 'claimName: dsh-secure-token') {
    throw 'Internet pool must receive only its own routing-token volume.'
}
if ($internetDocument -notmatch 'claimName: dsh-package-incoming' -or $internetDocument -match 'claimName: dsh-package-approved') {
    throw 'Internet pool must mount incoming packages and must not mount approved packages.'
}
$secureDocument = @($pools -split '(?m)^---\s*$' | Where-Object { $_ -match 'kind: Deployment' -and $_ -match 'name: dsh-secure' })[0]
if ($secureDocument -notmatch 'claimName: dsh-package-approved' -or $secureDocument -match 'claimName: dsh-package-incoming') {
    throw 'Secure pool must mount only the approved package cache read-only.'
}

foreach ($required in @(
    'name: dsh-environment-gateway',
    'DSH_OFFLINE_HOST',
    'DSH_ONLINE_HOST',
    'DSH_OFFLINE_TOKEN_FILE',
    'DSH_ONLINE_TOKEN_FILE',
    'claimName: dsh-secure-token',
    'claimName: dsh-internet-token',
    'claimName: dsh-auth-state',
    'runAsNonRoot: true'
)) {
    if (-not $gateway.Contains($required)) { throw "Missing gateway control: $required" }
}

foreach ($required in @('suspend: true', 'manifest.sha256', 'readOnly: true', 'claimName: dsh-package-incoming', 'claimName: dsh-package-approved')) {
    if (-not $promotion.Contains($required)) { throw "Missing package-promotion control: $required" }
}

foreach ($required in @('suspend: true', 'subPath: dsh', 'claimName: dsh-auth-state', 'claimName: dsh-secure-workspace', 'test -s /auth/.user_auth.json')) {
    if (-not $migration.Contains($required)) { throw "Missing auth-migration control: $required" }
}

foreach ($required in @('useradd --uid 10001', 'node /opt/dsh/scripts/configure_models.js', 'prepare-offline-deps.sh')) {
    if (-not $dockerfile.Contains($required)) { throw "Missing image control: $required" }
}
foreach ($required in @('PIP_NO_INDEX=1', 'PIP_FIND_LINKS=/packages/approved/python', 'npm_config_offline=true')) {
    if (-not $entrypoint.Contains($required)) { throw "Missing offline-runtime control: $required" }
}

Write-Output 'environment pool and gateway manifest controls passed'
