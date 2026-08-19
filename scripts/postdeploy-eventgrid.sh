#!/usr/bin/env sh
set -eu

for command in az azd; do
  command -v "$command" >/dev/null 2>&1 || {
    printf '%s\n' "Required command '$command' is not available." >&2
    exit 1
  }
done

resource_group=''
subscription_id=''
function_app_name=''
system_topic_name=''
event_subscription_name=''
container_name=''

if ! environment_values="$(azd env get-values)"; then
  printf '%s\n' 'Unable to load the AZD environment values.' >&2
  exit 1
fi

while IFS='=' read -r key value; do
  value=${value#\"}
  value=${value%\"}
  case "$key" in
    AZURE_RESOURCE_GROUP) resource_group=$value ;;
    AZURE_SUBSCRIPTION_ID) subscription_id=$value ;;
    AZURE_FUNCTION_APP_NAME) function_app_name=$value ;;
    EVENT_GRID_SYSTEM_TOPIC_NAME) system_topic_name=$value ;;
    EVENT_GRID_SUBSCRIPTION_NAME) event_subscription_name=$value ;;
    SOURCE_CONTAINER_NAME) container_name=$value ;;
  esac
done <<EOF
$environment_values
EOF

: "${resource_group:?Required AZD environment value AZURE_RESOURCE_GROUP is not set.}"
: "${subscription_id:?Required AZD environment value AZURE_SUBSCRIPTION_ID is not set.}"
: "${function_app_name:?Required AZD environment value AZURE_FUNCTION_APP_NAME is not set.}"
: "${system_topic_name:?Required AZD environment value EVENT_GRID_SYSTEM_TOPIC_NAME is not set.}"
: "${event_subscription_name:?Required AZD environment value EVENT_GRID_SUBSCRIPTION_NAME is not set.}"
: "${container_name:?Required AZD environment value SOURCE_CONTAINER_NAME is not set.}"

function_resource_id="/subscriptions/${subscription_id}/resourceGroups/${resource_group}/providers/Microsoft.Web/sites/${function_app_name}/functions/process_blob_upload"
subject_prefix="/blobServices/default/containers/${container_name}/blobs/"

if ! existing_subscription="$(az eventgrid system-topic event-subscription list \
  --resource-group "$resource_group" \
  --subscription "$subscription_id" \
  --system-topic-name "$system_topic_name" \
  --query "[?name=='${event_subscription_name}'].name | [0]" \
  --output tsv \
  --only-show-errors)"; then
  printf '%s\n' 'Unable to list Event Grid subscriptions.' >&2
  exit 1
fi

if [ -n "$existing_subscription" ]; then
  subscription_command='update'
else
  subscription_command='create'
fi

if ! az eventgrid system-topic event-subscription "$subscription_command" \
  --name "$event_subscription_name" \
  --resource-group "$resource_group" \
  --subscription "$subscription_id" \
  --system-topic-name "$system_topic_name" \
  --endpoint-type azurefunction \
  --endpoint "$function_resource_id" \
  --included-event-types 'Microsoft.Storage.BlobCreated' \
  --subject-begins-with "$subject_prefix" \
  --subject-ends-with '.json.log.gz' \
  --output none \
  --only-show-errors; then
  printf '%s\n' 'Unable to create or update the Event Grid Azure Function subscription.' >&2
  exit 1
fi

printf '%s\n' 'Event Grid Azure Function subscription configured.'
