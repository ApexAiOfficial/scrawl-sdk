// Ask a question of your datasets; the answer cites the records it used:
// `node examples/ask-with-citations.mjs "Which lamps cost under 20 EUR?" [datasetId]`
import { Scrawl } from "@apexaiofficial/scrawl";

const [question, datasetId] = process.argv.slice(2);
const client = new Scrawl();
const result = await client.ask(question, { datasetId });         // uses your default AI profile
console.log(result.answer);
for (const citation of result.citations ?? []) {
  console.log(`  [${citation.tag}] ${citation.title} ${citation.url} (document ${citation.document_id})`);
}
if (!result.answerable) console.error("(the datasets do not answer this)");
