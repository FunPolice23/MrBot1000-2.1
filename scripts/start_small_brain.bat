@echo off
REM Start Small Brain Ollama on 1660 Super only
REM The 4B model + context fits in 6 GB VRAM
REM 5060 Ti stays free for Big Brain

set CUDA_VISIBLE_DEVICES=1
set OLLAMA_HOST=127.0.0.1:11435
set OLLAMA_KEEP_ALIVE=5m
set OLLAMA_MAX_LOADED_MODELS=1

echo ========================================
echo   Small Brain Ollama
echo   GPU: 1660 Super (6 GB)
echo   Port: 11435
echo ========================================

ollama serve
