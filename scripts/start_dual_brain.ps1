#Requires -Version 5.1
<#
.SYNOPSIS
    Start LM Studio for dual-brain GPU isolation.
.DESCRIPTION
    Launches LM Studio Bionic with both GPUs visible.
    GPU isolation is configured in LM Studio's GUI per-model:
    
    - Big Brain model (14B-27B): GPU 0 = 5060 Ti enabled, GPU 1 = 1660S disabled
    - Small Brain model (3B-7B): GPU 0 = 5060Ti disabled, GPU 1 = 1660S enabled
    
    Setup:
    1. Open this script to launch LM Studio
    2. Load Big Brain model → Settings → GPU: 5060 Ti only
    3. Load Small Brain model → Settings → GPU: 1660 Super only
    4. Enable Local Server on port 1234
#>

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  LM Studio — Dual Brain GPU Isolated" -ForegroundColor Cyan
Write-Host "  GPU 0: RTX 5060 Ti (Big Brain)" -ForegroundColor Yellow
Write-Host "  GPU 1: GTX 1660 Super (Small Brain)" -ForegroundColor Yellow
Write-Host "  Port: 1234" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Cyan

& "D:\LMStudio\Bionic\Bionic.exe"
