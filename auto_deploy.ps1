
# Script de Auto-Despliegue a GitHub para GlamStore
# Autor: Antigravity

$ErrorActionPreference = "Stop"

Write-Host "🚀 Iniciando Auto-Despliegue a GitHub..." -ForegroundColor Cyan

# 1. Verificar si es repositorio Git
if (-not (Test-Path ".git")) {
    Write-Host "📦 Inicializando repositorio Git..." -ForegroundColor Yellow
    git init
    git branch -M main
}

# 2. Verificar Remote
$remotes = git remote -v
if (-not $remotes) {
    Write-Host "⚠️ No tienes un repositorio remoto configurado." -ForegroundColor Red
    $repoUrl = Read-Host "🔗 Ingrese la URL de su repositorio GitHub (https://github.com/...)"
    if ($repoUrl) {
        git remote add origin $repoUrl
        Write-Host "✅ Remoto configurado a: $repoUrl" -ForegroundColor Green
    } else {
        Write-Host "❌ URL vacía. No se puede continuar sin remoto." -ForegroundColor Red
        exit 1
    }
}

# 3. Agregar cambios
Write-Host "📝 Agregando cambios..." -ForegroundColor Cyan
git add .

# 4. Commit
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$commitMessage = "Auto-save: $timestamp"
Write-Host "💾 Creando commit: '$commitMessage'" -ForegroundColor Cyan
git commit -m "$commitMessage"

# 5. Push
Write-Host "⬆️ Subiendo a GitHub..." -ForegroundColor Cyan
try {
    git push -u origin main
    Write-Host "✅ ¡Éxito! Tu código está en GitHub." -ForegroundColor Green
} catch {
    Write-Host "❌ Error al subir. Verifica tus credenciales o permisos." -ForegroundColor Red
    Write-Host $_
}

Pause
