param sourceStorageAccountName string
param sourceContainerName string
param managedIdentityPrincipalId string
param roleDefinitionSubscriptionId string

var storageBlobDataReaderRoleDefinitionId = '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'

resource sourceStorageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: sourceStorageAccountName
}

resource sourceBlobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' existing = {
  parent: sourceStorageAccount
  name: 'default'
}

resource sourceContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' existing = {
  parent: sourceBlobService
  name: sourceContainerName
}

resource sourceContainerReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(sourceContainer.id, managedIdentityPrincipalId, storageBlobDataReaderRoleDefinitionId)
  scope: sourceContainer
  properties: {
    roleDefinitionId: subscriptionResourceId(roleDefinitionSubscriptionId, 'Microsoft.Authorization/roleDefinitions', storageBlobDataReaderRoleDefinitionId)
    principalId: managedIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}
