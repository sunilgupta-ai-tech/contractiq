// Runs contract-analysis requests one at a time.
//
// The first analysis of a document costs ~15 model calls and is then cached
// on the server. If two pages (or two widgets on one page) asked for it at
// the same moment, both would find the cache empty and pay twice. Queuing
// this browser's /contracts/* calls means the second request finds the
// first one's result already cached.

let tail: Promise<unknown> = Promise.resolve();

export function queued<T>(task: () => Promise<T>): Promise<T> {
  const run = tail.then(task, task);
  tail = run.catch(() => undefined); // a failure must not block later requests
  return run;
}
