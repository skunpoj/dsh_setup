$ErrorActionPreference = 'Stop'

$poolManifest = Join-Path $PSScriptRoot '..\k8s\dsh-environment-pools.yaml'
$gatewayManifest = Join-Path $PSScriptRoot '..\k8s\dsh-environment-gateway.yaml'
$pools = Get-Content -LiteralPath $poolManifest -Raw
$gateway = Get-Content -LiteralPath $gatewayManifest -Raw

foreach ($required in @(
    'name: dsh-secure',
    'name: dsh-internet',
    'dsh.bot.or.th/egress-mode: offline',
    'dsh.bot.or.th/egress-mode: online',
    'runAsNonRoot: true',
    'claimName: dsh-secure-state',
    'claimName: dsh-internet-state',
    'claimName: dsh-internet-staging'
)) {
    if (-not $pools.Contains($required)) { throw "Missing pool control: $required" }
}
if (($pools | Select-String -Pattern 'clusterIP: None' -AllMatches).Matches.Count -ne 2) {
    throw 'Both execution-pool Services must be headless for dynamic application routing.'
}

$internetDocument = @($pools -split '(?m)^---\s*$' | Where-Object { $_ -match 'kind: Deployment' -and $_ -match 'name: dsh-internet' })[0]
if ($internetDocument -match 'protected-workspace|subPath: dsh\s') {
    throw 'Internet pool must not mount the protected workspace.'
}
if ($internetDocument -notmatch 'subPath: dsh-routing/tokens/internet') {
    throw 'Internet pool must receive only its own routing-token subpath.'
}

foreach ($required in @(
    'name: dsh-environment-gateway',
    'DSH_OFFLINE_HOST',
    'DSH_ONLINE_HOST',
    'DSH_OFFLINE_TOKEN_FILE',
    'DSH_ONLINE_TOKEN_FILE',
    'subPath: dsh-routing/tokens/secure',
    'subPath: dsh-routing/tokens/internet',
    'runAsNonRoot: true'
)) {
    if (-not $gateway.Contains($required)) { throw "Missing gateway control: $required" }
}

Write-Output 'environment pool and gateway manifest controls passed'
