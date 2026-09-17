$ErrorActionPreference = "Stop"

Add-Type -AssemblyName PresentationFramework
Add-Type -AssemblyName PresentationCore
Add-Type -AssemblyName WindowsBase

Add-Type @"
using System;
using System.Runtime.InteropServices;

public static class NeveLudensTaskbar
{
    [DllImport("shell32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern int SetCurrentProcessExplicitAppUserModelID(string appId);
}
"@

$appIdResult = [NeveLudensTaskbar]::SetCurrentProcessExplicitAppUserModelID("NeveLudens.Desktop.Launcher")
if ($appIdResult -ne 0) {
    throw "Não foi possível configurar o identificador da barra de tarefas (HRESULT: $appIdResult)."
}

$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvPython = Join-Path $Repo ".venv\Scripts\python.exe"
$ConfigPath = Join-Path $Repo "neveludens_local_config.json"
$LogsDir = Join-Path $Repo "logs"
$OutDir = Join-Path $Repo "out"
$DebugDir = Join-Path $Repo "debug"
$LastCapturePath = Join-Path $OutDir "last_model_capture.png"
$InstallBat = Join-Path $Repo "instalar.bat"
$XamlPath = Join-Path $PSScriptRoot "ui\NeveLudens.xaml"
$IconPath = Join-Path $Repo "static\favicon.png"

$script:AgentProcess = $null
$script:ActiveProcess = $null
$script:ActiveKind = ""
$script:RunLogPath = $null
$script:LogReadPosition = 0
$script:StopFilePath = $null
$script:StopRequestedAt = $null
$script:ForcedStopIssued = $false
$script:CloseAfterStop = $false
$script:ForceStopAfterSeconds = 30
$script:OperationalState = "idle"
$script:CanStart = $false
$script:LoadingSettings = $true
$script:ApplyingPreset = $false
$script:CustomPreset = $null
$script:LastCaptureWriteTicks = 0

New-Item -ItemType Directory -Force -Path $LogsDir, $OutDir, $DebugDir | Out-Null
Set-Location $Repo

function Set-LocalEnvironment {
    $env:PYTHONUTF8 = "1"
    $env:PYTHONUNBUFFERED = "1"
    $env:DEBUG = "0"
    $env:BNB_CUDA_VERSION = "130"
    $env:HF_HOME = Join-Path $Repo ".cache\huggingface"
    $env:HF_HUB_CACHE = Join-Path $Repo ".cache\huggingface\hub"
    $env:TRANSFORMERS_CACHE = Join-Path $Repo ".cache\huggingface\transformers"
    $env:TORCH_HOME = Join-Path $Repo ".cache\torch"
    $env:PIP_CACHE_DIR = Join-Path $Repo ".cache\pip"
    $env:PATH = (Join-Path $Repo ".venv\Scripts") + ";" + $env:PATH
}

function Join-CommandLine {
    param([string[]]$Items)
    $escaped = foreach ($item in $Items) {
        if ($item -match '[\s"]') {
            '"' + ($item -replace '"', '\"') + '"'
        } else {
            $item
        }
    }
    return ($escaped -join " ")
}

function Stop-ProcessTree {
    param([int]$RootProcessId)
    Get-CimInstance Win32_Process -Filter "ParentProcessId=$RootProcessId" -ErrorAction SilentlyContinue | ForEach-Object {
        Stop-ProcessTree -RootProcessId ([int]$_.ProcessId)
    }
    Stop-Process -Id $RootProcessId -Force -ErrorAction SilentlyContinue
}

function Get-SavedConfig {
    if (-not (Test-Path $ConfigPath)) {
        return $null
    }
    try {
        return Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        return $null
    }
}

function Limit-MenuText {
    param(
        [string]$Text,
        [int]$MaxLength = 58
    )
    if ([string]::IsNullOrWhiteSpace($Text) -or $Text.Length -le $MaxLength) {
        return $Text
    }
    return $Text.Substring(0, $MaxLength - 1) + "..."
}

function Get-VisibleGameProcesses {
    $skip = @(
        "ApplicationFrameHost", "brave", "chrome", "Code", "cmd", "conhost",
        "dwm", "explorer", "firefox", "msedge", "powershell", "SearchHost",
        "ShellExperienceHost", "ShellHost", "steam", "steamwebhelper",
        "TextInputHost", "WindowsTerminal"
    )

    Get-Process |
        Where-Object { $_.MainWindowTitle -and $_.MainWindowTitle.Trim().Length -gt 0 } |
        Where-Object { $skip -notcontains $_.ProcessName } |
        Sort-Object ProcessName, Id |
        ForEach-Object {
            $exe = $_.ProcessName
            if (-not $exe.ToLowerInvariant().EndsWith(".exe")) {
                $exe = "$exe.exe"
            }
            $display = "{0}  |  PID {1}  |  {2}" -f $exe, $_.Id, $_.MainWindowTitle
            [PSCustomObject]@{
                Process = $exe
                Title = $_.MainWindowTitle
                Id = $_.Id
                Display = Limit-MenuText $display
                FullDisplay = $display
            }
        }
}

Set-LocalEnvironment

if (-not (Test-Path $XamlPath)) {
    [System.Windows.MessageBox]::Show("A interface não foi encontrada em $XamlPath.", "NeveLudens") | Out-Null
    exit 1
}

$xamlText = Get-Content -LiteralPath $XamlPath -Raw -Encoding UTF8
$reader = New-Object System.Xml.XmlNodeReader ([xml]$xamlText)
$window = [Windows.Markup.XamlReader]::Load($reader)

$script:WindowIcon = $null
if (Test-Path -LiteralPath $IconPath) {
    $script:WindowIcon = New-Object System.Windows.Media.Imaging.BitmapImage
    $script:WindowIcon.BeginInit()
    $script:WindowIcon.CacheOption = [System.Windows.Media.Imaging.BitmapCacheOption]::OnLoad
    $script:WindowIcon.UriSource = New-Object System.Uri($IconPath, [System.UriKind]::Absolute)
    $script:WindowIcon.EndInit()
    $script:WindowIcon.Freeze()
    $window.Icon = $script:WindowIcon
}

$window.Add_SourceInitialized({
    if ($script:WindowIcon) {
        $window.Icon = $script:WindowIcon
    }
})

$controlNames = @(
    "TitleBar", "BtnMinimize", "BtnMaximize", "BtnClose",
    "NavOverview", "NavSettings", "NavDiagnostics",
    "OverviewPage", "SettingsPage", "DiagnosticsPage",
    "SessionGameText", "StartButton", "StartButtonPowerIcon", "StartButtonLabel",
    "NotificationBar", "NotificationTitle", "NotificationDetail", "NotificationDetailsButton",
    "ProcessCombo", "ManualProcessBox", "RefreshButton",
    "LastCaptureImage", "LastCapturePlaceholder", "PresetCombo", "PresetDescriptionText",
    "ModelCombo", "BackendCombo", "RuntimeModeCombo", "DetailedOutputCheck", "GameModeCombo", "AgentSlotCombo",
    "MultimodalSupervisorCheck", "MemoryRecoveryCombo", "ReducedActionHorizonCheck", "AutoControlCalibrationCheck", "MenuActionsCheck",
    "DiagnoseButton", "LogBox", "CopyLogButton", "ClearLogButton"
)

foreach ($controlName in $controlNames) {
    $control = $window.FindName($controlName)
    if (-not $control) {
        throw "Controle WPF não encontrado: $controlName"
    }
    Set-Variable -Name $controlName -Value $control -Scope Script
}

$script:LogTimer = New-Object System.Windows.Threading.DispatcherTimer
$script:LogTimer.Interval = [TimeSpan]::FromMilliseconds(400)
$script:CaptureTimer = New-Object System.Windows.Threading.DispatcherTimer
$script:CaptureTimer.Interval = [TimeSpan]::FromMilliseconds(100)
$script:NotificationTimer = New-Object System.Windows.Threading.DispatcherTimer
$script:NotificationTimer.Interval = [TimeSpan]::FromSeconds(6)

function Get-Brush {
    param([string]$Name)
    return $window.FindResource($Name)
}

function Set-ComboByTag {
    param(
        $Combo,
        [string]$Tag,
        [string]$Fallback
    )
    $wanted = if ([string]::IsNullOrWhiteSpace($Tag)) { $Fallback } else { $Tag }
    foreach ($item in $Combo.Items) {
        if ([string]$item.Tag -eq $wanted) {
            $Combo.SelectedItem = $item
            return
        }
    }
    foreach ($item in $Combo.Items) {
        if ([string]$item.Tag -eq $Fallback) {
            $Combo.SelectedItem = $item
            return
        }
    }
}

function Get-ComboTag {
    param($Combo, [string]$Fallback)
    $selected = $Combo.SelectedItem
    if ($selected -and $selected.Tag) {
        return [string]$selected.Tag
    }
    return $Fallback
}

function Get-SelectedProcessName {
    $name = $ManualProcessBox.Text.Trim()
    if ([string]::IsNullOrWhiteSpace($name) -and $ProcessCombo.SelectedItem) {
        $name = [string]$ProcessCombo.SelectedItem.Process
    }
    if (-not [string]::IsNullOrWhiteSpace($name) -and -not $name.ToLowerInvariant().EndsWith(".exe")) {
        $name = "$name.exe"
    }
    return $name
}

function Get-ModelPath {
    $choice = Get-ComboTag $ModelCombo "default"
    switch ($choice) {
        "pizza_tower" { return Join-Path $Repo "models\pizza_tower\final_model.pt" }
        "pizza_tower_fast" { return Join-Path $Repo "models\pizza_tower\final_model_35.pt" }
        default { return Join-Path $Repo "models\ng.pt" }
    }
}

function Get-PresetSettings {
    param([ValidateSet("default", "performance", "quality")][string]$Name)

    switch ($Name) {
        "performance" {
            return [PSCustomObject][ordered]@{
                model_choice = "default"
                screenshot_backend = "auto"
                runtime_mode = "realtime"
                output_mode = "normal"
                game_mode = "default"
                agent_slot = "auto"
                multimodal_supervisor = "disabled"
                memory_mode = "temporary"
                reduced_action_horizon = $false
                auto_control_calibration = $false
                allow_menu = $false
            }
        }
        "quality" {
            return [PSCustomObject][ordered]@{
                model_choice = "pizza_tower_fast"
                screenshot_backend = "dxcam"
                runtime_mode = "precision"
                output_mode = "debug"
                game_mode = "default"
                agent_slot = "auto"
                multimodal_supervisor = "enabled"
                memory_mode = "persistent"
                reduced_action_horizon = $false
                auto_control_calibration = $false
                allow_menu = $false
            }
        }
        default {
            return [PSCustomObject][ordered]@{
                model_choice = "default"
                screenshot_backend = "auto"
                runtime_mode = "precision"
                output_mode = "normal"
                game_mode = "default"
                agent_slot = "auto"
                multimodal_supervisor = "disabled"
                memory_mode = "temporary"
                reduced_action_horizon = $false
                auto_control_calibration = $false
                allow_menu = $false
            }
        }
    }
}

function Get-CompatibleMemoryMode {
    param($Settings)
    if (-not $Settings) {
        return "temporary"
    }

    $propertyNames = @($Settings.PSObject.Properties.Name)
    if ($propertyNames -contains "memory_mode" -and
        [string]$Settings.memory_mode -in @("disabled", "temporary", "persistent")) {
        return [string]$Settings.memory_mode
    }
    if ($propertyNames -contains "advanced_memory" -and [bool]$Settings.advanced_memory) {
        return "persistent"
    }
    if (-not ($propertyNames -contains "smart_recovery") -or [bool]$Settings.smart_recovery) {
        return "temporary"
    }
    return "disabled"
}

function Get-OutputMode {
    if ([bool]$DetailedOutputCheck.IsChecked) {
        return "debug"
    }
    return "normal"
}

function Set-OutputMode {
    param([string]$Mode)
    $DetailedOutputCheck.IsChecked = [bool]($Mode -eq "debug")
}

function Get-CurrentUiSettings {
    return [PSCustomObject][ordered]@{
        model_choice = Get-ComboTag $ModelCombo "default"
        screenshot_backend = Get-ComboTag $BackendCombo "auto"
        runtime_mode = Get-ComboTag $RuntimeModeCombo "precision"
        output_mode = Get-OutputMode
        game_mode = Get-ComboTag $GameModeCombo "default"
        agent_slot = Get-ComboTag $AgentSlotCombo "auto"
        multimodal_supervisor = if ([bool]$MultimodalSupervisorCheck.IsChecked) { "enabled" } else { "disabled" }
        memory_mode = Get-ComboTag $MemoryRecoveryCombo "temporary"
        reduced_action_horizon = [bool]$ReducedActionHorizonCheck.IsChecked
        auto_control_calibration = [bool]$AutoControlCalibrationCheck.IsChecked
        allow_menu = [bool]$MenuActionsCheck.IsChecked
    }
}

function Set-UiSettings {
    param($Settings)
    if (-not $Settings) {
        return
    }

    $previousApplyingPreset = $script:ApplyingPreset
    $script:ApplyingPreset = $true
    try {
        Set-ComboByTag $ModelCombo ([string]$Settings.model_choice) "default"
        Set-ComboByTag $BackendCombo ([string]$Settings.screenshot_backend) "auto"
        Set-ComboByTag $RuntimeModeCombo ([string]$Settings.runtime_mode) "precision"
        Set-OutputMode ([string]$Settings.output_mode)
        Set-ComboByTag $GameModeCombo ([string]$Settings.game_mode) "default"
        Set-ComboByTag $AgentSlotCombo ([string]$Settings.agent_slot) "auto"
        $MultimodalSupervisorCheck.IsChecked = [bool]([string]$Settings.multimodal_supervisor -eq "enabled")
        Set-ComboByTag $MemoryRecoveryCombo (Get-CompatibleMemoryMode $Settings) "temporary"
        $ReducedActionHorizonCheck.IsChecked = [bool]$Settings.reduced_action_horizon
        $AutoControlCalibrationCheck.IsChecked = [bool]$Settings.auto_control_calibration
        $MenuActionsCheck.IsChecked = [bool]$Settings.allow_menu
    } finally {
        $script:ApplyingPreset = $previousApplyingPreset
    }
    Update-Readiness
}

function Test-UiSettingsMatch {
    param($Left, $Right)
    if (-not $Left -or -not $Right) {
        return $false
    }
    foreach ($propertyName in @(
        "model_choice", "screenshot_backend", "runtime_mode", "output_mode", "game_mode",
        "agent_slot", "multimodal_supervisor", "memory_mode", "reduced_action_horizon",
        "auto_control_calibration", "allow_menu"
    )) {
        if ([string]$Left.$propertyName -ne [string]$Right.$propertyName) {
            return $false
        }
    }
    return $true
}

function Update-PresetDescription {
    $description = switch (Get-ComboTag $PresetCombo "default") {
        "performance" { "Prioriza resposta rápida e baixo custo de processamento." }
        "quality" { "Ativa captura precisa, modelo acelerado e recursos avançados." }
        default { "" }
    }
    $PresetDescriptionText.Text = $description
    $PresetDescriptionText.Visibility = if ([string]::IsNullOrWhiteSpace($description)) {
        [System.Windows.Visibility]::Collapsed
    } else {
        [System.Windows.Visibility]::Visible
    }
}

function Initialize-PresetState {
    $config = Get-SavedConfig
    $currentSettings = Get-CurrentUiSettings
    if ($config -and $config.custom_preset) {
        $script:CustomPreset = $config.custom_preset
    }

    $selectedPreset = if ($config -and [string]$config.selected_preset -in @("default", "performance", "quality", "custom")) {
        [string]$config.selected_preset
    } else {
        ""
    }

    if ($selectedPreset -eq "custom") {
        $script:CustomPreset = $currentSettings
    } elseif ($selectedPreset -in @("default", "performance", "quality")) {
        if (-not (Test-UiSettingsMatch $currentSettings (Get-PresetSettings $selectedPreset))) {
            $selectedPreset = ""
        }
    }

    if ([string]::IsNullOrWhiteSpace($selectedPreset)) {
        foreach ($candidate in @("default", "performance", "quality")) {
            if (Test-UiSettingsMatch $currentSettings (Get-PresetSettings $candidate)) {
                $selectedPreset = $candidate
                break
            }
        }
    }

    if ([string]::IsNullOrWhiteSpace($selectedPreset)) {
        $selectedPreset = "custom"
        $script:CustomPreset = $currentSettings
    } elseif (-not $script:CustomPreset) {
        $script:CustomPreset = $currentSettings
    }

    $script:ApplyingPreset = $true
    try {
        Set-ComboByTag $PresetCombo $selectedPreset "default"
    } finally {
        $script:ApplyingPreset = $false
    }
    Update-PresetDescription
}

function Set-CustomPresetFromUi {
    if ($script:LoadingSettings -or $script:ApplyingPreset) {
        return
    }

    $script:CustomPreset = Get-CurrentUiSettings
    $script:ApplyingPreset = $true
    try {
        Set-ComboByTag $PresetCombo "custom" "custom"
    } finally {
        $script:ApplyingPreset = $false
    }
    Update-PresetDescription
    Save-UiConfig
}

function Update-LastCapturePreview {
    if ((Get-OutputMode) -ne "debug") {
        $script:LastCaptureWriteTicks = 0
        $LastCaptureImage.Source = $null
        $LastCaptureImage.Visibility = [System.Windows.Visibility]::Collapsed
        $LastCapturePlaceholder.Text = "Disponível na saída de depuração."
        $LastCapturePlaceholder.Visibility = [System.Windows.Visibility]::Visible
        return
    }

    if (-not (Test-Path -LiteralPath $LastCapturePath)) {
        $script:LastCaptureWriteTicks = 0
        $LastCaptureImage.Source = $null
        $LastCaptureImage.Visibility = [System.Windows.Visibility]::Collapsed
        $LastCapturePlaceholder.Text = "Aguardando captura detalhada"
        $LastCapturePlaceholder.Visibility = [System.Windows.Visibility]::Visible
        return
    }

    try {
        $captureFile = Get-Item -LiteralPath $LastCapturePath
        $bytes = [System.IO.File]::ReadAllBytes($LastCapturePath)
        $stream = New-Object System.IO.MemoryStream(,$bytes)
        try {
            $bitmap = New-Object System.Windows.Media.Imaging.BitmapImage
            $bitmap.BeginInit()
            $bitmap.CacheOption = [System.Windows.Media.Imaging.BitmapCacheOption]::OnLoad
            $bitmap.StreamSource = $stream
            $bitmap.EndInit()
            $bitmap.Freeze()
        } finally {
            $stream.Dispose()
        }
        $LastCaptureImage.Source = $bitmap
        $script:LastCaptureWriteTicks = $captureFile.LastWriteTimeUtc.Ticks
        $LastCaptureImage.Visibility = [System.Windows.Visibility]::Visible
        $LastCapturePlaceholder.Visibility = [System.Windows.Visibility]::Collapsed
    } catch {
        $LastCaptureImage.Source = $null
        $LastCaptureImage.Visibility = [System.Windows.Visibility]::Collapsed
        $LastCapturePlaceholder.Text = "Aguardando captura detalhada"
        $LastCapturePlaceholder.Visibility = [System.Windows.Visibility]::Visible
    }
}

function Sync-CapturePreviewUpdates {
    $detailedOutput = (Get-OutputMode) -eq "debug"
    $agentRunning = $script:ActiveKind -eq "agent" -and $script:ActiveProcess -and -not $script:ActiveProcess.HasExited

    Update-LastCapturePreview
    if ($detailedOutput -and $agentRunning) {
        $script:CaptureTimer.Start()
    } else {
        $script:CaptureTimer.Stop()
    }
}

function Save-UiConfig {
    if ($script:LoadingSettings) {
        return
    }
    try {
        $data = [ordered]@{}
        $existing = Get-SavedConfig
        if ($existing) {
            foreach ($property in $existing.PSObject.Properties) {
                $data[$property.Name] = $property.Value
            }
        }
        [void]$data.Remove("advanced_memory")
        [void]$data.Remove("smart_recovery")

        $processName = Get-SelectedProcessName
        $data["process"] = $processName
        $data["model_choice"] = Get-ComboTag $ModelCombo "default"
        $data["checkpoint_path"] = Get-ModelPath
        $data["screenshot_backend"] = Get-ComboTag $BackendCombo "auto"
        $data["runtime_mode"] = Get-ComboTag $RuntimeModeCombo "precision"
        $data["output_mode"] = Get-OutputMode
        $data["game_mode"] = Get-ComboTag $GameModeCombo "default"
        $data["agent_slot"] = Get-ComboTag $AgentSlotCombo "auto"
        $data["multimodal_supervisor"] = if ([bool]$MultimodalSupervisorCheck.IsChecked) { "enabled" } else { "disabled" }
        $data["memory_mode"] = Get-ComboTag $MemoryRecoveryCombo "temporary"
        $data["reduced_action_horizon"] = [bool]$ReducedActionHorizonCheck.IsChecked
        $data["auto_control_calibration"] = [bool]$AutoControlCalibrationCheck.IsChecked
        $data["allow_menu"] = [bool]$MenuActionsCheck.IsChecked
        $data["selected_preset"] = Get-ComboTag $PresetCombo "default"
        $data["custom_preset"] = if ($script:CustomPreset) { $script:CustomPreset } else { Get-CurrentUiSettings }
        $data["special_init"] = $processName.ToLowerInvariant() -in @("isaac-ng.exe", "cuphead.exe")
        $data["port"] = 5555

        $json = $data | ConvertTo-Json -Depth 6
        $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
        [System.IO.File]::WriteAllText($ConfigPath, $json, $utf8NoBom)
    } catch {
        Append-Log ("Não foi possível salvar a configuração: {0}" -f $_.Exception.Message)
    }
}

function Load-UiConfig {
    $config = Get-SavedConfig
    if (-not $config) {
        return
    }

    if ($config.process) {
        $ManualProcessBox.Text = [string]$config.process
    }
    Set-ComboByTag $ModelCombo ([string]$config.model_choice) "default"
    Set-ComboByTag $BackendCombo ([string]$config.screenshot_backend) "auto"
    Set-ComboByTag $RuntimeModeCombo ([string]$config.runtime_mode) "precision"
    Set-OutputMode ([string]$config.output_mode)
    Set-ComboByTag $GameModeCombo ([string]$config.game_mode) "default"
    Set-ComboByTag $AgentSlotCombo ([string]$config.agent_slot) "auto"
    $MultimodalSupervisorCheck.IsChecked = [bool]($config.multimodal_supervisor -eq "enabled")
    Set-ComboByTag $MemoryRecoveryCombo (Get-CompatibleMemoryMode $config) "temporary"
    $ReducedActionHorizonCheck.IsChecked = if ($null -eq $config.reduced_action_horizon) { $false } else { [bool]$config.reduced_action_horizon }
    $AutoControlCalibrationCheck.IsChecked = if ($null -eq $config.auto_control_calibration) { $false } else { [bool]$config.auto_control_calibration }
    $MenuActionsCheck.IsChecked = if ($null -eq $config.allow_menu) { $false } else { [bool]$config.allow_menu }
}

function Get-LogBrush {
    param([string]$Message)
    if ($Message -match '(?i)traceback|exception|falha|erro|error|failed') {
        return Get-Brush "DangerBrush"
    }
    if ($Message -match '(?i)warning|aviso|fallback|blocked|bloquead') {
        return Get-Brush "WarningBrush"
    }
    if ($Message -match '(?i)pronto|ready|carregado|loaded|execução|running') {
        return Get-Brush "SuccessBrush"
    }
    return [System.Windows.Media.Brushes]::LightGray
}

function Append-Log {
    param(
        [string]$Message,
        [bool]$Mirror = $true
    )
    if ([string]::IsNullOrWhiteSpace($Message)) {
        return
    }

    $writeUi = [Action]{
        $paragraph = New-Object System.Windows.Documents.Paragraph
        $paragraph.Margin = New-Object System.Windows.Thickness(0, 0, 0, 2)
        $run = New-Object System.Windows.Documents.Run($Message)
        $run.Foreground = Get-LogBrush $Message
        [void]$paragraph.Inlines.Add($run)
        [void]$LogBox.Document.Blocks.Add($paragraph)
        if ($LogBox.Document.Blocks.Count -gt 3000) {
            for ($i = 0; $i -lt 400; $i++) {
                if ($LogBox.Document.Blocks.FirstBlock) {
                    $LogBox.Document.Blocks.Remove($LogBox.Document.Blocks.FirstBlock)
                }
            }
        }
        $LogBox.ScrollToEnd()
    }

    try {
        if ($window.Dispatcher.CheckAccess()) {
            $writeUi.Invoke()
        } else {
            $window.Dispatcher.Invoke($writeUi)
        }
    } catch {}

    if ($Mirror -and $script:RunLogPath) {
        try {
            Add-Content -LiteralPath $script:RunLogPath -Value $Message -Encoding UTF8
        } catch {}
    }
}

function Show-Notification {
    param(
        [ValidateSet("info", "success", "warning", "danger")]
        [string]$Kind,
        [string]$Title,
        [string]$Detail,
        [bool]$ShowDetails = $false
    )
    $NotificationTitle.Text = $Title
    $NotificationDetail.Text = $Detail
    $NotificationDetailsButton.Visibility = if ($ShowDetails) { [System.Windows.Visibility]::Visible } else { [System.Windows.Visibility]::Collapsed }
    $NotificationBar.Background = Get-Brush "SurfaceRaisedBrush"
    switch ($Kind) {
        "success" {
            $NotificationBar.BorderBrush = New-Object System.Windows.Media.SolidColorBrush ([System.Windows.Media.Color]::FromRgb(47, 92, 70))
            $NotificationTitle.Foreground = Get-Brush "SuccessBrush"
        }
        "warning" {
            $NotificationBar.BorderBrush = New-Object System.Windows.Media.SolidColorBrush ([System.Windows.Media.Color]::FromRgb(95, 76, 38))
            $NotificationTitle.Foreground = Get-Brush "WarningBrush"
        }
        "danger" {
            $NotificationBar.BorderBrush = New-Object System.Windows.Media.SolidColorBrush ([System.Windows.Media.Color]::FromRgb(97, 51, 56))
            $NotificationTitle.Foreground = Get-Brush "DangerBrush"
        }
        default {
            $NotificationBar.BorderBrush = Get-Brush "BorderStrongBrush"
            $NotificationTitle.Foreground = Get-Brush "TextPrimaryBrush"
        }
    }
    $NotificationDetail.Foreground = Get-Brush "TextSecondaryBrush"
    $NotificationBar.Visibility = [System.Windows.Visibility]::Visible
    $script:NotificationTimer.Stop()
    $script:NotificationTimer.Start()
}

function Hide-Notification {
    $script:NotificationTimer.Stop()
    $NotificationBar.Visibility = [System.Windows.Visibility]::Collapsed
}

$script:NotificationTimer.Add_Tick({
    Hide-Notification
})

function Show-Page {
    param([ValidateSet("overview", "settings", "diagnostics")][string]$Page)
    $OverviewPage.Visibility = [System.Windows.Visibility]::Collapsed
    $SettingsPage.Visibility = [System.Windows.Visibility]::Collapsed
    $DiagnosticsPage.Visibility = [System.Windows.Visibility]::Collapsed
    $NavOverview.Tag = $null
    $NavSettings.Tag = $null
    $NavDiagnostics.Tag = $null

    switch ($Page) {
        "settings" {
            $SettingsPage.Visibility = [System.Windows.Visibility]::Visible
            $NavSettings.Tag = "active"
        }
        "diagnostics" {
            $DiagnosticsPage.Visibility = [System.Windows.Visibility]::Visible
            $NavDiagnostics.Tag = "active"
            $LogBox.ScrollToEnd()
        }
        default {
            $OverviewPage.Visibility = [System.Windows.Visibility]::Visible
            $NavOverview.Tag = "active"
            Sync-CapturePreviewUpdates
        }
    }
}

function Update-Readiness {
    $processName = Get-SelectedProcessName
    $environmentReady = Test-Path $VenvPython
    $processSelected = -not [string]::IsNullOrWhiteSpace($processName)
    $SessionGameText.Text = if ($processSelected) { $processName } else { "Nenhum jogo selecionado" }
    $script:CanStart = $environmentReady -and $processSelected
    if ($script:OperationalState -in @("idle", "error")) {
        $StartButton.IsEnabled = $script:CanStart
    }
}

function Set-ConfigurationEnabled {
    param([bool]$Enabled)
    foreach ($control in @(
        $ProcessCombo, $ManualProcessBox, $RefreshButton, $ModelCombo, $BackendCombo,
        $RuntimeModeCombo, $DetailedOutputCheck, $GameModeCombo, $AgentSlotCombo,
        $MultimodalSupervisorCheck, $MemoryRecoveryCombo, $MenuActionsCheck,
        $ReducedActionHorizonCheck, $AutoControlCalibrationCheck,
        $PresetCombo
    )) {
        $control.IsEnabled = $Enabled
    }
}

function Set-OperationalState {
    param(
        [ValidateSet("idle", "starting", "running", "stopping", "diagnosing", "error")]
        [string]$State,
        [string]$Detail = ""
    )
    $script:OperationalState = $State
    switch ($State) {
        "starting" {
            $StartButtonLabel.Text = "Parar"
            $StartButtonPowerIcon.Visibility = [System.Windows.Visibility]::Collapsed
            $StartButton.Width = 88
            $StartButton.Style = $window.FindResource("StopButton")
            $StartButton.IsEnabled = $true
            $DiagnoseButton.IsEnabled = $false
            Set-ConfigurationEnabled $false
        }
        "running" {
            $StartButtonLabel.Text = "Parar"
            $StartButtonPowerIcon.Visibility = [System.Windows.Visibility]::Collapsed
            $StartButton.Width = 88
            $StartButton.Style = $window.FindResource("StopButton")
            $StartButton.IsEnabled = $true
            $DiagnoseButton.IsEnabled = $false
            Set-ConfigurationEnabled $false
        }
        "stopping" {
            $StartButtonLabel.Text = "Encerrando"
            $StartButtonPowerIcon.Visibility = [System.Windows.Visibility]::Collapsed
            $StartButton.Width = 116
            $StartButton.Style = $window.FindResource("StopButton")
            $StartButton.IsEnabled = $false
            $DiagnoseButton.IsEnabled = $false
            Set-ConfigurationEnabled $false
        }
        "diagnosing" {
            $StartButtonLabel.Text = "Iniciar"
            $StartButtonPowerIcon.Visibility = [System.Windows.Visibility]::Visible
            $StartButton.Width = 88
            $StartButton.Style = $window.FindResource("PrimaryButton")
            $StartButton.IsEnabled = $false
            $DiagnoseButton.IsEnabled = $false
            Set-ConfigurationEnabled $false
        }
        "error" {
            $StartButtonLabel.Text = "Iniciar"
            $StartButtonPowerIcon.Visibility = [System.Windows.Visibility]::Visible
            $StartButton.Width = 88
            $StartButton.Style = $window.FindResource("PrimaryButton")
            $DiagnoseButton.IsEnabled = $true
            Set-ConfigurationEnabled $true
            Update-Readiness
        }
        default {
            $StartButtonLabel.Text = "Iniciar"
            $StartButtonPowerIcon.Visibility = [System.Windows.Visibility]::Visible
            $StartButton.Width = 88
            $StartButton.Style = $window.FindResource("PrimaryButton")
            $DiagnoseButton.IsEnabled = $true
            Set-ConfigurationEnabled $true
            Update-Readiness
        }
    }
}

function Refresh-Processes {
    $currentProcess = $ManualProcessBox.Text.Trim()
    $ProcessCombo.Items.Clear()
    foreach ($item in Get-VisibleGameProcesses) {
        [void]$ProcessCombo.Items.Add($item)
    }

    $matchedIndex = -1
    if (-not [string]::IsNullOrWhiteSpace($currentProcess)) {
        for ($i = 0; $i -lt $ProcessCombo.Items.Count; $i++) {
            if ([string]::Equals($ProcessCombo.Items[$i].Process, $currentProcess, [System.StringComparison]::OrdinalIgnoreCase)) {
                $matchedIndex = $i
                break
            }
        }
    }

    if ($matchedIndex -ge 0) {
        $ProcessCombo.SelectedIndex = $matchedIndex
    } elseif ([string]::IsNullOrWhiteSpace($currentProcess) -and $ProcessCombo.Items.Count -gt 0) {
        $ProcessCombo.SelectedIndex = 0
    } else {
        $ProcessCombo.SelectedIndex = -1
    }
    Append-Log ("Janelas detectadas: {0}" -f $ProcessCombo.Items.Count)
    Update-Readiness
}

function Update-StateFromLogLine {
    param([string]$Line)
    if ($script:ActiveKind -eq "agent" -and $script:OperationalState -eq "starting") {
        if ($Line -match '(?i)servidor pronto|model loaded, starting environment|starting environment|controle do jogo') {
            Set-OperationalState "running" "Agente em execução"
        }
    }
}

function Read-NewLogLines {
    if (-not $script:RunLogPath -or -not (Test-Path $script:RunLogPath)) {
        return
    }

    $stream = $null
    try {
        $stream = [System.IO.File]::Open($script:RunLogPath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
        if ($script:LogReadPosition -gt $stream.Length) {
            $script:LogReadPosition = 0
        }
        [void]$stream.Seek($script:LogReadPosition, [System.IO.SeekOrigin]::Begin)
        $streamReader = New-Object System.IO.StreamReader($stream, [System.Text.Encoding]::UTF8)
        $text = $streamReader.ReadToEnd()
        $script:LogReadPosition = $stream.Position
        $streamReader.Dispose()
    } catch {
        return
    } finally {
        if ($stream) {
            $stream.Dispose()
        }
    }

    if ([string]::IsNullOrWhiteSpace($text)) {
        return
    }

    foreach ($line in ($text -split "`r?`n")) {
        if (-not [string]::IsNullOrWhiteSpace($line)) {
            Append-Log -Message $line -Mirror:$false
            Update-StateFromLogLine $line
        }
    }
}

function Stop-Agent {
    if ($script:AgentProcess -and -not $script:AgentProcess.HasExited) {
        if ($script:StopRequestedAt) {
            return
        }
        Append-Log "Parada solicitada. Aguardando limpeza segura do controle e do modo de captura..."
        if ($script:StopFilePath) {
            try {
                Set-Content -LiteralPath $script:StopFilePath -Value ("stop requested at {0}" -f (Get-Date -Format "o")) -Encoding UTF8
            } catch {
                Append-Log ("Não consegui criar o sinal de parada: {0}" -f $_.Exception.Message)
            }
        }
        $script:StopRequestedAt = Get-Date
        $script:ForcedStopIssued = $false
        Set-OperationalState "stopping"
    }
}

function Ensure-LocalEnvironment {
    if (Test-Path $VenvPython) {
        return $true
    }
    $answer = [System.Windows.MessageBox]::Show(
        "O ambiente local .venv ainda não existe. Abrir o instalador agora?",
        "NeveLudens",
        [System.Windows.MessageBoxButton]::YesNo,
        [System.Windows.MessageBoxImage]::Warning
    )
    if ($answer -eq [System.Windows.MessageBoxResult]::Yes -and (Test-Path $InstallBat)) {
        Start-Process -FilePath $InstallBat -WorkingDirectory $Repo | Out-Null
    }
    return $false
}

function Start-LoggedPython {
    param(
        [string[]]$Arguments,
        [string]$StartedMessage,
        [ValidateSet("agent", "diagnostic")]
        [string]$Kind
    )

    if (-not (Ensure-LocalEnvironment)) {
        Update-Readiness
        return
    }
    if ($script:ActiveProcess -and -not $script:ActiveProcess.HasExited) {
        Show-Notification "warning" "Operação em andamento" "Aguarde a operação atual terminar antes de iniciar outra." $false
        return
    }

    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $script:RunLogPath = Join-Path $LogsDir ("gui_run_{0}.log" -f $stamp)
    $script:StopFilePath = $null
    $script:StopRequestedAt = $null
    $script:ForcedStopIssued = $false
    if ($Kind -eq "agent") {
        $script:StopFilePath = Join-Path $LogsDir ("gui_stop_{0}.flag" -f $stamp)
        Remove-Item -LiteralPath $script:StopFilePath -Force -ErrorAction SilentlyContinue
        $Arguments = @($Arguments) + @("--stop-file", $script:StopFilePath)
    }

    $script:LogReadPosition = 0
    [System.IO.File]::WriteAllText($script:RunLogPath, "", (New-Object System.Text.UTF8Encoding($false)))
    Append-Log $StartedMessage
    Append-Log ("Log espelho: {0}" -f $script:RunLogPath)
    Append-Log ("Comando: {0} {1}" -f $VenvPython, (Join-CommandLine $Arguments))
    $script:LogReadPosition = (Get-Item -LiteralPath $script:RunLogPath).Length

    $runCmdPath = [System.IO.Path]::ChangeExtension($script:RunLogPath, ".cmd")
    $argText = Join-CommandLine $Arguments
    $cmdLines = @(
        "@echo off",
        "cd /d `"$Repo`"",
        "set PYTHONUTF8=1",
        "set PYTHONUNBUFFERED=1",
        "set `"PYTHONPATH=$Repo;%PYTHONPATH%`"",
        "set BNB_CUDA_VERSION=130",
        "`"$VenvPython`" $argText >> `"$script:RunLogPath`" 2>&1"
    )
    Set-Content -LiteralPath $runCmdPath -Value $cmdLines -Encoding ASCII

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $env:ComSpec
    $psi.WorkingDirectory = $Repo
    $psi.Arguments = "/d /c `"$runCmdPath`""
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.EnvironmentVariables["PYTHONUTF8"] = "1"
    $psi.EnvironmentVariables["PYTHONUNBUFFERED"] = "1"
    $psi.EnvironmentVariables["BNB_CUDA_VERSION"] = "130"

    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    try {
        [void]$proc.Start()
    } catch {
        $message = "Falha ao iniciar o processo: {0}" -f $_.Exception.Message
        Append-Log $message
        Show-Notification "danger" "Não foi possível iniciar" $message $true
        Set-OperationalState "error" "Falha ao iniciar a operação"
        return
    }

    $script:ActiveProcess = $proc
    $script:ActiveKind = $Kind
    $script:LogTimer.Start()
    if ($Kind -eq "agent") {
        $script:AgentProcess = $proc
        Set-OperationalState "starting"
        Sync-CapturePreviewUpdates
    } else {
        Set-OperationalState "diagnosing"
    }
}

function Start-AgentFromUi {
    $processName = Get-SelectedProcessName
    if ([string]::IsNullOrWhiteSpace($processName)) {
        Show-Notification "warning" "Selecione um jogo" "Escolha uma janela detectada ou informe o executável antes de iniciar." $false
        Show-Page "overview"
        return
    }

    Save-UiConfig
    Hide-Notification
    $multimodalMode = if ([bool]$MultimodalSupervisorCheck.IsChecked) { "enabled" } else { "disabled" }
    $launchArgs = @(
        "scripts\launcher.py",
        "--process", $processName,
        "--screenshot-backend", (Get-ComboTag $BackendCombo "auto"),
        "--runtime-mode", (Get-ComboTag $RuntimeModeCombo "precision"),
        "--output-mode", (Get-OutputMode),
        "--game-mode", (Get-ComboTag $GameModeCombo "default"),
        "--model-choice", (Get-ComboTag $ModelCombo "default"),
        "--agent-slot", (Get-ComboTag $AgentSlotCombo "auto"),
        "--multimodal-supervisor", $multimodalMode,
        "--port", "5555",
        "--non-interactive"
    )
    $launchArgs += @("--memory-mode", (Get-ComboTag $MemoryRecoveryCombo "temporary"))
    if ([bool]$ReducedActionHorizonCheck.IsChecked) { $launchArgs += "--reduced-action-horizon" }
    if ([bool]$AutoControlCalibrationCheck.IsChecked) { $launchArgs += "--auto-control-calibration" }
    $launchArgs += if ([bool]$MenuActionsCheck.IsChecked) { "--allow-menu" } else { "--block-menu" }
    Start-LoggedPython -Arguments $launchArgs -StartedMessage ("Iniciando NeveLudens para {0}..." -f $processName) -Kind "agent"
}

function Start-DiagnosticFromUi {
    $processName = Get-SelectedProcessName
    if ([string]::IsNullOrWhiteSpace($processName)) {
        Show-Notification "warning" "Selecione um jogo" "O diagnóstico precisa de uma janela ou processo do jogo." $false
        Show-Page "overview"
        return
    }
    Hide-Notification
    Show-Page "diagnostics"
    $captureArgs = @("scripts\capture_check.py", "--process", $processName, "--backend", "all")
    Start-LoggedPython -Arguments $captureArgs -StartedMessage ("Diagnosticando captura de {0}..." -f $processName) -Kind "diagnostic"
}

function Complete-ActiveProcess {
    Read-NewLogLines
    $exitCode = $script:ActiveProcess.ExitCode
    $kind = $script:ActiveKind
    $stopWasRequested = $null -ne $script:StopRequestedAt
    Append-Log ("Processo encerrado com código {0}" -f $exitCode)
    $script:LogTimer.Stop()
    $script:CaptureTimer.Stop()

    if ($script:StopFilePath) {
        Remove-Item -LiteralPath $script:StopFilePath -Force -ErrorAction SilentlyContinue
    }
    $script:ActiveProcess = $null
    $script:ActiveKind = ""
    $script:AgentProcess = $null
    $script:StopFilePath = $null
    $script:StopRequestedAt = $null
    $script:ForcedStopIssued = $false
    Update-LastCapturePreview

    if ($kind -eq "diagnostic") {
        if ($exitCode -eq 0) {
            Hide-Notification
            Set-OperationalState "idle" "Diagnóstico concluído"
        } else {
            Show-Notification "danger" "Não foi possível verificar a captura" "O diagnóstico terminou com código $exitCode." $true
            Set-OperationalState "error" "Falha no diagnóstico de captura"
        }
    } elseif ($exitCode -eq 0 -or $stopWasRequested -or $exitCode -eq 130) {
        if ($stopWasRequested) {
            Hide-Notification
        }
        Set-OperationalState "idle" "Agente parado"
    } else {
        Show-Notification "danger" "A sessão foi encerrada com erro" "O processo terminou com código $exitCode. Os detalhes estão disponíveis nos logs." $true
        Set-OperationalState "error" "A sessão encontrou um erro"
    }

    if ($script:CloseAfterStop) {
        $script:CloseAfterStop = $false
        $window.Close()
    }
}

$script:LogTimer.Add_Tick({
    try {
        Read-NewLogLines
        if ($script:ActiveProcess -and -not $script:ActiveProcess.HasExited -and $script:StopRequestedAt -and -not $script:ForcedStopIssued) {
            $elapsedStop = ((Get-Date) - $script:StopRequestedAt).TotalSeconds
            if ($elapsedStop -ge $script:ForceStopAfterSeconds) {
                Append-Log ("Parada segura excedeu {0}s. Encerrando processo à força como último recurso." -f $script:ForceStopAfterSeconds)
                $script:ForcedStopIssued = $true
                Stop-ProcessTree -RootProcessId $script:ActiveProcess.Id
            }
        }
        if ($script:ActiveProcess -and $script:ActiveProcess.HasExited) {
            Complete-ActiveProcess
        }
    } catch {
        Append-Log ("Falha ao atualizar a interface: {0}" -f $_.Exception.Message)
    }
})

$script:CaptureTimer.Add_Tick({
    try {
        if ((Get-OutputMode) -ne "debug" -or
            $script:ActiveKind -ne "agent" -or
            -not $script:ActiveProcess -or
            $script:ActiveProcess.HasExited) {
            $script:CaptureTimer.Stop()
            return
        }

        if (Test-Path -LiteralPath $LastCapturePath) {
            $writeTicks = (Get-Item -LiteralPath $LastCapturePath).LastWriteTimeUtc.Ticks
            if ($writeTicks -ne $script:LastCaptureWriteTicks) {
                Update-LastCapturePreview
            }
        }
    } catch {
        # A prévia é opcional e nunca deve interferir na execução do agente.
    }
})

$TitleBar.Add_MouseLeftButtonDown({
    param($sender, $eventArgs)
    if ($eventArgs.ClickCount -eq 2) {
        $window.WindowState = if ($window.WindowState -eq [System.Windows.WindowState]::Maximized) { [System.Windows.WindowState]::Normal } else { [System.Windows.WindowState]::Maximized }
    } elseif ($eventArgs.ButtonState -eq "Pressed") {
        try { $window.DragMove() } catch {}
    }
})

$BtnMinimize.Add_Click({ $window.WindowState = [System.Windows.WindowState]::Minimized })
$BtnMaximize.Add_Click({
    $window.WindowState = if ($window.WindowState -eq [System.Windows.WindowState]::Maximized) { [System.Windows.WindowState]::Normal } else { [System.Windows.WindowState]::Maximized }
})
$BtnClose.Add_Click({ $window.Close() })

$NavOverview.Add_Click({ Show-Page -Page "overview" })
$NavSettings.Add_Click({ Show-Page -Page "settings" })
$NavDiagnostics.Add_Click({ Show-Page -Page "diagnostics" })
$NotificationDetailsButton.Add_Click({ Show-Page "diagnostics" })

$RefreshButton.Add_Click({
    Refresh-Processes
})

$ProcessCombo.Add_SelectionChanged({
    if ($ProcessCombo.SelectedItem) {
        $ManualProcessBox.Text = [string]$ProcessCombo.SelectedItem.Process
    }
    Update-Readiness
})
$ManualProcessBox.Add_TextChanged({ Update-Readiness })

$PresetCombo.Add_SelectionChanged({
    if ($script:LoadingSettings -or $script:ApplyingPreset) {
        return
    }

    $selectedPreset = Get-ComboTag $PresetCombo "default"
    if ($selectedPreset -eq "custom") {
        if (-not $script:CustomPreset) {
            $script:CustomPreset = Get-CurrentUiSettings
        }
        Set-UiSettings $script:CustomPreset
    } else {
        Set-UiSettings (Get-PresetSettings $selectedPreset)
    }
    Update-PresetDescription
    Save-UiConfig
})

$configurationCombos = @($ModelCombo, $BackendCombo, $RuntimeModeCombo, $GameModeCombo, $AgentSlotCombo, $MemoryRecoveryCombo)
foreach ($combo in $configurationCombos) {
    $combo.Add_SelectionChanged({
        Update-Readiness
        Set-CustomPresetFromUi
    })
}
$DetailedOutputCheck.Add_Checked({
    Sync-CapturePreviewUpdates
})
$DetailedOutputCheck.Add_Unchecked({
    Sync-CapturePreviewUpdates
})
$configurationToggles = @($DetailedOutputCheck, $MultimodalSupervisorCheck, $ReducedActionHorizonCheck, $AutoControlCalibrationCheck, $MenuActionsCheck)
foreach ($toggle in $configurationToggles) {
    $toggle.Add_Checked({
        Update-Readiness
        Set-CustomPresetFromUi
    })
    $toggle.Add_Unchecked({
        Update-Readiness
        Set-CustomPresetFromUi
    })
}

$StartButton.Add_Click({
    try {
        if ($script:AgentProcess -and -not $script:AgentProcess.HasExited) {
            Stop-Agent
        } else {
            Start-AgentFromUi
        }
    } catch {
        $message = "Falha ao iniciar: {0}" -f $_.Exception.Message
        Append-Log $message
        Show-Notification "danger" "Não foi possível iniciar" $message $true
        Set-OperationalState "error" "Falha ao iniciar o agente"
    }
})

$DiagnoseButton.Add_Click({
    try {
        Start-DiagnosticFromUi
    } catch {
        $message = "Falha no diagnóstico: {0}" -f $_.Exception.Message
        Append-Log $message
        Show-Notification "danger" "Não foi possível diagnosticar" $message $true
        Set-OperationalState "error" "Falha no diagnóstico"
    }
})

$CopyLogButton.Add_Click({
    try {
        $range = New-Object System.Windows.Documents.TextRange($LogBox.Document.ContentStart, $LogBox.Document.ContentEnd)
        [System.Windows.Clipboard]::SetText($range.Text)
        Hide-Notification
    } catch {
        Show-Notification "warning" "Não foi possível copiar" $_.Exception.Message $false
    }
})

$ClearLogButton.Add_Click({
    $LogBox.Document.Blocks.Clear()
    Hide-Notification
})

$window.Add_Closing({
    param($sender, $eventArgs)
    $script:CaptureTimer.Stop()
    $script:NotificationTimer.Stop()
    Save-UiConfig
    if ($script:ActiveProcess -and -not $script:ActiveProcess.HasExited -and -not $script:CloseAfterStop) {
        $eventArgs.Cancel = $true
        $script:CloseAfterStop = $true
        if ($script:ActiveKind -eq "agent") {
            Stop-Agent
        } else {
            Stop-ProcessTree -RootProcessId $script:ActiveProcess.Id
        }
    }
})

$window.Add_ContentRendered({
    if (-not $script:InitialPageRendered) {
        $script:InitialPageRendered = $true
        Show-Page -Page "overview"
    }
})

Load-UiConfig
Initialize-PresetState
Refresh-Processes
$script:LoadingSettings = $false
Sync-CapturePreviewUpdates
Update-Readiness
Set-OperationalState "idle"
Show-Page "overview"
Append-Log "Interface pronta. Selecione o jogo, confirme a configuração e inicie o agente."
[void]$window.ShowDialog()
