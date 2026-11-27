// A job's status has one spelling, the lower case; the SDK still reads the upper case older servers send.
// pending, running, completed, failed, cancelled and orphaned are what the API's JobStatus promises. Servers before
// that change sent COMPLETED from the job and dataset routes; the SDK turns those six words into the lower case on
// the responses that carry a job's status. Other statuses (a scrape's, an asset's, a pool entry's) are never touched.

import assert from "node:assert/strict";
import { test } from "node:test";

import { makeClient } from "./helpers.js";

const UPPER = ["PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED", "ORPHANED"];

test("a job reads either spelling and exposes the lower case", async () => {
  for (const given of UPPER) {
    for (const sent of [given, given.toLowerCase()]) {
      const { client } = makeClient([{ body: { job_id: "j1", status: sent } }]);
      assert.equal((await client.getJob("j1")).status, given.toLowerCase());
    }
  }
});

test("every job and dataset route exposes the lower case", async () => {
  const { client } = makeClient([
    { body: { jobs: [{ job_id: "a", status: "RUNNING" }, { job_id: "b", status: "completed" }], next_cursor: null } },
    { body: { job_id: "a", cancelled: true, status: "CANCELLED" } },
    { body: { job_id: "c", dataset_id: "d", status: "PENDING" } },
    { body: { job_id: "e", status: "PENDING" } },
    { body: { count: 2, versions: [{ version_id: "v1", status: "COMPLETED" }, { version_id: "v2", status: "ORPHANED" }],
      next_cursor: null } },
    { body: { dataset: { dataset_id: "d" }, versions: [{ version_id: "v1", status: "FAILED" }] } },
  ]);
  assert.deepEqual((await client.listJobs()).jobs.map((job) => job.status), ["running", "completed"]);
  assert.equal((await client.cancelJob("a")).status, "cancelled");
  assert.equal((await client.crawl("lab")).status, "pending");
  assert.equal((await client.extractDataset("d", { instruction: "titles" })).status, "pending");
  assert.deepEqual((await client.listVersions("d")).versions.map((v) => v.status), ["completed", "orphaned"]);
  assert.deepEqual((await client.getDataset("d")).versions.map((v) => v.status), ["failed"]);
});

test("statuses that are not a job status are left as sent", async () => {
  const { client } = makeClient([
    { body: { job_id: "j1", status: "completed", assets: [{ asset_id: "a1", status: "FAILED" }] } },
    { body: { entries: [{ entry_id: "p1", status: "ACTIVE" }] } },
    { body: { job_id: "j2", status: "QUEUED" } },
  ]);
  assert.equal((await client.getAssets("j1")).assets[0].status, "FAILED");
  assert.equal((await client.listProxyPool()).entries[0].status, "ACTIVE");
  assert.equal((await client.getJob("j2")).status, "QUEUED");
});
