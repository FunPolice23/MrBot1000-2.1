#Requires -Version 5.1
<#
.SYNOPSIS
    Shared llama.cpp launcher for the MrBot1000 brain roles.
.DESCRIPTION
    Owns the common llama-server command construction. Role wrappers provide
    only the role name; explicit parameters and trailing arguments can override
    local defaults without duplicating launcher logic.
#>

param(
    [ValidateSet("Big", "Small")]
    [string]$Role = "Big",
    [string]$Model,
    [int]$Port = 0,
    [string]$Device,
    [int]$ContextSize = 32768,
    [string]$LlamaServerPath = "D:\llama.cpp\llama-server.exe",
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ExtraArgs
)

if ($Role -eq "Big") {
    $roleLabel = "Big Brain"
    if (-not $Model) { $Model = "D:/llama.cpp/models/Qwen3.8-27B-UD-IQ3_XXS.gguf" }
    if ($Port -eq 0) { $Port = 1234 }
    if (-not $Device) { $Device = "CUDA0" }
    $gpuLabel = "5060 Ti (16 GB)"
}
else {
    $roleLabel = "Small Brain"
    if (-not $Model) { $Model = "D:/llama.cpp/models/Qwen3.5-4B-UD-Q5_K_XL.gguf" }
    if ($Port -eq 0) { $Port = 1235 }
    if (-not $Device) { $Device = "CUDA1" }
    $gpuLabel = "1660 Super (6 GB)"
}

if (-not (Test-Path -LiteralPath $LlamaServerPath -PathType Leaf)) {
    Write-Error "llama-server was not found at: $LlamaServerPath"
    exit 1
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  $roleLabel llama.cpp server" -ForegroundColor Cyan
Write-Host "  GPU: $gpuLabel + RAM" -ForegroundColor Yellow
Write-Host "  Device: $Device" -ForegroundColor Yellow
Write-Host "  Port: $Port" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Cyan

$command = @(
    "--host", "127.0.0.1",
    "--port", "$Port",
    "--device", $Device,
    "--ctx-size", "$ContextSize",
    "--n-gpu-layers", "all",
    "--split-mode", "none",
    "--model", $Model
)
if ($ExtraArgs) {
    $command += $ExtraArgs
}

& $LlamaServerPath @command
exit $LASTEXITCODE
