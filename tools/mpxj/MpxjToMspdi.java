// Minimal MPXJ converter used by importers/mpp_mpxj.py (invoked as a subprocess).
//
// Reads any MPXJ-supported schedule file (.mpp / .mpx / .xer / MSPDI XML / ...)
// via the universal reader and writes it back out as MS Project MSPDI XML, which
// the pure-Python importer (parse_msp_xml) then reads. This keeps the JVM fully
// OUT of the Python process (Commandment 1: never in-process JPype).
//
// Build + wire-up: see docs/MPXJ.md. Verified against MPXJ 16.2.0 (package
// org.mpxj; the Maven groupId is still net.sf.mpxj).
//
//   javac -cp 'lib/*' -d classes MpxjToMspdi.java
//   export SF_MPXJ_CMD="java -cp classes:lib/* MpxjToMspdi {input} {output}"
//
// Exit codes: 0 ok; 1 bad args; 2 MPXJ did not recognize the input format.

import org.mpxj.ProjectFile;
import org.mpxj.mspdi.MSPDIWriter;
import org.mpxj.reader.UniversalProjectReader;

public class MpxjToMspdi {
    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            System.err.println("usage: MpxjToMspdi <input> <output>");
            System.exit(1);
        }
        ProjectFile project = new UniversalProjectReader().read(args[0]);
        if (project == null) {
            System.err.println("MPXJ could not recognize the file: " + args[0]);
            System.exit(2);
        }
        new MSPDIWriter().write(project, args[1]);
    }
}
