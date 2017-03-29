#ps1_sysnative

$ManagerBlueprintsPath = "C:\cloudify-cli\cloudify-manager-blueprints"
$ManagerBlueprintPath = "$ManagerBlueprintsPath\simple-manager-blueprint.yaml"
$InputsFilePath = "$env:Temp\bootstrap_inputs.yaml"
$CliDestinationPath = "$env:Temp\cloudify-cli.exe"

$CliPackageUrl = $args[0]
$PrivateKeyPath = $args[1]
$PublicIP = $args[2]
$PrivateIP = $args[3]
$User = $args[4]

Write-Host "Downloading CLI package.."
$client = New-Object System.Net.WebClient
$client.DownloadFile($CliPackageUrl, $CliDestinationPath)

Write-Host "Installing CLI package.."
$CliDestinationPath /SILENT /VERYSILENT /SUPPRESSMSGBOXES

Write-Host "Creating inputs file.."
$BootstrapInputs = "public_ip: $PublicIP
private_ip: $PrivateIP
ssh_user: $User
ssh_key_filename: $PrivateKeyPath
admin_username: admin
admin_password: admin"

Out-File -FilePath $InputsFilePath -InputObject $BootstrapInputs

Write-Host "Bootstrapping cloudify manager.."
C:\cloudify-cli\embedded\Scripts\cfy.exe bootstrap $ManagerBlueprintPath -i $InputsFilePath -v --keep-up-on-failure
C:\cloudify-cli\embedded\Scripts\cfy.exe status

Write-Host "Bootstrap completed successfully!"
