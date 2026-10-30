// Infrastructure sketch for the claims intake platform.
// STATUS: written but NOT validated with `az bicep build` and NOT deployed.
// Resources: Log Analytics, Service Bus (queue with dead-lettering), Key Vault, Container Apps
// environment, and the API container app. The worker is a second container app with the same
// image and `python -m app.main worker` as its command (add it once the API app is confirmed).

targetScope = 'resourceGroup'

@description('Short prefix used in resource names, 3-8 lowercase letters.')
@minLength(3)
@maxLength(8)
param prefix string

param location string = resourceGroup().location

@description('Container image, for example myregistry.azurecr.io/claims-intake:1.')
param image string

@description('Set to anthropic, azure_openai or rule.')
param llmProvider string = 'rule'

var suffix = uniqueString(resourceGroup().id)

resource logs 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: '${prefix}-logs-${suffix}'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource bus 'Microsoft.ServiceBus/namespaces@2022-10-01-preview' = {
  name: '${prefix}-bus-${suffix}'
  location: location
  sku: { name: 'Standard', tier: 'Standard' }
}

resource casesQueue 'Microsoft.ServiceBus/namespaces/queues@2022-10-01-preview' = {
  parent: bus
  name: 'cases'
  properties: {
    maxDeliveryCount: 3                      // matches the worker: 3 attempts, then dead-letter
    deadLetteringOnMessageExpiration: true
    lockDuration: 'PT1M'
    defaultMessageTimeToLive: 'P1D'
  }
}

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: '${prefix}kv${take(suffix, 8)}'
  location: location
  properties: {
    sku: { family: 'A', name: 'standard' }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
  }
}

resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${prefix}-env'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

resource api 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${prefix}-api'
  location: location
  identity: { type: 'SystemAssigned' }      // grant it Key Vault Secrets User and Service Bus Data Receiver/Sender
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      ingress: { external: true, targetPort: 8000 }
      // API keys and the LLM key belong in Key Vault references; add them under `secrets`
      // with keyVaultUrl + identity before the first real deployment.
    }
    template: {
      containers: [
        {
          name: 'api'
          image: image
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            { name: 'LLM_PROVIDER', value: llmProvider }
            { name: 'SERVICEBUS_QUEUE', value: casesQueue.name }
          ]
          probes: [
            { type: 'Liveness', httpGet: { path: '/healthz', port: 8000 } }
          ]
        }
      ]
      scale: { minReplicas: 1, maxReplicas: 3 }
    }
  }
}

output apiFqdn string = api.properties.configuration.ingress.fqdn
output serviceBusNamespace string = bus.name
