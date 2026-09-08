#Requires -Version 5.1
<#
.SYNOPSIS
    Start Small Brain llama-server on 1660 Super only.
.DESCRIPTION
    Launches llama-server with GPU isolation.
    Uses only the 1660 Super (device 1) with RAM overflow.
    Port: 1235.
#>

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Small Brain llama-server" -ForegroundColor Cyan
Write-Host "  GPU: 1660 Super (6 GB) + RAM" -ForegroundColor Yellow
Write-Host "  Port: 1235" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Cyan

# Use the Clang llama-server build (has sm_75 kernels for the 1660 Super; the
# WindowsApps `llama.exe` MSVC build cannot run the 1660 Super at all) and the
# device by NAME (CUDA0/CUDA1) — this llama.cpp line rejects numeric --device.
& "D:\llama.cpp\llama-server.exe" `
    --host 127.0.0.1 `
    --port 1235 `
    --device CUDA1 `
    --ctx-size 32768 `
    --n-gpu-layers all `
    --split-mode none `
    --model "D:/LMStudio/models/lmstudio-community/Qwen3-4B-Thinking-2507-GGUF/Qwen3-4B-Thinking-2507-Q6_K.gguf"
