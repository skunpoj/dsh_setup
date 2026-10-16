$ErrorActionPreference = 'Stop'

$namespace = if ($env:DSH_TEST_NAMESPACE) { $env:DSH_TEST_NAMESPACE } else { 'llm' }
$manifest = Join-Path $PSScriptRoot '..\k8s\dsh-egress-policies.yaml'
$offlinePod = 'dsh-egress-offline-canary'
$onlinePod = 'dsh-egress-online-canary'

function Invoke-Probe([string]$Pod, [string]$Url) {
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & kubectl exec -n $namespace $Pod -- curl -k -sS --connect-timeout 5 --max-time 10 -o /dev/null -w '%{http_code}' $Url 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
    return [pscustomobject]@{ ExitCode = $exitCode; Output = ($output -join ' ') }
}

try {
    # Tests must not rewrite Production policy. Use the deployed DNS boundary.
    $resolver = kubectl -n $namespace get service dsh-internal-dns -o jsonpath='{.spec.clusterIP}'
    if ($LASTEXITCODE -ne 0 -or -not $resolver) { throw 'Reviewed internal DNS service required' }
    @"
apiVersion: v1
kind: Pod
metadata:
  name: $offlinePod
  namespace: $namespace
  labels:
    app: dsh-egress-canary
    dsh.bot.or.th/egress-mode: offline
spec:
  restartPolicy: Never
  automountServiceAccountToken: false
  dnsPolicy: None
  dnsConfig:
    nameservers: ["$resolver"]
  containers:
    - name: curl
      image: curlimages/curl:8.12.1
      command: ["sh", "-c", "sleep 900"]
---
apiVersion: v1
kind: Pod
metadata:
  name: $onlinePod
  namespace: $namespace
  labels:
    app: dsh-egress-canary
    dsh.bot.or.th/egress-mode: online
spec:
  restartPolicy: Never
  automountServiceAccountToken: false
  containers:
    - name: curl
      image: curlimages/curl:8.12.1
      command: ["sh", "-c", "sleep 900"]
"@ | kubectl apply -f - | Out-Null

    kubectl wait -n $namespace --for=condition=Ready "pod/$offlinePod" "pod/$onlinePod" --timeout=180s | Out-Null

    $offlinePublic = Invoke-Probe $offlinePod 'https://github.com'
    $offlineModel = Invoke-Probe $offlinePod 'http://litellm.llm.svc.cluster.local:4000/health/liveliness'
    $onlinePublic = Invoke-Probe $onlinePod 'https://github.com'

    if ($offlinePublic.ExitCode -eq 0) { throw "Offline pod unexpectedly reached GitHub: $($offlinePublic.Output)" }
    if ($offlineModel.ExitCode -ne 0 -or $offlineModel.Output -notmatch '200') { throw "Offline pod could not reach LiteLLM: $($offlineModel.Output)" }
    if ($onlinePublic.ExitCode -ne 0 -or $onlinePublic.Output -notmatch '200') { throw "Online pod could not reach GitHub: $($onlinePublic.Output)" }

    Write-Output 'PASS: offline public egress blocked; offline LiteLLM allowed; online public egress allowed.'
}
finally {
    kubectl delete pod -n $namespace $offlinePod $onlinePod --ignore-not-found --wait=false | Out-Null
}
