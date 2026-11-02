# 环境自检脚本（不启动服务）
#
# 用法:
#   .\scripts\check.ps1
#   .\scripts\check.ps1 -Port 8001
#   .\scripts\check.ps1 -Python <python.exe 路径>
#
# 说明: 转发到 start.ps1 -Check，检查解释器/依赖、configs.yaml、模型权重、
#       前端产物、Node/npm、ffmpeg、端口占用、数据目录可写性。
#       退出码 0 = 通过（可能有警告），1 = 有错误。
#       本文件必须保存为 UTF-8 with BOM（PowerShell 5.1 中文兼容）。

param(
    [string]$Python = $env:PESTDET_PYTHON,
    [int]$Port = 8000
)

$startScript = Join-Path $PSScriptRoot "start.ps1"
if ($Python) {
    & $startScript -Check -Port $Port -Python $Python
} else {
    & $startScript -Check -Port $Port
}
exit $LASTEXITCODE