$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command py -ErrorAction SilentlyContinue }
if (-not $python) { throw 'Python não foi encontrado no PATH.' }
Start-Process 'http://127.0.0.1:8765'
& $python.Source (Join-Path $root 'server.py')
