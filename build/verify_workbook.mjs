import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const root = "/Users/kenielpeart/Downloads/innovation camp data";
const buildDir = `${root}/outputs/clean_cooking_hackathon/build`;
const workbookPath = `${root}/outputs/clean_cooking_hackathon/clean_cooking_hackathon_aggregate.xlsx`;

const input = await FileBlob.load(workbookPath);
const workbook = await SpreadsheetFile.importXlsx(input);

const sheets = ["Target Countries", "Country Data", "Oloika ECooker", "MiniGrid", "Case Lessons", "Sources"];
for (const sheetName of sheets) {
  const preview = await workbook.render({ sheetName, autoCrop: "all", scale: 1, format: "png" });
  const safeName = sheetName.toLowerCase().replaceAll(" ", "_");
  await fs.writeFile(`${buildDir}/${safeName}_preview.png`, new Uint8Array(await preview.arrayBuffer()));
}

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "final formula error scan",
});
console.log(errors.ndjson);

const target = await workbook.inspect({
  kind: "table",
  sheetId: "Target Countries",
  range: "A1:L18",
  include: "values",
  tableMaxRows: 18,
  tableMaxCols: 12,
});
console.log(target.ndjson);
