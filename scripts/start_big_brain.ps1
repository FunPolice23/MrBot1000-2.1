#Requires -Version 5.1
<#
.SYNOPSIS
    Start Big Brain llama-server on 5060 Ti only.
.DESCRIPTION
    Launches llama-server with GPU isolation.
    Uses only the 5060 Ti (device 0) with RAM overflow.
    Port: 1234.
#>

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Big Brain llama-server" -ForegroundColor Cyan
Write-Host "  GPU: 5060 Ti (16 GB) + RAM" -ForegroundColor Yellow
Write-Host "  Port: 1234" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Cyan

# Use the Clang llama-server build (has sm_75 kernels for the 1660 Super; the
# WindowsApps `llama.exe` MSVC build cannot run the 1660 Super at all) and the
# device by NAME (CUDA0/CUDA1) — this llama.cpp line rejects numeric --device.
& "D:\llama.cpp\llama-server.exe" `
    --host 127.0.0.1 `
    --port 1234 `
    --device CUDA0 `
    --ctx-size 32768 `
    --n-gpu-layers all `
    --split-mode none `
    --model "D:/LMStudio/models/lmstudio-community/Qwen3.8-27B-GGUF/Qwen3.8-27B-Q4_K_M.gguf"
