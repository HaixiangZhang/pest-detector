# 启动 pest_detector Web 服务（FastAPI + Uvicorn）
#
# 用法（在项目根或任意目录执行均可）:
#   .\scripts\start.ps1                 # 自检 + 启动；Ctrl+C 停止
#   .\scripts\start.ps1 -Check          # 只做环境自检，不启动（等价于 scripts\check.ps1）
#   .\scripts\start.ps1 -Open           # 启动后自动打开浏览器
#   .\scripts\start.ps1 -Build          # 强制重新构建前端
#   .\scripts\start.ps1 -Reload         # 开发热重载（改后端代码自动重启）
#   .\scripts\start.ps1 -BindHost 0.0.0.0 -Port 8000
#   .\scripts\start.ps1 -Python <python.exe 路径>
#   .\scripts\start.ps1 -Install        # 依赖缺失时，自动装进当前 conda 环境
#
# 说明:
#   - 自动探测"装有项目依赖"的 Python（torch / ultralytics / fastapi / uvicorn），
#     因此无需手动 conda activate，也不受 `powershell -File` 子进程切成 base 的影响。
#   - 探测顺序: -Python > $env:PESTDET_PYTHON > 当前 conda 环境 > PATH 的 python > 其它 conda 环境 > .venv
#   - 启动前自动自检: 解释器/依赖、configs.yaml、模型权重、前端产物、ffmpeg、端口占用、数据目录。
#   - web/dist 不存在时自动构建前端（需要 Node.js）。
#   - 推理在**进程内**单 worker 串行执行，请勿用多 worker 启动。
#   - 本文件必须保存为 UTF-8 with BOM，否则 PowerShell 5.1 会把中文按 GBK 解码成乱码。

param(
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8000,
    [string]$Python = $env:PESTDET_PYTHON,
    [switch]$Build,
    [switch]$Reload,
    [switch]$Install,
    [switch]$Check,
    [switch]$Open
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONPATH = Join-Path $root "src"

$script:FailCount = 0
$script:WarnCount = 0

function Write-Item([string]$Status, [string]$Label, [string]$Detail) {
    switch ($Status) {
        "OK"    { $color = "Green" }
        "WARN"  { $color = "Yellow" }
        "FAIL"  { $color = "Red" }
        default { $color = "Gray" }
    }
    if ($Status -eq "FAIL") { $script:FailCount++ }
    elseif ($Status -eq "WARN") { $script:WarnCount++ }
    Write-Host ("  [{0,-4}] {1}" -f $Status, $Label) -ForegroundColor $color -NoNewline
    if ($Detail) { Write-Host "  $Detail" -ForegroundColor DarkGray } else { Write-Host "" }
}

# --- 解释器探测 -------------------------------------------------------------
# 判据: 同时具备 torch / ultralytics / fastapi / uvicorn 四个发行版。
# 用 importlib.metadata 查"已安装发行版"，不真正 import（快、不加载 CUDA）。
# torch / ultralytics 不会出现在用户级 site-packages，因此能有效区分项目环境与其它解释器。
$probeCode = "import importlib.metadata as m; [m.version(p) for p in ('torch','ultralytics','fastapi','uvicorn')]"

function Test-ProjectPython([string]$exe) {
    if (-not $exe) { return $false }
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $null = & $exe -c $probeCode 2>$null
        $ok = ($LASTEXITCODE -eq 0)
    } catch { $ok = $false }
    $ErrorActionPreference = $prev
    return $ok
}

# 从 conda.bat / conda.exe / python.exe 的路径反推"含 python.exe 的目录"
# （如 ...\miniconda3\python.exe 或 ...\miniconda3\envs\yolo11\python.exe）
# 注意: 入参可能是裸命令名（如 "conda"、模块名），此时无从反推，必须安全返回空串。
function Get-CondaBaseFromExe([string]$path) {
    if (-not $path) { return "" }
    $path = $path.Trim().Trim('"')
    if (-not $path) { return "" }
    try { $d = Split-Path -Path $path -Parent -ErrorAction Stop } catch { return "" }
    if (-not $d) { return "" }
    for ($i = 0; $i -lt 3; $i++) {
        if (-not $d) { break }
        $leaf = Split-Path -Path $d -Leaf -ErrorAction SilentlyContinue
        if ($leaf -in @("bin", "condabin", "Scripts", "Library")) {
            $next = Split-Path -Path $d -Parent -ErrorAction SilentlyContinue
            if (-not $next) { break }
            $d = $next
        } else { break }
    }
    if (-not $d) { return "" }
    if (Test-Path (Join-Path $d "python.exe")) { return $d }
    return ""
}

# 解释器缓存: 首次成功探测后写入，之后双击启动可直接复用（无需 conda 在 PATH）
$script:PythonCacheFile = Join-Path $root ".pestdet-python"

function Get-CachedPython {
    if (Test-Path $script:PythonCacheFile) {
        try {
            $p = [System.IO.File]::ReadAllText($script:PythonCacheFile).Trim()
            if ($p -and (Test-Path $p)) { return $p }
        } catch { }
    }
    return ""
}

function Save-CachedPython([string]$exe) {
    if (-not $exe) { return }
    try {
        [System.IO.File]::WriteAllText($script:PythonCacheFile, $exe,
            (New-Object System.Text.UTF8Encoding $true))
    } catch { }
}

function Get-CandidatePythons {
    $list = New-Object System.Collections.Generic.List[string]
    if ($Python) { $list.Add($Python) }
    $cached = Get-CachedPython
    if ($cached) { $list.Add($cached) }
    if ($env:CONDA_PREFIX) { $list.Add((Join-Path $env:CONDA_PREFIX "python.exe")) }

    # 收集可能的 conda 安装根（不依赖已激活环境，支持双击运行）
    $bases = New-Object System.Collections.Generic.List[string]
    $probeExes = New-Object System.Collections.Generic.List[string]
    if ($env:CONDA_EXE) { $probeExes.Add($env:CONDA_EXE) }
    foreach ($name in @("conda", "python")) {
        foreach ($cmd in @(Get-Command $name -ErrorAction SilentlyContinue)) {
            if ($cmd.Path) { $probeExes.Add($cmd.Path) }
            elseif ($cmd.Source) { $probeExes.Add($cmd.Source) }
        }
    }
    foreach ($exe in $probeExes) {
        $b = Get-CondaBaseFromExe $exe
        if ($b) { $bases.Add($b) }
    }
    foreach ($parent in @($env:USERPROFILE, $env:LOCALAPPDATA, "C:\ProgramData", "C:\", "D:\")) {
        if (-not $parent) { continue }
        foreach ($name in @("miniconda3", "anaconda3", "miniforge3", "mambaforge", "Continuum\anaconda3")) {
            $cand = Join-Path $parent $name
            if (Test-Path (Join-Path $cand "python.exe")) { $bases.Add($cand) }
        }
    }

    foreach ($b in ($bases | Where-Object { $_ } | Select-Object -Unique)) {
        $list.Add((Join-Path $b "python.exe"))
        $envsDir = Join-Path $b "envs"
        if (Test-Path $envsDir) {
            Get-ChildItem $envsDir -Directory -ErrorAction SilentlyContinue | ForEach-Object {
                $cand = Join-Path $_.FullName "python.exe"
                if (Test-Path $cand) { $list.Add($cand) }
            }
        }
    }

    $list.Add("python")
    $venv = Join-Path $root ".venv\Scripts\python.exe"
    if (Test-Path $venv) { $list.Add($venv) }
    return ($list | Where-Object { $_ } | Select-Object -Unique)
}

# 解析部署权重: configs.yaml 的 model_path，留空则回退 runs/registry.json 最新登记。
function Get-ModelPath {
    $cfg = Join-Path $root "configs.yaml"
    if (Test-Path $cfg) {
        $m = Select-String -Path $cfg -Pattern '^\s*model_path:\s*([^#]*?)\s*(?:#.*)?$' -ErrorAction SilentlyContinue |
             Select-Object -First 1
        if ($m) {
            $v = $m.Matches[0].Groups[1].Value.Trim().Trim('"').Trim("'")
            if ($v) {
                if ([System.IO.Path]::IsPathRooted($v)) { return $v }
                return (Join-Path $root $v)
            }
        }
    }
    $reg = Join-Path $root "runs\registry.json"
    if (Test-Path $reg) {
        try {
            $j = Get-Content $reg -Raw -Encoding UTF8 | ConvertFrom-Json
            $names = @($j.weights.PSObject.Properties.Name | Sort-Object { [int]($_ -replace '^pest', '') })
            if ($names.Count -gt 0) {
                $rp = $j.weights.($names[-1]).path
                if ($rp) {
                    if ([System.IO.Path]::IsPathRooted($rp)) { return $rp }
                    return (Join-Path $root $rp)
                }
            }
        } catch { }
    }
    return ""
}

# ============================================================================
# 环境自检
# ============================================================================
Write-Host ""
Write-Host "pest_detector 环境自检" -ForegroundColor Cyan
Write-Host ("-" * 60) -ForegroundColor DarkGray

# 1) 解释器 + 依赖
$chosen = $null
$candidates = @()
try { $candidates = @(Get-CandidatePythons) } catch { $candidates = @("python") }
foreach ($cand in $candidates) {
    if (Test-ProjectPython $cand) { $chosen = $cand; break }
}

if (-not $chosen -and $Install) {
    $target = if ($env:CONDA_PREFIX) { Join-Path $env:CONDA_PREFIX "python.exe" } elseif ($Python) { $Python } else { "python" }
    Write-Host "[安装] 向 $target 安装 Web 依赖（临时禁用 user site，确保装进环境本身）..." -ForegroundColor Cyan
    $env:PYTHONNOUSERSITE = "1"
    & $target -m pip install -e ".[web]"
    Remove-Item Env:PYTHONNOUSERSITE -ErrorAction SilentlyContinue
    if (Test-ProjectPython $target) { $chosen = $target }
}

if ($chosen) {
    Save-CachedPython $chosen
    Write-Item "OK" "Python 解释器" $chosen
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $info = & $chosen -c "import sys, importlib.metadata as m; print('py' + sys.version.split()[0]); print(' '.join(p + '=' + m.version(p) for p in ('torch','ultralytics','fastapi','uvicorn','pydantic')))" 2>$null
    $ErrorActionPreference = $prev
    if ($info) { Write-Host ("         " + ($info -join "  ")) -ForegroundColor DarkGray }
} else {
    Write-Item "FAIL" "Python 解释器" "未找到装有项目依赖的 Python（需 torch / ultralytics / fastapi / uvicorn）"
    Write-Host "         已尝试:" -ForegroundColor DarkGray
    foreach ($c in $candidates) { Write-Host "           - $c" -ForegroundColor DarkGray }
}

# 2) configs.yaml
$cfgPath = Join-Path $root "configs.yaml"
if (Test-Path $cfgPath) {
    Write-Item "OK" "configs.yaml" $cfgPath
} else {
    Write-Item "FAIL" "configs.yaml" "缺失（服务无法启动；请从版本库恢复）"
}

# 3) 模型权重
$modelPath = Get-ModelPath
if (-not $modelPath) {
    Write-Item "WARN" "模型权重" "configs.yaml 的 model_path 为空且 runs/registry.json 无登记 → 任务会在运行时失败"
} elseif (Test-Path $modelPath) {
    $mb = [math]::Round((Get-Item $modelPath).Length / 1MB, 1)
    Write-Item "OK" "模型权重" "$modelPath  (${mb} MB)"
} else {
    Write-Item "FAIL" "模型权重" "路径不存在: $modelPath"
}

# 4) 前端产物
$distIndex = Join-Path $root "web\dist\index.html"
if (Test-Path $distIndex) {
    $built = (Get-Item $distIndex).LastWriteTime.ToString("yyyy-MM-dd HH:mm")
    Write-Item "OK" "前端产物 web/dist" "构建于 $built（前端有改动时加 -Build 重建）"
} else {
    Write-Item "WARN" "前端产物 web/dist" "不存在 → 启动时会尝试自动构建（需要 Node.js）"
}

# 5) Node / npm
$npmCmd = Get-Command npm -ErrorAction SilentlyContinue
$nodeCmd = Get-Command node -ErrorAction SilentlyContinue
if ($npmCmd -and $nodeCmd) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $nodeVer = (& node --version 2>$null)
    $ErrorActionPreference = $prev
    Write-Item "OK" "Node / npm" "node $nodeVer"
} else {
    Write-Item "WARN" "Node / npm" "未找到 → 无法构建前端（已有 web/dist 时不影响启动）"
}

# 6) ffmpeg（可选：输出视频转 H.264，浏览器播放更流畅）
$ffmpegCmd = Get-Command ffmpeg -ErrorAction SilentlyContinue
if ($ffmpegCmd) {
    Write-Item "OK" "ffmpeg" $ffmpegCmd.Source
} else {
    Write-Item "WARN" "ffmpeg" "未在 PATH 中找到 → 输出视频保留 mp4v（可播，但 4K 拖动可能卡）"
}

# 7) 端口占用
$listen = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listen) {
    $pids = @($listen | Select-Object -ExpandProperty OwningProcess -Unique)
    $names = ($pids | ForEach-Object { "PID $_" }) -join ", "
    Write-Item "FAIL" "端口 $Port" "已被占用（$names）→ 换端口: -Port 8001，或先结束该进程"
} else {
    Write-Item "OK" "端口 $Port" "空闲"
}

# 8) 数据目录可写
$dataDirs = @((Join-Path $root "data\uploads"), (Join-Path $root "runs"))
$badDirs = @()
foreach ($d in $dataDirs) {
    try {
        if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
        $probe = Join-Path $d ".write_test"
        Set-Content -Path $probe -Value "ok" -ErrorAction Stop
        Remove-Item $probe -Force -ErrorAction SilentlyContinue
    } catch { $badDirs += $d }
}
if ($badDirs.Count -eq 0) {
    Write-Item "OK" "数据目录可写" "data\uploads  runs\"
} else {
    Write-Item "FAIL" "数据目录可写" ("不可写: " + ($badDirs -join ", "))
}

Write-Host ("-" * 60) -ForegroundColor DarkGray
if ($script:FailCount -eq 0) {
    $tail = if ($script:WarnCount -gt 0) { "（$script:WarnCount 项警告，不影响启动）" } else { "" }
    Write-Host "自检通过 $tail" -ForegroundColor Green
} else {
    Write-Host "自检发现 $script:FailCount 项错误、$script:WarnCount 项警告" -ForegroundColor Red
}
Write-Host ""

if ($Check) {
    exit $(if ($script:FailCount -gt 0) { 1 } else { 0 })
}

if ($script:FailCount -gt 0) {
    Write-Host "解决办法:" -ForegroundColor Yellow
    Write-Host "  1) 激活项目环境后重跑:  conda activate yolo11" -ForegroundColor Yellow
    Write-Host "  2) 显式指定解释器:      -Python <python.exe 路径>" -ForegroundColor Yellow
    Write-Host "  3) 自动装 Web 依赖:     -Install" -ForegroundColor Yellow
    Write-Host "  4) 端口被占用:          -Port 8001" -ForegroundColor Yellow
    exit 1
}

# --- 前端构建 ---------------------------------------------------------------
if ($Build -or -not (Test-Path $distIndex)) {
    if (-not $npmCmd) {
        Write-Host "[前端] 未找到 npm，跳过构建；根路径将没有界面（仅 /docs 可用）" -ForegroundColor Yellow
    } else {
        Write-Host "[前端] 构建中 (web/dist) ..." -ForegroundColor Cyan
        Push-Location (Join-Path $root "web")
        if (-not (Test-Path "node_modules")) { npm install }
        npm run build
        $buildOk = ($LASTEXITCODE -eq 0)
        Pop-Location
        if (-not $buildOk) { Write-Host "[错误] 前端构建失败" -ForegroundColor Red; exit 1 }
    }
} else {
    Write-Host "[前端] web/dist 已存在，跳过构建（需要重建时加 -Build）" -ForegroundColor DarkGray
}

# --- 启动 -------------------------------------------------------------------
$urlHost = if ($BindHost -eq "0.0.0.0") { "127.0.0.1" } else { $BindHost }
$url = "http://${urlHost}:$Port/"
Write-Host "[启动] $url  (Ctrl+C 停止)" -ForegroundColor Cyan

if ($Open) {
    Start-Job -ScriptBlock { param($u) Start-Sleep -Seconds 3; Start-Process $u } -ArgumentList $url | Out-Null
}

$serverArgs = @("-m", "pestdet.server", "--host", $BindHost, "--port", "$Port")
if ($Reload) { $serverArgs += "--reload" }
& $chosen @serverArgs