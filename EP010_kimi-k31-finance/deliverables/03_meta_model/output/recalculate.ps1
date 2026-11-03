param([string]$WorkbookPath = 'output/meta_model.xlsx')
$ErrorActionPreference = 'Stop'
$p = (Resolve-Path $WorkbookPath).Path
$x = New-Object -ComObject Excel.Application
$x.Visible = $false
$x.DisplayAlerts = $false
try {
    $w = $x.Workbooks.Open($p)
    $x.CalculateFullRebuild()
    $w.Save()
    $w.Close()
    Write-Output 'EXCEL_RECALC_SUCCESS'
} finally {
    $x.Quit()
}
