$ErrorActionPreference = "Stop"

Add-Type -AssemblyName PresentationFramework
Add-Type -AssemblyName PresentationCore
Add-Type -AssemblyName WindowsBase

$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvPython = Join-Path $Repo ".venv\Scripts\python.exe"
$ConfigPath = Join-Path $Repo "neveludens_local_config.json"
$LogsDir = Join-Path $Repo "logs"
$OutDir = Join-Path $Repo "out"
$DebugDir = Join-Path $Repo "debug"
$InstallBat = Join-Path $Repo "instalar.bat"
$script:AgentProcess = $null
$script:ActiveProcess = $null
$script:ActiveIsAgent = $false
$script:RunLogPath = $null
$script:LogReadPosition = 0

New-Item -ItemType Directory -Force -Path $LogsDir, $OutDir, $DebugDir | Out-Null
Set-Location $Repo

function Set-LocalEnvironment {
    $env:PYTHONUTF8 = "1"
    $env:PYTHONUNBUFFERED = "1"
    $env:DEBUG = "0"
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

function Get-SavedProcessName {
    if (-not (Test-Path $ConfigPath)) {
        return ""
    }
    try {
        $config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
        if ($config.process) {
            return [string]$config.process
        }
    } catch {
        return ""
    }
    return ""
}

function Limit-MenuText {
    param(
        [string]$Text,
        [int]$MaxLength = 44
    )
    if ([string]::IsNullOrWhiteSpace($Text) -or $Text.Length -le $MaxLength) {
        return $Text
    }
    return $Text.Substring(0, $MaxLength - 1) + "…"
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
        Sort-Object ProcessName |
        ForEach-Object {
            $exe = $_.ProcessName
            if (-not $exe.ToLowerInvariant().EndsWith(".exe")) {
                $exe = "$exe.exe"
            }
            $display = "{0}   PID {1}   {2}" -f $exe, $_.Id, $_.MainWindowTitle
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

$xaml = @"
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="NeveLudens - Iniciar"
        Width="840" Height="640"
        WindowStartupLocation="CenterScreen"
        ResizeMode="NoResize"
        WindowStyle="None"
        AllowsTransparency="True"
        Background="Transparent"
        FontFamily="Segoe UI Variable, Segoe UI">
    <Window.Resources>
        <Style x:Key="PrimaryBtn" TargetType="Button">
            <Setter Property="Background" Value="#111111"/>
            <Setter Property="Foreground" Value="White"/>
            <Setter Property="BorderThickness" Value="0"/>
            <Setter Property="Padding" Value="22,9"/>
            <Setter Property="FontSize" Value="13"/>
            <Setter Property="FontWeight" Value="SemiBold"/>
            <Setter Property="Cursor" Value="Hand"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Button">
                        <Border x:Name="bd" Background="{TemplateBinding Background}" CornerRadius="8" Padding="{TemplateBinding Padding}">
                            <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
                        </Border>
                        <ControlTemplate.Triggers>
                            <Trigger Property="IsMouseOver" Value="True">
                                <Setter TargetName="bd" Property="Background" Value="#262626"/>
                            </Trigger>
                            <Trigger Property="IsEnabled" Value="False">
                                <Setter TargetName="bd" Property="Opacity" Value="0.4"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

        <Style x:Key="GhostBtn" TargetType="Button" BasedOn="{StaticResource PrimaryBtn}">
            <Setter Property="Background" Value="#F4F4F5"/>
            <Setter Property="Foreground" Value="#111111"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Button">
                        <Border x:Name="bd" Background="{TemplateBinding Background}" CornerRadius="8" Padding="{TemplateBinding Padding}">
                            <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
                        </Border>
                        <ControlTemplate.Triggers>
                            <Trigger Property="IsMouseOver" Value="True">
                                <Setter TargetName="bd" Property="Background" Value="#E4E4E7"/>
                            </Trigger>
                            <Trigger Property="IsEnabled" Value="False">
                                <Setter TargetName="bd" Property="Opacity" Value="0.45"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

        <Style x:Key="DangerBtn" TargetType="Button" BasedOn="{StaticResource PrimaryBtn}">
            <Setter Property="Background" Value="#DC2626"/>
            <Setter Property="Foreground" Value="White"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Button">
                        <Border x:Name="bd" Background="{TemplateBinding Background}" CornerRadius="8" Padding="{TemplateBinding Padding}">
                            <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
                        </Border>
                        <ControlTemplate.Triggers>
                            <Trigger Property="IsMouseOver" Value="True">
                                <Setter TargetName="bd" Property="Background" Value="#B91C1C"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

        <Style x:Key="WindowCloseBtn" TargetType="Button">
            <Setter Property="Width" Value="44"/>
            <Setter Property="Height" Value="32"/>
            <Setter Property="Background" Value="Transparent"/>
            <Setter Property="Foreground" Value="#71717A"/>
            <Setter Property="BorderThickness" Value="0"/>
            <Setter Property="FontSize" Value="22"/>
            <Setter Property="Cursor" Value="Hand"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Button">
                        <Border x:Name="bd" Background="{TemplateBinding Background}" CornerRadius="6">
                            <TextBlock Text="{TemplateBinding Content}" Foreground="{TemplateBinding Foreground}" FontSize="{TemplateBinding FontSize}"
                                       HorizontalAlignment="Center" VerticalAlignment="Center" Margin="0,-5,0,0"/>
                        </Border>
                        <ControlTemplate.Triggers>
                            <Trigger Property="IsMouseOver" Value="True">
                                <Setter TargetName="bd" Property="Background" Value="#E4E4E7"/>
                                <Setter Property="Foreground" Value="#111111"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

        <Style x:Key="Card" TargetType="Border">
            <Setter Property="Background" Value="White"/>
            <Setter Property="BorderBrush" Value="#E4E4E7"/>
            <Setter Property="BorderThickness" Value="1"/>
            <Setter Property="CornerRadius" Value="10"/>
            <Setter Property="Padding" Value="20"/>
        </Style>

        <Style TargetType="ComboBox">
            <Setter Property="FontSize" Value="13"/>
            <Setter Property="Padding" Value="8,4"/>
            <Setter Property="MinHeight" Value="32"/>
            <Setter Property="MaxDropDownHeight" Value="220"/>
        </Style>

        <Style TargetType="TextBox">
            <Setter Property="FontSize" Value="13"/>
            <Setter Property="Padding" Value="8,5"/>
            <Setter Property="MinHeight" Value="32"/>
        </Style>

        <Style x:Key="ToggleCheck" TargetType="CheckBox">
            <Setter Property="FontSize" Value="13"/>
            <Setter Property="Foreground" Value="#111111"/>
            <Setter Property="Cursor" Value="Hand"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="CheckBox">
                        <Grid>
                            <Grid.ColumnDefinitions>
                                <ColumnDefinition Width="Auto"/>
                                <ColumnDefinition Width="*"/>
                            </Grid.ColumnDefinitions>
                            <Border x:Name="SwitchTrack" Width="42" Height="24" CornerRadius="12" Background="#D4D4D8">
                                <Ellipse x:Name="SwitchThumb" Width="18" Height="18" Fill="White" Margin="3" HorizontalAlignment="Left"/>
                            </Border>
                            <ContentPresenter Grid.Column="1" Margin="10,0,0,0" VerticalAlignment="Center"/>
                        </Grid>
                        <ControlTemplate.Triggers>
                            <Trigger Property="IsChecked" Value="True">
                                <Setter TargetName="SwitchTrack" Property="Background" Value="#111111"/>
                                <Setter TargetName="SwitchThumb" Property="HorizontalAlignment" Value="Right"/>
                            </Trigger>
                            <Trigger Property="IsEnabled" Value="False">
                                <Setter TargetName="SwitchTrack" Property="Opacity" Value="0.45"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>
    </Window.Resources>

    <Border CornerRadius="14" Background="#FAFAFA" BorderBrush="#E4E4E7" BorderThickness="1">
        <Grid>
            <Grid.RowDefinitions>
                <RowDefinition Height="56"/>
                <RowDefinition Height="*"/>
                <RowDefinition Height="68"/>
            </Grid.RowDefinitions>

            <Grid x:Name="TitleBar" Grid.Row="0" Background="Transparent">
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="Auto"/>
                </Grid.ColumnDefinitions>
                <StackPanel Orientation="Horizontal" Margin="18,0,0,0" VerticalAlignment="Center">
                    <TextBlock Text="NeveLudens" FontSize="15" FontWeight="SemiBold" Foreground="#111111" VerticalAlignment="Center"/>
                    <TextBlock Text="  ·  Iniciar" FontSize="13" Foreground="#71717A" VerticalAlignment="Center"/>
                </StackPanel>
                <StackPanel Grid.Column="1" Orientation="Horizontal" Margin="0,0,12,0" VerticalAlignment="Center">
                    <Button x:Name="BtnMinimize" Content="−" Style="{StaticResource WindowCloseBtn}" Margin="0,0,2,0"/>
                    <Button x:Name="BtnClose" Content="×" Style="{StaticResource WindowCloseBtn}"/>
                </StackPanel>
            </Grid>

            <Grid Grid.Row="1" Margin="32,8,32,0">
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="310"/>
                    <ColumnDefinition Width="28"/>
                    <ColumnDefinition Width="*"/>
                </Grid.ColumnDefinitions>

                <StackPanel Grid.Column="0">
                    <TextBlock Text="Jogo" FontSize="22" FontWeight="SemiBold" Foreground="#111111"/>
                    <TextBlock Text="Escolha o processo e o modo de captura." FontSize="13" Foreground="#71717A" Margin="0,4,0,16"/>

                    <Border Style="{StaticResource Card}">
                        <Grid>
                            <Grid.RowDefinitions>
                                <RowDefinition Height="Auto"/>
                                <RowDefinition Height="Auto"/>
                                <RowDefinition Height="Auto"/>
                                <RowDefinition Height="Auto"/>
                                <RowDefinition Height="Auto"/>
                                <RowDefinition Height="Auto"/>
                                <RowDefinition Height="Auto"/>
                                <RowDefinition Height="Auto"/>
                            </Grid.RowDefinitions>

                            <TextBlock Grid.Row="0" Text="Janela detectada:" FontSize="13" Foreground="#52525B" Margin="0,0,0,6"/>
                            <ComboBox Grid.Row="1" x:Name="ProcessCombo" Margin="0,0,0,12"
                                      ScrollViewer.HorizontalScrollBarVisibility="Disabled">
                                <ComboBox.ItemTemplate>
                                    <DataTemplate>
                                        <TextBlock Text="{Binding Display}" Width="224" TextTrimming="CharacterEllipsis"
                                                   ToolTip="{Binding FullDisplay}"/>
                                    </DataTemplate>
                                </ComboBox.ItemTemplate>
                            </ComboBox>

                            <TextBlock Grid.Row="2" Text="Processo do jogo (.exe):" FontSize="13" Foreground="#52525B" Margin="0,0,0,6"/>
                            <TextBox Grid.Row="3" x:Name="ManualProcessBox" Margin="0,0,0,12"/>

                            <StackPanel Grid.Row="4">
                                <TextBlock Text="Captura:" FontSize="13" Foreground="#52525B" Margin="0,0,0,6"/>
                                <ComboBox x:Name="BackendCombo">
                                    <ComboBoxItem Content="Automático" Tag="auto" IsSelected="True"/>
                                    <ComboBoxItem Content="DXcam" Tag="dxcam"/>
                                    <ComboBoxItem Content="PyAutoGUI" Tag="pyautogui"/>
                                </ComboBox>
                            </StackPanel>

                            <StackPanel Grid.Row="5" Margin="0,12,0,0">
                                <TextBlock Text="Modo:" FontSize="13" Foreground="#52525B" Margin="0,0,0,6"/>
                                <ComboBox x:Name="RuntimeModeCombo">
                                    <ComboBoxItem Content="Precisão" Tag="precision" IsSelected="True"/>
                                    <ComboBoxItem Content="Tempo real" Tag="realtime"/>
                                </ComboBox>
                            </StackPanel>

                            <StackPanel Grid.Row="6" Margin="0,12,0,0">
                                <CheckBox x:Name="MenuActionsCheck" Content="Permitir ações de menu" IsChecked="True"
                                          Style="{StaticResource ToggleCheck}"/>
                            </StackPanel>

                            <Button Grid.Row="7" x:Name="RefreshButton" Content="Atualizar" Style="{StaticResource GhostBtn}"
                                    HorizontalAlignment="Right" Margin="0,18,0,0"/>
                        </Grid>
                    </Border>
                </StackPanel>

                <Border Grid.Column="1" Width="1" Background="#E4E4E7" Margin="0,4,0,0"/>

                <Grid Grid.Column="2">
                    <Grid.RowDefinitions>
                        <RowDefinition Height="Auto"/>
                        <RowDefinition Height="*"/>
                    </Grid.RowDefinitions>
                    <StackPanel Grid.Row="0" Margin="0,0,0,16">
                        <TextBlock Text="Execução" FontSize="22" FontWeight="SemiBold" Foreground="#111111"/>
                        <TextBlock Text="Acompanhe o log de execução." FontSize="13" Foreground="#71717A" Margin="0,4,0,0"/>
                    </StackPanel>

                    <Border Grid.Row="1" Background="#0A0A0A" CornerRadius="10" Padding="14,12">
                        <TextBox x:Name="LogBox" Background="Transparent" Foreground="#D4D4D4" BorderThickness="0"
                                 IsReadOnly="True" FontFamily="Consolas" FontSize="11" TextWrapping="Wrap"
                                 AcceptsReturn="True" VerticalScrollBarVisibility="Auto" HorizontalScrollBarVisibility="Disabled"/>
                    </Border>
                </Grid>
            </Grid>

            <Border Grid.Row="2" BorderBrush="#EEEEEE" BorderThickness="0,1,0,0" Padding="32,0,32,0">
                <StackPanel Orientation="Horizontal" HorizontalAlignment="Right" VerticalAlignment="Center">
                    <Button x:Name="DiagnoseButton" Style="{StaticResource GhostBtn}" Content="Diagnosticar" Margin="0,0,10,0"/>
                    <Button x:Name="StartButton" Style="{StaticResource PrimaryBtn}" Content="Iniciar"/>
                </StackPanel>
            </Border>
        </Grid>
    </Border>
</Window>
"@

$reader = New-Object System.Xml.XmlNodeReader ([xml]$xaml)
$window = [Windows.Markup.XamlReader]::Load($reader)

$TitleBar = $window.FindName("TitleBar")
$BtnMinimize = $window.FindName("BtnMinimize")
$BtnClose = $window.FindName("BtnClose")
$ProcessCombo = $window.FindName("ProcessCombo")
$ManualProcessBox = $window.FindName("ManualProcessBox")
$BackendCombo = $window.FindName("BackendCombo")
$RuntimeModeCombo = $window.FindName("RuntimeModeCombo")
$MenuActionsCheck = $window.FindName("MenuActionsCheck")
$RefreshButton = $window.FindName("RefreshButton")
$StartButton = $window.FindName("StartButton")
$DiagnoseButton = $window.FindName("DiagnoseButton")
$LogBox = $window.FindName("LogBox")
$script:LogTimer = New-Object System.Windows.Threading.DispatcherTimer
$script:LogTimer.Interval = [TimeSpan]::FromMilliseconds(500)

function Append-Log {
    param(
        [string]$Message,
        [bool]$Mirror = $true
    )
    if ([string]::IsNullOrWhiteSpace($Message)) {
        return
    }

    $writeUi = [Action]{
        $LogBox.AppendText($Message + "`r`n")
        $LogBox.ScrollToEnd()
    }

    try {
        if ($window.Dispatcher.CheckAccess()) {
            $writeUi.Invoke()
        } else {
            $window.Dispatcher.Invoke($writeUi)
        }
    } catch {
        return
    }

    if ($Mirror -and $script:RunLogPath) {
        try {
            Add-Content -LiteralPath $script:RunLogPath -Value $Message -Encoding UTF8
        } catch {}
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
        $reader = New-Object System.IO.StreamReader($stream, [System.Text.Encoding]::UTF8)
        $text = $reader.ReadToEnd()
        $script:LogReadPosition = $stream.Position
        $reader.Dispose()
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

function Get-BackendName {
    $selected = $BackendCombo.SelectedItem
    if ($selected -and $selected.Tag) {
        return [string]$selected.Tag
    }
    return "auto"
}

function Get-RuntimeMode {
    $selected = $RuntimeModeCombo.SelectedItem
    if ($selected -and $selected.Tag) {
        return [string]$selected.Tag
    }
    return "precision"
}

function Get-AllowMenuActions {
    return [bool]$MenuActionsCheck.IsChecked
}

function Set-RunButtonState {
    param([bool]$Running)
    if ($Running) {
        $StartButton.Content = "Parar"
        $StartButton.Style = $window.FindResource("DangerBtn")
        $DiagnoseButton.IsEnabled = $false
    } else {
        $StartButton.Content = "Iniciar"
        $StartButton.Style = $window.FindResource("PrimaryBtn")
        $DiagnoseButton.IsEnabled = $true
    }
}

function Stop-Agent {
    if ($script:AgentProcess -and -not $script:AgentProcess.HasExited) {
        Append-Log "Parada solicitada pelo usuário."
        Stop-ProcessTree -RootProcessId $script:AgentProcess.Id
    }
    Set-RunButtonState -Running $false
}

function Start-LoggedPython {
    param(
        [string[]]$Arguments,
        [string]$StartedMessage,
        [switch]$IsAgent
    )

    if (-not (Test-Path $VenvPython)) {
        $answer = [System.Windows.MessageBox]::Show(
            "O ambiente local .venv ainda não existe. Abrir o instalador agora?",
            "NeveLudens",
            [System.Windows.MessageBoxButton]::YesNo,
            [System.Windows.MessageBoxImage]::Warning
        )
        if ($answer -eq [System.Windows.MessageBoxResult]::Yes -and (Test-Path $InstallBat)) {
            Start-Process -FilePath $InstallBat -WorkingDirectory $Repo | Out-Null
        }
        return
    }

    if ($script:ActiveProcess -and -not $script:ActiveProcess.HasExited) {
        [System.Windows.MessageBox]::Show("Já existe uma execução em andamento. Aguarde terminar ou pare o agente atual.", "NeveLudens") | Out-Null
        return
    }

    $script:RunLogPath = Join-Path $LogsDir ("gui_run_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
    $script:LogReadPosition = 0
    Set-Content -LiteralPath $script:RunLogPath -Value @() -Encoding UTF8
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

    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi

    try {
        [void]$proc.Start()
    } catch {
        $message = "Falha ao iniciar o processo: {0}" -f $_.Exception.Message
        Append-Log $message
        [System.Windows.MessageBox]::Show($message, "NeveLudens") | Out-Null
        Set-RunButtonState -Running $false
        return
    }

    $script:ActiveProcess = $proc
    $script:ActiveIsAgent = [bool]$IsAgent
    $DiagnoseButton.IsEnabled = $false
    $script:LogTimer.Start()

    if ($IsAgent) {
        $script:AgentProcess = $proc
        Set-RunButtonState -Running $true
    }
}

$script:LogTimer.Add_Tick({
    try {
        Read-NewLogLines
        if ($script:ActiveProcess -and $script:ActiveProcess.HasExited) {
            Read-NewLogLines
            $exitCode = $script:ActiveProcess.ExitCode
            $wasAgent = $script:ActiveIsAgent
            Append-Log ("Processo encerrado com código {0}" -f $exitCode)
            $script:LogTimer.Stop()
            $script:ActiveProcess = $null
            $script:ActiveIsAgent = $false
            $script:AgentProcess = $null
            Set-RunButtonState -Running $false
            if (-not $wasAgent) {
                $DiagnoseButton.IsEnabled = $true
            }
        }
    } catch {}
})

$TitleBar.Add_MouseLeftButtonDown({
    param($sender, $eventArgs)
    if ($eventArgs.ButtonState -eq "Pressed") {
        try { $window.DragMove() } catch {}
    }
})

$BtnClose.Add_Click({ $window.Close() })
$BtnMinimize.Add_Click({ $window.WindowState = "Minimized" })
$RefreshButton.Add_Click({ Refresh-Processes })

$ProcessCombo.Add_SelectionChanged({
    if ($ProcessCombo.SelectedItem) {
        $ManualProcessBox.Text = [string]$ProcessCombo.SelectedItem.Process
    }
})

$StartButton.Add_Click({
    try {
        if ($script:AgentProcess -and -not $script:AgentProcess.HasExited) {
            Stop-Agent
            return
        }

        $processName = Get-SelectedProcessName
        if ([string]::IsNullOrWhiteSpace($processName)) {
            [System.Windows.MessageBox]::Show("Escolha uma janela da lista ou digite o .exe do jogo.", "NeveLudens") | Out-Null
            return
        }
        $launchArgs = @(
            "scripts\launcher.py",
            "--process", $processName,
            "--screenshot-backend", (Get-BackendName),
            "--runtime-mode", (Get-RuntimeMode),
            "--port", "5555",
            "--non-interactive"
        )
        if (Get-AllowMenuActions) {
            $launchArgs += "--allow-menu"
        } else {
            $launchArgs += "--block-menu"
        }
        Start-LoggedPython -Arguments $launchArgs -StartedMessage ("Iniciando NeveLudens para {0}..." -f $processName) -IsAgent
    } catch {
        $message = "Falha ao iniciar: {0}" -f $_.Exception.Message
        Append-Log $message
        [System.Windows.MessageBox]::Show($message, "NeveLudens") | Out-Null
        Set-RunButtonState -Running $false
    }
})

$DiagnoseButton.Add_Click({
    try {
        $processName = Get-SelectedProcessName
        if ([string]::IsNullOrWhiteSpace($processName)) {
            [System.Windows.MessageBox]::Show("Escolha uma janela da lista ou digite o .exe do jogo.", "NeveLudens") | Out-Null
            return
        }
        $captureArgs = @("scripts\capture_check.py", "--process", $processName, "--backend", "all")
        Start-LoggedPython -Arguments $captureArgs -StartedMessage ("Diagnosticando captura de {0}..." -f $processName)
    } catch {
        $message = "Falha no diagnóstico: {0}" -f $_.Exception.Message
        Append-Log $message
        [System.Windows.MessageBox]::Show($message, "NeveLudens") | Out-Null
    }
})

$window.Add_Closing({
    if ($script:ActiveProcess -and -not $script:ActiveProcess.HasExited) {
        Stop-ProcessTree -RootProcessId $script:ActiveProcess.Id
    }
})

$saved = Get-SavedProcessName
if ($saved) {
    $ManualProcessBox.Text = $saved
}
Refresh-Processes
Append-Log "Interface pronta. Abra o jogo, selecione o processo e clique em Iniciar."
[void]$window.ShowDialog()
