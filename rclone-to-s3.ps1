[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Position = 0, Mandatory)][IO.FileInfo]$Target
)


echo rclone sync $PSScriptRoot\_out_all cppreference:$Target
echo rclone metadata set myS3:$Target --metadata "Content-Encoding=br" --include "*.html" --include "*.css" --include "*.js" 