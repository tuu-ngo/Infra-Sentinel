<#
.SYNOPSIS
  Thu thập evidence cho drill mất AZ (Mandate 17 req#2) — chạy 3 lần theo 3 pha.

.DESCRIPTION
  Gom đúng các mục EV-01, EV-02, EV-04, EV-06, EV-07, EV-08 trong
  docs/runbooks/mandate-17-fis-az-drill.md §9. EV-03 (probe ngoài) do
  drill-probe.ps1 chạy liên tục; EV-05 (Grafana) phải quay màn hình tay.

  Mỗi mục chạy trong try/catch riêng: một lệnh hỏng không được làm mất
  những mục còn lại — giữa lúc fault thì mất mạng tới cluster là chuyện
  bình thường, và bản thân việc lệnh timeout cũng là evidence.

.EXAMPLE
  # T-30: trước khi bắn
  .\drill-capture.ps1 -Phase before

  # T+1..T+4: gọi lại vài lần trong lúc fault đang chạy
  .\drill-capture.ps1 -Phase during -ExperimentId EXPxxxxxxxx

  # T+10: sau khi fault đã hết
  .\drill-capture.ps1 -Phase after -ExperimentId EXPxxxxxxxx
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory)][ValidateSet('before', 'during', 'after')][string]$Phase,
  # EXP… — do `aws fis start-experiment` sinh ra. Chỉ dùng cho pha during/after.
  [string]$ExperimentId,
  # EXT… — id template, cố định sau khi terraform apply scope m17-fis.
  [string]$TemplateId = 'EXT9JSZivevPf3Hoe',
  [string]$OutDir  = "$PSScriptRoot\..\..\docs\evidence\mandate-17\drill-evidence",
  [string]$Profile = 'techx-new',
  [string]$Region  = 'ap-southeast-1',
  [string]$Namespace = 'techx-tf3',
  [string]$TargetAz  = 'ap-southeast-1b',
  [string]$AlbDimension = 'app/techx-tf3-frontend-internal/b184898d4ef16831'
)

$env:AWS_PROFILE = $Profile
$env:AWS_REGION  = $Region
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

# Tiền tố số giữ file xếp đúng thứ tự thời gian khi mentor mở thư mục.
$prefix = @{ before = '0'; during = '3'; after = '4' }[$Phase]
$stamp  = (Get-Date).ToUniversalTime().ToString('yyyyMMdd-HHmmss')

function Save-Evidence {
  param([string]$Id, [string]$Title, [scriptblock]$Body)
  $file = Join-Path $OutDir "$prefix$Id-$Phase.txt"
  $head = "# $Title`n# phase=$Phase  utc=$stamp`n" + ('-' * 72)
  try {
    $out = & $Body 2>&1 | Out-String
    "$head`n$out" | Out-File -Encoding utf8 $file
    "  [ok]   $Id  $Title"
  }
  catch {
    "$head`n!! LỆNH LỖI (bản thân điều này cũng là evidence) !!`n$_" | Out-File -Encoding utf8 $file
    "  [FAIL] $Id  $Title  -> $($_.Exception.Message)"
  }
}

"== thu evidence pha '$Phase' -> $OutDir  (UTC $stamp) =="

# Tunnel SSM tự đóng khi session hết hạn. Nếu nó chết mà không ai để ý, mọi mục
# kubectl bên dưới chỉ ghi được thông báo lỗi và ta mất evidence của đúng phút
# quan trọng nhất. Cảnh báo to ngay từ đầu thay vì để phát hiện lúc đọc file.
if (-not (Test-NetConnection -ComputerName 127.0.0.1 -Port 8443 -InformationLevel Quiet -WarningAction SilentlyContinue)) {
  Write-Host "!! TUNNEL SSM (localhost:8443) ĐANG ĐÓNG — các mục kubectl sẽ RỖNG." -ForegroundColor Red
  Write-Host "   Mở lại rồi chạy lại lệnh này:" -ForegroundColor Red
  Write-Host "   bash scripts/kube-tunnel.sh" -ForegroundColor Red
  if ($Phase -eq 'during') {
    # §7 runbook: mất kubectl giữa drill là tiêu chí ABORT — không chạy mù.
    Write-Host "   ĐANG Ở PHA 'during': mất kubectl là tiêu chí ABORT (runbook §7)." -ForegroundColor Red
    Write-Host "   aws fis stop-experiment --id <EXP...> --region $Region" -ForegroundColor Red
  }
  Write-Host ""
}

# --- EV-01: bản đồ node -> AZ -------------------------------------------------
Save-Evidence '0-nodes' 'EV-01 node -> AZ / capacity type' {
  kubectl get nodes -o wide --request-timeout=30s
  "`n--- nhãn zone ---"
  kubectl get nodes --request-timeout=30s -o custom-columns="NODE:.metadata.name,ZONE:.metadata.labels['topology\.kubernetes\.io/zone'],CAPACITY:.metadata.labels['karpenter\.sh/capacity-type'],READY:.status.conditions[-1].type,UNSCHEDULABLE:.spec.unschedulable"
}

# --- EV-06: pod + endpoint ----------------------------------------------------
Save-Evidence '1-pods' 'EV-06 pod trong namespace' {
  kubectl get pods -n $Namespace -o wide --request-timeout=30s
}

Save-Evidence '3-endpoints' 'EV-06 endpoint (endpoint bị gỡ = Service đã loại pod chết)' {
  kubectl get endpoints -n $Namespace --request-timeout=30s
}

# --- EV-02: phân bố theo AZ, tính bằng code chứ không đọc bằng mắt ------------
Save-Evidence '2-placement' "EV-02 phân bố replica theo AZ (mục tiêu: mọi service ra tiền có >=1 replica NGOÀI $TargetAz)" {
  $nodeAz = @{}
  (kubectl get nodes -o json --request-timeout=30s | ConvertFrom-Json).items |
    ForEach-Object { $nodeAz[$_.metadata.name] = $_.metadata.labels.'topology.kubernetes.io/zone' }

  $rows = (kubectl get pods -n $Namespace -o json --request-timeout=30s | ConvertFrom-Json).items |
    Where-Object { $_.status.phase -eq 'Running' } |
    ForEach-Object {
      $app = if ($_.metadata.labels.'app.kubernetes.io/name') { $_.metadata.labels.'app.kubernetes.io/name' }
             elseif ($_.metadata.labels.app)                  { $_.metadata.labels.app }
             else                                             { $_.metadata.ownerReferences[0].name }
      [pscustomobject]@{ App = $app; Node = $_.spec.nodeName; AZ = $nodeAz[$_.spec.nodeName] }
    }

  # BÀI HỌC 30/07: chỉ hỏi "có >=1 replica NGOÀI AZ mục tiêu không" là CHƯA ĐỦ.
  # frontend và frontend-proxy đều có 2/2 replica nằm trọn trong 1c, và vẫn được
  # chấm 'ok' khi mục tiêu là 1b. Khi experiment bị đổi sang 1c thì cả hai chết
  # sạch và storefront API sập. Luôn liệt kê service dồn hết vào MỘT AZ bất kỳ.
  "##### SERVICE CHỈ NẰM TRONG ĐÚNG 1 AZ — mất AZ đó là chết hẳn #####"
  $rows | Group-Object App | ForEach-Object {
    $azs = @($_.Group.AZ | Sort-Object -Unique)
    if ($azs.Count -eq 1) {
      [pscustomobject]@{ App = $_.Name; Replicas = @($_.Group).Count; OnlyAZ = $azs[0] }
    }
  } | Sort-Object OnlyAZ, App | Format-Table -AutoSize

  "##### Phân bố theo AZ mục tiêu ($TargetAz) #####"
  $rows | Group-Object App | Sort-Object Name | ForEach-Object {
    # @() bắt buộc: .Count trên kết quả 1 phần tử trả null trong PS 5.1
    $inTarget = @($_.Group | Where-Object { $_.AZ -eq $TargetAz }).Count
    $total    = @($_.Group).Count
    [pscustomobject]@{
      App       = $_.Name
      Replicas  = $total
      AZs       = (($_.Group.AZ | Sort-Object -Unique) -join ',')
      "In$TargetAz" = $inTarget
      Outside   = $total - $inTarget
      Verdict   = $(if (($total - $inTarget) -ge 1) { 'ok' } else { 'ALL-IN-TARGET-AZ' })
    }
  } | Format-Table -AutoSize
}

# --- EV-04: FIS -----------------------------------------------------------
# CHÚ Ý hai loại id khác nhau, rất dễ nhầm:
#   TemplateId   EXT…  -> bản thiết kế, có sẵn sau khi terraform apply
#   ExperimentId EXP…  -> một lần chạy cụ thể, CHỈ tồn tại sau start-experiment
# Pha 'before' chưa có experiment nào, nên chụp template.
if ($Phase -eq 'before') {
  Save-Evidence '4-template' 'EV-04 template FIS (target, action, stop condition)' {
    aws fis get-experiment-template --id $TemplateId --region $Region --output json
  }

  # BÀI HỌC 30/07: template ĐÃ bị một `terraform apply` chạy local trên máy khác
  # đổi mục tiêu từ 1b sang 1c mà không ai biết. File 04 lúc đó ĐÃ chứa subnet sai
  # nhưng không ai đối chiếu, nên drill bắn nhầm AZ đang chứa 2/2 replica frontend.
  # Từ nay đối chiếu bằng máy, ngay trước khi bắn.
  $tplSubnet = aws fis get-experiment-template --id $TemplateId --region $Region `
    --query "experimentTemplate.targets.*.resourceArns[0]" --output text
  $wantSubnet = aws ec2 describe-subnets --region $Region `
    --filters "Name=tag:Name,Values=techx-corp-tf3-vpc-private-$TargetAz" `
    --query "Subnets[0].SubnetId" --output text
  $tplAz = aws ec2 describe-subnets --region $Region --subnet-ids ($tplSubnet -split '/')[-1] `
    --query "Subnets[0].AvailabilityZone" --output text

  if ($tplAz -ne $TargetAz) {
    Write-Host ""
    Write-Host "!!!!!! DUNG LAI — TEMPLATE DANG NHAM VAO AZ KHAC !!!!!!" -ForegroundColor Red
    Write-Host "   template nham : $tplAz  ($tplSubnet)"              -ForegroundColor Red
    Write-Host "   ban dinh ban  : $TargetAz  ($wantSubnet)"          -ForegroundColor Red
    Write-Host "   KHONG duoc start-experiment cho toi khi khop."      -ForegroundColor Red
    Write-Host "   Kiem ai sua:  aws cloudtrail lookup-events --lookup-attributes ``" -ForegroundColor Red
    Write-Host "     AttributeKey=EventName,AttributeValue=UpdateExperimentTemplate --region $Region" -ForegroundColor Red
    Write-Host ""
  }
  else {
    Write-Host "  [ok]   target khop: template -> $tplAz ($wantSubnet)" -ForegroundColor Green
  }
}
elseif ($ExperimentId) {
  Save-Evidence '4-experiment' 'EV-04 trang thai experiment FIS' {
    aws fis get-experiment --id $ExperimentId --region $Region --output json
  }
}
else {
  "  [bỏ qua] EV-04 — pha '$Phase' cần -ExperimentId (id EXP… do start-experiment sinh ra)"
}

# --- pha BEFORE: ghi lại NACL gốc để pha AFTER đối chiếu ----------------------
# FIS thực hiện disrupt-connectivity bằng cách TRÁO network ACL của subnet sang
# một NACL deny-all rồi trả lại. Không chụp NACL gốc trước thì sau này không có
# gì chứng minh nó đã được trả nguyên trạng (EV-08).
if ($Phase -eq 'before') {
  Save-Evidence '5-nacl-baseline' 'EV-08 baseline: NACL dang gan vao subnet muc tieu' {
    $subnet = aws ec2 describe-subnets --region $Region `
      --filters "Name=tag:Name,Values=techx-corp-tf3-vpc-private-$TargetAz" `
      --query "Subnets[0].SubnetId" --output text
    "subnet=$subnet"
    # Dump nguyen ban, khong --query: it cho hong hon, va nhieu evidence hon.
    aws ec2 describe-network-acls --region $Region `
      --filters "Name=association.subnet-id,Values=$subnet" --output json
  }

  Save-Evidence '6-alarm' 'Điều kiện tiên quyết: alarm stop-condition phải OK' {
    aws cloudwatch describe-alarms --alarm-names tf3-fis-stop-storefront-5xx `
      --region $Region --query 'MetricAlarms[0].{Name:AlarmName,State:StateValue,Updated:StateUpdatedTimestamp}' --output json
  }
}

# --- pha AFTER: chứng minh đã hồi phục + số liệu độc lập từ AWS ---------------
if ($Phase -eq 'after') {
  Save-Evidence '5-nacl-restored' 'EV-08 NACL da tra nguyen trang (so voi 05-nacl-baseline-before.txt)' {
    $subnet = aws ec2 describe-subnets --region $Region `
      --filters "Name=tag:Name,Values=techx-corp-tf3-vpc-private-$TargetAz" `
      --query "Subnets[0].SubnetId" --output text
    "subnet=$subnet"
    aws ec2 describe-network-acls --region $Region `
      --filters "Name=association.subnet-id,Values=$subnet" --output json
  }

  # EV-07 lấy bằng CLI thay vì ảnh chụp console: mentor tự chạy lại được.
  Save-Evidence '7-cloudwatch-alb' 'EV-07 CloudWatch ALB quanh cửa sổ bắn (nguồn độc lập với Prometheus)' {
    $end   = (Get-Date).ToUniversalTime()
    $start = $end.AddMinutes(-45)
    foreach ($m in 'HTTPCode_Target_5XX_Count', 'HTTPCode_Target_2XX_Count', 'RequestCount', 'TargetResponseTime') {
      $stat = if ($m -eq 'TargetResponseTime') { 'Average' } else { 'Sum' }
      "===== $m ($stat, 60s) ====="
      # Chuoi --query dung nhay DOI va build trong 1 bien: '&' trong JMESPath la
      # toan tu goi ham cua PowerShell neu de tran, se lam vo ca script.
      $q = "sort_by(Datapoints,&Timestamp)[].[Timestamp,$stat]"
      aws cloudwatch get-metric-statistics --region $Region `
        --namespace AWS/ApplicationELB --metric-name $m `
        --dimensions "Name=LoadBalancer,Value=$AlbDimension" `
        --start-time $start.ToString('yyyy-MM-ddTHH:mm:ssZ') `
        --end-time   $end.ToString('yyyy-MM-ddTHH:mm:ssZ') `
        --period 60 --statistics $stat `
        --query $q --output text
    }
  }

  Save-Evidence '8-restart-check' 'Pod nào bị restart / tạo lại sau fault' {
    kubectl get pods -n $Namespace --request-timeout=30s `
      -o custom-columns="POD:.metadata.name,AGE:.metadata.creationTimestamp,RESTARTS:.status.containerStatuses[0].restartCount,NODE:.spec.nodeName,PHASE:.status.phase"
    "`n--- sự kiện gần nhất ---"
    kubectl get events -n $Namespace --sort-by=.lastTimestamp --request-timeout=30s
  }
}

""
"== xong. file trong $OutDir =="
Get-ChildItem $OutDir -Filter "$prefix*-$Phase.txt" | Select-Object Name, Length, LastWriteTime | Format-Table -AutoSize
