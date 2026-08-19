from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize(
    "relative_path",
    ["scripts/postdeploy-eventgrid.ps1", "scripts/postdeploy-eventgrid.sh"],
)
def test_event_grid_hooks_use_secretless_native_function_endpoint(
    relative_path: str,
) -> None:
    content = (ROOT / relative_path).read_text()

    assert "azurefunction" in content
    assert "/functions/process_blob_upload" in content
    assert "Microsoft.Storage.BlobCreated" in content
    assert ".json.log.gz" in content
    assert "functionapp keys" not in content
    assert "blobs_extension" not in content
    assert "/runtime/webhooks/blobs" not in content
    assert "endpoint-type webhook" not in content


def test_powershell_hook_checks_every_native_exit_code() -> None:
    content = (ROOT / "scripts/postdeploy-eventgrid.ps1").read_text()

    assert "function Invoke-CheckedNativeCommand" in content
    assert "$exitCode = $LASTEXITCODE" in content
    assert "if ($exitCode -ne 0)" in content
    assert "throw" in content
    assert "event-subscription', 'list'" in content


def test_shell_hook_guards_list_and_configuration_failures() -> None:
    content = (ROOT / "scripts/postdeploy-eventgrid.sh").read_text()

    assert 'if ! existing_subscription="$(az eventgrid' in content
    assert 'if ! az eventgrid system-topic event-subscription "$subscription_command"' in content
    assert "exit 1" in content
