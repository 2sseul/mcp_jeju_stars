# Claude Code 알림 훅: Windows 토스트 알림 + 효과음
# Notification / Stop 훅에서 호출된다. 훅 입력 JSON은 stdin으로 들어온다.
# 한글 문구는 이 파일 안에만 둔다 (PS 5.1에서 인자로 넘기면 콘솔 코드페이지 때문에 깨짐).
# 이 파일은 반드시 UTF-8 BOM으로 저장할 것.
param(
  [ValidateSet('notification', 'stop')]
  [string]$Event = 'notification'
)

$Title = 'Claude Code'
$Message = if ($Event -eq 'stop') { '작업이 완료되었습니다' } else { '입력을 기다리고 있습니다' }

# stdin JSON에 message 필드가 있으면 그걸 우선 사용 (Notification 훅)
try {
  $raw = [Console]::In.ReadToEnd()
  if ($raw) {
    $payload = $raw | ConvertFrom-Json
    if ($payload.message) { $Message = [string]$payload.message }
  }
} catch { }

function Show-Toast($t, $m) {
  [void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
  [void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]

  $tt = [System.Security.SecurityElement]::Escape($t)
  $mm = [System.Security.SecurityElement]::Escape($m)
  $xmlText = @"
<toast>
  <visual>
    <binding template="ToastGeneric">
      <text>$tt</text>
      <text>$mm</text>
    </binding>
  </visual>
  <audio src="ms-winsoundevent:Notification.Default" />
</toast>
"@

  $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
  $xml.LoadXml($xmlText)
  $toast = New-Object Windows.UI.Notifications.ToastNotification $xml
  $appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
  [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show($toast)
}

function Show-Balloon($t, $m) {
  # 토스트가 막혀 있는 환경(집중 지원, 정책 등)을 위한 대체 경로
  Add-Type -AssemblyName System.Windows.Forms
  $icon = New-Object System.Windows.Forms.NotifyIcon
  $icon.Icon = [System.Drawing.SystemIcons]::Information
  $icon.Visible = $true
  $icon.ShowBalloonTip(5000, $t, $m, [System.Windows.Forms.ToolTipIcon]::Info)
  Start-Sleep -Milliseconds 6000
  $icon.Dispose()
}

try { Show-Toast $Title $Message } catch { try { Show-Balloon $Title $Message } catch { } }

# 토스트 오디오와 별개로 확실히 소리가 나도록 시스템 사운드를 재생
try {
  $wav = Join-Path $env:WINDIR 'Media\Windows Notify System Generic.wav'
  if (Test-Path $wav) {
    (New-Object System.Media.SoundPlayer $wav).PlaySync()
  } else {
    [System.Media.SystemSounds]::Asterisk.Play()
    Start-Sleep -Milliseconds 800
  }
} catch { }
