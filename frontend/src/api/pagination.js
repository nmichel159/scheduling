export const CURSOR_PAGE_SIZE = 250;

/** Fetch every stable ID-cursor page while keeping each API response bounded. */
export async function fetchAllCursorPages(fetchPage, getLastId) {
  const rows = [];
  let afterId;

  for (let pageNumber = 0; pageNumber < 1000; pageNumber += 1) {
    const page = await fetchPage(afterId, CURSOR_PAGE_SIZE);
    rows.push(...page);
    if (page.length < CURSOR_PAGE_SIZE) return rows;

    const nextAfterId = getLastId(page[page.length - 1]);
    if (!Number.isInteger(nextAfterId) || nextAfterId === afterId) {
      throw new Error('Invalid or non-advancing API cursor.');
    }
    afterId = nextAfterId;
  }

  throw new Error('API cursor exceeded the maximum number of pages.');
}
