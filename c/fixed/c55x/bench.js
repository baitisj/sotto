// Run bench.out on TI's C55x Rev 3.0 cycle-accurate simulator through Debug Server
// Scripting (CCS 5.5): dss bench.js CCXML OUT. bench.c reads in.raw and writes out.bit and
// out.raw (CIO file I/O) in the current folder, and prints the cycle counts.
// SPDX-License-Identifier: MIT
importPackage(Packages.com.ti.debug.engine.scripting);
importPackage(Packages.com.ti.ccstudio.scripting.environment);
importPackage(Packages.java.lang);

var ccxml = arguments[0], prog = arguments[1];
var script = ScriptingEnvironment.instance();
script.traceSetConsoleLevel(TraceLevel.INFO);
script.setScriptTimeout(-1);
var ds = script.getServer("DebugServer.1");
ds.setConfig(ccxml);
var s = ds.openSession(".*");
s.memory.loadProgram(prog);
s.clock.enable();                 // the profile clock that clock() reads
var t0 = System.currentTimeMillis();
s.target.run();                   // until exit; CIO output goes to the console
print("simulated in " + (System.currentTimeMillis() - t0) / 1000 + " s");
s.terminate();
ds.stop();
