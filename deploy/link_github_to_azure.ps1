# Lets the GitHub "deploy" workflow update the Azure Container App, without storing any password
# or key in GitHub. Run once, by the Azure subscription owner, after the Container App exists:
#
#     .\deploy\link_github_to_azure.ps1
#
# What it creates in Azure:
#   1. An app registration and service principal named github-aviation-deploy: an identity for the workflow.
#   2. A federated credential: Azure accepts this identity's sign-in ONLY from GitHub Actions runs of
#      IsaacMcCalla/aviation-accident-analytics on the main branch (OpenID Connect; nothing to leak).
#      GitHub's tokens name the repository with its owner and repository ID numbers
#      (repo:IsaacMcCalla@744968/aviation-accident-analytics@1437579775:ref:refs/heads/main), so a
#      deleted-and-recreated repository with the same name can't inherit access. The script looks the
#      IDs up; a subject without them fails with AADSTS700213 "No matching federated identity record".
#   3. A Contributor role assignment scoped to the aviation-dashboard Container App only: the workflow
#      can update that one app and nothing else in the subscription.
# It then prints the five values to add as GitHub repository variables (they are IDs, not secrets).
#
# To undo: az ad app delete --id <AZURE_CLIENT_ID>   (removes the identity and its access)

$ErrorActionPreference = "Stop"
$az = "C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"
$repo = "IsaacMcCalla/aviation-accident-analytics"
$group = "rg-aviation-dashboard"
$app = "aviation-dashboard"

$clientId = & $az ad app create --display-name github-aviation-deploy --query appId --output tsv --only-show-errors
& $az ad sp create --id $clientId --only-show-errors --output none

$gh = Invoke-RestMethod -Headers @{ "User-Agent" = "aviation-accident-analytics" } "https://api.github.com/repos/$repo"
$owner, $name = $repo.Split("/")
$credential = @{
    name        = "github-main-branch"
    issuer      = "https://token.actions.githubusercontent.com"
    subject     = "repo:${owner}@$($gh.owner.id)/${name}@$($gh.id):ref:refs/heads/main"
    description = "GitHub Actions deploy workflow, main branch only"
    audiences   = @("api://AzureADTokenExchange")
} | ConvertTo-Json
$credentialFile = New-TemporaryFile
Set-Content -Path $credentialFile -Value $credential -Encoding utf8
& $az ad app federated-credential create --id $clientId --parameters "@$credentialFile" --only-show-errors --output none
Remove-Item $credentialFile

$scope = & $az containerapp show --name $app --resource-group $group --query id --output tsv
# a brand-new service principal can take a minute to be usable for role assignments; retry briefly
for ($i = 0; $i -lt 8; $i++) {
    & $az role assignment create --assignee $clientId --role Contributor --scope $scope --only-show-errors --output none 2>$null
    if ($LASTEXITCODE -eq 0) { break }
    Start-Sleep -Seconds 15
}
if ($LASTEXITCODE -ne 0) { throw "role assignment failed; run the script again in a minute" }

Write-Host ""
Write-Host "Done. Add these as GitHub repository VARIABLES (not secrets):"
Write-Host "  github.com/$repo > Settings > Secrets and variables > Actions > Variables tab > New repository variable"
Write-Host ""
Write-Host "  AZURE_CLIENT_ID        $clientId"
Write-Host "  AZURE_TENANT_ID        $(& $az account show --query tenantId --output tsv)"
Write-Host "  AZURE_SUBSCRIPTION_ID  $(& $az account show --query id --output tsv)"
Write-Host "  AZURE_RESOURCE_GROUP   $group"
Write-Host "  AZURE_CONTAINERAPP     $app"
