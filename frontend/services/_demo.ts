/** Simulated latency so loading states are exercised in demo mode too. */
export const demoDelay = <T,>(value: T, ms = 350): Promise<T> =>
  new Promise((resolve) => setTimeout(() => resolve(structuredClone(value)), ms));
