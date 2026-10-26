param([Parameter(Mandatory=$true)][string]$Scene,[Parameter(Mandatory=$true)][string]$Output,[Parameter(Mandatory=$true)][string]$Launch,[ValidateRange(1024,65535)][int]$Port=8767)
$ErrorActionPreference='Stop'
$EditorUrl='http://127.0.0.1:'+[string]$Port
try { $Existing=Invoke-RestMethod -Uri ($EditorUrl+'/status') -TimeoutSec 2 } catch { $Existing=$null }
if ($Existing) { throw ('Port '+$Port+' already serves an editor; inspect it instead of launching a duplicate') }
New-Item -ItemType Directory -Path $Launch | Out-Null
$Stdout=Join-Path $Launch 'stdout.txt'
$Stderr=Join-Path $Launch 'stderr.txt'
$ArgsList=@('-NoProfile','-ExecutionPolicy','Bypass','-File','E:\foundationPos\setup\run_manual_mask_editor.ps1','-Scene',('"'+$Scene+'"'),'-Output',('"'+$Output+'"'),'-Port',[string]$Port)
$Process=Start-Process powershell.exe -ArgumentList $ArgsList -WorkingDirectory E:\foundationPos -WindowStyle Hidden -RedirectStandardOutput $Stdout -RedirectStandardError $Stderr -PassThru
$Info=[ordered]@{created_utc=[DateTime]::UtcNow.ToString('o'); pid=$Process.Id; scene=$Scene; output=$Output; url=$EditorUrl; stdout=$Stdout; stderr=$Stderr; annotation_complete=$false; masks_confirmed_by_agent=$false}
$Info|ConvertTo-Json -Depth 6|Set-Content -LiteralPath (Join-Path $Launch 'launch.json') -Encoding UTF8
$Deadline=[DateTime]::UtcNow.AddSeconds(30)
while([DateTime]::UtcNow -lt $Deadline){
    $Process.Refresh()
    if($Process.HasExited){throw ('Editor exited: '+$Stderr)}
    try{$Status=Invoke-RestMethod -Uri ($EditorUrl+'/status') -TimeoutSec 2}catch{$Status=$null}
    if($Status -and $Status.total_frames -eq 72){
        $Status|ConvertTo-Json -Depth 5|Set-Content -LiteralPath (Join-Path $Launch 'ready.json') -Encoding UTF8
        @{ready=$true;url=$Info.url;scene=$Scene;output=$Output;status=$Status;launch=$Launch}|ConvertTo-Json -Depth 7
        exit 0
    }
    Start-Sleep -Milliseconds 300
}
throw ('Editor readiness timed out; preserve evidence '+$Launch)
