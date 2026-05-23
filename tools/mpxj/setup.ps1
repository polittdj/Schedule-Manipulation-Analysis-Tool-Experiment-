<#
.SYNOPSIS
    Install MPXJ (the native .mpp reader) locally for Schedule Forensics on Windows.

.DESCRIPTION
    The Windows equivalent of setup.sh. Requires Java (JDK >= 17) and Maven (mvn) on
    PATH. Produces, next to this script, .\lib (MPXJ + its dependency jars) and
    .\classes (the compiled MpxjToMspdi converter). Then enable native .mpp parsing
    in the CLI and the web UI by pointing the tool at this directory:

        $env:SF_MPXJ_HOME = "<this directory>"   # current PowerShell session
        setx SF_MPXJ_HOME "<this directory>"      # persist for new sessions

    LAW 1: everything here runs locally; no schedule data leaves the machine.

.NOTES
    Native .mpp on Windows can also be read through your installed MS Project via the
    COM path (no Java needed) -- pick "MS Project" in the web UI's reader choice. MPXJ
    is the cross-platform alternative this script installs.
#>
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$MpxjVersion = if ($env:MPXJ_VERSION) { $env:MPXJ_VERSION } else { "16.2.0" }

foreach ($req in @(
        @{ Name = "java"; Hint = "install a JDK >= 17" },
        @{ Name = "mvn"; Hint = "install Apache Maven" })) {
    if (-not (Get-Command $req.Name -ErrorAction SilentlyContinue)) {
        Write-Error "ERROR: $($req.Name) not found ($($req.Hint))."
        exit 1
    }
}

# pom.xml is generated here because the repo's data-sovereignty .gitignore blocks
# all *.xml files (LAW 1). It is disposable build input, not source.
$pom = @"
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>local</groupId><artifactId>mpxj-runner</artifactId><version>1.0</version>
  <packaging>jar</packaging>
  <properties><maven.compiler.release>17</maven.compiler.release></properties>
  <dependencies>
    <dependency>
      <groupId>net.sf.mpxj</groupId><artifactId>mpxj</artifactId><version>$MpxjVersion</version>
    </dependency>
  </dependencies>
</project>
"@
Set-Content -LiteralPath "pom.xml" -Value $pom -Encoding UTF8

Write-Host "Resolving MPXJ $MpxjVersion + dependencies into .\lib ..."
mvn -q dependency:copy-dependencies "-DoutputDirectory=lib" "-DincludeScope=runtime"
if ($LASTEXITCODE -ne 0) { Write-Error "Maven dependency resolution failed."; exit 1 }

Write-Host "Compiling MpxjToMspdi ..."
javac -cp "lib/*" -d classes MpxjToMspdi.java
if ($LASTEXITCODE -ne 0) { Write-Error "javac compilation failed."; exit 1 }

Write-Host ""
Write-Host "MPXJ ready. Enable native .mpp parsing with:"
Write-Host "    `$env:SF_MPXJ_HOME = `"$PSScriptRoot`"   # this PowerShell session"
Write-Host "    setx SF_MPXJ_HOME `"$PSScriptRoot`"        # persist for new sessions"
