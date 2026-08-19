<#
.SYNOPSIS
  EV-03 — probe liên tục từ NGOÀI cluster trong suốt drill mất AZ.

.DESCRIPTION
  Đây là bằng chứng MẠNH NHẤT của bài drill, vì hai lý do:
    1. Đúng góc nhìn khách hàng — không phải chỉ số nội bộ tự chấm điểm mình.
    2. Nó chạy trên máy bạn, nên sống sót kể cả khi drill làm gãy Prometheus,
       Jaeger, OpenSearch hay đường kubectl.

  Ghi mỗi dòng một mốc, kèm UTC, và flush ngay xuống đĩa từng dòng — mất điện
  giữa chừng vẫn còn dữ liệu tới giây cuối.

  Chạy TRƯỚC khi bắn ít nhất 5 phút (để có "before" sạch) và để nguyên cho tới
  ít nhất 10 phút sau khi fault kết thúc. Dừng bằng Ctrl+C.

.EXAMPLE
  .\drill-probe.ps1
  .\drill-probe.ps1 -IntervalSeconds 2 -OutFile .\10-external-probe.log
#>
[CmdletBinding()]
param(
  [string]$BaseUrl = 'https://d2tn71186d7ilz.cloudfront.net',
  [string[]]$Paths = @('/', '/api/products', '/api/cart'),
  [int]$IntervalSeconds = 2,
  [int]$TimeoutSeconds  = 10,
  [string]$OutFile = "$PSScriptRoot\..\..\docs\evidence\mandate-17\drill-evidence\10-external-probe.log"
)

# .NET giữ current-directory RIÊNG, không theo `cd` của PowerShell. Nếu để $OutFile
# tương đối, StreamWriter sẽ ghi vào một chỗ khác (hoặc fail) và $writer thành null —
# probe chết ngay dòng đầu, đúng lúc cần nó nhất. Ép tuyệt đối trước khi làm gì khác.
$OutFile = [System.IO.Path]::GetFullPath(
  [System.IO.Path]::Combine((Get-Location -PSProvider FileSystem).ProviderPath, $OutFile))
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutFile) | Out-Null

$header = @(
  "# EV-03 probe ngoài cluster — Mandate 17 req#2 AZ drill"
  "# base=$BaseUrl  paths=$($Paths -join ' ')  interval=${IntervalSeconds}s  timeout=${TimeoutSeconds}s"
  "# bắt đầu (UTC): $((Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'))"
  "# cột: <utc> " + (($Paths | ForEach-Object { "<code$_ ms$_>" }) -join ' ')
  ('-' * 78)
)
$header | Out-File -Encoding utf8 $OutFile
$header | Write-Host

# StreamWriter với AutoFlush: mỗi dòng xuống đĩa ngay, không đệm.
$writer = [System.IO.StreamWriter]::new($OutFile, $true, [System.Text.Encoding]::UTF8)
$writer.AutoFlush = $true

$total = 0; $bad = 0
try {
  while ($true) {
    $utc   = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    $parts = foreach ($p in $Paths) {
      # curl.exe chứ không phải Invoke-WebRequest: IWR ném exception khi gặp
      # mã lỗi HTTP và sẽ làm đứt vòng lặp đúng vào lúc ta cần dữ liệu nhất.
      $r = & curl.exe -s -o NUL -w '%{http_code} %{time_total}' --max-time $TimeoutSeconds "$BaseUrl$p" 2>$null
      if ([string]::IsNullOrWhiteSpace($r)) { $r = '000 timeout' }
      $code = ($r -split '\s+')[0]
      $total++
      if ($code -notmatch '^2\d\d$|^3\d\d$') { $bad++ }
      $r
    }
    $line = "$utc  " + ($parts -join '  ')
    $writer.WriteLine($line)

    # Tô màu để người trực nhìn thấy ngay, không phải đọc log.
    if ($line -match '\s5\d\d\s|\s000\s') { Write-Host $line -ForegroundColor Red }
    elseif ($line -match '\s4\d\d\s')     { Write-Host $line -ForegroundColor Yellow }
    else                                   { Write-Host $line }

    Start-Sleep -Seconds $IntervalSeconds
  }
}
finally {
  $summary = @(
    ('-' * 78)
    "# kết thúc (UTC): $((Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'))"
    "# tổng request: $total   không-thành-công: $bad"
  )
  $summary | ForEach-Object { $writer.WriteLine($_) }
  $writer.Close()
  $summary | Write-Host
  Write-Host "log: $OutFile"
}
