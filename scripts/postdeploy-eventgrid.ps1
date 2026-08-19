Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

foreach ($tool in @('az', 'azd')) {
  if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
    throw "Required command '$tool' is not available."
  }
}

function Invoke-CheckedNativeCommand {
  param(
    [Parameter(Mandatory)]
    [string] $Command,
    [string[]] $Arguments = @()
  )

  $commandOutput = & $Command @Arguments
  $exitCode = $LASTEXITCODE
  if ($exitCode -ne 0) {
    throw "Command '$Command' failed with exit code $exitCode."
  }

  return $commandOutput
}

$environmentValues = @{}
$environmentLines = @(Invoke-CheckedNativeCommand -Command 'azd' -Arguments @('env', 'get-values'))
$environmentLines | ForEach-Object {
  if ($_ -match '^(?<key>[^=]+)=(?<value>.*)$') {
    $environmentValues[$matches.key] = $matches.value -replace '^"|"$'
  }
}

function Get-RequiredEnvironmentValue([string]$Name) {
  if (-not $environmentValues.ContainsKey($Name) -or [string]::IsNullOrWhiteSpace($environmentValues[$Name])) {
    throw "Required AZD environment value '$Name' is not set."
  }

  return $environmentValues[$Name]
}

$resourceGroup = Get-RequiredEnvironmentValue 'AZURE_RESOURCE_GROUP'
$subscriptionId = Get-RequiredEnvironmentValue 'AZURE_SUBSCRIPTION_ID'
$functionAppName = Get-RequiredEnvironmentValue 'AZURE_FUNCTION_APP_NAME'
$systemTopicName = Get-RequiredEnvironmentValue 'EVENT_GRID_SYSTEM_TOPIC_NAME'
$eventSubscriptionName = Get-RequiredEnvironmentValue 'EVENT_GRID_SUBSCRIPTION_NAME'
$containerName = Get-RequiredEnvironmentValue 'SOURCE_CONTAINER_NAME'
$functionResourceId = "/subscriptions/${subscriptionId}/resourceGroups/${resourceGroup}/providers/Microsoft.Web/sites/${functionAppName}/functions/process_blob_upload"
$subjectPrefix = "/blobServices/default/containers/${containerName}/blobs/"

$existingSubscription = (
  Invoke-CheckedNativeCommand -Command 'az' -Arguments @(
    'eventgrid', 'system-topic', 'event-subscription', 'list',
    '--resource-group', $resourceGroup,
    '--subscription', $subscriptionId,
    '--system-topic-name', $systemTopicName,
    '--query', "[?name=='${eventSubscriptionName}'].name | [0]",
    '--output', 'tsv',
    '--only-show-errors'
  )
) -join ''
$subscriptionCommand = if ([string]::IsNullOrWhiteSpace($existingSubscription)) { 'create' } else { 'update' }

Invoke-CheckedNativeCommand -Command 'az' -Arguments @(
  'eventgrid', 'system-topic', 'event-subscription', $subscriptionCommand,
  '--name', $eventSubscriptionName,
  '--resource-group', $resourceGroup,
  '--subscription', $subscriptionId,
  '--system-topic-name', $systemTopicName,
  '--endpoint-type', 'azurefunction',
  '--endpoint', $functionResourceId,
  '--included-event-types', 'Microsoft.Storage.BlobCreated',
  '--subject-begins-with', $subjectPrefix,
  '--subject-ends-with', '.json.log.gz',
  '--output', 'none',
  '--only-show-errors'
) | Out-Null

Write-Output 'Event Grid Azure Function subscription configured.'
