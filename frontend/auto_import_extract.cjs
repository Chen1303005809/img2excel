const fs = require("node:fs");
const ts = require("typescript");

require.extensions[".ts"] = (module, filename) => {
  const source = fs.readFileSync(filename, "utf8");
  const result = ts.transpileModule(source, {
    compilerOptions: {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.CommonJS,
      esModuleInterop: true,
    },
    fileName: filename,
  });
  module._compile(result.outputText, filename);
};

const { isPositionLimitDocument, extractPositionLimitTable } = require("./src/positionLimitModel.ts");
const { isExceptionMonitoringDocument, extractExceptionTradeTable } = require("./src/exceptionTradeModel.ts");

let input = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => { input += chunk; });
process.stdin.on("end", () => {
  try {
    const request = JSON.parse(input);
    const documents = request.documents || [];
    const extracted = documents.map((document) => {
      if (isPositionLimitDocument(document)) {
        return { kind: "position", ...extractPositionLimitTable(document) };
      }
      if (isExceptionMonitoringDocument(document)) {
        return { kind: "open_total", ...extractExceptionTradeTable(document) };
      }
      return { kind: "unsupported", rows: [], unmappedCells: [], unmappedLimitCells: [] };
    });
    process.stdout.write(JSON.stringify(extracted));
  } catch (error) {
    process.stderr.write(String(error && error.stack || error));
    process.exitCode = 1;
  }
});
