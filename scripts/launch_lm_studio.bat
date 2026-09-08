@echo off
REM Launch LM Studio Bionic with 5060 Ti only (hides 1660 Super)
REM This leaves the 1660 Super free for Ollama Small Brain

set CUDA_VISIBLE_DEVICES=0
start "" "D:\LMStudio\Bionic\LM Studio.exe"
