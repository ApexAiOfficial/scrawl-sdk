// A job's status reaches you as the server sent it; the SDK's own logic reads either spelling.
// pending, running, completed, failed, cancelled and orphaned are what the API's JobStatus promises today. Servers
// before that change sent COMPLETED from the job and dataset routes. This release (a patch) never rewrites a status:
// code written for 0.1.4 sees exactly what it saw before, against either server, and the SDK's waits read either
// spelling. Comparing with the lower case is the way forward; the upper case is deprecated.

import assert from "node:assert/strict";
import { test } from "node:test";

import { makeClient } from "./helpers.js";

const UPPER = ["PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED", "ORPHANED"];

test("a job status is passed through in either spelling", async () => {
  for (const given of UPPER) {
    for (const sent of [given, given.toLowerCase()]) {
      const { client } = makeClient([{ body: { job_id: "j1", status: sent } }]);
      assert.equal((await client.getJob("j1")).status, sent);
    }
  }
});

test("every job and dataset route passes the status through", async () => {
  const { client } = makeClient([
    { body: { jobs: [{ job_id: "a", status: "RUNNING" }, { job_id: "b", status: "completed" }], next_cursor: null } },
    { body: { job_id: "a", cancelled: true, status: "CANCELLED" } },
    { body: { job_id: "c", dataset_id: "d", status: "pending" } },
    { body: { job_id: "e", status: "PENDING" } },
    { body: { count: 2, versions: [{ version_id: "v1", status: "COMPLETED" }, { version_id: "v2", status: "orphaned" }],
      next_cursor: null } },
    { body: { crawl_id: "s1", status: "RUNNING", done: false, pages: [] } },
  ]);
  assert.deepEqual((await client.listJobs()).jobs.map((job) => job.status), ["RUNNING", "completed"]);
  assert.equal((await client.cancelJob("a")).status, "CANCELLED");
  assert.equal((await client.crawl("lab")).status, "pending");
  assert.equal((await client.extractDataset("d", { instruction: "titles" })).status, "PENDING");
  assert.deepEqual((await client.listVersions("d")).versions.map((v) => v.status), ["COMPLETED", "orphaned"]);
  assert.equal((await client.siteCrawlStatus("s1")).status, "RUNNING");
});

test("waitForJob stops on a finished job in either spelling", async () => {
  for (const finished of ["COMPLETED", "completed", "FAILED", "failed", "CANCELLED", "orphaned"]) {
    const { client, fetch } = makeClient([{ body: { job_id: "j1", status: "PENDING" } },
      { body: { job_id: "j1", status: "running" } }, { body: { job_id: "j1", status: finished } }]);
    assert.equal((await client.waitForJob("j1")).status, finished);
    assert.equal(fetch.calls.length, 3);
  }
});
