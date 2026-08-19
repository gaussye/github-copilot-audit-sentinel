param environmentName string
param location string
param sourceStorageAccountResourceId string
param sourceBlobServiceUri string
param sourceContainerName string
param processorServiceName string = ''
param applicationInsightsName string = ''
param appServicePlanName string = ''
param logAnalyticsName string = ''
param runtimeStorageAccountName string = ''

var abbrs = loadJsonContent('./abbreviations.json')
var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))
var tags = {
  'azd-env-name': environmentName
  workload: 'github-copilot-audit'
}
var functionAppName = !empty(processorServiceName) ? processorServiceName : '${abbrs.webSitesFunctions}${resourceToken}'
var planName = !empty(appServicePlanName) ? appServicePlanName : '${abbrs.webServerFarms}${resourceToken}'
var workspaceName = !empty(logAnalyticsName) ? logAnalyticsName : '${abbrs.operationalInsightsWorkspaces}copilotaudit${resourceToken}'
var insightsName = !empty(applicationInsightsName) ? applicationInsightsName : '${abbrs.insightsComponents}copilotaudit${resourceToken}'
var storageName = !empty(runtimeStorageAccountName) ? runtimeStorageAccountName : '${abbrs.storageStorageAccounts}${resourceToken}'
var deploymentStorageContainerName = 'app-package-${take(functionAppName, 32)}-${take(resourceToken, 7)}'
var dcrName = 'dcr-copilot-audit-${take(resourceToken, 12)}'
var systemTopicName = 'egst-copilot-audit-${take(resourceToken, 12)}'
var streamName = 'Custom-GitHubCopilotAudit_CL'
var workspaceResourceId = resourceId('Microsoft.OperationalInsights/workspaces', workspaceName)

// Preserve the official template's FC1 plan and AVM resource composition.
module appServicePlan 'br/public:avm/res/web/serverfarm:0.1.1' = {
  name: 'appserviceplan'
  params: {
    name: planName
    sku: {
      name: 'FC1'
      tier: 'FlexConsumption'
    }
    reserved: true
    location: location
    tags: tags
  }
}

module logAnalytics 'br/public:avm/res/operational-insights/workspace:0.11.1' = {
  name: 'dedicated-loganalytics'
  params: {
    name: workspaceName
    location: location
    tags: tags
    dataRetention: 30
  }
}

module monitoring 'br/public:avm/res/insights/component:0.6.0' = {
  name: 'appinsights'
  params: {
    name: insightsName
    location: location
    tags: tags
    workspaceResourceId: workspaceResourceId
    disableLocalAuth: true
  }
  dependsOn: [
    logAnalytics
  ]
}

module runtimeStorage 'br/public:avm/res/storage/storage-account:0.8.3' = {
  name: 'runtime-storage'
  params: {
    name: storageName
    location: location
    tags: tags
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    minimumTlsVersion: 'TLS1_2'
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Allow'
      bypass: 'AzureServices'
    }
    blobServices: {
      containers: [
        {
          name: deploymentStorageContainerName
        }
      ]
    }
  }
}

resource auditTable 'Microsoft.OperationalInsights/workspaces/tables@2022-10-01' = {
  name: '${workspaceName}/GitHubCopilotAudit_CL'
  properties: {
    plan: 'Analytics'
    schema: {
      name: 'GitHubCopilotAudit_CL'
      columns: [
        { name: 'TimeGenerated', type: 'datetime' }
        { name: 'EventId', type: 'string' }
        { name: 'GitHubRequestId', type: 'string' }
        { name: 'UserId', type: 'string' }
        { name: 'EnterpriseId', type: 'string' }
        { name: 'EventType', type: 'string' }
        { name: 'Endpoint', type: 'string' }
        { name: 'Model', type: 'string' }
        { name: 'InteractionType', type: 'string' }
        { name: 'ToolNames', type: 'string' }
        { name: 'StatusCode', type: 'int' }
        { name: 'SourceBlob', type: 'string' }
        { name: 'SourceRecordIndex', type: 'int' }
        { name: 'PayloadBytes', type: 'long' }
        { name: 'ParseStatus', type: 'string' }
        { name: 'IngestedAt', type: 'datetime' }
        { name: 'RawEvent', type: 'string' }
        { name: 'RawEncoding', type: 'string' }
        { name: 'RawContentHash', type: 'string' }
        { name: 'RawChunkIndex', type: 'int' }
        { name: 'RawChunkCount', type: 'int' }
      ]
    }
  }
  dependsOn: [
    logAnalytics
  ]
}

// API 2024-03-11 creates a Direct DCR-owned logs ingestion endpoint. A DCE is
// only needed for private-link ingestion, which this public-endpoint architecture does not use.
resource dataCollectionRule 'Microsoft.Insights/dataCollectionRules@2024-03-11' = {
  name: dcrName
  location: location
  kind: 'Direct'
  tags: tags
  properties: {
    streamDeclarations: {
      '${streamName}': {
        columns: [
          { name: 'TimeGenerated', type: 'datetime' }
          { name: 'EventId', type: 'string' }
          { name: 'GitHubRequestId', type: 'string' }
          { name: 'UserId', type: 'string' }
          { name: 'EnterpriseId', type: 'string' }
          { name: 'EventType', type: 'string' }
          { name: 'Endpoint', type: 'string' }
          { name: 'Model', type: 'string' }
          { name: 'InteractionType', type: 'string' }
          { name: 'ToolNames', type: 'string' }
          { name: 'StatusCode', type: 'int' }
          { name: 'SourceBlob', type: 'string' }
          { name: 'SourceRecordIndex', type: 'int' }
          { name: 'PayloadBytes', type: 'long' }
          { name: 'ParseStatus', type: 'string' }
          { name: 'IngestedAt', type: 'datetime' }
          { name: 'RawEvent', type: 'string' }
          { name: 'RawEncoding', type: 'string' }
          { name: 'RawContentHash', type: 'string' }
          { name: 'RawChunkIndex', type: 'int' }
          { name: 'RawChunkCount', type: 'int' }
        ]
      }
    }
    destinations: {
      logAnalytics: [
        {
          name: 'auditWorkspace'
          workspaceResourceId: workspaceResourceId
        }
      ]
    }
    dataFlows: [
      {
        streams: [
          streamName
        ]
        destinations: [
          'auditWorkspace'
        ]
        outputStream: streamName
        transformKql: '''
          source
          | project
              TimeGenerated = todatetime(TimeGenerated),
              EventId = tostring(EventId),
              GitHubRequestId = tostring(GitHubRequestId),
              UserId = tostring(UserId),
              EnterpriseId = tostring(EnterpriseId),
              EventType = tostring(EventType),
              Endpoint = tostring(Endpoint),
              Model = tostring(Model),
              InteractionType = tostring(InteractionType),
              ToolNames = tostring(ToolNames),
              StatusCode = toint(StatusCode),
              SourceBlob = tostring(SourceBlob),
              SourceRecordIndex = toint(SourceRecordIndex),
              PayloadBytes = tolong(PayloadBytes),
              ParseStatus = tostring(ParseStatus),
              IngestedAt = todatetime(IngestedAt),
              RawEvent = tostring(RawEvent),
              RawEncoding = tostring(RawEncoding),
              RawContentHash = tostring(RawContentHash),
              RawChunkIndex = toint(RawChunkIndex),
              RawChunkCount = toint(RawChunkCount)
          '''
      }
    ]
  }
  dependsOn: [
    auditTable
  ]
}

resource sentinel 'Microsoft.OperationsManagement/solutions@2015-11-01-preview' = {
  name: 'SecurityInsights(${workspaceName})'
  location: location
  plan: {
    name: 'SecurityInsights(${workspaceName})'
    product: 'OMSGallery/SecurityInsights'
    publisher: 'Microsoft'
    promotionCode: ''
  }
  properties: {
    workspaceResourceId: workspaceResourceId
  }
  dependsOn: [
    logAnalytics
  ]
}

resource workbook 'Microsoft.Insights/workbooks@2023-06-01' = {
  name: guid(resourceGroup().id, workspaceName, 'GitHub Copilot Audit Sentinel')
  location: location
  kind: 'shared'
  properties: {
    displayName: 'GitHub Copilot Audit Sentinel'
    serializedData: loadTextContent('./workbook.json')
    version: '1.0'
    sourceId: workspaceResourceId
    category: 'sentinel'
  }
  dependsOn: [
    sentinel
    auditTable
  ]
}

module processor 'app/processor.bicep' = {
  name: 'processor'
  params: {
    name: functionAppName
    location: location
    tags: tags
    applicationInsightsName: insightsName
    appServicePlanId: appServicePlan.outputs.resourceId
    runtimeName: 'python'
    runtimeVersion: '3.12'
    storageAccountName: storageName
    deploymentStorageContainerName: deploymentStorageContainerName
    sourceBlobServiceUri: sourceBlobServiceUri
    logsIngestionEndpoint: dataCollectionRule.properties.endpoints.logsIngestion
    dcrImmutableId: dataCollectionRule.properties.immutableId
    dcrStreamName: streamName
  }
  dependsOn: [
    monitoring
    runtimeStorage
  ]
}

module rbac 'app/rbac.bicep' = {
  name: 'rbac-assignments'
  params: {
    runtimeStorageAccountName: storageName
    appInsightsName: insightsName
    dataCollectionRuleName: dcrName
    managedIdentityPrincipalId: processor.outputs.SERVICE_PROCESSOR_IDENTITY_PRINCIPAL_ID
  }
  dependsOn: [
    monitoring
    runtimeStorage
  ]
}

resource blobCreatedSystemTopic 'Microsoft.EventGrid/systemTopics@2022-06-15' = {
  name: systemTopicName
  location: location
  tags: tags
  properties: {
    source: sourceStorageAccountResourceId
    topicType: 'Microsoft.Storage.StorageAccounts'
  }
}

output functionAppName string = processor.outputs.SERVICE_PROCESSOR_NAME
output functionPrincipalId string = processor.outputs.SERVICE_PROCESSOR_IDENTITY_PRINCIPAL_ID
output processorBaseUrl string = processor.outputs.SERVICE_PROCESSOR_BASE_URL
output logAnalyticsWorkspaceName string = workspaceName
output logsIngestionEndpoint string = dataCollectionRule.properties.endpoints.logsIngestion
output dataCollectionRuleImmutableId string = dataCollectionRule.properties.immutableId
output dataCollectionStreamName string = streamName
output eventGridSystemTopicName string = blobCreatedSystemTopic.name
output sourceContainerName string = sourceContainerName
