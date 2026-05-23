#!/usr/bin/env bash
# Install MPXJ (the native .mpp reader) locally for Schedule Forensics.
#
# Requires Java (JDK >= 17) and Maven (mvn) on PATH. Produces, next to this
# script, ./lib (MPXJ + its dependency jars) and ./classes (the compiled
# MpxjToMspdi converter). Then enable native .mpp parsing in the CLI and the web
# UI by pointing the tool at this directory:
#
#     export SF_MPXJ_HOME="$(cd "$(dirname "$0")" && pwd)"
#
# LAW 1: everything here runs locally; no schedule data leaves the machine.
set -euo pipefail
cd "$(dirname "$0")"
MPXJ_VERSION="${MPXJ_VERSION:-16.2.0}"

command -v java >/dev/null 2>&1 || { echo "ERROR: Java not found (install a JDK >= 17)." >&2; exit 1; }
command -v mvn  >/dev/null 2>&1 || { echo "ERROR: Maven (mvn) not found (install Apache Maven)." >&2; exit 1; }

# pom.xml is generated here because the repo's data-sovereignty .gitignore blocks
# all *.xml files (LAW 1). It is disposable build input, not source.
cat > pom.xml <<POM
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>local</groupId><artifactId>mpxj-runner</artifactId><version>1.0</version>
  <packaging>jar</packaging>
  <properties><maven.compiler.release>17</maven.compiler.release></properties>
  <dependencies>
    <dependency>
      <groupId>net.sf.mpxj</groupId><artifactId>mpxj</artifactId><version>${MPXJ_VERSION}</version>
    </dependency>
  </dependencies>
</project>
POM

echo "Resolving MPXJ ${MPXJ_VERSION} + dependencies into ./lib ..."
mvn -q dependency:copy-dependencies -DoutputDirectory=lib -DincludeScope=runtime
echo "Compiling MpxjToMspdi ..."
javac -cp 'lib/*' -d classes MpxjToMspdi.java

echo
echo "MPXJ ready. Enable native .mpp parsing with:"
echo "    export SF_MPXJ_HOME=\"$(pwd)\""
