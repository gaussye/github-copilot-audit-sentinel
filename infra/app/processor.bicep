param name string

@description('Primary location for the Flex Consumption Function App.')
param location string = resourceGroup().location

param tags object = {}
param applicationInsightsName string
param appServicePlanId string
param runtimeName string
param runtimeVersion string
param serviceName string = 'processor'
param storageAccountName string
param deploymentStorageContainerName string
param instanceMemoryMB int = 2048
param maximumInstanceCount int = 100
param sourceStorageAccountResourceId string
param sourceStorageAccountName string
param sourceContainerName string
param logsIngestionEndpoint string
param dcrImmutableId string
param dcrStreamName string

var kind = 'functionapp,linux'

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource applicationInsights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: applicationInsightsName
}

var appSettings = {
  AzureWebJobsStorage__credential: 'managedidentity'
  AzureWebJobsStorage__blobServiceUri: storageAccount.properties.primaryEndpoints.blob
  AzureWebJobsStorage__queueServiceUri: storageAccount.properties.primaryEndpoints.queue
  APPLICATIONINSIGHTS_AUTHENTICATION_STRING: 'Authorization=AAD'
  APPLICATIONINSIGHTS_CONNECTION_STRING: applicationInsights.properties.?ConnectionString ?? ''
  SOURCE_STORAGE_ACCOUNT_RESOURCE_ID: sourceStorageAccountResourceId
  SOURCE_STORAGE_ACCOUNT_NAME: sourceStorageAccountName
  SOURCE_CONTAINER_NAME: sourceContainerName
  LOGS_INGESTION_ENDPOINT: logsIngestionEndpoint
  DCR_IMMUTABLE_ID: dcrImmutableId
  DCR_STREAM_NAME: dcrStreamName
}

// This is the official template's Flex Consumption Function App pattern, adapted to use
// its required system-assigned identity for both deployment and runtime storage access.
module processor 'br/public:avm/res/web/site:0.15.1' = {
  name: '${serviceName}-flex-consumption'
  params: {
    kind: kind
    name: name
    location: location
    tags: union(tags, { 'azd-service-name': serviceName })
    serverFarmResourceId: appServicePlanId
    managedIdentities: {
      systemAssigned: true
    }
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${storageAccount.properties.primaryEndpoints.blob}${deploymentStorageContainerName}'
          authentication: {
            type: 'SystemAssignedIdentity'
          }
        }
      }
      scaleAndConcurrency: {
        instanceMemoryMB: instanceMemoryMB
        maximumInstanceCount: maximumInstanceCount
      }
      runtime: {
        name: runtimeName
        version: runtimeVersion
      }
    }
    siteConfig: {
      alwaysOn: false
    }
    appSettingsKeyValuePairs: appSettings
  }
}

output SERVICE_PROCESSOR_NAME string = processor.outputs.name
output SERVICE_PROCESSOR_ID string = processor.outputs.resourceId
output SERVICE_PROCESSOR_IDENTITY_PRINCIPAL_ID string = processor.outputs.?systemAssignedMIPrincipalId ?? ''
output SERVICE_PROCESSOR_BASE_URL string = 'https://${processor.outputs.defaultHostname}'
