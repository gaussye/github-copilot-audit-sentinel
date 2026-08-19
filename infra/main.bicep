targetScope = 'subscription'

@minLength(1)
@maxLength(64)
@description('The AZD environment name used to generate unique resource names.')
param environmentName string

@description('Primary location for all new resources.')
param location string = 'westus2'

@description('Existing resource group that hosts the source storage account and new resources.')
param resourceGroupName string = 'aks-test'

@description('Subscription containing the existing source storage account.')
param sourceSubscriptionId string = '3456866f-6478-471f-8d59-a29a335d797a'

@description('Resource group containing the existing source storage account.')
param sourceResourceGroupName string = 'aks-test'

@description('Existing account that receives GitHub Copilot audit logs.')
param sourceStorageAccountName string = 'ypycopilottest'

@description('Existing blob container that receives GitHub Copilot audit logs.')
param sourceContainerName string = 'github-copilot-audit-log'

param processorServiceName string = ''
param applicationInsightsName string = ''
param appServicePlanName string = ''
param logAnalyticsName string = ''
param runtimeStorageAccountName string = ''

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' existing = {
  name: resourceGroupName
}

resource sourceResourceGroup 'Microsoft.Resources/resourceGroups@2024-03-01' existing = {
  scope: subscription(sourceSubscriptionId)
  name: sourceResourceGroupName
}

resource sourceStorageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  scope: sourceResourceGroup
  name: sourceStorageAccountName
}

module infrastructure 'resources.bicep' = {
  name: 'github-copilot-audit-infrastructure'
  scope: rg
  params: {
    environmentName: environmentName
    location: location
    sourceStorageAccountResourceId: sourceStorageAccount.id
    sourceBlobServiceUri: sourceStorageAccount.properties.primaryEndpoints.blob
    sourceContainerName: sourceContainerName
    processorServiceName: processorServiceName
    applicationInsightsName: applicationInsightsName
    appServicePlanName: appServicePlanName
    logAnalyticsName: logAnalyticsName
    runtimeStorageAccountName: runtimeStorageAccountName
  }
}

module sourceContainerRbac 'source-rbac.bicep' = {
  name: 'source-container-reader-rbac'
  scope: sourceResourceGroup
  params: {
    sourceStorageAccountName: sourceStorageAccountName
    sourceContainerName: sourceContainerName
    managedIdentityPrincipalId: infrastructure.outputs.functionPrincipalId
    roleDefinitionSubscriptionId: sourceSubscriptionId
  }
}

output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_LOCATION string = location
output AZURE_SUBSCRIPTION_ID string = subscription().subscriptionId
output AZURE_FUNCTION_APP_NAME string = infrastructure.outputs.functionAppName
output SERVICE_PROCESSOR_BASE_URL string = infrastructure.outputs.processorBaseUrl
output LOG_ANALYTICS_WORKSPACE_NAME string = infrastructure.outputs.logAnalyticsWorkspaceName
output LOGS_INGESTION_ENDPOINT string = infrastructure.outputs.logsIngestionEndpoint
output DATA_COLLECTION_RULE_IMMUTABLE_ID string = infrastructure.outputs.dataCollectionRuleImmutableId
output DATA_COLLECTION_STREAM_NAME string = infrastructure.outputs.dataCollectionStreamName
output EVENT_GRID_SYSTEM_TOPIC_NAME string = infrastructure.outputs.eventGridSystemTopicName
output SOURCE_CONTAINER_NAME string = infrastructure.outputs.sourceContainerName
