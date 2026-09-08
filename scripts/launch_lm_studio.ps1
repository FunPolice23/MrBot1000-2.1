#Requires -Version 5.1
<#
.SYNOPSIS
    Launch LM Studio Bionic with 5060 Ti only (hides 1660 Super).
.DESCRIPTION
    Sets CUDA_VISIBLE_DEVICES=0 so LM Studio only sees the 5060 Ti.
    This leaves the 1660 Super free for Ollama Small Brain.
    
    Usage:
        .\scripts\launch_lm_studio.ps1
#>

$lmStudioPath = "D:\LMStudio\Bionic\LM Studio.exe"

if (-not (Test-Path $lmStudioPath)) {
    Write-Error "LM Studio not found at: $lmStudioPath"
    Write-Host "Update `$lmStudioPath in this script to match your installation." -ForegroundColor Yellow
    exit 1
}

Write-Host "Launching LM Studio with 5060 Ti only..." -ForegroundColor Cyan
Write-Host "GPU: CUDA_VISIBLE_DEVICES=0 (5060 Ti)" -ForegroundColor Yellow

$env:CUDA_VISIBLE_DEVICES = "0"
Start-Process $lmStudioPath

Write-Host "LM Studio launched. 1660 Super is free for Small Brain." -ForegroundColor Green
