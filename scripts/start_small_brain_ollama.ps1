#Requires -Version 5.1
<#
.SYNOPSIS
    Start Small Brain Ollama on the 1660 Super.
.DESCRIPTION
    Canonical Ollama launcher for the Small Brain role. The BAT file is only
    a compatibility wrapper for users who launch it from Explorer or cmd.exe.
#>

$env:CUDA_VISIBLE_DEVICES = "1"
$env:OLLAMA_HOST = "127.0.0.1:11435"
$env:OLLAMA_KEEP_ALIVE = "5m"
$env:OLLAMA_MAX_LOADED_MODELS = "1"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Small Brain Ollama" -ForegroundColor Cyan
Write-Host "  GPU: 1660 Super (6 GB)" -ForegroundColor Yellow
Write-Host "  Port: 11435" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Cyan

& ollama serve @args
exit $LASTEXITCODE
