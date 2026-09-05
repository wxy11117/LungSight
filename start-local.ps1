$ErrorActionPreference = 'Stop'

$siteDirectory = $PSScriptRoot
$backendDirectory = Join-Path $siteDirectory 'backend'
$pythonExecutable = Join-Path $backendDirectory '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $pythonExecutable)) {
  throw '缺少 backend/.venv，请先按照 backend/README.md 安装依赖。'
}

$backendProcess = Start-Process `
  -FilePath $pythonExecutable `
  -ArgumentList '-m', 'uvicorn', 'app:app', '--host', '127.0.0.1', '--port', '8001' `
  -WorkingDirectory $backendDirectory `
  -WindowStyle Hidden `
  -PassThru

try {
  Write-Host 'LungSight 后端已启动：http://127.0.0.1:8001'
  Write-Host '正在启动网页，按 Ctrl+C 可同时结束本地服务。'
  Set-Location -LiteralPath $siteDirectory
  & pnpm build
  if ($LASTEXITCODE -ne 0) { throw '网页构建失败。' }
  & pnpm start
}
finally {
  if (-not $backendProcess.HasExited) {
    Stop-Process -Id $backendProcess.Id
  }
}
